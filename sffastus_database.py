"""SffastDatabase - high-level read-only interface to a Subaru FAST2 sffastus file.

Encapsulates parser creation, file handle, VIN resolution, figure image extraction,
and callout coordinate loading behind a simple API.

All model block data is lazy-loaded and cached on first access.

Usage:
    db = SffastDatabase.open()                    # default paths
    db = SffastDatabase.open(sffastus="SFCDUS2/sffastus", figname="...", itca=[...])
    vehicle = db.resolve_vin("JF1GD70655L510047")
    pages = db.get_vin_figures(vehicle)  # list[FigurePage] with .type 'figure'|'bulletin'
    img = db.get_fig_img(vehicle.model_rec, "940", "01")   # -> WandImage
    callouts = db.get_fig_callouts(vehicle.model_rec, "940", "01", vehicle)
    db.close()
"""

import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, List, Optional

from wand.image import Image as WandImage

from sffastus_parser import (
    CatalogApplicabilityRecord466,
    EngineSpecRecord230,
    FIGGroupCategoryRecord184,
    FIGIllustrationPage89,
    FIGIllustrationRecord183,
    FigureIndexRecord22,
    InventoryRecord199,
    PartGroupRecord185,
    SffastusBlockParser,
    SffastusHeader,
    ModelIndexRecord288,
    parse_figname_txt,
    parse_itca_data,
    ItcaPartsCatalog,
    parse_model_index,
    iter_model_blocks,
)

from parsers_common import (
    get_vehicle_by_vin,
    filter_cat466_parts,
    eval_spec_logic,
    date_in_range,
    Vehicle,
)

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640

DEFAULT_SFFASTUS = "SFCDUS2/sffastus"
DEFAULT_FIGNAME = "SFCDUS2/sffastpg/win/figname.txt"
DEFAULT_ITCA = ["SFCDUS1/ITCA_DATA.TXT", "SFCDUS2/itca_data.txt", "SFCDUS3/itca_data.txt"]


@dataclass
class FigurePage:
    """An applicable figure page for a vehicle."""
    figure: str        # figure code, e.g. "940"
    page: str          # page code, e.g. "01"
    type: str          # 'figure' | 'bulletin'


@dataclass
class FigureCallout:
    """A single callout on a figure image."""
    code: str          # callout code (e.g. "94088A", "W130076")
    px_x: int          # pixel X on 1280x640 image
    px_y: int          # pixel Y on 1280x640 image
    description: str   # English description
    part_number: str   # part number (from Cat466 or Inventory199), or ''
    source: str        # 'part_group' | 'inventory'


@dataclass
class FigureCrossRef:
    """A cross-reference arrow on a figure image."""
    ref_figure: str    # target figure code
    px_x: int
    px_y: int


def _make_g4_tiff(raw_data: bytes, width: int, height: int) -> bytes:
    ifd_offset = 8 + len(raw_data)
    header = struct.pack('<2sHI', b'II', 42, ifd_offset)
    entries = [
        (256, 3, 1, width),
        (257, 3, 1, height),
        (258, 3, 1, 1),
        (259, 3, 1, 4),
        (262, 3, 1, 0),
        (273, 4, 1, 8),
        (278, 3, 1, height),
        (279, 4, 1, len(raw_data)),
        (292, 4, 1, 0),
    ]
    ifd = struct.pack('<H', len(entries))
    for tag, typ, count, val in entries:
        ifd += struct.pack('<HHII', tag, typ, count, val)
    ifd += struct.pack('<I', 0)
    return header + raw_data + ifd


