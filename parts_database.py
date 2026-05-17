"""SubaruPartsDatabase — abstract interface for Subaru parts catalog databases.

Factory method SubaruPartsDatabase.open(path) auto-detects the format:
  - If path is a SQLite file -> Epc3Database (EPC3 format)
  - Otherwise -> SffastDatabase (FAST2 sffastus binary format)

Shared data types (FigurePage, FigureCallout, FigureCrossRef, PartMatch, etc.)
are defined here so both backends can use them without circular imports.
"""

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from sffastus_parser import ItcaCode


# ── Shared data types (moved from sffastus_database.py) ──────────────────────


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
    callout_code: str  # callout code (e.g. "94088A", "W130076", "42037BA")
    variant: str       # variant letter (e.g. "A", "B") or '' if none
    px_x: int          # pixel X on 1280x640 image
    px_y: int          # pixel Y on 1280x640 image
    description: str   # English description (PG185 desc_en or Inv199 name_en)
    parts: List[PartMatch]  # matched parts (deduped); empty if unmatched
    source: str        # 'part_group' | 'inventory'

    @property
    def code(self) -> str:
        """Legacy accessor: 'callout_code variant' or just 'callout_code'."""
        if self.variant:
            return f'{self.callout_code} {self.variant}'
        return self.callout_code


@dataclass
class FigureCrossRef:
    """A cross-reference arrow on a figure image."""
    ref_figure: str    # target figure code
    px_x: int
    px_y: int


# ── Abstract interface ────────────────────────────────────────────────────────


class SubaruPartsDatabase(ABC):
    """Abstract interface to a Subaru parts catalog database.

    Implementations:
      - SffastDatabase  (FAST2 sffastus binary)
      - Epc3Database    (EPC3 SQLite)
    """

    @classmethod
    def open(cls, path: str = None, **kwargs) -> 'SubaruPartsDatabase':
        """Factory: auto-detect format from path and return the right backend.

        Args:
            path: file path.  None = default FAST2 (SFCDUS2/sffastus).
                  If the file is a SQLite database -> Epc3Database.
                  Otherwise -> SffastDatabase.
            **kwargs: passed through to the backend's open().

        Returns:
            SubaruPartsDatabase instance (call .close() when done).
        """
        if path is None:
            from sffastus_database import SffastDatabase
            return SffastDatabase.open(**kwargs)

        # Detect SQLite by magic bytes
        try:
            with open(path, 'rb') as f:
                magic = f.read(16)
            if magic[:6] == b'SQLite':
                from epc3_database import Epc3Database
                return Epc3Database.open(path, **kwargs)
        except (OSError, IOError):
            pass

        # Default: FAST2 binary
        from sffastus_database import SffastDatabase
        return SffastDatabase.open(sffastus=path, **kwargs)

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> 'SubaruPartsDatabase':
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── VIN resolution ────────────────────────────────────────────────────

    @abstractmethod
    def resolve_vin(self, vin: str):
        """Resolve a VIN to a Vehicle object.

        Returns an object with attributes:
            .vin_rec   — has .vin, .model_code, .body_model, .color_code,
                         .trim_code, .option_code, .destination_code, .body_production_date
            .model_rec — opaque handle passed back to other db methods
            .spec      — has .applied_model, .body_config, .engine,
                         .transmission, .trim_level, .drivetrain (or None)
            .codes     — set of spec code strings
            .vehicle_date — str YYYYMM

        Raises LookupError if VIN or model not found.
        """
        ...

    @abstractmethod
    def get_model_year(self, vehicle) -> str:
        """Find the model year label for a vehicle (e.g. "'05MY")."""
        ...

    # ── VIN figures ───────────────────────────────────────────────────────

    @abstractmethod
    def get_vin_figures(self, vehicle) -> List[FigurePage]:
        """Get applicable figure pages for a vehicle."""
        ...

    # ── Figure info lookups ───────────────────────────────────────────────

    @abstractmethod
    def get_fig_info(self, model_rec, fig: str):
        """Look up figure illustration info.

        Returns object with .desc_en, .fig_group_code, or None.
        """
        ...

    @abstractmethod
    def get_figname(self, fig: str) -> str:
        """Get figure description by code."""
        ...

    @abstractmethod
    def get_fig_page(self, model_rec, fig: str, page: str):
        """Look up figure page metadata.

        Returns object with .image_size, .label, or None.
        """
        ...

    @abstractmethod
    def get_fig_category(self, model_rec, group_code: str):
        """Look up figure group category.

        Returns object with .desc_en, or None.
        """
        ...

    # ── Callouts and cross-references ─────────────────────────────────────

    @abstractmethod
    def get_fig_callouts(self, model_rec, fig: str, page: str,
                         vehicle=None) -> List[FigureCallout]:
        """Get callout coordinates + matched parts for a figure page."""
        ...

    @abstractmethod
    def get_fig_xrefs(self, model_rec, fig: str, page: str) -> List[FigureCrossRef]:
        """Get figure cross-reference arrows for a figure page."""
        ...

    # ── Raw record counts (for diagnostic display) ───────────────────────

    @abstractmethod
    def get_engine_specs(self, model_rec) -> list:
        """Engine spec / figure applicability records."""
        ...

    @abstractmethod
    def get_fig_illustration_pages(self, model_rec) -> list:
        """Figure page image metadata records."""
        ...

    @abstractmethod
    def get_fig_group_categories(self, model_rec) -> list:
        """Figure group category records."""
        ...

    @abstractmethod
    def get_fig_illustrations(self, model_rec) -> list:
        """Figure illustration description records."""
        ...

    @abstractmethod
    def get_part_groups(self, model_rec) -> list:
        """Part group callout records."""
        ...

    @abstractmethod
    def get_inventory_records(self, model_rec) -> list:
        """Inventory/hardware callout records."""
        ...

    @abstractmethod
    def get_catalog_parts(self, model_rec) -> list:
        """Parts catalog applicability records."""
        ...
