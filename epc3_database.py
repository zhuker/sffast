"""Epc3Database — EPC3 SQLite implementation of SubaruPartsDatabase.

Reads parts data from the Subaru EPC3 SQLite database (successor to FAST2).

Usage:
    db = Epc3Database.open("/path/to/master")
    vehicle = db.resolve_vin("JF1GD79M05G062133")
    pages = db.get_vin_figures(vehicle)
    db.close()
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from parts_database import (
    SubaruPartsDatabase,
    FigurePage,
    PartMatch,
    FigureCallout,
    FigureCrossRef,
)


# ── Lightweight record types (duck-compatible with FAST2 types) ───────────────


@dataclass
class Epc3VinRec:
    """VIN record from M_SYARYO. Attribute-compatible with VINModelRecord."""
    vin: str
    model_code: str
    body_model: str
    color_code: str
    trim_code: str
    option_code: str
    destination_code: str
    body_production_date: str          # BD_SEISAN_YMD (YYYYMMDD)
    engine_production_date: str = ''   # EG_SEISAN_YMD
    trans_production_date: str = ''    # TM_SEISAN_YMD


@dataclass
class Epc3ModelRec:
    """Model record for EPC3. Carries model_code + model_position for bitmask filtering."""
    model_code: str
    model_position: int
    model_name: str = ''
    series_code: str = ''
    start_date: str = ''
    end_date: str = ''


@dataclass
class Epc3SpecRec:
    """Spec record from M_SEKKEI_KATASHIKI. Attribute-compatible with ModelSpecRecord103."""
    applied_model: str
    body_config: str
    engine: str
    drivetrain: str
    transmission: str
    trim_level: str
    spec_option: str = ''


@dataclass
class Epc3Vehicle:
    """Vehicle resolved from EPC3 database. Attribute-compatible with parsers_common.Vehicle."""
    vin_rec: Epc3VinRec
    model_rec: Epc3ModelRec
    spec: Optional[Epc3SpecRec]
    codes: set
    vehicle_date: str


# ── Info types for figure metadata ────────────────────────────────────────────


@dataclass
class _FigInfo:
    """Return type for get_fig_info(). Has .desc_en, .fig_group_code."""
    desc_en: str
    fig_group_code: str


@dataclass
class _FigPageInfo:
    """Return type for get_fig_page(). Has .image_size, .label."""
    image_size: int
    label: str


@dataclass
class _FigCategoryInfo:
    """Return type for get_fig_category(). Has .desc_en."""
    desc_en: str


# ── Bitmask utilities ─────────────────────────────────────────────────────────


def _check_bitmask(applied_model_hex: str, position: int) -> bool:
    """Check if model position (1-based) is set in the 250-char hex bitmask."""
    if not applied_model_hex or position < 1:
        return False
    pos0 = position - 1  # 0-based
    byte_idx = pos0 // 8
    bit_idx = pos0 % 8
    hex_offset = byte_idx * 2
    if hex_offset + 2 > len(applied_model_hex):
        return False
    try:
        byte_val = int(applied_model_hex[hex_offset:hex_offset + 2], 16)
    except ValueError:
        return False
    return bool(byte_val & (0x80 >> bit_idx))


def _date_in_range(vehicle_yyyymm: str, start_yyyymmdd: str, end_yyyymmdd: str) -> bool:
    """Check if vehicle production date (YYYYMM) falls within an EPC3 date range (YYYYMMDD)."""
    if start_yyyymmdd:
        start = start_yyyymmdd[:6]
        if vehicle_yyyymm < start:
            return False
    if end_yyyymmdd:
        end = end_yyyymmdd[:6]
        if vehicle_yyyymm > end:
            return False
    return True


# ── Main database class ──────────────────────────────────────────────────────


class Epc3Database(SubaruPartsDatabase):
    """EPC3 SQLite implementation of SubaruPartsDatabase."""

    AREA_CD = 'L'
    KOKUNAI_FLG = '2'
    SUBARU_FLG = '1'

    def __init__(self, conn: sqlite3.Connection, area_cd: str = 'L') -> None:
        self._conn = conn
        self.AREA_CD = area_cd
        self._cache: dict = {}

    @classmethod
    def open(cls, path: str, area_cd: str = 'L', **kwargs) -> 'Epc3Database':
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return cls(conn, area_cd)

    def close(self) -> None:
        self._conn.close()

    def _area_filter(self) -> str:
        """SQL WHERE fragment for area/market filtering."""
        return f"AREA_CD = '{self.AREA_CD}' AND KOKUNAI_FLG = '{self.KOKUNAI_FLG}' AND SUBARU_FLG = '{self.SUBARU_FLG}'"

    def _q(self, sql: str, params=()) -> list:
        """Execute a query and return all rows as sqlite3.Row objects."""
        return self._conn.execute(sql, params).fetchall()

    # ── VIN resolution ────────────────────────────────────────────────────

    def resolve_vin(self, vin: str) -> Epc3Vehicle:
        if len(vin) < 17:
            raise LookupError(f"VIN too short: {vin}")

        prefix = vin[:11]
        seq = vin[11:]
        af = self._area_filter()

        # Find VIN record: exact prefix match, smallest VIN_AFTER >= sequence
        rows = self._q(f"""
            SELECT * FROM M_SYARYO
            WHERE VIN_BEFORE = ? AND VIN_AFTER >= ? AND {af}
            ORDER BY VIN_AFTER ASC LIMIT 1
        """, (prefix, seq))

        if not rows:
            # Fallback: closest prefix <= search prefix
            rows = self._q(f"""
                SELECT * FROM M_SYARYO
                WHERE VIN_BEFORE <= ? AND {af}
                ORDER BY VIN_BEFORE DESC LIMIT 1
            """, (prefix,))
            if rows and rows[0]['VIN_AFTER'] < seq:
                rows = []

        if not rows:
            raise LookupError(f"VIN {vin} not found in EPC3 database")

        r = rows[0]
        model_code = r['SHASHUCTLG']
        body_model = r['MODEL']
        model_position = r['MODEL_POSITION']

        vin_rec = Epc3VinRec(
            vin=vin,
            model_code=model_code,
            body_model=body_model,
            color_code=r['COLOR_CD'] or '',
            trim_code=r['TRIM_CD'] or '',
            option_code=r['OPTION_CD'] or '',
            destination_code=r['DESTINATION'] or '',
            body_production_date=r['BD_SEISAN_YMD'] or '',
            engine_production_date=r['EG_SEISAN_YMD'] or '',
            trans_production_date=r['TM_SEISAN_YMD'] or '',
        )

        # Model catalog
        model_rows = self._q(f"""
            SELECT * FROM M_SHASHUCTLG WHERE CODE = ? AND {af}
        """, (model_code,))
        if model_rows:
            mr = model_rows[0]
            model_rec = Epc3ModelRec(
                model_code=model_code,
                model_position=model_position,
                model_name=mr['NAME'] or '',
                series_code=mr['SHASHU_GROUP'] or '',
                start_date=mr['SAIYO_YM'] or '',
                end_date=mr['HAISHI_YM'] or '',
            )
        else:
            model_rec = Epc3ModelRec(model_code=model_code, model_position=model_position)

        # Spec codes from M_SEKKEI_KATASHIKI
        spec_rows = self._q(f"""
            SELECT * FROM M_SEKKEI_KATASHIKI
            WHERE SHASHUCTLG = ? AND MODEL_POSITION = ? AND {af}
        """, (model_code, model_position))

        spec = None
        codes = set()
        if spec_rows:
            sr = spec_rows[0]
            # KIGOU_1=BODY, KIGOU_2=ENGINE, KIGOU_3=TRAIN, KIGOU_4=MISSION,
            # KIGOU_5=GRADE, KIGOU_6=SUS, KIGOU_7=DESTINAT, ...
            kigou = {}
            for i in range(1, 24):
                k = f'KIGOU_{i}'
                try:
                    val = sr[k]
                except (IndexError, KeyError):
                    break
                if val:
                    kigou[i] = val
                    codes.add(val)

            spec = Epc3SpecRec(
                applied_model=sr['SEKKEI_KATASHIKI'] or body_model,
                body_config=kigou.get(1, ''),
                engine=kigou.get(2, ''),
                drivetrain=kigou.get(3, ''),
                transmission=kigou.get(4, ''),
                trim_level=kigou.get(5, ''),
                spec_option=kigou.get(6, ''),
            )

        vehicle_date = vin_rec.body_production_date[:6] if vin_rec.body_production_date else ''
        return Epc3Vehicle(
            vin_rec=vin_rec, model_rec=model_rec,
            spec=spec, codes=codes, vehicle_date=vehicle_date,
        )

    # ── Model year ────────────────────────────────────────────────────────

    def get_model_year(self, vehicle) -> str:
        body_model = vehicle.vin_rec.body_model
        model_code = vehicle.model_rec.model_code
        version_letter = body_model[3] if len(body_model) > 3 else ''
        if not version_letter:
            return ''
        af = self._area_filter()
        rows = self._q(f"""
            SELECT BIKOU FROM M_NENKAI
            WHERE SHASHUCTLG = ? AND VIEW_NENKAI = ? AND {af}
        """, (model_code, version_letter))
        if rows:
            label = rows[0]['BIKOU'] or ''
            return label.strip()
        return ''

    # ── VIN figures ───────────────────────────────────────────────────────

    def get_vin_figures(self, vehicle) -> List[FigurePage]:
        model_code = vehicle.model_rec.model_code
        model_position = vehicle.model_rec.model_position
        vehicle_date = vehicle.vehicle_date
        af = self._area_filter()

        rows = self._q(f"""
            SELECT FIG_NO, FIG_NUM, APPLIED_MODEL, SAIYOU_YM, HAISHI_YM, ILLUST_NOTE
            FROM M_ILLUST_NARROW
            WHERE SHASHUCTLG = ? AND {af}
            ORDER BY FIG_NO, FIG_NUM
        """, (model_code,))

        result = []
        for r in rows:
            if not _check_bitmask(r['APPLIED_MODEL'], model_position):
                continue
            if not _date_in_range(vehicle_date, r['SAIYOU_YM'] or '', r['HAISHI_YM'] or ''):
                continue
            page_num = int(r['FIG_NUM']) if r['FIG_NUM'] and r['FIG_NUM'].isdigit() else 0
            page_type = 'bulletin' if page_num >= 40 else 'figure'
            result.append(FigurePage(
                figure=r['FIG_NO'],
                page=r['FIG_NUM'],
                type=page_type,
            ))
        return result

    # ── Figure info lookups ───────────────────────────────────────────────

    def get_fig_info(self, model_rec, fig: str):
        model_code = model_rec.model_code
        key = ('fig_info', model_code, fig)
        if key in self._cache:
            return self._cache[key]

        af = self._area_filter()

        # Get figure name
        desc = ''
        rows = self._q(f"""
            SELECT FIG_NAME FROM M_FIG_NAME
            WHERE FIG_NO = ? AND LANGUAGE = 'ENG' AND {af}
        """, (fig,))
        if rows:
            desc = rows[0]['FIG_NAME'] or ''

        # Get figure group
        group_code = ''
        rows = self._q(f"""
            SELECT FIG_GROUP FROM M_FIG_GROUP
            WHERE SHASHUCTLG = ? AND FIG_NO = ? AND {af}
        """, (model_code, fig))
        if rows:
            group_code = rows[0]['FIG_GROUP'] or ''

        if not desc and not group_code:
            self._cache[key] = None
            return None

        info = _FigInfo(desc_en=desc, fig_group_code=group_code)
        self._cache[key] = info
        return info

    def get_figname(self, fig: str) -> str:
        af = self._area_filter()
        rows = self._q(f"""
            SELECT FIG_NAME FROM M_FIG_NAME
            WHERE FIG_NO = ? AND LANGUAGE = 'ENG' AND {af}
        """, (fig,))
        return rows[0]['FIG_NAME'] if rows else ''

    def get_fig_page(self, model_rec, fig: str, page: str):
        model_code = model_rec.model_code
        key = ('fig_page', model_code, fig, page)
        if key in self._cache:
            return self._cache[key]

        af = self._area_filter()
        rows = self._q(f"""
            SELECT WIDTH, HEIGHT, length(ILLUST) as img_len
            FROM M_ILLUST_IMAGE
            WHERE SHASHUCTLG = ? AND FIG_NO = ? AND FIG_NUM = ? AND {af}
        """, (model_code, fig, page))

        if not rows:
            self._cache[key] = None
            return None

        # Get label from M_ILLUST_NARROW
        label = ''
        narrow_rows = self._q(f"""
            SELECT ILLUST_NOTE FROM M_ILLUST_NARROW
            WHERE SHASHUCTLG = ? AND FIG_NO = ? AND FIG_NUM = ? AND {af}
            LIMIT 1
        """, (model_code, fig, page))
        if narrow_rows:
            raw = narrow_rows[0]['ILLUST_NOTE'] or ''
            label = ' '.join(raw.split())

        info = _FigPageInfo(image_size=rows[0]['img_len'] or 0, label=label)
        self._cache[key] = info
        return info

    def get_fig_category(self, model_rec, group_code: str):
        key = ('fig_cat', group_code)
        if key in self._cache:
            return self._cache[key]

        af = self._area_filter()
        rows = self._q(f"""
            SELECT FIG_GROUP_NAME FROM M_FIG_GROUP_NAME
            WHERE FIG_GROUP = ? AND LANGUAGE = 'ENG' AND {af}
        """, (group_code,))

        if not rows:
            self._cache[key] = None
            return None

        info = _FigCategoryInfo(desc_en=rows[0]['FIG_GROUP_NAME'] or '')
        self._cache[key] = info
        return info

    # ── Callouts and cross-references ─────────────────────────────────────

    def _get_filtered_parts(self, model_rec, vehicle, fig: str = None, page: str = None):
        """Get parts from M_PARTS_CATALOG filtered by bitmask + date.

        Returns list of (row_dict, variant) tuples.
        """
        model_code = model_rec.model_code
        model_position = model_rec.model_position
        vehicle_date = vehicle.vehicle_date
        af = self._area_filter()

        sql = f"""
            SELECT PARTS_CODE, PARTS_NUMBER, APPLIED_MODEL, NENKAI,
                   SAIYOU_YMD, HAISHI_YMD, FIG_NO, FIG_NUM,
                   KATASHIKI, TEKIYOU, KOSHOKU_SHOGEN, SOUBETSU_RANK,
                   GOTAIOU_PARTS_NUMBER, COLOR_CODE, TRIM_CODE, DESTINATION
            FROM M_PARTS_CATALOG
            WHERE SHASHUCTLG = ? AND {af}
        """
        params = [model_code]
        if fig is not None:
            sql += " AND FIG_NO = ?"
            params.append(fig)
        if page is not None:
            sql += " AND FIG_NUM = ?"
            params.append(page)

        rows = self._q(sql, params)
        result = []
        for r in rows:
            if not _check_bitmask(r['APPLIED_MODEL'], model_position):
                continue
            if not _date_in_range(vehicle_date, r['SAIYOU_YMD'] or '', r['HAISHI_YMD'] or ''):
                continue
            # TODO: color, trim, option, destination filtering (stages 3-6)
            result.append(dict(r))
        return result

    def _get_part_desc(self, parts_code: str) -> str:
        """Look up English part description from M_PARTS_NAME."""
        key = ('part_desc', parts_code)
        if key in self._cache:
            return self._cache[key]
        af = self._area_filter()
        # Strip variant suffix if present (e.g. "11021" from "11021*C")
        code = parts_code.split('*')[0] if '*' in parts_code else parts_code
        rows = self._q(f"""
            SELECT PARTS_CODE_NAME FROM M_PARTS_NAME
            WHERE PARTS_CODE = ? AND LANGUAGE = 'ENG' AND {af}
        """, (code,))
        desc = rows[0]['PARTS_CODE_NAME'] if rows else ''
        self._cache[key] = desc
        return desc

    def get_fig_callouts(self, model_rec, fig: str, page: str,
                         vehicle=None) -> List[FigureCallout]:
        model_code = model_rec.model_code
        af = self._area_filter()

        # 1. Get callout coordinates from M_ILLUST KUBUN=3
        illust_rows = self._q(f"""
            SELECT DATA, START_X, START_Y, END_X, END_Y
            FROM M_ILLUST
            WHERE SHASHUCTLG = ? AND FIG_NO = ? AND FIG_NUM = ? AND KUBUN = '3' AND {af}
        """, (model_code, fig, page))

        # 2. Get matching parts (filtered by vehicle)
        parts_by_callout: dict[str, list[dict]] = defaultdict(list)
        if vehicle:
            filtered = self._get_filtered_parts(model_rec, vehicle, fig, page)
            for pr in filtered:
                code = pr['PARTS_CODE']
                if code:
                    parts_by_callout[code].append(pr)

        # 3. Build callout list
        callouts: list[FigureCallout] = []
        for r in illust_rows:
            data = r['DATA'] or ''
            if not data:
                continue

            # Parse callout code and variant from DATA (e.g. "11021*C", "B50607")
            if '*' in data:
                callout_code, variant = data.split('*', 1)
            else:
                callout_code = data
                variant = ''

            # Coordinates: EPC3 uses bounding boxes, convert to center point
            try:
                sx, sy = int(r['START_X']), int(r['START_Y'])
                ex, ey = int(r['END_X']), int(r['END_Y'])
                px_x = (sx + ex) // 2
                px_y = (sy + ey) // 2
            except (ValueError, TypeError):
                continue

            desc = self._get_part_desc(callout_code)

            # Match parts
            part_list: list[PartMatch] = []
            entries = parts_by_callout.get(callout_code, [])
            seen: set = set()
            for pr in entries:
                pn = pr['PARTS_NUMBER'] or ''
                dedup_key = (callout_code, pn)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                part_desc = desc or self._get_part_desc(callout_code)
                part_list.append(PartMatch(
                    part_number=pn,
                    description=part_desc,
                    variant=variant,
                    usage_notes=pr['TEKIYOU'] or '',
                    part_spec=pr['KOSHOKU_SHOGEN'] or '',
                ))

            callouts.append(FigureCallout(
                callout_code=callout_code,
                variant=variant,
                px_x=px_x,
                px_y=px_y,
                description=desc,
                parts=part_list,
                source='part_group',
            ))

        return callouts

    def get_fig_xrefs(self, model_rec, fig: str, page: str) -> List[FigureCrossRef]:
        model_code = model_rec.model_code
        af = self._area_filter()

        rows = self._q(f"""
            SELECT DATA, START_X, START_Y, END_X, END_Y
            FROM M_ILLUST
            WHERE SHASHUCTLG = ? AND FIG_NO = ? AND FIG_NUM = ? AND KUBUN = '1' AND {af}
        """, (model_code, fig, page))

        xrefs = []
        for r in rows:
            ref_fig = (r['DATA'] or '').strip()
            if not ref_fig:
                continue
            try:
                sx, sy = int(r['START_X']), int(r['START_Y'])
                ex, ey = int(r['END_X']), int(r['END_Y'])
                px_x = (sx + ex) // 2
                px_y = (sy + ey) // 2
            except (ValueError, TypeError):
                continue
            xrefs.append(FigureCrossRef(ref_figure=ref_fig, px_x=px_x, px_y=px_y))
        return xrefs

    # ── Count accessors ───────────────────────────────────────────────────

    def _count_cached(self, cache_key: str, sql: str, params=()) -> list:
        """Query and cache rows for count accessors."""
        if cache_key in self._cache:
            return self._cache[cache_key]
        rows = self._q(sql, params)
        self._cache[cache_key] = rows
        return rows

    def get_engine_specs(self, model_rec) -> list:
        model_code = model_rec.model_code
        af = self._area_filter()
        return self._count_cached(
            ('engine_specs', model_code),
            f"SELECT FIG_NO, FIG_NUM FROM M_ILLUST_NARROW WHERE SHASHUCTLG = ? AND {af}",
            (model_code,),
        )

    def get_fig_illustration_pages(self, model_rec) -> list:
        model_code = model_rec.model_code
        af = self._area_filter()
        return self._count_cached(
            ('fig_pages', model_code),
            f"SELECT FIG_NO, FIG_NUM FROM M_ILLUST_IMAGE WHERE SHASHUCTLG = ? AND {af}",
            (model_code,),
        )

    def get_fig_group_categories(self, model_rec) -> list:
        af = self._area_filter()
        return self._count_cached(
            ('fig_group_cats',),
            f"SELECT DISTINCT FIG_GROUP FROM M_FIG_GROUP_NAME WHERE LANGUAGE = 'ENG' AND {af}",
        )

    def get_fig_illustrations(self, model_rec) -> list:
        model_code = model_rec.model_code
        af = self._area_filter()
        return self._count_cached(
            ('fig_illustrations', model_code),
            f"SELECT DISTINCT FIG_NO FROM M_FIG_GROUP WHERE SHASHUCTLG = ? AND {af}",
            (model_code,),
        )

    def get_part_groups(self, model_rec) -> list:
        model_code = model_rec.model_code
        af = self._area_filter()
        return self._count_cached(
            ('part_groups', model_code),
            f"SELECT ID FROM M_ILLUST WHERE SHASHUCTLG = ? AND KUBUN = '3' AND {af}",
            (model_code,),
        )

    def get_inventory_records(self, model_rec) -> list:
        # EPC3 doesn't have a separate inventory table; hardware callouts
        # are in M_ILLUST KUBUN=3 alongside part callouts.
        return []

    def get_catalog_parts(self, model_rec) -> list:
        model_code = model_rec.model_code
        af = self._area_filter()
        return self._count_cached(
            ('catalog_parts', model_code),
            f"SELECT ID FROM M_PARTS_CATALOG WHERE SHASHUCTLG = ? AND {af}",
            (model_code,),
        )
