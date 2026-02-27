# Subaru EPC3 SQLite Database Format

Analysis of `SUBARU_EPC3_EUR_GEN_0519/master` — the next-generation Subaru parts catalog database, successor to the FAST2 `sffastus` binary format.

## Overview

- **Format**: SQLite 3.x (v3.20.1), page size 1024, ~3GB
- **Version**: `1905` (DVD_CREATE_DATE: 2019-04-17), app version `1.2.0`
- **Application**: Java WAR web app (`subaru-epc.war.zip`), uses `System.Data.SQLite.dll` for desktop client
- **Encoding**: UTF-8
- **Markets**: Multi-market via `AREA_CD` column (L=LHD, R=RHD)

Every table has three discriminator columns:
- `AREA_CD` — market (L=LHD, R=RHD)
- `KOKUNAI_FLG` — domestic flag (always `2` in this dataset)
- `SUBARU_FLG` — Subaru flag (always `1` in this dataset)

## Key Architecture Differences from sffastus

| Aspect | sffastus (FAST2) | EPC3 SQLite |
|--------|-----------------|-------------|
| Format | Custom binary, 2048-byte blocks, encoded pointers | Standard SQLite |
| Spec logic | Text expressions (`EJ22# +EJ25D`, `.MT`) | 250-byte hex bitmask, 1 bit per model position |
| Images | CCITT Group 4 raw, custom pointer encoding | Base64-encoded PNG in TEXT columns |
| Figure callouts | PartGroupRecord185 + InventoryRecord199 | Unified `M_ILLUST` table with KUBUN discriminator |
| Cross-refs | FigureIndexRecord22 | `M_ILLUST` with KUBUN=1 |
| ITCA | Separate `ITCA_DATA.TXT` flat file | `M_EXCHANGE_PARTS` table |
| Market | US-only (SFCDUS*) | Multi-market via AREA_CD |
| VIN records | 38-byte binary VIN ranges | `M_SYARYO` with VIN_BEFORE/VIN_AFTER columns |
| Callout coords | Center point (x,y) | Bounding box (START_X, START_Y, END_X, END_Y) |

## Table-to-sffastus Record Mapping

| EPC3 Table | Rows | sffastus Equivalent | Purpose |
|------------|------|--------------------|---------|
| M_SYARYO | 3,950,027 | VINRecord + VINModelRecord69 | VIN → vehicle resolution |
| M_SHASHUCTLG | 43 | ModelIndexRecord288 | Model catalog |
| M_PARTS_CATALOG | 2,561,821 | CatalogApplicabilityRecord466 | Parts applicability |
| M_PARTS_NAME | 104,968 | MultilingualPartRecord180/182/192 | Part descriptions (4 languages) |
| M_EXCHANGE_PARTS | 204,634 | ItcaRecord251 | Part supersession (ITCA) |
| M_FIG_NAME | 2,040 | figname.txt | Figure names |
| M_FIG_GROUP_NAME | 136 | FIGGroupCategoryRecord184 | Figure group names |
| M_FIG_GROUP | 7,135 | FIGGroupCategoryRecord184 (partial) | Model → figure group → figures |
| M_ILLUST (KUBUN=3) | 285,579 | PartGroupRecord185 + InventoryRecord199 | Callout coordinates |
| M_ILLUST (KUBUN=1) | 17,010 | FigureIndexRecord22 | Figure cross-references |
| M_ILLUST (KUBUN=4) | 18,555 | (new) | Multi-figure references |
| M_ILLUST_IMAGE | 21,773 | FIGIllustrationPage89 + G4 data | Figure images (base64 PNG) |
| M_ILLUST_NARROW | 21,773 | EngineSpecRecord230 | Figure applicability |
| M_COLOR_NAME | 11,608 | ColorRecord91 | Color codes (4 languages) |
| M_NENKAI | 237 | ModelYearRecord44 | Model year versions |
| M_SEKKEI_KATASHIKI | 1,520 | ModelSpecRecord103 | Design model → spec mapping |
| M_TOKUCHO_KUBUN | 247 | (categories in ModelIndexRecord288) | Spec category names |
| M_TOKUCHO_KIGOU | 869 | (embedded in spec logic) | Spec code values with bitmask |
| M_MODEL | 5,005 | BodyModelRecord17 | Body model → position mapping |
| M_KIGOU_RYAKUGO | 5,069 | VariantGlossaryRecord81 | Abbreviation glossary |
| M_OPTION_CODE | 2,698 | SpecMappingRecord22 | Option code → position |
| M_OP_HYOUGEN | 6,776 | (usage notes in Cat466) | Option expression lookup |
| M_DAIHYO_FIG | 128,420 | (no equivalent) | Parts code → representative figure |
| M_PARTS_WORD | 1,543,051 | CodeIndexRecord33 | Keyword search index |
| M_ZENTAIZU / _IMAGE | 717 / 43 | (body model illustration) | Full-vehicle clickable diagrams |
| M_EMOKUJI | 7,958 | (no equivalent) | Pictorial index thumbnails |
| M_PRICE / M_SHIKIRI | 0 / 0 | (no equivalent) | Price data (empty) |
| M_ACCIDENT_GROUP/NAME/IMAGE | 2,198/varies/82 | (no equivalent) | Accident repair groups |
| M_TENKEN | 5,305 | (no equivalent) | Inspection/maintenance records |
| M_KIRIKAE | 0 | (no equivalent) | Switchover data (empty) |

