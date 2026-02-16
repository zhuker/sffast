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
from collections import defaultdict
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
    ItcaCode,
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
class BulletinMatch:
    """A bulletin page reachable through a vehicle's ITCA interchangeability chain."""
    figure: str            # bulletin figure code (e.g. "911")
    page: str              # bulletin page code (e.g. "41")
    bulletin_part: str     # part number embedded in the bulletin spec
    source_figure: str     # figure where the triggering part appears
    source_page: str       # page where the triggering part appears
    source_callout: str    # callout code on that page
    source_part: str       # vehicle's Cat466 part number on that callout
    itca_code: Optional[ItcaCode]  # ITCA code on the interchangeable record (None if direct match)


@dataclass
class ItcaChainLink:
    """A single hop in an ITCA supersession chain."""
    part_number: str              # supersedes_to part number
    code: ItcaCode                # ITCA condition code
    bulletin_figure: str = ''     # bulletin figure code (e.g. "004") or ''
    bulletin_page: str = ''       # bulletin page code (e.g. "40") or ''
    bulletin_label: str = ''      # bulletin label (e.g. "I&S BULLETIN COVER-OIL SEPR") or ''


@dataclass
class PartMatch:
    """A part matched to a figure callout."""
    part_number: str   # Cat466 part_id or Inv199 part_number
    description: str   # resolved via lookup_part_desc (PG185 + ITCA fallback)
    variant: str       # '' or 'A'-'H' (spec logic variant prefix)
    usage_notes: str   # from Cat466 (or '')
    part_spec: str     # from Cat466 (or '')
    itca_chain: Optional[List[ItcaChainLink]] = None
    bulletin_figure: str = ''     # bulletin for this part itself ('' if none)
    bulletin_page: str = ''
    bulletin_label: str = ''