class SffastDatabase:
    """High-level read-only interface to a Subaru FAST2 sffastus data file."""

    def __init__(self, f: BinaryIO, parser: SffastusBlockParser, header: SffastusHeader,
                 models: dict[str, ModelIndexRecord288],
                 figname_lookup: dict[str, str]) -> None:
        self._f = f
        self._parser = parser
        self._header = header
        self._models = models
        self._figname_lookup = figname_lookup
        self._cache: dict = {}

    @classmethod
    def open(cls, sffastus: str = DEFAULT_SFFASTUS, figname: str = DEFAULT_FIGNAME,
             itca: Optional[List[str]] = None) -> 'SffastDatabase':
        """Open a database from file paths.

        Args:
            sffastus: path to the sffastus binary file
            figname: path to figname.txt
            itca: list of ITCA_DATA.TXT paths (default: all 3 SFCDUS dirs)

        Returns:
            SffastDatabase instance (caller should call .close() when done)
        """
        if itca is None:
            itca = list(DEFAULT_ITCA)

        figname_records = list(parse_figname_txt(figname)) if Path(figname).exists() else []
        figure_codes = {r.figure_code for r in figname_records}
        figname_lookup = {r.figure_code: r.description for r in figname_records}

        itca_records = []
        for itca_path in itca:
            if Path(itca_path).exists():
                itca_records.extend(parse_itca_data(itca_path))
        parts_catalog = ItcaPartsCatalog(itca_records)

        parser = SffastusBlockParser(figure_codes=figure_codes, parts_catalog=parts_catalog)

        f = open(sffastus, 'rb')
        header = SffastusHeader.parse(f.read(50))
        f.seek(0)
        models = parse_model_index(f, header)

        return cls(f, parser, header, models, figname_lookup)

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> 'SffastDatabase':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- Lazy loading --

    def _load(self, model_rec: ModelIndexRecord288, record_cls: type,
              parse_method: callable) -> list:
        """Load all records of a type for a model, cached on first call."""
        key = (model_rec.model_code, record_cls.ID)
        if key not in self._cache:
            records = []
            for bo in iter_model_blocks(model_rec, record_cls.ID):
                records.extend(parse_method(self._f, bo))
            self._cache[key] = records
        return self._cache[key]

    def _get_filtered_parts(self, model_rec: ModelIndexRecord288,
                            vehicle: Vehicle) -> List[tuple[CatalogApplicabilityRecord466, str]]:
        """Get Cat466 parts filtered by vehicle spec/date, cached per VIN."""
        key = (model_rec.model_code, '_filtered', vehicle.vin_rec.vin)
        if key not in self._cache:
            all_parts = self.get_catalog_parts(model_rec)
            self._cache[key] = filter_cat466_parts(all_parts, vehicle)
        return self._cache[key]

    # -- VIN resolution --

    def resolve_vin(self, vin: str) -> Vehicle:
        """Resolve a VIN to a Vehicle (with model, spec, codes).

        Raises LookupError if VIN or model not found.
        """
        return get_vehicle_by_vin(self._f, self._parser, vin)

    # -- Model access --

    def get_model(self, model_code: str) -> Optional[ModelIndexRecord288]:
        return self._models.get(model_code)

    # -- Raw record accessors (lazy-loaded) --

    def get_engine_specs(self, model_rec: ModelIndexRecord288) -> List[EngineSpecRecord230]:
        """EngineSpecRecord230 — figure applicability rules."""
        return self._load(model_rec, EngineSpecRecord230,
                          self._parser.parse_engine_spec_records_230)

    def get_fig_illustration_pages(self, model_rec: ModelIndexRecord288) -> List[FIGIllustrationPage89]:
        """FIGIllustrationPage89 — figure page image metadata."""
        return self._load(model_rec, FIGIllustrationPage89,
                          self._parser.parse_fig_illustration_page_records_89)

    def get_fig_illustrations(self, model_rec: ModelIndexRecord288) -> List[FIGIllustrationRecord183]:
        """FIGIllustrationRecord183 — figure descriptions."""
        return self._load(model_rec, FIGIllustrationRecord183,
                          self._parser.parse_fig_illustration_records_183)

    def get_fig_group_categories(self, model_rec: ModelIndexRecord288) -> List[FIGGroupCategoryRecord184]:
        """FIGGroupCategoryRecord184 — figure category descriptions."""
        return self._load(model_rec, FIGGroupCategoryRecord184,
                          self._parser.parse_fig_group_category_records_184)

    def get_part_groups(self, model_rec: ModelIndexRecord288) -> List[PartGroupRecord185]:
        """PartGroupRecord185 — callout descriptions with coordinates."""
        return self._load(model_rec, PartGroupRecord185,
                          self._parser.parse_part_group_records_185)

    def get_inventory_records(self, model_rec: ModelIndexRecord288) -> List[InventoryRecord199]:
        """InventoryRecord199 — fastener/hardware callouts."""
        return self._load(model_rec, InventoryRecord199,
                          self._parser.parse_inventory_records_199)

    def get_catalog_parts(self, model_rec: ModelIndexRecord288) -> List[CatalogApplicabilityRecord466]:
        """CatalogApplicabilityRecord466 — parts catalog."""
        return self._load(model_rec, CatalogApplicabilityRecord466,
                          self._parser.parse_catalog_applicability_records_466)

    def get_figure_index_records(self, model_rec: ModelIndexRecord288) -> List[FigureIndexRecord22]:
        """FigureIndexRecord22 — figure cross-references."""
        return self._load(model_rec, FigureIndexRecord22,
                          self._parser.parse_figure_index_records_22)

    # -- VIN figures --

    def get_vin_figures(self, vehicle: Vehicle) -> List[FigurePage]:
        """Get applicable figure pages for a vehicle.

        Returns list of FigurePage with type 'figure' or 'bulletin'.
        Bulletins are I&S pages (page >= 40).
        """
        model_rec = vehicle.model_rec
        codes = vehicle.codes
        vehicle_date = vehicle.vehicle_date

        result = []
        for rec in self.get_engine_specs(model_rec):
            spec_expr = rec.applicable_model
            parts = re.split(r'\s{3,}', spec_expr, maxsplit=1)
            spec_only = parts[0].strip()

            if not eval_spec_logic(spec_only, codes):
                continue
            if not date_in_range(vehicle_date, rec.start_date, rec.end_date):
                continue

            page_num = int(rec.figure_page) if rec.figure_page.isdigit() else 0
            page_type = 'bulletin' if page_num >= 40 else 'figure'
            result.append(FigurePage(figure=rec.figure, page=rec.figure_page, type=page_type))

        return result

    # -- ITCA parts catalog --

    @property
    def parts_catalog(self) -> ItcaPartsCatalog:
        return self._parser.parts_catalog

    # -- Figure name lookup --

    def get_figname(self, fig_code: str) -> str:
        """Get figure description from figname.txt."""
        return self._figname_lookup.get(fig_code, '')

    # -- Figure category lookup (184) --

    def _get_fig184_lookup(self, model_rec: ModelIndexRecord288) -> dict[str, FIGGroupCategoryRecord184]:
        """Lazy-cached group_code -> FIGGroupCategoryRecord184 lookup."""
        key = (model_rec.model_code, '_fig184_lookup')
        if key not in self._cache:
            self._cache[key] = {
                r.fig_group_code: r
                for r in self.get_fig_group_categories(model_rec)
            }
        return self._cache[key]

    def get_fig_category(self, model_rec: ModelIndexRecord288,
                         group_code: str) -> Optional[FIGGroupCategoryRecord184]:
        """Look up a figure group category by code (e.g. '0A')."""
        return self._get_fig184_lookup(model_rec).get(group_code)

    # -- Figure description lookup (183, deduped) --

    def _get_fig183_lookup(self, model_rec: ModelIndexRecord288) -> dict[str, FIGIllustrationRecord183]:
        """Lazy-cached fig_code -> FIGIllustrationRecord183 lookup.

        Each figure appears twice (by-system 0A-9B and by-binder A1-D3);
        prefers the "by system" record whose group_code exists in fig184.
        """
        key = (model_rec.model_code, '_fig183_lookup')
        if key not in self._cache:
            from collections import defaultdict
            fig184_lookup = self._get_fig184_lookup(model_rec)
            by_fig = defaultdict(list)
            for r in self.get_fig_illustrations(model_rec):
                by_fig[r.fig_group_code2].append(r)
            lookup = {}
            for fig_code, records in by_fig.items():
                best = records[0]
                for r in records:
                    if r.fig_group_code in fig184_lookup:
                        best = r
                        break
                lookup[fig_code] = best
            self._cache[key] = lookup
        return self._cache[key]

    def get_fig_info(self, model_rec: ModelIndexRecord288,
                     fig_code: str) -> Optional[FIGIllustrationRecord183]:
        """Look up a figure's illustration record (description, group code)."""
        return self._get_fig183_lookup(model_rec).get(fig_code)

    # -- Part description lookup (PG185 + ITCA fallback) --

    def _get_part_desc_lookup(self, model_rec: ModelIndexRecord288) -> dict[tuple[str, str], str]:
        """Lazy-cached (figure, callout_code) -> desc_en from PartGroupRecord185."""
        key = (model_rec.model_code, '_part_desc_lookup')
        if key not in self._cache:
            lookup: dict[tuple[str, str], str] = {}
            for r in self.get_part_groups(model_rec):
                code = r.part_code.split()[0]
                k = (r.figure, code)
                if k not in lookup:
                    lookup[k] = r.desc_en
            self._cache[key] = lookup
        return self._cache[key]

    def lookup_part_desc(self, model_rec: ModelIndexRecord288,
                         fig: str, callout_code: str, part_id: str = '') -> str:
        """Look up a part description: PG185 first, then ITCA fallback."""
        code = callout_code.split()[0]
        desc = self._get_part_desc_lookup(model_rec).get((fig, code), '')
        if desc:
            return desc
        if part_id and self._parser.parts_catalog:
            catalog = self._parser.parts_catalog
            recs = catalog.lookup(part_id)
            if not recs:
                base = part_id[:10].strip()
                if base:
                    recs = catalog.lookup(base)
            if recs:
                return recs[0].description
        return ''

    # -- Figure page lookup (89) --

    def _get_fig89_lookup(self, model_rec: ModelIndexRecord288) -> dict[tuple[str, str], FIGIllustrationPage89]:
        """Lazy-cached (fig, page) -> FIGIllustrationPage89 lookup."""
        key = (model_rec.model_code, '_fig89_lookup')
        if key not in self._cache:
            self._cache[key] = {
                (r.fig_index, r.page_index): r
                for r in self.get_fig_illustration_pages(model_rec)
            }
        return self._cache[key]

    def get_fig_page(self, model_rec: ModelIndexRecord288,
                     fig: str, page: str) -> Optional[FIGIllustrationPage89]:
        """Look up a figure page record (has_image check, label, image_size)."""
        return self._get_fig89_lookup(model_rec).get((fig, page))

    # -- Figure image --

    def get_fig_img(self, model_rec: ModelIndexRecord288,
                    fig: str, page: str) -> Optional[WandImage]:
        """Extract a figure image as a WandImage.

        Returns WandImage instance (caller must close), or None if not found.
        """
        r = self.get_fig_page(model_rec, fig, page)
        if not r:
            return None
        fig_offset = r.get_figure_offset()
        size = r.image_size
        if size == 0 or fig_offset == 0:
            return None
        self._f.seek(fig_offset)
        raw_data = self._f.read(size)
        tiff_data = _make_g4_tiff(raw_data, IMAGE_WIDTH, IMAGE_HEIGHT)
        return WandImage(blob=tiff_data, format='tiff')

    # -- Callout coordinates --

    def get_fig_callouts(self, model_rec: ModelIndexRecord288,
                         fig: str, page: str,
                         vehicle: Vehicle = None) -> List[FigureCallout]:
        """Get callout coordinates for a figure page.

        Merges PartGroupRecord185 and InventoryRecord199 coordinates.
        If vehicle is provided, matches Cat466 part numbers to callouts.
        """
        # Build part lookup from Cat466 if vehicle provided
        part_lookup = {}  # callout_code -> part_id
        if vehicle:
            for rec, variant in self._get_filtered_parts(model_rec, vehicle):
                if rec.figure_ref and len(rec.figure_ref) >= 4:
                    ref_fig = rec.figure_ref[1:]
                else:
                    continue
                if ref_fig != fig:
                    continue
                rec_page = rec.figure_page.strip()
                if rec_page and rec_page != page:
                    continue
                callout = rec.callout_code.strip()
                if callout not in part_lookup:
                    part_lookup[callout] = rec.part_id

        callouts = []

        # Source 1: PartGroupRecord185 (main part callouts)
        for r in self.get_part_groups(model_rec):
            if r.figure.strip() == fig and r.figure_page.strip() == page:
                code = r.part_code.strip()
                if code and r.x > 0 and r.y > 0:
                    callouts.append(FigureCallout(
                        code=code,
                        px_x=math.floor(r.x / 2),
                        px_y=math.floor(r.y / 2),
                        description=r.desc_en,
                        part_number=part_lookup.get(code, ''),
                        source='part_group',
                    ))

        # Source 2: InventoryRecord199 (fastener/hardware callouts)
        for r in self.get_inventory_records(model_rec):
            if r.figure.strip() == fig and r.figure_page.strip() == page:
                code = r.part_code.strip()
                if code and r.x > 0 and r.y > 0:
                    pn = part_lookup.get(code, '') or r.part_number.strip()
                    callouts.append(FigureCallout(
                        code=code,
                        px_x=math.floor(r.x / 2),
                        px_y=math.floor(r.y / 2),
                        description=r.name_en,
                        part_number=pn,
                        source='inventory',
                    ))

        return callouts

    # -- Figure cross-references --

    def get_fig_xrefs(self, model_rec: ModelIndexRecord288,
                      fig: str, page: str) -> List[FigureCrossRef]:
        """Get figure cross-reference arrows for a figure page."""
        xrefs = []
        for r in self.get_figure_index_records(model_rec):
            if r.figure.strip() == fig and r.page.strip() == page:
                if r.x > 0 and r.y > 0:
                    xrefs.append(FigureCrossRef(
                        ref_figure=r.ref_figure.strip(),
                        px_x=math.floor(r.x / 2),
                        px_y=math.floor(r.y / 2),
                    ))
        return xrefs