## Table Schemas

### M_SYARYO — VIN Records (3.95M rows)

Maps VIN ranges to vehicle specifications. Equivalent to sffastus VINRecord (38-byte) + VINModelRecord (69-byte).

```sql
CREATE TABLE M_SYARYO (
    ID INTEGER PRIMARY KEY,
    VIN_BEFORE TEXT,           -- VIN range start (11 chars, e.g. "JF1GD70655L")
    VIN_AFTER TEXT,            -- VIN range end (sequence number, e.g. "510047")
    SHASHUCTLG TEXT,           -- model code (e.g. "G11")
    OEM_SYASYU_CD TEXT,        -- OEM vehicle code
    MODEL TEXT,                -- body model (e.g. "GD4AL3G")  [≈ VINModelRecord.body_model]
    KATASHIKI_RUIBETSU TEXT,   -- model classification
    COLOR_CD TEXT,             -- color code (e.g. "02C")      [≈ VINModelRecord.color_code]
    TRIM_CD TEXT,              -- trim code (e.g. "H20")       [≈ VINModelRecord.trim_code]
    OPTION_CD TEXT,            -- option code (e.g. "NX")      [≈ VINModelRecord.option_code]
    SHIYO_PATTERN_NO TEXT,     -- spec pattern number
    MODEL_POSITION INTEGER,    -- position in bitmask
    BD_SEISAN_YMD TEXT,        -- body production date (YYYYMMDD)   [≈ VINModelRecord.date1]
    EG_SEISAN_YMD TEXT,        -- engine production date (YYYYMMDD) [≈ VINModelRecord.date2]
    TM_SEISAN_YMD TEXT,        -- transmission prod date (YYYYMMDD) [≈ VINModelRecord.date3]
    DESTINATION TEXT,          -- destination code (e.g. "EC")      [≈ VINModelRecord.destination_code]
    KUBUN TEXT,                -- classification
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
-- Indexed on (VIN_BEFORE, VIN_AFTER, SHASHUCTLG, AREA_CD, KOKUNAI_FLG, SUBARU_FLG)
```

VIN prefixes found: `4S3`, `4S4`, `JF1`, `JF2`, `JF3` (new), plus some blank entries.

Model coverage by VIN count:
- S13 (Forester): 419K, S12: 358K, B13 (Legacy): 241K, G33 (XV): 241K
- B14: 220K, G11 (Impreza): 220K, S11: 226K, G10: 205K

### M_SHASHUCTLG — Model Catalog (43 rows)

Master list of all vehicle models. Equivalent to ModelIndexRecord288.

```sql
CREATE TABLE M_SHASHUCTLG (
    CODE TEXT,                 -- model code (e.g. "G11")      [≈ model_code]
    NAME TEXT,                 -- model name (e.g. "IMPREZA")  [≈ model_name]
    SAIYO_YM TEXT,             -- start date YYYYMM             [≈ start_date]
    HAISHI_YM TEXT,            -- end date YYYYMM (empty=current) [≈ end_date]
    SHASHU_GROUP TEXT,         -- series code (e.g. "G")        [≈ series_code]
    SHAKAKU TEXT,              -- (empty in dataset)
    DAIHYO TEXT,               -- chassis code patterns (e.g. "GD#,GG#")
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT,
    PRIMARY KEY (CODE, AREA_CD, KOKUNAI_FLG, SUBARU_FLG)
);
```