@dataclass
class FigureCallout:
    """A single callout on a figure image."""
    code: str          # callout code (e.g. "94088A", "W130076")
    px_x: int          # pixel X on 1280x640 image
    px_y: int          # pixel Y on 1280x640 image
    description: str   # English description (PG185 desc_en or Inv199 name_en)
    parts: List[PartMatch]  # matched parts (deduped); empty if unmatched
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

    # -- Bulletin index (lazy) --

    def _get_bulletin_index(self, model_rec: ModelIndexRecord288) -> dict[str, list[tuple[str, str]]]:
        """Lazy-cached bulletin_part_number -> [(fig, page), ...] from EngineSpecRecord230.

        Bulletin entries have page >= 40 and applicable_model = "ALL" + embedded part number.
        """
        key = (model_rec.model_code, '_bulletin_index')
        if key not in self._cache:
            index: dict[str, list[tuple[str, str]]] = defaultdict(list)
            for rec in self.get_engine_specs(model_rec):
                page_num = int(rec.figure_page) if rec.figure_page.isdigit() else 0
                if page_num < 40:
                    continue
                parts = re.split(r'\s{3,}', rec.applicable_model, maxsplit=1)
                if len(parts) >= 2:
                    embedded_pn = parts[1].strip()
                    if embedded_pn:
                        index[embedded_pn].append((rec.figure, rec.figure_page))
            self._cache[key] = dict(index)
        return self._cache[key]

    def get_bulletin_index(self, model_rec: ModelIndexRecord288) -> dict[str, list[tuple[str, str]]]:
        """Public access to bulletin_part_number -> [(fig, page), ...] index."""
        return self._get_bulletin_index(model_rec)

    # -- VIN bulletins (ITCA chain walk) --

    def get_vin_bulletins(self, vehicle: Vehicle) -> List[BulletinMatch]:
        """Find I&S Bulletin pages reachable through the vehicle's ITCA chain.

        Walks each applicable Cat466 part -> ITCA interchangeability -> bulletin index.
        Returns BulletinMatch entries with full provenance (source figure/callout/part).
        """
        model_rec = vehicle.model_rec
        bulletin_index = self._get_bulletin_index(model_rec)
        if not bulletin_index:
            return []

        catalog = self.parts_catalog

        # Collect vehicle parts with their figure/page/callout provenance
        filtered = self._get_filtered_parts(model_rec, vehicle)
        results: list[BulletinMatch] = []
        seen: set[tuple[str, str, str]] = set()  # (bulletin_fig, bulletin_page, source_part)

        for rec, _ in filtered:
            pn = rec.part_id.strip()
            if not pn:
                continue

            fig_ref = ''
            if rec.figure_ref and len(rec.figure_ref) >= 4:
                fig_ref = rec.figure_ref[1:]  # strip group letter
            page_ref = rec.figure_page.strip()
            callout = rec.callout_code.strip()

            # Collect all part numbers reachable through ITCA chain
            # (part itself + interchangeable parts with bulletin-eligible codes)
            chain: list[tuple[str, Optional[ItcaCode]]] = [(pn, None)]

            itca_recs = catalog.lookup(pn)
            for ir in itca_recs:
                code = ItcaCode.from_str(ir.itca_code)
                if code and code.has_bulletin:
                    # Forward: this part supersedes to another
                    sup = ir.supersedes_to.strip()
                    if sup and sup != pn:
                        chain.append((sup, code))
                    # Reverse: another part that shares this supersedes_to target
                    own_pn = ir.part_number.strip()
                    if own_pn and own_pn != pn:
                        chain.append((own_pn, code))

            for chain_pn, code in chain:
                if chain_pn not in bulletin_index:
                    continue
                for bfig, bpage in bulletin_index[chain_pn]:
                    dedup_key = (bfig, bpage, pn)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    results.append(BulletinMatch(
                        figure=bfig,
                        page=bpage,
                        bulletin_part=chain_pn,
                        source_figure=fig_ref,
                        source_page=page_ref,
                        source_callout=callout,
                        source_part=pn,
                        itca_code=code,
                    ))

        return results

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
        If vehicle is provided, matches Cat466 part numbers to callouts
        and populates each callout's parts list with all matching records
        (deduped by callout_code + part_id).
        """
        # Build Cat466 lookup: base_code -> [(rec, variant), ...]
        cat466_by_callout: dict[str, list] = defaultdict(list)
        if vehicle:
            for rec, variant in self._get_filtered_parts(model_rec, vehicle):
                if not (rec.figure_ref and len(rec.figure_ref) >= 4):
                    continue
                if rec.figure_ref[1:] != fig:
                    continue
                rec_page = rec.figure_page.strip()
                if rec_page and rec_page != page:
                    continue
                base = rec.callout_code.split()[0] if rec.callout_code else ''
                if base:
                    cat466_by_callout[base].append((rec, variant))

        bulletin_index = self._get_bulletin_index(model_rec)

        def _bulletin_fields(pn: str) -> tuple[str, str, str]:
            """Look up bulletin fig/page/label for a part number."""
            entries = bulletin_index.get(pn)
            if not entries:
                return ('', '', '')
            bfig, bpage = entries[0]
            fig89 = self.get_fig_page(model_rec, bfig, bpage)
            label = " ".join(fig89.label.split()) if fig89 and fig89.label else ""
            return (bfig, bpage, label)

        def _build_chain(part_id: str) -> Optional[List[ItcaChainLink]]:
            """Build ITCA chain with bulletin refs for a part number."""
            if not self._parser.parts_catalog:
                return None
            raw = self._parser.parts_catalog.follow_chain(part_id)
            if not raw:
                return None
            chain = []
            for pn, code in raw:
                bf, bp, bl = _bulletin_fields(pn)
                chain.append(ItcaChainLink(
                    part_number=pn, code=code,
                    bulletin_figure=bf, bulletin_page=bp, bulletin_label=bl,
                ))
            return chain

        def _build_parts(base_code: str, position: str = '') -> List[PartMatch]:
            """Build deduped PartMatch list for a callout code.

            If position is set (e.g. 'A' from PG185 part_code "11021  A"),
            only include Cat466 records whose variant matches that position.
            Records with variant='' (no position prefix) match all positions.
            """
            entries = cat466_by_callout.get(base_code)
            if not entries:
                return []
            seen: set = set()
            result: list[PartMatch] = []
            for rec, variant in entries:
                if position and variant and variant != position:
                    continue
                key = (rec.callout_code, rec.part_id)
                if key in seen:
                    continue
                seen.add(key)
                desc = self.lookup_part_desc(model_rec, fig, rec.callout_code, rec.part_id)
                chain = _build_chain(rec.part_id)
                bf, bp, bl = _bulletin_fields(rec.part_id)
                result.append(PartMatch(
                    part_number=rec.part_id,
                    description=desc,
                    variant=variant,
                    usage_notes=rec.usage_notes or '',
                    part_spec=rec.part_spec or '',
                    itca_chain=chain,
                    bulletin_figure=bf, bulletin_page=bp, bulletin_label=bl,
                ))
            return result

        callouts: list[FigureCallout] = []

        # Source 1: PartGroupRecord185 (main part callouts)
        for r in self.get_part_groups(model_rec):
            if r.figure.strip() == fig and r.figure_page.strip() == page:
                code = r.part_code.strip()
                if code and r.x > 0 and r.y > 0:
                    parts = code.split()
                    base = parts[0]
                    position = parts[1] if len(parts) > 1 else ''
                    callouts.append(FigureCallout(
                        code=code,
                        px_x=math.floor(r.x / 2),
                        px_y=math.floor(r.y / 2),
                        description=r.desc_en,
                        parts=_build_parts(base, position),
                        source='part_group',
                    ))

        # Source 2: InventoryRecord199 (fastener/hardware callouts)
        for r in self.get_inventory_records(model_rec):
            if r.figure.strip() == fig and r.figure_page.strip() == page:
                code = r.part_code.strip()
                if code and r.x > 0 and r.y > 0:
                    code_parts = code.split()
                    base = code_parts[0]
                    position = code_parts[1] if len(code_parts) > 1 else ''
                    parts = _build_parts(base, position)
                    if not parts:
                        pn = r.part_number.strip()
                        if pn:
                            parts = [PartMatch(
                                part_number=pn,
                                description=r.name_en,
                                variant='',
                                usage_notes='',
                                part_spec='',
                            )]
                    callouts.append(FigureCallout(
                        code=code,
                        px_x=math.floor(r.x / 2),
                        px_y=math.floor(r.y / 2),
                        description=r.name_en,
                        parts=parts,
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
