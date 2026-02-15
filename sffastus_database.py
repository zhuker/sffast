"""SffastDatabase - high-level read-only interface to a Subaru FAST2 sffastus file.

Encapsulates parser creation, file handle, VIN resolution, figure image extraction,
and callout coordinate loading behind a simple API.

Usage:
    db = SffastDatabase.open()                    # default paths
    db = SffastDatabase.open(sffastus="SFCDUS2/sffastus", figname="...", itca=[...])
    vehicle = db.resolve_vin("JF1GD70655L510047")
    img = db.get_fig_img("940", "01")             # -> WandImage (caller must close)
    callouts = db.get_fig_callouts("940", "01")   # -> list[FigureCallout]
    db.close()
"""

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, List, Optional

from wand.image import Image as WandImage

from sffastus_parser import (
    CatalogApplicabilityRecord466,
    FIGIllustrationPage89,
    FigureIndexRecord22,
    InventoryRecord199,
    PartGroupRecord185,
    SffastusBlockParser,
    SffastusHeader,
    ModelIndexRecord288,
    decode_block_pointer,
    parse_figname_txt,
    parse_itca_data,
    ItcaPartsCatalog,
    parse_model_index,
    iter_model_blocks,
)

from parsers_common import (
    get_vehicle_by_vin,
    Vehicle,
)

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 640

DEFAULT_SFFASTUS = "SFCDUS2/sffastus"
DEFAULT_FIGNAME = "SFCDUS2/sffastpg/win/figname.txt"
DEFAULT_ITCA = ["SFCDUS1/ITCA_DATA.TXT", "SFCDUS2/itca_data.txt", "SFCDUS3/itca_data.txt"]


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
                 models: dict):
        self._f = f
        self._parser = parser
        self._header = header
        self._models = models  # model_code -> ModelIndexRecord288

    @classmethod
    def open(cls, sffastus: str = DEFAULT_SFFASTUS, figname: str = DEFAULT_FIGNAME,
             itca: list = None) -> 'SffastDatabase':
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

        figure_codes = set()
        if Path(figname).exists():
            figure_codes = {r.figure_code for r in parse_figname_txt(figname)}

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

        return cls(f, parser, header, models)

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- VIN resolution --

    def resolve_vin(self, vin: str) -> Vehicle:
        """Resolve a VIN to a Vehicle (with model, spec, codes).

        Raises LookupError if VIN or model not found.
        """
        return get_vehicle_by_vin(self._f, self._parser, vin)

    # -- Model access --

    def get_model(self, model_code: str) -> Optional[ModelIndexRecord288]:
        return self._models.get(model_code)

    # -- Figure image --

    def _find_fig89(self, model_rec: ModelIndexRecord288,
                    fig: str, page: str) -> Optional[FIGIllustrationPage89]:
        for bo in iter_model_blocks(model_rec, FIGIllustrationPage89.ID):
            for r in self._parser.parse_fig_illustration_page_records_89(self._f, bo):
                if r.fig_index == fig and r.page_index == page:
                    return r
        return None

    def get_fig_img(self, model_rec: ModelIndexRecord288,
                    fig: str, page: str) -> Optional[WandImage]:
        """Extract a figure image as a WandImage.

        Args:
            model_rec: ModelIndexRecord288 for the vehicle's model
            fig: figure code, e.g. "940"
            page: page code, e.g. "01"

        Returns:
            WandImage instance (caller must close), or None if not found.
        """
        fig89 = self._find_fig89(model_rec, fig, page)
        if not fig89:
            return None
        fig_offset = fig89.get_figure_offset()
        size = fig89.image_size
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

        Args:
            model_rec: ModelIndexRecord288 for the vehicle's model
            fig: figure code, e.g. "940"
            page: page code, e.g. "01"
            vehicle: optional Vehicle for part number matching via Cat466

        Returns:
            List of FigureCallout with pixel coordinates and part numbers.
        """
        f = self._f
        parser = self._parser

        # Build part lookup from Cat466 if vehicle provided
        part_lookup = {}  # callout_code -> part_id
        if vehicle:
            from parsers_common import filter_cat466_parts
            model_parts = []
            for bo in iter_model_blocks(model_rec, CatalogApplicabilityRecord466.ID):
                model_parts.extend(parser.parse_catalog_applicability_records_466(f, bo))
            filtered = filter_cat466_parts(model_parts, vehicle)
            for rec, variant in filtered:
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
        for bo in iter_model_blocks(model_rec, PartGroupRecord185.ID):
            for r in parser.parse_part_group_records_185(f, bo):
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
        for bo in iter_model_blocks(model_rec, InventoryRecord199.ID):
            for r in parser.parse_inventory_records_199(f, bo):
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
        for bo in iter_model_blocks(model_rec, FigureIndexRecord22.ID):
            for r in self._parser.parse_figure_index_records_22(self._f, bo):
                if r.figure.strip() == fig and r.page.strip() == page:
                    if r.x > 0 and r.y > 0:
                        xrefs.append(FigureCrossRef(
                            ref_figure=r.ref_figure.strip(),
                            px_x=math.floor(r.x / 2),
                            px_y=math.floor(r.y / 2),
                        ))
        return xrefs