Models in EPC3 not in sffastus SFCDUS2:
- A10 (L Series 1985-94), B10 (Legacy 1989-94), B14 (Legacy 2009-14), B15 (Legacy 2014+)
- C11 (SVX early), D10 (E Series), D11 (E12)
- G12-G14 (newer Impreza), G22-G24 (Impreza variants), G33-G34, G43 (XV/Crosstrek)
- J10 (Justy), R10-R13 (kei: M70/M80/Vivio)
- S13-S14, S23-S24 (newer Forester), V10 (WRX/Levorg), Y10 (Exiga), Z10 (BRZ)

### M_PARTS_CATALOG — Parts Applicability (2.56M rows)

The main parts catalog. Equivalent to CatalogApplicabilityRecord466.

```sql
CREATE TABLE M_PARTS_CATALOG (
    ID INTEGER PRIMARY KEY,
    SHASHUCTLG TEXT,           -- model code                    [≈ model_code]
    OEM_SHASHU_CODE TEXT,      -- OEM vehicle code
    PARTS_CODE TEXT,           -- callout code (e.g. "11021")   [≈ callout_code]
    PARTS_NUMBER TEXT,         -- part number (e.g. "11021AA020") [≈ part_id]
    NENKAI TEXT,               -- model year version (A,B,C...) [≈ date_flag]
    SAIYOU_YMD TEXT,           -- adoption date YYYYMMDD        [≈ date range start]
    HAISHI_YMD TEXT,           -- discontinue date YYYYMMDD     [≈ date range end]
    ILLUST_KIGOU TEXT,         -- illustration symbol
    QUANTITY TEXT,              -- quantity (e.g. "01")
    FIG_GROUP TEXT,            -- figure group (e.g. "0A")
    FIG_NO TEXT,               -- figure number (e.g. "004")    [≈ figure_ref]
    FIG_NUM TEXT,              -- figure page (e.g. "02")       [≈ figure_page]
    COLOR_CODE TEXT,           -- color restriction
    TRIM_CODE TEXT,            -- trim restriction
    TEKIYOGAI_KUBUN TEXT,      -- applicability classification
    KIRIKAE_FROM TEXT,         -- switchover from
    KIRIKAE_TO TEXT,           -- switchover to
    APPLIED_MODEL TEXT,        -- 250-char hex bitmask          [≈ spec_logic — SEE BELOW]
    OP_FLG TEXT,               -- option flag ("*" = has option condition)
    OPTION_POSITION TEXT,      -- option position hex (25 bytes) [new]
    SHIYOU_PATTERN_NO TEXT,    -- spec pattern number
    DESTINATION TEXT,          -- destination codes              [≈ destination_codes]
    KATASHIKI TEXT,            -- spec expression (e.g. "161 +20#") [≈ spec_logic text form]
    TEKIYOU TEXT,              -- usage notes                   [≈ usage_notes]
    KOYU_SHOGEN TEXT,          -- specific evidence
    KOSHOKU_SHOGEN TEXT,       -- decorative evidence           [≈ part_spec]
    TANKA TEXT,                -- unit price code
    SOUBETSU_RANK TEXT,        -- packaging rank                [≈ supplier_code]
    HANBAI_JOKEN TEXT,         -- sales conditions
    GOTAIOU_PARTS_NUMBER TEXT, -- corresponding part number     [≈ related_part]
    GOTAIOU_JOKEN TEXT,        -- corresponding condition
    ZAIKO TEXT,                -- inventory status
    TOKUSETSU TEXT,            -- special note
    LINE_OP1..LINE_OP5 TEXT,   -- line option flags
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### Bitmask Spec Logic (APPLIED_MODEL)

The biggest change from sffastus. Instead of text expressions, applicability uses a **250-character hex string** (125 bytes = 1000 bits). Each bit corresponds to a `MODEL_POSITION` from `M_MODEL`.

Example for G11: `FFF00000...FFFC0000...` means positions 1-12 and 201-214 are set (all sedan + wagon variants).

To check if a part applies to a vehicle:
1. Get the vehicle's `MODEL_POSITION` from `M_MODEL` (via body model code)
2. Convert APPLIED_MODEL hex to bytes
3. Check if bit at position N is set: `byte[N // 8] & (0x80 >> (N % 8))`

Model positions 1-47 = Sedan (GD#), 201-237 = Wagon (GG#) for G11.

The `KATASHIKI` column preserves a human-readable version (e.g. "161 +20#"), but the bitmask is the authoritative source for filtering.

### M_PARTS_NAME — Part Descriptions (105K rows)

Multilingual part names. Equivalent to MultilingualPartRecord180/182/192.

```sql
CREATE TABLE M_PARTS_NAME (
    ID INTEGER PRIMARY KEY,
    PARTS_CODE TEXT,           -- callout code (e.g. "96001A")
    PARTS_CODE_NAME TEXT,      -- description (e.g. "GARNISH-REAR QUARTER,LEFT")
    LANGUAGE TEXT,             -- ENG, GER, FRA, SPA
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

4 languages × 26,242 parts = 104,968 rows.

### M_EXCHANGE_PARTS — ITCA Supersession (205K rows)

Part interchange data. Equivalent to ItcaRecord251.

```sql
CREATE TABLE M_EXCHANGE_PARTS (
    ID INTEGER PRIMARY KEY,
    PARTS_NUMBER TEXT,           -- current part number       [≈ part_number]
    EXCHANGE_PARTS_NUMBER TEXT,  -- supersedes to             [≈ supersedes_to]
    PARTS_CODE_NAME TEXT,        -- description               [≈ description]
    HYOUZI_ORDER INTEGER,        -- display order
    JOKEN TEXT,                  -- ITCA condition code (1-9) [≈ itca_code]
    PARTS_CODE TEXT,             -- parts code                [≈ part_code]
    QUANTITY TEXT,                -- quantity                  [≈ quantity]
    TEKIYOU TEXT,                -- application notes
    ZAIKO TEXT,                  -- inventory status
    SOUBETSU_RANK TEXT,          -- packaging rank
    TANKA TEXT,                  -- price code
    KIGOU TEXT,                  -- symbol/mark
    HANBAI_AREA TEXT,            -- sales area
    TEKIYOU_DATE TEXT,           -- application date
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

JOKEN (condition) code distribution:
- 2 (new→old): 135,084 — most common
- 1 (mutual): 31,560
- 6 (w/other parts): 18,782
- 9 (compulsory): 9,516
- 4 (simple mod): 3,284
- 7 (both sides): 2,720
- 3 (old→new): 2,336
- 8 (kit): 1,332
- 5: 20 (rare, not in sffastus ItcaCode enum)

### M_ILLUST — Callout Coordinates (321K rows)

Unified table for all figure annotations. Replaces three separate sffastus record types.

```sql
CREATE TABLE M_ILLUST (
    ID INTEGER PRIMARY KEY,
    SHASHUCTLG TEXT,           -- model code
    FIG_NO TEXT,               -- figure number (e.g. "004")
    FIG_NUM TEXT,              -- figure page (e.g. "01")
    KUBUN TEXT,                -- type discriminator (see below)
    DATA TEXT,                 -- content (varies by KUBUN)
    START_X TEXT,              -- bounding box left X
    START_Y TEXT,              -- bounding box top Y
    END_X TEXT,                -- bounding box right X
    END_Y TEXT,                -- bounding box bottom Y
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

**KUBUN values:**
- **KUBUN=3** (285,579 rows): Part callouts. DATA = callout code, optionally with variant suffix after `*` (e.g. "11021\*A", "0370S\*B", "25240"). Equivalent to PartGroupRecord185 + InventoryRecord199.
- **KUBUN=1** (17,010 rows): Figure cross-references. DATA = target figure number (e.g. "010", "004"). Equivalent to FigureIndexRecord22.
- **KUBUN=4** (18,555 rows): Multi-figure references. DATA = 9-char encoded string, likely pairs of fig+page references.

Coordinates are bounding boxes (START_X, START_Y, END_X, END_Y) on the 1280×640 image, unlike sffastus which stored center points that needed dividing by 2.

### M_ILLUST_IMAGE — Figure Images (22K rows)

Figure page images stored as base64-encoded PNG.

```sql
CREATE TABLE M_ILLUST_IMAGE (
    SHASHUCTLG TEXT,           -- model code
    FIG_NO TEXT,               -- figure number
    FIG_NUM TEXT,              -- figure page
    WIDTH TEXT,                -- image width (always "1280")
    HEIGHT TEXT,               -- image height (always "640")
    ILLUST TEXT,               -- base64-encoded PNG data
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

To extract an image:
```python
import base64
png_bytes = base64.b64decode(illust_text)
# Write directly as .png file
```

Image sizes range from ~8KB to ~24KB (compressed PNG, 1-bit black & white line drawings).

### M_ILLUST_NARROW — Figure Applicability (22K rows)

Controls which figures appear for which vehicles. Equivalent to EngineSpecRecord230.

```sql
CREATE TABLE M_ILLUST_NARROW (
    SHASHUCTLG TEXT,           -- model code
    FIG_NO TEXT,               -- figure number                [≈ figure]
    FIG_NUM TEXT,              -- figure page                  [≈ figure_page]
    ILLUST_NOTE TEXT,          -- page label/description       [≈ applicable_model text part]
    TEKIYO_SHASHU TEXT,        -- spec codes (e.g. "154 +161") [≈ spec logic text]
    SAIYOU_YM TEXT,            -- adoption date YYYYMM         [≈ start_date]
    HAISHI_YM TEXT,            -- discontinue date YYYYMM      [≈ end_date]
    APPLIED_MODEL TEXT,        -- 250-char hex bitmask
    GOKAN_FLG TEXT,            -- compatibility flag ("0" or "1")
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT,
    HANSHITA_NO TEXT           -- plate number
);
```

### M_NENKAI — Model Year Versions (237 rows)

Model year date ranges. Equivalent to ModelYearRecord44.

```sql
CREATE TABLE M_NENKAI (
    SHASHUCTLG TEXT,           -- model code                   [≈ model_code]
    VIEW_NENKAI TEXT,          -- display version letter        [≈ version]
    NENKAI TEXT,               -- internal version letter
    SAIYO_YMD TEXT,            -- start date YYYYMMDD           [≈ date_from]
    HAISHI_YMD TEXT,           -- end date YYYYMMDD             [≈ date_to]
    BIKOU TEXT,                -- label (e.g. "'01MY")          [≈ label]
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_SEKKEI_KATASHIKI — Design Model Specs (1,520 rows)

Maps design model codes to spec category values. Equivalent to ModelSpecRecord103.

```sql
CREATE TABLE M_SEKKEI_KATASHIKI (
    SHASHUCTLG TEXT,           -- model code
    SEKKEI_KATASHIKI TEXT,     -- design model (e.g. "GD4-K3G") [≈ applied_model]
    SAIYOU_YM TEXT,            -- adoption date YYYYMM
    HAISHI_YM TEXT,            -- discontinue date YYYYMM
    OEM_SYASYU_CD TEXT,        -- OEM vehicle code
    MODEL_POSITION INTEGER,    -- position in bitmask
    KIGOU_1..KIGOU_23 TEXT,    -- spec values for each KUBUN category
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

KIGOU_1 through KIGOU_23 map to M_TOKUCHO_KUBUN categories:
- KIGOU_1 = BODY (e.g. "S"=Sedan, "W"=Wagon)
- KIGOU_2 = ENGINE (e.g. "161"=EJ161, "205"=EJ205)
- KIGOU_3 = TRAIN (e.g. "2W"=2WD, "4W"=4WD)
- KIGOU_4 = MISSION (e.g. "5MT", "AT")
- KIGOU_5 = GRADE (e.g. "BASE", "TS", "STI")
- KIGOU_6 = SUS (e.g. "N/S"=Non-Sunroof)
- KIGOU_7+ = additional categories (DESTINAT, etc.)

### M_TOKUCHO_KIGOU — Spec Code Definitions (869 rows)

Defines each spec code value with its bitmask applicability.

```sql
CREATE TABLE M_TOKUCHO_KIGOU (
    SHASHUCTLG TEXT,           -- model code
    KUBUN_NUMBER TEXT,         -- category number (1=BODY, 2=ENGINE, etc.)
    KIGOU TEXT,                -- code value (e.g. "S", "161", "5MT")
    KIGOU_ORDER TEXT,          -- sort order
    KIGOU_NAME TEXT,           -- description (e.g. "SEDAN", "1600CC EMPI SOHC NA")
    APPLIED_POSITION TEXT,     -- 250-char hex bitmask of applicable model positions
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_COLOR_NAME — Color Codes (11,608 rows)

Paint/trim color names. Equivalent to ColorRecord91.

```sql
CREATE TABLE M_COLOR_NAME (
    SHASHUCTLG TEXT,           -- model code                   [≈ model_code]
    NENKAI TEXT,               -- model year version
    KUBUN TEXT,                -- "C" for color
    CODE TEXT,                 -- color code (e.g. "02C")      [≈ paint_code]
    LANGUAGE TEXT,             -- ENG, GER, FRA, SPA
    NAME TEXT,                 -- color name (e.g. "WR BLUE MICA") [≈ color_name_en]
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_MODEL — Body Model Positions (5,005 rows)

Maps body model codes to bitmask positions. Equivalent to BodyModelRecord17.

```sql
CREATE TABLE M_MODEL (
    ID INTEGER PRIMARY KEY,
    SHASHUCTLG TEXT,           -- model code
    MODEL TEXT,                -- body model code (e.g. "GD4AL3G") [≈ body_model]
    MODEL_POSITION INTEGER,    -- bit position in APPLIED_MODEL bitmask
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

Multiple body model codes can share the same MODEL_POSITION (e.g. different model year variants of the same configuration).

### M_FIG_GROUP_NAME — Figure Group Names (136 rows)

```sql
CREATE TABLE M_FIG_GROUP_NAME (
    FIG_GROUP TEXT,            -- group code (e.g. "0A")
    FIG_GROUP_NAME TEXT,       -- name (e.g. "ENGINE MAIN")
    LANGUAGE TEXT,             -- ENG, GER, FRA, SPA
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

Groups: 0A (ENGINE MAIN), 0B (ENGINE AUXILIARIES), 0C (ENGINE ELECTRICAL), 1A (MANUAL TRANS), 1B (AUTO TRANS), 1C (DIFFERENTIAL), 2A (SUSPENSION/BRAKE), 3A (STEERING), etc.

### M_FIG_GROUP — Figure-to-Group Mapping (7,135 rows)

```sql
CREATE TABLE M_FIG_GROUP (
    ID INTEGER PRIMARY KEY,
    SHASHUCTLG TEXT,           -- model code
    FIG_GROUP TEXT,            -- group code (e.g. "0A")
    FIG_NO TEXT,               -- figure number (e.g. "004")
    START_X TEXT,              -- clickable region on group index image
    START_Y TEXT,
    END_X TEXT,
    END_Y TEXT,
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_KIGOU_RYAKUGO — Abbreviation Glossary (5,069 rows)

Equivalent to VariantGlossaryRecord81.

```sql
CREATE TABLE M_KIGOU_RYAKUGO (
    SHASHUCTLG TEXT,           -- model code
    KIGOU TEXT,                -- abbreviation (e.g. "161 (EJ161)")
    IMI TEXT,                  -- meaning (e.g. "1600CC EMPI SOHC NA")
    HYOUZI_ORDER INTEGER,      -- display order
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_OP_HYOUGEN — Option Expressions (6,776 rows)

Maps option codes to human-readable descriptions per model year.

```sql
CREATE TABLE M_OP_HYOUGEN (
    SHASHUCTLG TEXT,           -- model code
    NENKAI TEXT,               -- model year version (A,B,C...)
    LINE_OP TEXT,              -- option code (e.g. "AICNO", "BRSDO")
    HYOUGEN TEXT,              -- expression (e.g. "FOR A/C", "FOR ABS")
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

Pattern: code ending in "O" = "FOR xxx", ending in "X" = "EXC.xxx".

### M_DAIHYO_FIG — Representative Figure (128,420 rows)

Maps parts codes to their primary figure (no sffastus equivalent).

```sql
CREATE TABLE M_DAIHYO_FIG (
    SHASHUCTLG TEXT,
    PARTS_CODE TEXT,           -- callout code
    FIG_NO TEXT,               -- representative figure number
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_PARTS_WORD — Search Keywords (1.54M rows)

Full-text search index. Equivalent to CodeIndexRecord33.

```sql
CREATE TABLE M_PARTS_WORD (
    ID INTEGER PRIMARY KEY,
    SHASHUCTLG TEXT,
    PARTS_CODE TEXT,           -- callout code
    LANGUAGE TEXT,             -- ENG, GER, FRA, SPA
    WORD TEXT,                 -- keyword (e.g. "BOLT", "FLANGE", "PILOT")
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_PARTS_NUM_NM — Part Number Names (varies)

Direct part number to name mapping (separate from parts code names).

```sql
CREATE TABLE M_PARTS_NUM_NM (
    PARTS_NUMBER TEXT,         -- full part number (e.g. "000026047")
    LANGUAGE TEXT,
    PARTS_NAME TEXT,           -- name (e.g. "BOLT")
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_ZENTAIZU / M_ZENTAIZU_IMAGE — Body Model Diagrams

Full-vehicle illustration with clickable regions mapping to figure groups.

```sql
CREATE TABLE M_ZENTAIZU (
    ID INTEGER PRIMARY KEY,
    SHASHUCTLG TEXT,
    FIG_GROUP TEXT,            -- target figure group
    START_X TEXT, START_Y TEXT, END_X TEXT, END_Y TEXT,  -- clickable region
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);

CREATE TABLE M_ZENTAIZU_IMAGE (
    SHASHUCTLG TEXT,
    WIDTH TEXT, HEIGHT TEXT,    -- always 1280x640
    ILLUST TEXT,               -- base64-encoded PNG
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

### M_ACCIDENT_GROUP — Collision Repair Groups

Groups figures by accident repair zone (no sffastus equivalent).

```sql
CREATE TABLE M_ACCIDENT_GROUP (
    FIG_NO TEXT,               -- figure number
    ACCIDENT_GROUP TEXT,       -- group letter (A-Z)
    GROUP_ORDER TEXT,          -- sort order
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);

CREATE TABLE M_ACCIDENT_GROUP_NAME (
    ACCIDENT_GROUP TEXT,       -- group letter
    LANGUAGE TEXT,
    ACCIDENT_GROUP_NAME TEXT,  -- e.g. "Front Body", "Cooling & Engine"
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

Groups: A (Front Body), B (Cooling & Engine), C (Front Suspension & Steering), D (Door & Side Body), etc.

### M_EMOKUJI — Pictorial Index (7,958 rows)

Thumbnail images for the illustrated figure index.

```sql
CREATE TABLE M_EMOKUJI (
    SHASHUCTLG TEXT,
    EMOKUJI_GROUP TEXT,        -- group code (e.g. "A1")
    FIG_NO TEXT,               -- figure number
    EMOKUJI_ORDER INTEGER,     -- display order
    ILLUST TEXT,               -- base64-encoded thumbnail image
    AREA_CD TEXT, KOKUNAI_FLG TEXT, SUBARU_FLG TEXT
);
```

## Bitmask Filtering — Corrected (from SQL queries)

The APPLIED_MODEL bitmask is filtered **per hex character position**, not per individual bit. The SQL pattern is:

```sql
SUBSTR(APPLIED_MODEL, CAST(#{index} AS INTEGER), 1) = #{appliedModel}
```

Where `index` is a 1-based position into the 250-char hex string, and `appliedModel` is a single hex character. Multiple position checks are AND-ed together via `<foreach>` to filter by spec category.

The `GET_POSITION_LIST` query from `SyasyuMapper.xml` generates index+value pairs from `M_SEKKEI_KATASHIKI` using the `KIGOU_N` columns joined to `M_TOKUCHO_KIGOU.APPLIED_POSITION`.

## VIN Resolution Flow (from SQL queries)

1. Query `M_SYARYO` with VIN prefix (11 chars): `VIN_BEFORE <= #{vin} ORDER BY VIN_BEFORE DESC LIMIT 1`
2. Get `SHASHUCTLG` (model code) and `MODEL` (body model code)
3. Join `M_NENKAI` using `SUBSTR(MODEL, 4, 1) = VIEW_NENKAI` — the 4th char of body model is the model year version letter
4. Look up `MODEL_POSITION` from `M_MODEL` for the body model
5. Look up spec codes from `M_SEKKEI_KATASHIKI` using design model (dynamic KIGOU_1..KIGOU_23 columns via `<foreach>`)
6. Use position to check bitmask in `M_PARTS_CATALOG.APPLIED_MODEL` via `SUBSTR(APPLIED_MODEL, position, 1) = hexDigit`

## Parts Narrowing Pipeline (7 stages, from JS business logic)

Parts from `M_PARTS_CATALOG` are filtered through 7 sequential stages:

1. **Body model match** — `SHASHUCTLG` and model year (`NENKAI`)
2. **Bitmask position check** — `SUBSTR(APPLIED_MODEL, position, 1) = hexDigit`
3. **Color code filter** — `COLOR_CODE` column (blank = all colors)
4. **Trim code filter** — `TRIM_CODE` column (blank = all trims)
5. **Option position filter** — `OPTION_POSITION` hex string checked similarly to APPLIED_MODEL
6. **Destination filter** — `DESTINATION` column
7. **Date range filter** — `SAIYOU_YMD` / `HAISHI_YMD` checked against vehicle production dates

## Figure Rendering Flow (from SQL queries)

1. Get applicable figures: `M_ILLUST_NARROW` filtered by bitmask `SUBSTR(APPLIED_MODEL, idx, 1) = val` for each spec category
2. Get figure image: `M_ILLUST_IMAGE.ILLUST` → base64 decode → PNG (1280×640)
3. Get callout coords: `M_ILLUST` WHERE KUBUN=3 (bounding boxes START_X/Y, END_X/Y)
4. Get cross-refs: `M_ILLUST` WHERE KUBUN=1 (DATA = target figure number)
5. Get tooltip data per KUBUN type:
   - KUBUN=1: `DATA` → `M_FIG_NAME.FIG_NAME` (figure name)
   - KUBUN=3: `DATA` → `M_PARTS_NAME.PARTS_CODE_NAME` (part description)
   - KUBUN=4: `DATA` → `M_PARTS_CATALOG.PARTS_CODE` → `M_PARTS_NAME.PARTS_CODE_NAME` (part via catalog lookup)
6. Filter parts from `M_PARTS_CATALOG` through 7-stage narrowing pipeline
7. Look up part descriptions from `M_PARTS_NAME`

## Exchange Parts (ITCA) Chain Resolution

The JS client walks `M_EXCHANGE_PARTS` recursively:
1. Query `EXCHANGE_PARTS_NUMBER` for a given `PARTS_NUMBER`
2. Follow the chain: each supersession's target becomes the next query's input
3. Continue until no more rows match (terminal part)
4. JOKEN (condition code) at each link determines the relationship type

Reverse lookup: `SELECT_SYASYU_BY_PARTS_NUMBER` finds all model codes that use a given part number by joining `M_EXCHANGE_PARTS` back to `M_PARTS_CATALOG`.

## Web Application Architecture (from WAR file)

- **Stack**: Spring MVC 4.2.3 + MyBatis 3.1.1 + SQLite JDBC 3.20.0
- **Company**: jp.co.qualica.pittqube
- **Key libraries**: JasperReports + iText (PDF export), Apache POI (Excel export)
- **MyBatis mapper files** (SQL queries):
  - `IllustMapper.xml` — figure images, callout coords, tooltips, body diagrams, accident repair
  - `SyaryouMapper.xml` — VIN resolution, model type search, spec code lookup
  - `SyasyuMapper.xml` — model catalog, spec browsing, bitmask position generation, reverse part lookup
  - `BuhinMapper.xml` — part code/name search, price lookup, exchange parts applicability

## Japanese Column Name Glossary

| Japanese (romaji) | English |
|-------------------|---------|
| SHASHUCTLG | Vehicle catalog (model code) |
| KATASHIKI | Model type / chassis code |
| NENKAI | Model year |
| SAIYOU/SAIYO | Adoption (start date) |
| HAISHI | Discontinue (end date) |
| SEISAN | Production |
| TEKIYOU | Application / usage |
| TEKIYOGAI | Non-applicable |
| KIGOU | Symbol / code |
| RYAKUGO | Abbreviation |
| TOKUCHO | Characteristic / feature |
| KUBUN | Classification / type |
| HYOUZI | Display |
| HYOUGEN | Expression |
| GOTAIOU | Corresponding |
| JOKEN | Condition |
| TANKA | Unit price |
| SOUBETSU | Packaging |
| HANBAI | Sales |
| KOKUNAI | Domestic |
| SHIKIRI | Cost price |
| ZENTAIZU | Overall diagram |
| EMOKUJI | Pictorial index |
| KIRIKAE | Switchover |
| TENKEN | Inspection |
| DAIHYO | Representative |
| ILLUST | Illustration |
| SYARYO | Vehicle |
| SHIYO | Specification |
| KOYU | Specific/unique |
| KOSHOKU | Decorative/color |
| SHOGEN | Evidence/note |
| ZAIKO | Inventory |
| TOKUSETSU | Special |
