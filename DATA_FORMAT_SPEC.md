# Subaru FAST 2 Data Format Specification

## Purpose
This document describes all known data file formats for validation against the Windows application.

## Official Documentation Sources
- **FAST2 A&B MANUAL US.pdf** (November 2017) - Installation and Operation Manual
- Extracted from `pdf/FAST2.txt`

---

## Official File Formats (From Manual)

### SF_PRICE.DAT - Price Data (Official)
**Location:** SUBARUEX2 folder
**Record length:** 46 bytes (CR.LF terminated)

| Offset | Width | Field | Notes |
|--------|-------|-------|-------|
| 0 | 15 | Part number | Left-aligned |
| 15 | 8 | Price A | Zero-padded, last 2 digits = decimal |
| 23 | 8 | Price B | Zero-padded, last 2 digits = decimal |
| 31 | 15 | Substitute parts | Space-padded if empty |

### SF_ORDER.DAT - UOE Order Output (Official)
**Record length:** 19 bytes (CR.LF terminated)

| Offset | Width | Field | Notes |
|--------|-------|-------|-------|
| 0 | 15 | Part number | Left-aligned |
| 15 | 4 | Order quantity | Zero-padded |

### Description Data Files (Official)
**Location:** SUBARUEX2 folder

| File | Purpose |
|------|---------|
| sftitle.txt | Window titles |
| sfmenubr.txt | Menu bar text |
| sfbutton.txt | Button labels |
| sfitem.txt | List items |
| sfmessag.txt | Messages |
| sfspec.txt | Specifications |
| sffignm.txt | Figure names |
| sfpcdnm.txt | Part code names |
| sffiggnm.txt | Figure group names |

### MEMO.MDB / MEMO_LINK.MDB (Official)
**Format:** Microsoft Access database
**Purpose:** User memos attached to parts/illustrations

---

## 1. SFFASTUS - VIN Cross-Reference Database

**Location:** `SFCDUS*/sffastus`
**Size:** 147MB (US1) → 511MB (US2) → 608MB (US3)
**Format:** Binary, uncompressed

### Block Pointer Encoding - **VALIDATED ✓**

All section-level pointers use a 4-byte encoding. The general formula from SFCOMMON.DLL (FUN_100012f0):

```
Byte layout:  [b0] [b1] [b2] [pad]
Block number: (b1 - 4 + b0 * 60) * 75 + b2
File offset:  block_number * 2048
```

For header and body model range index pointers, `b0` is always 0, reducing to `(b1 - 4) * 75 + b2`. In model index block pointers (entries 0–29 of the block index array), `b0` can be non-zero for models with data in the upper half of the file — `b0` acts as a mega-section multiplier (each b0 increment = 60 × 75 × 2048 = 9,216,000 bytes).

**Examples (b0=0, header pointers):**

| Raw bytes | b1 | b2 | Block | File offset |
|-----------|----|----|-------|-------------|
| `00 04 00 00` | 4 | 0 | 0 | 0x000000 |
| `00 04 01 00` | 4 | 1 | 1 | 0x000800 |
| `00 0A 00 00` | 10 | 0 | 450 | 0x0E1000 |
| `00 1E 00 00` | 30 | 0 | 1950 | 0x3E5000 |
| `00 29 00 00` | 41 | 0 | 2775 | 0x56D800 |

**Figure data pointers** (used in FIGIllustrationPage89.ptr3 and FIGGroupCategoryRecord184 trailer) extend this with sub-block precision:

```
Byte layout:  [marker] [b1] [b2] [b3]
File offset:  ((b1 - 4 + marker * 60) * 75 + b2) * 2048 + b3 * 8
```

Here `marker` IS part of the address (not just a flag). For G11: marker=0x2A for figures 001–607, marker=0x2B for figures 620–970.

**Validation Status:** ✓ Standard formula verified across 21 pointers (header + body model range index) in all 3 SFCDUS versions. Extended formula verified across all 704 G11 figure page records (490 at marker 0x2A + 214 at marker 0x2B). Model index block pointers verified for all 10 SFCDUS2 models across 30 pointer indices.

### File Header (0x00-0x31) - **VALIDATED ✓**

**Size:** 50 bytes (first block 0x00-0x800 is header + padding)

The header describes the contiguous section layout of the VIN-data portion of the file. All sections are laid out sequentially with no gaps.

**Structure:**

| Offset | Width | Field | Encoding | Description |
|--------|-------|-------|----------|-------------|
| 0x00 | 4 | Magic | — | Always `00 04 01 00` |
| 0x04 | 2 | US VIN Count | BE u16 | Number of US VIN blocks |
| 0x06 | 4 | Range Index Ptr | Block ptr | Pointer → body model range index block |
| 0x0A | 2 | Range Index Count | BE u16 | Range index block count (always 1) |
| 0x0C | 4 | JDM VIN Ptr | Block ptr | Pointer → JDM VIN start block |
| 0x10 | 2 | JDM VIN Count | BE u16 | Number of JDM VIN blocks |
| 0x12 | 4 | Body Model Ptr | Block ptr | Pointer → body model (17-byte) start block |
| 0x16 | 2 | Body Model Count | BE u16 | Number of body model blocks |
| 0x18 | 4 | VIN Detail Ptr | Block ptr | Pointer → VIN detail (69-byte) start block |
| 0x1C | 4 | VIN Detail Count | BE u32 | Number of VIN detail blocks |
| 0x20 | 6 | Catalog Desc 1 | 4-byte ptr + BE u16 | Catalog section descriptor |
| 0x26 | 6 | Catalog Desc 2 | 4-byte ptr + BE u16 | Catalog section descriptor |
| 0x2C | 6 | Catalog Desc 3 | 4-byte ptr + BE u16 | Catalog section descriptor |

**Derived (computed) fields:**
- `us_vin_start_block = 1` (always starts right after header block 0)
- `model_index_start_block = 1 + us_vin_count`
- `model_index_count = range_index_block - model_index_start_block`

**Contiguous layout (each section starts where the previous ends):**

```
Block 0:        Header (1 block)
Block 1:        US VIN Index (us_vin_count blocks)
                Model Index (model_index_count blocks)
                Body Model Range Index (1 block)
                JDM VIN Index (jdm_vin_count blocks)
                Body Model Records (body_model_count blocks)
                VIN Detail Records (vin_detail_count blocks)
                ... Catalog sections follow ...
```

**Cross-version values:**

| Field | SFCDUS1 | SFCDUS2 | SFCDUS3 |
|-------|---------|---------|---------|
| US VIN blocks | 10 | 36 | 51 |
| Model index blocks | 1 | 3 | 3 |
| Range index block | 12 | 40 | 55 |
| JDM VIN blocks | 489 | 1946 | 2755 |
| Body model blocks | 2 | 7 | 9 |
| VIN detail blocks | 25898 | 103096 | 111625 |
| Range index offset | 0x6000 | 0x14000 | 0x1B800 |

**Catalog descriptors (bytes 0x20-0x31):** Three entries of [4-byte ptr + 2-byte count]. The pointer encoding extends to 3-level: `(b0-4)*5625 + (b1-4)*75 + b2`. Sequential differences exactly match counts across all versions, but resulting values exceed file block count — they address a virtual space, likely catalog-section-specific. Further investigation needed.

**Validation Status:** ✓ All section pointers verified across SFCDUS1/2/3. Contiguous layout confirmed — each section starts exactly where the previous ends.

### File Layout (SFCDUS2)

| Section | Offset | Blocks | Purpose |
|---------|--------|--------|---------|
| Header | 0x000000 | 1 | File header (50 bytes + padding) |
| US VIN Index | 0x000800 | 36 | US VINs (4S3...) — 38-byte range records |
| Model Index | 0x013000 | 3 | Model metadata — 288-byte records |
| Body Model Range Index | 0x014000 | 1 | 18-byte range → block pointer index |
| JDM VIN Index | 0x014800 | 1,946 | JDM VINs (JF1/JF2...) — 38-byte range records |
| Body Model Records | 0x3E1800 | 7 | 17-byte body model → model code map |
| VIN Detail Records | 0x3E5000 | 103,096 | 69-byte full VIN specifications |
| Catalog Data | 0x0CDF9000+ | ~158,000+ | 466-byte applicability + indexes + multilingual |

### Model Table (0x32 - 0x200)

This region acts as a primary index, mapping Model Codes (6 chars) to a **32-bit Pointer**.
*   **Entry size:** 10 bytes (6-byte ASCII Code + 4-byte block pointer)
*   The pointer uses the standard block pointer encoding `(b1-4)*75+b2`
*   Points into the JDM VIN section (the pointer value matches the JDM VIN start block from the header)

**Cross-version model codes:**

| SFCDUS1 | SFCDUS2 | SFCDUS3 |
|---------|---------|---------|
| A10, A11, B10, C10, C11, J10 | B11, B12, B13, C12, G10, G11, S10, S11, S12, W10 | B14, B15, G12, G13, G23, G33, G14, G24, S13, V10 |

### Model Index Records (0x13000 - 0x14000) - **VALIDATED ✓**

**Record size:** 288 bytes
**Encoding:** CP437

Located at offset `0x13000`, this section contains metadata and block pointers for each model series. The block index array is the primary lookup mechanism — it maps each block type to a file offset and block count, enabling direct seeks to any model's data without scanning the entire file.

The records are aligned to **2KB blocks** (7 records per block, 32 bytes padding).
*   **Block 0:** `0x13000` (Contains B11...S10, 7 records)
*   **Block 1:** `0x13800` (Contains S11...W10, 3 records)

**Record Structure (288 bytes)**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g., `B11   `, `W10   ` |
| 0x06 | 180 | Block Index Array | 45 × 4-byte entries: 30 block pointers + 15 count pairs (see below) |
| 0xBA | 2 | Series Code | Single letter (`B `, `G `, etc.) |
| 0xBC | 15 | Model Name | e.g., `LEGACY         `, `TRIBECA        ` |
| 0xCB | 6 | Start Date | `YYYYMM` (ASCII, e.g., "199310") |
| 0xD1 | 6 | End Date | `YYYYMM` (ASCII, e.g., "199905") |
| 0xD7 | 8 | Features | Flags |
| 0xDF | 8 | Category 1 | `BODY    ` |
| 0xE7 | 8 | Category 2 | `ENGINE  ` |
| 0xEF | 8 | Category 3 | `TRAIN   ` |
| 0xF7 | 8 | Category 4 | `MISSION ` |
| 0xFF | 8 | Category 5 | `GRADE   ` |
| 0x107 | 8 | Category 6 | `SUS     ` |
| 0x10F | 17 | Trailer | Padding/Reserved |

#### Block Index Array (180 bytes at offset 0x06) - **VALIDATED ✓**

The 180-byte block index array consists of 45 × 4-byte entries divided into two regions:

**Entries 0–29: Block Pointers**

Each 4-byte entry is a standard block pointer decoded via `block_number = (byte1 - 4 + byte0 * 60) * 75 + byte2; file_offset = block_number * 2048`. Points to the first block of each section for this model.

| Index | Block Type | Record Size | Description |
|-------|-----------|-------------|-------------|
| 0 | `multilingual_part_167` | 167 | Mono-lingual (EN) descriptions with spec codes |
| 1 | `category_index_20` | 20 | Category code → pointer index (text variant) |
| 2 | `part_range_24` | 24 | Part number range index |
| 3 | `multilingual_part_180` | 180 | 4-language part names |
| 4 | `model_spec_103` | 103 | Applied model specifications (body/engine/trans/trim) |
| 5 | `multilingual_part_192` | 192 | 4-language part names with figure codes |
| 6 | `catalog_applicability_466` | 466 | Part applicability (largest section, ~97K blocks) |
| 7 | `color_record_91` | 91 | Paint/color codes with multilingual names |
| 8 | `glossary_record_28` | 28 | Technical terminology index |
| 9 | `code_index_record_33` | 33 | Part code index with multilingual qualifiers |
| 10 | `fig_group_category_184` | 184 | FIG group categories (0A–9B, A1–D3) |
| 11 | `fig_illustration_183` | 183 | FIG illustration descriptions (by-system) |
| 12 | `fig_illustration_page_89` | 89 | FIG page sub-index with image pointers |
| 13 | `engine_spec_230` | 230 | Engine specs and figure applicability |
| 14 | `part_group_185` | 185 | Part callout coordinates on figures |
| 15 | `inventory_199` | 199 | Fastener/hardware callout coordinates |
| 16 | (figure image A) | — | Raw CCITT Group 4 compressed image data |
| 17 | (figure image B) | — | Raw CCITT Group 4 compressed image data |
| 18 | (figure image C) | — | Raw CCITT Group 4 compressed image data (main bulk) |
| 19 | `variant_glossary_81` | 81 | Variant code → description mapping |
| 20 | (NULL separator) | — | All zeros (0x00000000) |
| 21 | `version_index_20` | 20 | Version letter+digit → binary data (binary variant) |
| 22 | `fig_illustration_183` (B) | 183 | FIG illustration descriptions (by-binder variant) |
| 23 | (figure image D) | — | Raw CCITT Group 4 compressed image data |
| 24 | `model_year_44` | 44 | Version letters → date ranges and MY labels |
| 25 | `multilingual_part_182` | 182 | 4-language part names with figure linkage |
| 26 | `code_index_record_33` (B) | 33 | Secondary code index |
| 27 | `figure_index_22` | 22 | Inter-figure cross-reference arrows with coordinates |
| 28 | `spec_mapping_22` (A) | 22 | Spec code → description mapping |
| 29 | `spec_mapping_22` (B) | 22 | Spec code → description mapping (secondary) |

**Entries 30–44: Block Count Pairs**

Each 4-byte entry contains two BE uint16 values — block counts for two consecutive pointer indices. The pairing is sequential: entry [30] holds counts for indices 0 and 1, entry [31] for indices 2 and 3, etc.

| Entry | High uint16 (count for) | Low uint16 (count for) |
|-------|------------------------|----------------------|
| 30 | Index 0 (multilingual_part_167) | Index 1 (category_index_20) |
| 31 | Index 2 (part_range_24) | Index 3 (multilingual_part_180) |
| 32 | Index 4 (model_spec_103) | Index 5 (multilingual_part_192) |
| 33 | Index 6 (catalog_applicability_466) | Index 7 (color_record_91) |
| 34 | Index 8 (glossary_record_28) | Index 9 (code_index_record_33) |
| 35 | Index 10 (fig_group_category_184) | Index 11 (fig_illustration_183) |
| 36 | Index 12 (fig_illustration_page_89) | Index 13 (engine_spec_230) |
| 37 | Index 14 (part_group_185) | Index 15 (inventory_199) |
| 38 | **Anomalous** (NOT index 16 count) | Index 17 (figure image B) |
| 39 | Index 18 (figure image C) | Index 19 (variant_glossary_81) |
| 40 | (zero, skips NULL at 20) | Index 21 (version_index_20) |
| 41 | Index 22 (fig_illustration_183 B) | Index 23 (figure image D) |
| 42 | Index 24 (model_year_44) | Index 25 (multilingual_part_182) |
| 43 | Index 26 (code_index_33 B) | Index 27 (figure_index_22) |
| 44 | Index 28 (spec_mapping_22 A) | Index 29 (spec_mapping_22 B) |

**Entry [38] Anomaly:** The high uint16 of entry [38] does NOT contain the block count for index 16 (figure image A). For G11, it reads 9344 while the actual section has only 5 blocks. The value may encode something else (e.g., image count or byte count). All other 29 count values match actual block counts exactly.

**Example: Direct Lookup for G11 Catalog Applicability**

```
Index 6 → catalog_applicability_466
Pointer entry [6]: bytes at array offset 24 → decode_block_pointer() → file offset 0x17462000
Count entry [33] high uint16: 2694 blocks
→ Read 2694 blocks starting at 0x17462000, each containing 4 × 466-byte records
```

**Example Records:**
- B11 (LEGACY): 199310 to 199905
- B12 (LEGACY): 199902 to 200604
- G10 (IMPREZA): 199206 to 200011
- C12 (SVX): 199308 to 199611

**Validation Status:** ✓ Block index array verified across all 10 SFCDUS2 models. 29 of 30 pointer/count pairs confirmed by reading actual blocks and running detect_block_type(). Layout is identical across all models.

### Body Model Range Index (18-byte Type) - **VALIDATED ✓**

**Record size:** 18 bytes
**Location:** Single block at the "transition" between model index and JDM VIN sections (pointed to by header offset 0x06)

| Version | Offset | Block | Records |
|---------|--------|-------|---------|
| SFCDUS1 | 0x6000 | 12 | 4 |
| SFCDUS2 | 0x14000 | 40 | 7 |
| SFCDUS3 | 0x1B800 | 55 | 6 |

Binary search index: given a 7-byte body model code, find which body model data block to read.

**Record Structure (18 bytes)**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 7 | Model From | First body model code in range (e.g., `BD6AY1G`) |
| 0x07 | 7 | Model To | Last body model code in range (e.g., `BH9CY5R`) |
| 0x0E | 4 | Block Pointer | `00 b1 b2 00` — target block for this range |

**Notes:**
- Ranges are sorted by model code and contiguous (no gaps)
- Each pointer resolves to a body model (17-byte) data block whose first record's body model code matches `model_from`
- Sentinel: record starting with `0x2A` (`*`) marks end of list, rest is zero-padded
- The header's "Range Index Ptr" field always points to this block
- Always occupies exactly 1 block

**Validation Status:** ✓ All pointers verified across SFCDUS1/2/3 — target block's first record matches `model_from` in every case.

### Body Model Records (17-byte Type) (0x3E1800 - 0x3E5000) - **VALIDATED ✓**

Maps **Body Model Codes** (7 chars) to **Model Codes** (e.g., B11) and a configuration index.
*   **Block Alignment:** 2KB blocks.
*   **Records per Block:** 120 records (2040 bytes) + 8 bytes padding.
*   **Range:** 7 blocks in SFCDUS2 (754 records total, all 10 models).
*   Terminated by `0x2A` (`*`) fill bytes after the last valid record.

**Record Structure (17 bytes)**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 7 | Body Model | e.g., `BD6AY1G`, `SHMDY6S`, `WXEAY2U` |
| 0x07 | 2 | Constant | Always `0x0001` (Big Endian) |
| 0x09 | 6 | Model Code | e.g., `B11   `, `S12   ` |
| 0x0F | 2 | Config Index | BE uint16 (range 0x0001-0x0197, 116 unique values) |

**Validation Status:** ✓ 754 records parsed and validated across 7 blocks.

### US VIN Records (0x800+) - **TO VALIDATE**

```
Extracted from SFCDUS1/sffastus
Found 3 contiguous VIN regions (>= 10 blocks):
       Start          End   Blocks    Records
----------------------------------------------
0x00000800  0x00005800        10  ~      530
0x00006800  0x000FB000       489  ~    25917
0x000FD000  0x03392000     25898  ~  1372594
----------------------------------------------
                     Total     26397  ~  1399041

Extracted from SFCDUS2/sffastus
=== 2KB VIN Block Analysis ===
File size: 535,420,928 bytes (510.6 MB)

Found 3 contiguous VIN regions (>= 10 blocks):
       Start          End   Blocks    Records
----------------------------------------------
0x00000800  0x00013000        37  ~     1961
0x00014800  0x003E1800      1946  ~   103138
0x003E5000  0x0CD41000    103096  ~  5464088
----------------------------------------------
                     Total    105079  ~  5569187


Extracted from SFCDUS3/sffastus
Found 4 contiguous VIN regions (>= 10 blocks):
       Start          End   Blocks    Records
----------------------------------------------
0x00000800  0x0001A800        52  ~     2756
0x0001C000  0x0057D800      2755  ~   146015
0x00580800  0x0DF85000    111625  ~  5916125
0x0DF85800  0x122AC000     34381  ~  1822193
----------------------------------------------
                     Total    148813  ~  7887089
```

**Record size:** 38 bytes

```
Offset  Size  Field
------  ----  -----
0x00    17    VIN Range Start (ASCII)
0x11    17    VIN Range End (ASCII)
0x22    4     Pointer (LE uint32)
```

```
Extracted from SFCDUS2/sffastus

=== Detailed VIN Block Inspection (First 2 Blocks) ===

[Block 0] Offset: 0x000800 - 0x001000
Status: 53 records found
Padding: 35 bytes at end
Content:
  Rec 00: 4S3BD3350T1200011 -> 4S3BD4350V7205795 | Ptr: 0x00290400 (Sec:1024, Idx:41)
  Rec 01: 4S3BD4350V7205800 -> 4S3BD4350X7260279 | Ptr: 0x002A0400 (Sec:1024, Idx:42)
  Rec 02: 4S3BD4350X7260282 -> 4S3BD4351V7209242 | Ptr: 0x002B0400 (Sec:1024, Idx:43)
  ...
  Rec 34: 4S3BD635XS7222787 -> 4S3BD6550S7225288 | Ptr: 0x00000500 (Sec:1280, Idx:0)
  Rec 35: 4S3BD6550S7225291 -> 4S3BD6552S7216088 | Ptr: 0x00010500 (Sec:1280, Idx:1)
  Rec 36: 4S3BD6552S7216110 -> 4S3BD6553S7236317 | Ptr: 0x00020500 (Sec:1280, Idx:2)
```


**Example:** `4S3BD3350T1200011` to `4S3BD4350V720579`

**Validation:** Enter a VIN in the app, verify the range matching behavior.

### VIN-Model Detail Records (69-byte Type) (0x3E5000+) - **VALIDATED ✓**

**Record size:** 69 bytes
**Encoding:** CP437

Full vehicle specification records keyed by VIN. Each record maps a specific VIN to its complete build configuration including model, body type, color, trim, options, and production dates. Located immediately after the VIN range index blocks.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 17 | VIN | Full VIN (e.g. `JF2SHAEC0CH440463`) |
| 0x11 | 1 | Null | Null terminator |
| 0x12 | 1 | Flag | Typically `0x01` |
| 0x13 | 6 | Model Code | e.g. `S12   `, `B11   ` |
| 0x19 | 7 | Body Model | e.g. `SHMDY6S`, `BD6AY1G` |
| 0x20 | 3 | Color Code | Paint/color code (e.g. `G1U`) |
| 0x23 | 3 | Trim Code | Interior trim code (e.g. `H20`) |
| 0x26 | 2 | Main Option Code | Main option code (e.g. `NT`) |
| 0x28 | 1 | Padding | Space |
| 0x29 | 2 | Binary Flags | Unknown flags |
| 0x2B | 8 | Date 1 | `YYYYMMDD` (e.g. `20120116`) |
| 0x33 | 8 | Date 2 | `YYYYMMDD` (e.g. `20120112`) |
| 0x3B | 8 | Date 3 | `YYYYMMDD` (e.g. `20120112`) |
| 0x43 | 2 | Destination Code | Market/destination (e.g. `U5`) |

**Notes:**
- Records are contiguous; parsing stops when VIN fails validation
- Color/trim/option codes were previously treated as a single 9-byte "spec_code" field
- Destination code indicates target market (e.g. `U5` = US market)
- Three date fields may represent production, shipping, and registration dates

**Validation:** Parse records from VIN pointer targets and verify model/body/color combinations match known Subaru specifications.

### Model-Spec Records (0x0F000000+) - **TO VALIDATE**

**Record size:** ~69 bytes (estimated)

```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code ("W10   ", "B12   ")
0x06    7     Part/Figure Reference
0x0D    10    Part Number
0x17    6     Date Code ("F2004")
0x1D+   var   Engine/spec codes (EJ257, EJ255)
```

**Validation:** Search for a known part number in the app, check if model code matches.

### Catalog Applicability Records (466-byte Type) (0x0CDF9000+) - **VALIDATED ✓**

**Record size:** 466 bytes
**Encoding:** CP437

Defines part applicability per model: which parts apply to which engine/body/trim configurations, with date ranges and destination market codes. The largest block type in the file (~97,000 blocks in SFCDUS2, ~389,000 records).

**Structure (466 bytes):**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `B11   `, `G11   ` |
| 0x06 | 7 | Group/Category | Callout code (e.g. `H505301`, `98201A`, `14878`) |
| 0x0D | 12 | Part ID | Part number (e.g. `98271FE090OE`, `42162AC190`) |
| 0x19 | 3 | Padding | Spaces |
| 0x1C | 1 | Date Flag | Letter code A-H indicating validity period type |
| 0x1D | 16 | Date Range | `YYYYMMDDYYYYMMDD` (start + end, e.g. `1997100119990531`) |
| 0x2D | 19 | Destination Codes | Market/destination codes (e.g. `C0U4`, `U5U6`, spaces if universal) |
| 0x40 | 64 | Spec Logic | Boolean expression for applicability (e.g. `EJ22# +EJ25D`, `S +W`) |
| 0x80 | 32 | Usage Notes / OP | Operational notes (e.g. `LH`, `FOR A/C`, `FRONT`, `-E/#979080`) |
| 0xA0 | 46 | Part Spec / Color | Part specification and color (e.g. `T=4.68`, `CLARION`, `PAINT FOR USAGE`, `MARK"7"  BLUE`) |
| 0xCE | 10 | Ref Code | 10-digit internal reference code (e.g. `0100000009`, `*00017300`) |
| 0xD8 | 12 | Related Part | Companion/superseding part number (e.g. `13228AB102`) or spaces |
| 0xE4 | 6 | Fig Qualifier | Right-justified number + optional letter prefix (E/L) |
| 0xEA | 4 | Figure Ref | Group letter (A-Z) + 3-digit number (e.g. `A012`, `B081`) |
| 0xEE | 2 | Padding | Spaces |
| 0xF0 | 2 | Figure Page | Page within figure (e.g. `04`) or spaces |
| 0xF2 | 44 | Secondary Ref | Binder cross-ref code (e.g. `B20`) at start, mostly spaces |
| 0x11E | 4 | Market Code | Locale code (e.g. `C`, `T`, `ND`, `MI`, `GL`) |
| 0x122 | 15 | Bitmask | Binary flags — 5 active bytes at offsets 290–291, 302–304; rest zero |
| 0x131 | 109 | Padding | Always zeros |
| 0x19E | 2 | Marker | `0x00` + `0x2A` (`*`, 84%) or `0x20` (` `, 16%) |
| 0x1A0 | 25 | Feature Mask | `0x40` (`@`) fill when marker=`*`; single flag byte when marker=` ` |
| 0x1B9 | 15 | Supplier Code | Distribution/supplier code (e.g. `SSPCQ`, `COWPX`, `SUNRO`) or spaces |
| 0x1C8 | 10 | Padding | Trailing spaces |

**Destination Codes (offset 0x2D, 19 bytes):**

Present in ~23% of records. Codes appear in pairs and can be concatenated:

| Code | Meaning |
|------|---------|
| C0 | Canada |
| C4, C5, C6 | Canada variants |
| U0, U1 | US variants (early models) |
| U4, U5, U6 | US variants (common) |
| UT | US (other) |

Records with empty destination codes (spaces) apply universally to all markets.

**Group/Category (offset 0x06, 7 bytes):**

This is the full callout code that matches part_code entries in Part Group Records (185-byte). Originally decoded as 5 bytes + 2 bytes "padding", but the 2-byte suffix is part of the code:
- `H505301` = group `H5053` + suffix `01`
- `98201A` = group `98201` + suffix `A`
- `14878` = group `14878` + empty suffix (spaces stripped)

**Part ID (offset 0x0D, 12 bytes):**

Full part number including optional 2-character suffix. ~14% of records use the suffix (e.g. `OE`, `NV`, `TG`, `ML`). Originally decoded as 10 bytes, truncating these suffixes.

**Spec Logic Expression Syntax:**
- `+` separates alternatives (OR): `EJ22# +EJ25D` = EJ22x or EJ25D
- `.` combines requirements (AND): `WOBK.25GT.255` = Wagon Outback AND 25GT AND EJ255
- `*` negation (NOT): `*AT` = not automatic transmission
- `#` single-character wildcard: `EJ22#` matches EJ22E, EJ22G, etc.
- Parentheses for grouping: `S.(I#+25GT+25GTLTD) +WOBK`
- Single letters for body types: `S` = Sedan, `W` = Wagon
- Engine codes: `EJ22#`, `EJ25D`, `253`, `255`, `257`, `30D`
- Trim codes: `25GT`, `25GLI`, `STI`, `BASE`
- **Variant prefix:** ~7.4% of records have a letter A-H at position 0 as a variant selector, not part of the spec expression. E.g. `AS.(WRX+STI)` = variant `A` + spec `S.(WRX+STI)`. Matches space-separated variant suffix in Part Group part_code (e.g. `98281  A`).
  - The variant letter is **independent of the date_flag** — a record can have `date_flag='D'` with `spec_logic='AS +W'` (variant `A`, date period `D`).
  - The app displays variant letters as `*A`, `*B`, `*C` next to the callout code (e.g. `94071P *A`, `94071P *B`, `94071P *C`).
  - Multiple variants of the same callout code typically represent different part options (e.g. color variants: `*A` = DARK GRAY, `*B` = OFF BLACK, `*C` = generic).

**Usage Notes / OP (offset 0x80, 32 bytes):**

Operational context displayed in the app's "OP" column. Present in ~2% of G11 records. Common values:

| Value | Meaning |
|-------|---------|
| `LH`, `RH`, `RH & LH` | Side (left/right hand) |
| `FOR A/C`, `EXC.A/C` | Air conditioning applicability |
| `FOR ABS`, `EXC.ABS` | Anti-lock brake applicability |
| `FRONT`, `REAR` | Position |
| `DOJ`, `BJ` | Joint type (double-offset / birfield) |
| `-E/#979080`, `E/#979081-` | Serial number range (before/after) |
| `W:2PCS`, `AT.253:5PCS` | Quantity |
| `MANUAL`, `AUTO` | Transmission type |

**Part Spec / Part Color (offset 0xA0, 46 bytes):**

Part specification and color data displayed in the app's "Part Spec. Part Color" column. Present in ~13% of G11 records. Examples:

| Value | Category |
|-------|----------|
| `T=4.68`, `T=4.69` ... `T=5.09` | Valve lifter thickness |
| `CLARION`, `MATSUSHITA`, `NIPPON ANTENNA`, `DENSO 156700-1` | Manufacturer/supplier |
| `M6`, `M6X12`, `6X13X13` | Bolt/fastener size |
| `D=20`, `D=15` | Diameter |
| `G/R=4.111`, `G/R=3.900` | Gear ratio |
| `12V-8W` | Electrical specification |
| `RH`, `LH`, `LH LIFTER`, `GEAR SHIFT` | Position/type |
| `STD`, `STD GRADE"A"`, `STD GRADE"B"` | Grade/quality |
| `OS,0.25`, `OS,0.50` | Oversize |
| `MARK"3"`, `MARK"7"  BLUE` | Mark/color |
| `PAINT FOR USAGE` | Paint requirement |
| `US GRAY`, `CO GRAY` | Market-specific color |
| `EJ251AW3AB`, `EJ205BW5BB` | Engine assembly code |
| `STABILIZER(D=20)` | Component specification |

**Ref Code (offset 0xCE, 10 bytes):**

10-digit internal reference code. 1,924 unique values for G11. Structure appears to be `XXYY...YYZZ` where XX is a 2-digit prefix (commonly `01` or `02`), middle digits vary, and ZZ is `00` or `09`. Some values have `*` prefix (e.g. `*00017300`). Purpose not fully understood — may be a cross-reference to pricing or inventory data.

**Related Part (offset 0xD8, 12 bytes):**

Companion or superseding part number. Present in ~16% of G11 records. Examples:
- Part `13228AB101` → related `13228AB102` (next revision of same valve lifter)
- Part `010006120` → related `010006126` (related bolt)

**Supplier Code (offset 0x1B9, 15 bytes):**

Distribution or supplier code. Present in ~16% of G11 records (when marker byte = `0x20`). Known codes:

| Code | Likely Meaning |
|------|----------------|
| `SSPCQ`, `SSPCW`, `SSPCD`, `SSPCC`, `SSPCV`, `SSPCY`, `SSPCE`, `SSPCZ`, `SSPCM` | Subaru Spare Parts Center + location variant |
| `COWPX`, `COWPO` | Distribution center |
| `SUNRO`, `SUNRX` | Distribution center |
| `AICNO`, `AICNX` | Distribution center |
| `KAWAX`, `KAWAO` | Distribution center |
| `SPOLO` | Distribution center |
| `COWPXKAWAX`, `COWPOKAWAX`, `COWPXKAWAO`, `COWPOKAWAO` | Combined multi-source codes |

**Market Code (offset 0x11E, 4 bytes):**

Present in ~12% of G11 records. Known values: `C` (1923×), `T` (1742×), `ND` (430×), `MI` (334×), `GL` (73×), `NI` (58×), `CN` (51×), `PN` (43×), `ZX` (27×), `NK` (11×), `SY` (3×). Exact meaning TBD.

**Example Records:**
```
Model B11, Group 42162, Part 42162AC190: Date E 1997.10.01-1999.05.31, Spec "EJ22# +EJ25D"
Model B13, Group 01000, Part 010006107: Date A 2003.11.01-2005.05.31, Spec "A25GLI.255 +WOBK.25GT.255"
Model G11, Group H505301, Part 807505301: Spec "205 +257", Fig B081 Page 04
```

**Notes:**
- 4 records per 2KB block (466×4 = 1864 bytes, 184 bytes padding)
- Blocks terminated by invalid model code in padding region
- Each range is terminated by one `******...` (asterisk) sentinel record and one null record

**Validation Status:** ✓ 389,192 records validated across 97,303 blocks (10 model ranges). All model codes valid, all dates 16-digit numeric, all group_category and part_id non-empty. Figure parts lookup verified against Windows app for figures 081-04 and 343-02 (G11 STI).

### Code Index Records (33-byte Type) (0x0DE42800+) - **VALIDATED ✓**

**Record size:** 33 bytes
**Encoding:** CP437

Index of part codes organized by model and category, with multilingual qualifiers.
Located in blocks around `0x0DE42800`. **6,468 blocks detected (2.5% of file).**

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    1     Category            Single byte code classification
0x07    15    Size/Variant        Multilingual part qualifiers (NOT padding!)
0x16    7     Part Code           7-character part code (space-padded)
0x1D    4     Metadata            Binary flags or reference pointers
```

**Size/Variant Field (offset 0x07, 15 bytes):**
- **97.4% of records** have non-empty content in this field
- Contains full multilingual part description qualifiers:
  - English: "ASSEMBLY", "RIGHT", "FRONT", "LEFT", "REAR", "COMPLETE"
  - French: "ENSEMBLE", "ARRIèRE", "AVANT", "GAUCHE" (LEFT)
  - Spanish: "CONJUNTO", "CONSOLA", "CUBIERTA"
  - German: "RECHTS" (RIGHT), "SCHRAUBE" (SCREW), "ABDECKUNG" (COVER)
- Also contains size/dimension codes: "ST", "5X20", "+)", single digits (0-9)
- Full words stored, not truncated suffixes

**Part Code Field (offset 0x16, 7 bytes):**
- 7-character field for part codes (matches official documentation)
- Space-padded when code is shorter than 7 characters
- Examples: "28391  ", "28491B ", "81608  "

**Notes:**
- Category is a single byte (e.g., 0x31='1', 0x30='0', 0x32='2')
- Size/variant field provides multilingual qualifiers - full descriptions likely stored elsewhere
- Part code field length matches official spec: "Part codes are 7 characters"
- Significant presence in the file (2.5%) underscores its importance for data indexing

**Validation Status:** ✓ Structure validated by parsing 400,230 records from all 6,468 blocks

### Glossary/Terminology Records (28-byte Type) (0x0DE23800+) - **VALIDATED ✓**

**Record size:** 28 bytes
**Encoding:** CP437

Index of technical terms, abbreviations, and part terminology used throughout the catalog.
Located in blocks around `0x0DE23800`. **632 blocks detected (0.2% of file).**

**Structure:**
```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code (e.g., "B11   ")
0x06    1     Category/Type byte
0x07    17    Term/Text (e.g., "AUTO", "AXLE", "5X20")
0x18    4     Metadata/Flags
```

**Examples:**
- Automotive terms: "AUTO", "AUTOMATIC", "AXLE"
- Part terms: "B.P.T.", "BACK", "BAFFLE"
- Technical codes: "5X20", "ST", "+)", "/", "1", "10"

**Notes:**
- Category byte appears to group related terms
- Terms are left-aligned with space padding
- Metadata may indicate term usage context or references

**Validation:** Cross-reference terms with part descriptions and technical documentation.

### FIG Group Category Records (184-byte Type) (0x0DF9A000+) - **VALIDATED ✓**

**Record size:** 184 bytes
**Encoding:** CP437

Contains multilingual descriptions for FIG group codes (e.g., "0A", "1B"). These categories are used for top-level navigation in the FAST 2 application.
Located in blocks around `0x0DF9A000`.

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    2     FIG Group Code      2-character code (e.g., "0A", "9B")
0x08    40    Description (EN)    English category name
0x30    40    Description (DE)    German category name
0x58    40    Description (FR)    French category name
0x80    40    Description (ES)    Spanish category name
0xA8    16    Trailer/Metadata    LE reference pointers or flags
```

**Two Grouping Schemes:**

Group codes `0A`–`9B` are "by system" categories (17 groups mapping to figure number ranges). Group codes `A1`–`D3` are "by book/binder" categories (groups of ~20 figures each, likely matching physical binder tab dividers in the printed catalog).

| Code | Category (EN) | FIG Range |
|------|---------------|-----------|
| 0A | ENGINE MAIN | 001-036 |
| 0B | ENGINE AUXILIARIES | 040-082 |
| 0C | ENGINE ELECTRICAL PARTS | 090-096 |
| 1A | MANUAL TRANSMISSION | 100-130 |
| 1B | AUTOMATIC TRANSMISSION | 150-184 |
| 1C | DIFFERENTIAL & PROPELLER SHAFT | 190-199 |
| 2A | SUSPENSION, AXLE & BRAKE | 200-292 |
| 3A | STEERING SYSTEM & CABLE | 341-380 |
| 4A | ENGINE MOUNTING & COOLING | 410-450 |
| 5A | BODY, KEY KIT & BUMPER | 505-595 |
| 6A | DOOR PARTS | 605-622 |
| 6B | SEAT & INSTRUMENT PANEL | 640-660 |
| 7A | HEATER & AIR CONDITIONER | 720-732 |
| 8A | BODY ELECTRICAL PARTS (1) | 810-836 |
| 8B | BODY ELECTRICAL PARTS (2) | 840-899 |
| 9A | OUTER ACCESSORIES | 900-922 |
| 9B | INNER ACCESSORIES | 930-970 |

**Trailer Structure (16 bytes at 0xA8):**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 2 | Trailer ID | BE u16, varies per record |
| 0x02 | 2 | Record Index | BE u16 (index into EngineSpecRecord230 list) |
| 0x04 | 4 | ptr1 | Figure data pointer → FIGIllustrationRecord183 blocks for this category |
| 0x08 | 2 | Figure Count | BE u16, number of unique figures in this category |
| 0x0A | 4 | ptr2 | Figure data pointer → binary catalog data for this category |
| 0x0E | 2 | Record Count | BE u16, number of catalog records for this category |

ptr1 and ptr2 use the same encoding as FIGIllustrationPage89.ptr3:
`offset = ((byte1 - 4 + marker * 60) * 75 + byte2) * 2048 + byte3 * 8`

**Example (G11, group 0A "ENGINE MAIN"):**
- ptr1 → `0x17256000` = `fig_illustration_183` block, Figure Count = 17
- ptr2 → `0x17462000` = binary catalog data, Record Count = 5197

**Hierarchy: FIGGroupCategoryRecord184 → FIGIllustrationRecord183 → FIGIllustrationPage89**

```
FIGGroupCategoryRecord184  (e.g., "0A" = "ENGINE MAIN")
  │  linked by: fig_group_code
  │  ptr1 in trailer points to the 183 blocks
  │
  └── FIGIllustrationRecord183  (e.g., group="0A", code2="004" = "CYLINDER BLOCK")
        │  linked by: fig_group_code2 == fig_index
        │
        └── FIGIllustrationPage89  (e.g., fig="004", page="01", label="SYSTEM")
```

**Notes:**
- Multilingual strings are space-padded to 40 bytes
- Validated by scanning the file and matching codes to application categories
- Trailer pointers verified: ptr1 resolves to `fig_illustration_183` blocks for all 17 G11 categories

### FIG Illustration Records (183-byte Type) (0x0DF9B000+) - **VALIDATED ✓**

**Record size:** 183 bytes
**Encoding:** CP437

Contains multilingual descriptions for individual FIG illustrations (e.g., "CYLINDER BLOCK", "PISTON & CRANKSHAFT"). Links FIG group categories (184-byte) to individual figure pages (89-byte).
Located in blocks around `0x0DF9B000`.

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    2     FIG Group Code      Category code (e.g., "0A", "1B") — links to FIGGroupCategoryRecord184
0x08    5     FIG Group Code 2    3-digit figure code (e.g., "004") — links to FIGIllustrationPage89.fig_index
0x0D    40    Description (EN)    Illustration name in English
0x35    40    Description (DE)    Illustration name in German
0x5D    40    Description (FR)    Illustration name in French
0x85    40    Description (ES)    Illustration name in Spanish
0xAD    10    Trailer/Metadata    LE reference pointers or flags
```

**Examples (Model G11, Group 0A):**
- `fig_group_code="0A"`, `code2="004"`, desc=`CYLINDER BLOCK`
- `fig_group_code="0A"`, `code2="010"`, desc=`PISTON & CRANKSHAFT`
- `fig_group_code="0B"`, `code2="040"`, desc=`TURBO CHARGER`

**Record counts per group code (G11, 379 total):**
- By-system groups (`0A`–`9B`): 3–17 figures each (e.g., `0A` = 17 figures, `1C` = 3 figures)
- By-binder groups (`A1`–`D3`): ~20 figures each (pagination for physical catalog binders)

**Notes:**
- `fig_group_code` links up to FIGGroupCategoryRecord184 (parent category)
- `fig_group_code2` links down to FIGIllustrationPage89 (individual pages via `fig_index`)
- Record size (183) is one byte smaller than the FIG Group category records
- FIGGroupCategoryRecord184 trailer `ptr1` points directly to the 183-byte blocks for that category

**Validation:** ✓ Matches FIG illustration titles in the illustrated index menu. All 379 G11 records link to valid category codes and figure indices.

### FIG Illustration Page Records (89-byte Type) (0x0DFA5000+) - **VALIDATED ✓**

**Record size:** 89 bytes
**Encoding:** CP437

Contains sub-indexing for FIG illustrations, mapping specific FIG indices to page numbers, labels, and pointers to CCITT Group 4 compressed image data (1280x640, 1-bit bilevel).
Located in blocks around `0x0DFA5000`.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `B11   `, `G11   ` |
| 0x06 | 3 | FIG Index | Illustration index (e.g., `002`) |
| 0x09 | 2 | Padding | Usually spaces |
| 0x0B | 2 | Page Index | Page number (e.g., `01`, `02`) |
| 0x0D | 40 | Label | Page-level note shown in app (see below) |
| 0x35 | 4 | ptr1 | Model-level pointer (constant within a model group) |
| 0x39 | 4 | ptr2 | Model-level pointer (constant within a model group) |
| 0x3D | 8 | Reserved | Zeros |
| 0x45 | 4 | ptr3 | Figure image data pointer (per-page, see encoding below) |
| 0x49 | 12 | Unknown | Other metadata fields |
| 0x55 | 2 | Image Size | Raw G4 data byte count (big-endian uint16) |
| 0x57 | 2 | Reserved | Zeros |

**ptr3 Encoding (4 bytes):**

```
Format: [marker] [byte1] [byte2] [byte3]
          0x2A

position   = (byte1 - ref_byte1) * 19200 + byte2 * 256 + byte3
file_offset = base + position * 8
```

- 19200 = 75 × 256 (same factor 75 as section-level block pointers)
- Each `byte1` section covers 153,600 bytes (19200 × 8)
- `base` and `ref_byte1` are model-specific constants
- Figure data is packed contiguously, 8-byte aligned

**Known model constants:**

| Model | ref_byte1 | base | Records offset |
|-------|-----------|------|----------------|
| G11 | `0x1A` | `0x1745D000` | `0x1725E800` |

**Image Size (s2):**

The 2-byte big-endian value at record offset 0x55 is the exact byte count of raw CCITT Group 4 data at the ptr3 offset. Verified for all 23 G11 records.

**Label Field (0x0D, 40 bytes):** - **VALIDATED ✓**

Page-level note displayed in the Windows application alongside the figure name. Contains sub-system identification, model year applicability, and/or engine codes. Examples from G11:

| Figure | Page | Label |
|--------|------|-------|
| 004 | 01 | `SYSTEM` |
| 004 | 02 | `BODY` |
| 006 | 04 | `SYSTEM                       '02MY-'06MY` |
| 006 | 05 | `BODY` |
| 040 | 02 | `'02MY-'06MY` |
| 050 | 02 | `INTAKE MANIFOLD BODY 257(-'06MY)` |
| 081 | 04 | `SOLENOID VALVE               '04MY-'06MY` |
| 002 | 06 | `ENGINE GASKET & SEAL KIT '04MY-'06MY` |

- Empty for many pages (especially single-page figures)
- Internal whitespace padding between sub-system name and MY range
- `'NNMY` = model year notation (e.g., `'02MY` = 2002 model year)
- `'NNMY-` = from that MY onward; `'NNMY-'NNMY` = range
- I&S Bulletin pages (40+) use labels like `I&S BULLETIN        HEAD ASSY-CYL    RH`

**Relationship to parent records:**
- `fig_index` links up to FIGIllustrationRecord183 via `fig_group_code2` (figure-level descriptions)
- FIGIllustrationRecord183.`fig_group_code` links to FIGGroupCategoryRecord184 (top-level categories)

**Notes:**
- Index numbers are ASCII strings, not 16-bit integers.
- ptr1 and ptr2 are constant for all records within a model group.
- All images decode to 1280×640 pixels (height is a fixed constant, not stored in the record).
- Figure pages use T.6 uncompressed mode extensions; requires ImageMagick/Wand for decoding (Pillow/libtiff does not support uncompressed mode).

**Validation Status:** ✓ ptr3 formula verified across all 704 G11 records with zero errors. All figure pages successfully decoded to 1280×640 PNG images matching the Windows application display. Labels verified against Windows app for figures 004, 006, 040, 050, 081 (G11 STI).

### Variant Glossary Records (81-byte Type) (0x0E6E9000+) - **VALIDATED ✓**
 
 **Record size:** 81 bytes
 **Encoding:** CP437
 
 Maps model-specific configuration codes (body types, engine codes, transmission types, etc.) to their full descriptive names. These names are used in the "Applied Model" specification display and vehicle selection.
 
 Located in blocks around `0x0E6E9000`. **54 blocks detected in SFCDUS2.**
 
 **Structure:**
 ```
 Offset  Size  Field               Description
 ------  ----  -----               -----------
 0x00    6     Model Code          "B11", "G11", etc.
 0x06    15    Variant Code        Variant code (e.g., "2200CC", "SW", "5MT")
 0x15    60    Description         Full descriptive name
 ```
 
 **Notes:**
 - The first record in some blocks may have leading spaces before the model code to maintain certain byte-padding requirements.
 - Variant codes include:
   - Engine displacement (e.g., "2200CC", "2500CC")
   - Body styles (e.g., "SW" for Station Wagon, "TW" for Touring Wagon, "SEDAN")
   - Transmission types (e.g., "MT", "AT", "5MT")
   - Trim levels and other variant qualifiers.
 - Descriptions are typically formatted as `CATEGORY : VALUE` (e.g., `GRADE : OUT BACK`).
 
 **Validation:** Variant names match the technical specifications and grading levels for the respective Subaru model years.
 
 ### Part Group Records (185-byte Type) (0x0DFD3000+)

**Record size:** 185 bytes
**Encoding:** CP437

Contains descriptive names and **callout coordinates** for part groups. These are the main part callouts shown on figure illustrations (assemblies, panels, clips, etc.). Each record maps a callout code to its X,Y position on the figure image.

Located in blocks around `0x0DFD3000`.

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    3     Figure              FIG index (e.g., "940")
0x09    4     Figure Page         Page within figure (e.g., "01  ")
0x0D    8     Part Code           Callout code (e.g., "94088A", "W130076")
0x15    40    Description (EN)    English label
0x3D    40    Description (DE)    German label
0x65    40    Description (FR)    French label
0x8D    40    Description (ES)    Spanish label
0xB5    2     X Coordinate        BE uint16 - callout position on figure
0xB7    2     Y Coordinate        BE uint16 - callout position on figure
```

**Coordinate Space:**
- X range: 0-2560, Y range: 0-1280
- Divide by 2 to get pixel coordinates on 1280x640 figure images
- Coordinates point to the top-left corner of the callout label bounding box (with ~2px upward offset)

**Notes:**
- Each multilingual field (EN, DE, FR, ES) is exactly 40 bytes.
- The first 12 bytes of the EN field often contain a part base code or reference (e.g., "  0110100   ").
- In other languages, the first 12 bytes are typically spaces, though they may overflow from long descriptions.

**Position Indicators in Descriptions:**

Descriptions use a comma-separated suffix to indicate position/side. The app extracts RIGHT/LEFT and displays them as `<RH>`/`<LH>` next to the callout number. Other suffixes (FRONT, REAR, UPPER, LOWER, etc.) are NOT displayed in the app. Common suffixes (G11, 4328 descriptions with commas):

| Suffix | Count | App Display |
|--------|-------|-------------|
| `RIGHT` | 327 | `<RH>` |
| `LEFT` | 305 | `<LH>` |
| `FRONT` | 85 | (none) |
| `REAR` | 67 | (none) |
| `REVERSE` | 37 | (none) |
| `INNER` | 30 | (none) |
| `UPPER` | 24 | (none) |
| `LOWER` | 24 | (none) |
| `FRONT RIGHT` | 19 | `<RH>` |
| `FRONT LEFT` | 19 | `<LH>` |
| `REAR RIGHT` | 15 | `<RH>` |
| `SIDE` | 15 | (none) |
| `REAR LEFT` | 13 | `<LH>` |
| `OUTER` | 11 | (none) |
| `CENTER` | 8 | (none) |

For compound suffixes like `FRONT RIGHT`, the app extracts only the RIGHT/LEFT component and shows `<RH>`/`<LH>`.

Examples:
- `TRIM PANEL-FRONT DOOR,RIGHT` → callout shows `<RH>`, description `TRIM PANEL-FRONT DOOR`
- `TRIM PANEL-FRONT DOOR,LEFT` → callout shows `<LH>`, description `TRIM PANEL-FRONT DOOR`
- Callout pairs: base code (e.g. `94213`) = RH, `A`-suffixed code (e.g. `94213A`) = LH

App-tested examples:
- fig 941-04 callout 94213 = `<RH>`, 94213A = `<LH>` (description suffix RIGHT/LEFT)
- fig 262-03 callout 26292 = `<RH>`, 26292A = `<LH>` (description suffix RIGHT/LEFT)
- fig 022-01 callout 13570 — description has `,FRONT` suffix, no indicator shown in app
- fig 070-02 callout 46052 — description has `,UPPER` suffix, no indicator shown in app

**Validation:** Index numbers and labels match the high-level category navigation in the FAST 2 application.

### Engine Spec Records (230-byte Type) (0x0DFB1000+) - **NEW**

**Record size:** 230 bytes
**Encoding:** CP437

Contains engine specifications, types, and production periods for specific model series. These records likely define the powerplant configurations available for selection in the catalog.
Located in blocks around `0x0DFB1000`.

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    3     Figure              FIG index (e.g., "002")
0x09    4     Figure Page         Section/Page within figure (e.g., "01  ")
0x0D    75    Applicable Model    Engine/Spec description (e.g., "EJ22# +EJ25D...")
0x58    5     Padding             Usually spaces
0x5D    6     Start Date          Production start (YYYYMM)
0x63    6     End Date            Production end (YYYYMM)
0x69    125   Trailer/Metadata    Binary metadata
```

**Notes:**
- Date fields are ASCII strings (e.g., "199310").
- The trailer contains binary data that might link to further specifications or engine-specific part modifications.

**Validation:** Engine types match the production periods known for the respective Subaru models.

### Color/Paint Code Records (91-byte Type) (0x0DE1F800+) - **NEW**

**Record size:** 91 bytes
**Encoding:** CP437

Defines paint/color codes with multilingual color names.
Located in blocks around `0x0DE1F800`.

**Structure:**
```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code (e.g., "B11   ")
0x06    4     Paint Code (e.g., "AC 0")
0x0A    20    Color Name EN (e.g., "LIGHT SILVER M")
0x1E    20    Color Name DE (e.g., "HELLSILBER M")
0x32    20    Color Name FR (e.g., "ARGENT CLAIR M")
0x46    20    Color Name ES (e.g., "PLATA CLARO M")
0x5A    1     Padding/Reserved
```

**Notes:**
- Contains color names in 4 languages (English, German, French, Spanish)
- Paint codes follow standard automotive format
- Similar structure to 180-byte multilingual part records

**Validation:** Cross-reference paint codes with known Subaru color catalogs.

### Figure Cross-Reference Records (22-byte Type) (0x0E75D800+) - **VALIDATED ✓**

**Record size:** 22 bytes
**Encoding:** CP437

Stores inter-figure cross-reference arrows with X,Y coordinates. Each record represents a "see also figure Z" link drawn on a figure page at a specific position. Located in blocks around `0x0E75D800` (B11), `0x17BA3800` (G11), etc.

**Structure:**

| Offset | Width | Field        | Description |
|--------|-------|--------------|-------------|
| 0x00 | 6 | Model Code   | e.g. `B11   `, `G11   ` |
| 0x06 | 3 | Figure       | Source figure code (e.g. `003`) |
| 0x09 | 2 | Padding      | Spaces |
| 0x0B | 2 | Page         | Page within figure (e.g. `01`) |
| 0x0D | 3 | Ref Figure   | Target figure code (e.g. `004`, `010`) |
| 0x10 | 2 | Padding      | Spaces |
| 0x12 | 2 | X Coordinate | BE uint16, position on source figure |
| 0x14 | 2 | Y Coordinate | BE uint16, position on source figure |

**Notes:**
- Coordinates use ~2x pixel coordinate space (X: 0-2400, Y: 0-1280 for 1280×640 figures)
- Pointed to by `ptr_xref` in FIGIllustrationPage89 (offset 0x41, 4 bytes)
- `xref_count` in FIGIllustrationPage89 (offset 0x53) stores the number of unique cross-references per page
- All `ref_figure` values are valid figure codes from `figname.txt`

### Spec Mapping Records (22-byte Type) (0x17BA7000+) - **VALIDATED ✓**

**Record size:** 22 bytes
**Encoding:** CP437

Maps model-specific spec codes to short descriptions (e.g., `AAICN` -> `OFOR A/C`).

**Structure:**

| Offset | Width | Field       | Description |
|--------|-------|-------------|-------------|
| 0x00 | 6 | Model Code  | e.g. `G11   ` |
| 0x06 | 5 | Option Code | Alpha spec code (e.g. `AAICN`) |
| 0x0B | 11 | Description | Short description text (e.g. `OFOR A/C   `) |

Example Option Codes:
- AAICN: Air Conditioning (O = For A/C, X = Excluding A/C)
- ABRSD: Anti-lock Brakes (O = For ABS, X = Excluding ABS)
- ACRUI: Cruise Control (O = For Cruise, X = Excluding Cruise)
- ARFRL: Roof Rails (O = For R/R, X = Excluding R/R)
- ASDAB: Side Airbags (O = For Side-A/B)

**Notes for 22-byte records:**
- High density of records throughout the latter half of the file.
- Records are strictly 22-byte aligned and typically grouped in full 2KB blocks.
- Distinction between `Figure Index` and `Spec Mapping` is primarily based on the presence of digits in the 5-char code field (bytes 6-11).

### Model Specification Records (103-byte Type) (0x0CD4B800+) - **VALIDATED ✓**

**Record size:** 103 bytes
**Encoding:** CP437

Defines detailed "Applied Model" specifications for Subaru vehicles. Fields are variable-length and padded with spaces.
Located in blocks around `0x0CD4B800`.

**Structure Overview:**
```
Offset  Size  Field               Examples
------  ----  -----               --------
0x00    6     Model Code          "B11", "G11", "B13"
0x06    15    Production Period   "011199601199805"
0x15    18    Applied Model       "BD7-Y3M", "GDF-YEH"
0x27    8     Body Config         "S" (Sedan), "W" (Wagon), "WOBK" (Wagon Outback)
0x2F    8     Engine Code         "EJ22EZ", "EJ25D", "255", "257"
0x37    8     Drivetrain          "F4WD", "4W"
0x3F    8     Transmission        "MT", "5MT", "6MT", "AT"
0x47    8     Trim Level          "L", "BASE", "STI", "25GT"
0x4F    6     Spec/Option         "N/S" (Non-Sunroof), "YAD"
0x55    18    Padding/Reserved
```

**Notes:**
- Fields use variable-length values with space padding (e.g., "MT" vs "5MT")
- Parser uses wider capture windows to handle variations
- Turbo engines identifiable by codes: 255, 257, 205, 207, or 'T' in engine code
- Manual transmissions contain "MT" substring

**Validation:** Parse records from known offsets and verify engine/transmission/trim combinations match known Subaru specifications.

### Category Index Records (20-byte Type, Text Variant) (0x0CD42000+) - **NEW**

**Record size:** 20 bytes
**Encoding:** CP437

One block per model code (10 blocks in SFCDUS2). Each record maps a 2-letter category code to a binary pointer. The label byte 6 is a letter A-J and byte 7 is a letter (C or T). The 8-byte payload is printable ASCII text.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `B11   `, `G11   ` |
| 0x06 | 2 | Label | Category code letter pair (e.g. `AC`, `ET`, `GT`) |
| 0x08 | 8 | Payload | Printable ASCII data |
| 0x10 | 4 | Pointer | Binary pointer/metadata |

**Notes:**
- Blocks are terminated by `0x2A` (`*`) fill bytes after the last valid record
- All records within a block share the same model code
- Byte 7 distinguishes this from the version index variant (letter vs digit)
- 20-byte records can false-match as `multilingual_part_180` (20x9=180 aligns model codes); detection must occur before 180-byte checks

### Version Index Records (20-byte Type, Binary Variant) (0x0E6ED000+) - **NEW**

**Record size:** 20 bytes
**Encoding:** CP437

One block per model code (10 blocks in SFCDUS2). Each record maps a version letter + digit to binary data. The label byte 6 is a letter A-D and byte 7 is a digit 1-9. The 8-byte payload is binary (not printable text).

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `B11   `, `G11   ` |
| 0x06 | 2 | Label | Version letter + digit (e.g. `A1`, `B3`, `D2`) |
| 0x08 | 8 | Payload | Binary data |
| 0x10 | 4 | Pointer | Binary pointer/metadata |

**Notes:**
- Same block structure as category index variant (terminated by `0x2A` fill)
- All records within a block share the same model code
- Byte 7 distinguishes this from the category index variant (digit vs letter)
- 20 blocks total in SFCDUS2: 10 category index + 10 version index (one of each per model)

### Part Range Records (24-byte Type) (0x0CD42800+) - **NEW**

**Record size:** 24 bytes
**Encoding:** CP437

Appears to define valid part number ranges for a model.
Located in blocks around `0x0CD42800`.

```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code (e.g., "B11   ")
0x06    7     Part Number Start (e.g., "11711  ")
0x0D    7     Part Number End (e.g., "12024  ")
0x14    4     Metadata (e.g., 0x17 0x19 Index 0x00)
```

### Multilingual Part Records (167-byte Type) (0x0CD41000+) - **NEW**

**Record size:** 167 bytes
**Encoding:** CP437

Appears to be mono-lingual (English) descriptions with spec codes.
Located in blocks around `0x0CD41000`.

```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code (e.g., "B11   ")
0x06    11    Spec Code (e.g., "103TW      ")
0x11    25    Description (e.g., "WAGON(STEP ROOF)         ")
0x2A    125   Trailer/Padding
```

### Multilingual Part Records (180-byte Type) (0x0CD45000+) - **NEW**

**Record size:** 180 bytes
**Encoding:** CP437 (NOT Latin-1)

Contains part names in 4 languages (English, German, French, Spanish).
Located in blocks around `0x0CD45000` (in SFCDUS2).

```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code (e.g., "B11   ")
0x06    7     Part Code (e.g., "13028  ")
0x0D    40    English Name
0x35    40    German Name (Deutsch)
0x5D    40    French Name (Français)
0x85    40    Spanish Name (Español)
0xAD    7     Trailer (binary flags/metadata)
```

### Inventory Records (199-byte Type) (0x0E147000+) - **VALIDATED ✓**

**Record size:** 199 bytes
**Encoding:** CP437

Maps figure callout codes to part numbers with multilingual names and X,Y coordinates indicating where the callout appears on the figure illustration. Located in blocks around `0x0E147000` (B11), `0x17451000` (G11), etc.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `B11   ` |
| 0x06 | 5 | Figure | FIG index (e.g. `004  `) |
| 0x0B | 2 | Figure Page | Section/Page within figure (e.g. `01`) |
| 0x0D | 15 | Part Number | Full 15-char part number |
| 0x1C | 2 | X Coordinate | BE uint16, callout position on figure |
| 0x1E | 2 | Y Coordinate | BE uint16, callout position on figure |
| 0x20 | 7 | Part Code | 7-character part code |
| 0x27 | 40 | Name EN | English part name |
| 0x4F | 40 | Name DE | German part name |
| 0x77 | 40 | Name FR | French part name |
| 0x9F | 40 | Name ES | Spanish part name |

**Notes:**
- `Part Number` matches the 15-character length used in `SF_PRICE.DAT`.
- `Part Code` matches the 7-character length used in official documentation.
- All names are space-padded to 40 bytes.
- Record is a superset of information, linking figure/page to actual global part numbers.
- X,Y coordinates use a coordinate space of approximately 2x the 1280×640 pixel figure dimensions (X range 0-2400, Y range 0-1280).
- Pointed to by `ptr_extra` in FIGIllustrationPage89 (offset 0x3D, 4 bytes) for standard parts (bolts, clips, screws).

### Multilingual Part Records (182-byte Type) (0x0E73B000+) - **VALIDATED ✓**

**Record size:** 182 bytes
**Encoding:** CP437

Another variant of multilingual part names, likely linking model codes and figures to specific part designations.
Located in blocks around `0x0E73B000`.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `B11   ` |
| 0x06 | 7 | Part Code | 7-char part code (e.g. `10101  `) |
| 0x0D | 5 | Figure | FIG index (e.g. `010  `) |
| 0x12 | 40 | Name EN | English part name |
| 0x3A | 40 | Name DE | German part name |
| 0x62 | 40 | Name FR | French part name |
| 0x8A | 40 | Name ES | Spanish part name |
| 0xB2 | 4 | Trailer/Metadata | Binary metadata (e.g. counter) |

**Notes:**
- High density of records (Found 43 blocks in SFCDUS2).
- Similar to 192-byte and 180-byte variants but with different field alignment.

### Multilingual Part Records (192-byte Type) (0x0CD4D000+) - **VALIDATED ✓**

**Record size:** 192 bytes
**Encoding:** CP437

Contains part names in 4 languages (English, German, French, Spanish) in a single record.

```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code (e.g., "B11   ")
0x06    6     Part Code (e.g., "0951S ")
0x0C    5     Figure Code (e.g., " 421 ")
0x11    3     Index (e.g., " 1 ", "11 ")
0x14    40    English Name
0x3C    40    German Name (Deutsch)
0x64    40    French Name (Français)
0x8C    40    Spanish Name (Español)
0xB4    12    Trailer (binary flags/metadata)
```

**Example record:**
```
Model:  B11
Part:   10005
Figure: 094
Index:  0
EN:     1HANGER-ENGINE,FRONT
DE:     AUFHÄNGUNG - MOTOR, VORN
FR:     SUPPORT - MOTEUR, AVANT
ES:     PÉNDOLA MOTOR, DELANTERA
```

**Note:** Name fields include leading digit prefix (e.g., "1FUEL HOSE", "2HANGER COMPLETE-ENGINE").

### Model Year Version Records (44-byte Type) - **VALIDATED ✓**

**Record size:** 44 bytes
**Encoding:** CP437

One block per model code (10 blocks in SFCDUS2). Maps version letters to production date ranges and model year labels. Used to define the catalog versions available for each model series.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `G11   `, `B11   ` |
| 0x06 | 1 | Version Letter | Sequential A,B,C... (skips I) |
| 0x07 | 8 | Date From | Production start `YYYYMMDD` |
| 0x0F | 8 | Date To | Production end `YYYYMMDD` |
| 0x17 | 20 | Model Year Label | e.g. `'02MY`, `'08MY(C5:'09MY INC)` |
| 0x2B | 1 | Version Letter | Repeated (validated: always matches byte 6) |

**Block locations in SFCDUS2:**

| Offset | Model | Versions | Years |
|--------|-------|----------|-------|
| 0x0E73A800 | B11 | A-E | '95MY-'99MY |
| 0x1085E000 | B12 | A-G | '00MY-'06MY |
| 0x13055800 | B13 | A-E | '05MY-'09MY |
| 0x13C87800 | C12 | C-F | '94MY-'97MY |
| 0x15C59800 | G10 | A-J | '93MY-'01MY |
| 0x17B7A800 | G11 | A-F | '02MY-'07MY |
| 0x18BDA800 | S10 | A-E | '98MY-'02MY |
| 0x1A823000 | S11 | A-F | '03MY-'08MY |
| 0x1C686800 | S12 | A-E | '09MY-'13MY |
| 0x1E5B4000 | W10 | A-J | '06MY-'14MY |

**Notes:**
- 46 records per 2KB block (2024 bytes) + 24 bytes padding
- `******...` (0x2A fill) marks end of valid records, rest is zero-padded
- Version letters are sequential A-Z but skip I (e.g. G10 goes A..H,J)
- Date ranges overlap between consecutive versions (production overlap between model years)
- C12 starts at version C (earlier versions may exist in SFCDUS1)

**Validation Status:** ✓ 61 records across 10 blocks. Version letter at byte 43 matches byte 6 in all records.

### Empty Blocks (Asterisk-Padded) - **VALIDATED ✓**

**Block size:** 2048 bytes
**Content:** Variable number of `0x2A` (`*`) bytes followed by `0x00` bytes — no other values.

These blocks appear at the end of record ranges where the last block is only partially filled. The asterisk fill marks the end of valid data (same sentinel used within record blocks, e.g. Model Year), and the remaining bytes are zero-padded.

**17 blocks in SFCDUS2:**

| Offset | Asterisks | Zeros |
|--------|-----------|-------|
| 0x0FED7000 | 91 | 1957 |
| 0x10889000 | 167 | 1881 |
| 0x1308D800 | 180 | 1868 |
| 0x13109000 | 192 | 1856 |
| 0x13D59800 | 192 | 1856 |
| 0x15C1B000 | 183 | 1865 |
| 0x15D4E000 | 192 | 1856 |
| 0x1729A000 | 230 | 1818 |
| 0x17B42000 | 183 | 1865 |
| 0x17BA8000 | 167 | 1881 |
| 0x187E1800 | 199 | 1849 |
| 0x18BF4800 | 182 | 1866 |
| 0x1BF42000 | 466 | 1582 |
| 0x1C6B5000 | 180 | 1868 |
| 0x1DF8E000 | 91 | 1957 |
| 0x1E581800 | 183 | 1865 |
| 0x1FE9D800 | 251 | 1797 |

**Notes:**
- Asterisk counts correspond to record sizes of adjacent block types (e.g. 91 = ColorRecord91, 183 = FIGIllustrationRecord183, 192 = multilingual_part)
- Detected as block type `'empty'` in the parser

### Part Number Index Records (21-byte Type) (0x1E5DE800+) - **NEW**

**Record size:** 21 bytes
**Encoding:** CP437
**Detection requires:** `ItcaPartsCatalog` (validates part numbers against itca_data.txt)

Simple part number index - each record contains a single part number with a 6-byte metadata/pointer field.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 15 | Part Number | 15-char part number (e.g., `000009513      `) |
| 0x0F | 6 | Metadata | Binary data (block index or pointer) |

**Notes:**
- 97 records per 2KB block (2057 bytes) + 11 bytes padding
- Part numbers match entries in `itca_data.txt`
- Disambiguation from 34-byte records requires checking at least 2 records (42 bytes)

### Part Number Range Index Records (34-byte Type) (0x1E5D6800+) - **NEW**

**Record size:** 34 bytes
**Encoding:** CP437
**Detection requires:** `ItcaPartsCatalog` (validates part numbers against itca_data.txt)

Part number range index that maps sorted part number ranges to block pointers. Each record defines a range covering ~97 records from `itca_data.txt`. Used for binary search lookup of parts.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 15 | Part Number From | Start of range (e.g., `000009513      `) |
| 0x0F | 15 | Part Number To | End of range (e.g., `002117201      `) |
| 0x1E | 1 | Constant | Always `0x37` (55) |
| 0x1F | 2 | Block Index | BE 16-bit block index (e.g., `0x1441` = 5185) |
| 0x21 | 1 | Constant | Always `0x00` |

**Notes:**
- 60 records per 2KB block (2040 bytes) + 8 bytes zero padding
- 16 consecutive blocks at `0x1E5D6800` cover all 94,000 itca_data.txt records
- Block index increments by 1 per record but is not strictly sequential (gap from `0x144A` to `0x1500`)
- Part number ranges are sorted and contiguous — `part_number_to` of record N connects to `part_number_from` of record N+1

### ITCA Records in sffastus (251-byte Type) - **NEW**

**Record size:** 251 bytes
**Encoding:** CP437
**Detection requires:** `ItcaPartsCatalog` (validates part numbers against itca_data.txt)

Binary representation of ITCA parts catalog records embedded in sffastus. Contains the same data as `itca_data.txt` but with multilingual descriptions (4 languages) and a different field layout.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 15 | Part Number | Current part number |
| 0x0F | 15 | Supersedes To | Supersedes-to part number |
| 0x1E | 1 | ITCA Code | Status/type code |
| 0x1F | 40 | Description EN | English part name |
| 0x47 | 40 | Description DE | German part name |
| 0x6F | 40 | Description FR | French part name |
| 0x97 | 40 | Description ES | Spanish part name |
| 0xBF | 40 | Quantity | Quantity field (padded) |
| 0xE7 | 9 | Part Code | Part code |
| 0xF0 | 11 | Unknown | Trailing binary data |

**Notes:**
- 8 records per 2KB block (2008 bytes) + 40 bytes padding
- Extends the text-based `itca_data.txt` format with multilingual descriptions
- Part numbers validated against `ItcaPartsCatalog` for block detection

---

## 2. ITCA_DATA.TXT - Parts Catalog

**Location:** `SFCDUS*/itca_data.txt`
**Size:** 5.9MB (US1) → 7.8MB (US2) → 8.2MB (US3)
**Format:** Fixed-width ASCII, Latin-1 encoding, CRLF terminators
**Records:** ~94,000 parts

### Record Structure - **FROM OFFICIAL MANUAL ✓**

**Source:** FAST2 A&B MANUAL US.pdf
**Record size:** 87 bytes/rec (split by CR.LF)

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0 | 16 | Part number | Current part number |
| 16 | 1 | ITCA code | Status/type code |
| 17 | 1 | Blank | Separator |
| 18 | 16 | ITCA part number | Supersedes-to part number |
| 34 | 2 | Q'ty | Quantity |
| 36 | 1 | Blank | Separator |
| 37 | 8 | Part code | Figure/category code |
| 45 | 40 | Part name | Description text |
| 85 | 2 | CR.LF | Line terminator |

**Empirical Offsets (Validated against SFCDUS1):**
- **Part Number:** `line[0:16]`
- **ITCA Code:** `line[16:17]`
- **Supersedes:** `line[18:34]`
- **Qty:** `line[34:36]`
- **Part Code:** `line[37:45]`
- **Description:** `line[45:85]`

**Note:** Manual states 87 bytes total. Field widths sum to 86 + terminator.

### ITCA Condition Codes - **FROM OFFICIAL MANUAL ✓**

| Code | Meaning | Description |
|------|---------|-------------|
| 1 | Mutual interchange | New ↔ Old (both directions) |
| 2 | New replaces old | New → Old only |
| 3 | Old replaces new | Old → New only |
| 4 | With modifications | New replaces old with simple mods |
| 6 | With other parts | New + other parts replace old |
| 7 | RH/LH pair | Replace both sides for color match |
| 8 | Kit replaces | New parts kit replaces old |
| 9 | Compulsory | Forced replacement |

**Note:** Codes 4, 6, 7, 8 have detailed ITCA Bulletin data available (Version A only).

**Validation:** Look up a superseded part, verify app shows chain to current part.

---

## 3. TEKIOUS.TXT - Figure Block Index

**Location:** `SFCDUS*/tekious.txt`
**Size:** 1.2MB (US1) → 2.1MB (US2) → 1.9MB (US3)
**Format:** Binary with ASCII content, NO line terminators
**⚠️ WARNING:** Do NOT read with cat/head/tail - will hang!

### Structure - **VALIDATED ✓**

**Header:** 0x00-0x800 (metadata + null padding)
**Data:** Starts at offset 0x800

**Record size:** 256 bytes
**Entry size:** 16 bytes (16 entries per record)

```
Entry format (16 bytes):
Offset  Size  Field
------  ----  -----
0x00    9     Figure Number (ASCII, left-padded)
0x09    7     Block Index (ASCII, right-padded)
```

**Example entries:**
- `010006107      0` → Figure 010006107, Block 0
- `010106250 00220` → Figure 010106250, Block 220

**Validation:** Match figure numbers to what appears in the app diagram viewer.

---

## 4. FIGNAME.TXT - Figure Group Descriptions - **VALIDATED ✓**

**Location:** `SFCDUS*/sffastpg/win/figname.txt`
**Size:** ~15 KB (348 records)
**Format:** Fixed-width ASCII, 44 bytes per line
**Encoding:** ASCII

### Structure

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 3 | Figure Code | 3-digit code (e.g., "001", "040") |
| 0x03 | 41 | Description | Space-padded description |

### Key Codes - **VALIDATED ✓**

| Code | Description | App Category |
|------|-------------|--------------|
| 001 | ENGINE ASSEMBLY | ? |
| 010 | PISTON & CRANKSHAFT | ? |
| 040 | TURBO CHARGER | ? |
| 050 | INTAKE MANIFOLD | ? |
| 055 | EXHAUST MANIFOLD | ? |
| 072 | INTER COOLER | ? |
| 100 | MT, CLUTCH | ? |
| 125 | MT, DIFFERENTIAL CONTROL UNIT | ? |
| 200 | FRONT SUSPENSION | ? |
| 201 | REAR SUSPENSION | ? |
| 262 | FRONT BRAKE | ✓ |
| 263 | REAR BRAKE | ✓ |

**Validation Status:** ✓ All records parsed successfully. Format validated across SFCDUS1, SFCDUS2, and SFCDUS3. All known codes match expected descriptions.

---

## 5. FIGGNAME.TXT - High-Level Categories

**Location:** `SFCDUS*/sffastpg/win/figgname.txt`
**Size:** 748 bytes
**Format:** 2-char code + category name

### Categories - **FROM OFFICIAL MANUAL ✓**

| Code | Name | FIG Range |
|------|------|-----------|
| 0A | ENGINE MAIN | 000-039 |
| 0B | ENGINE AUXILIARIES | 040-089 |
| 0C | ENGINE ELECTRICAL PARTS | 090-099 |
| 1A | MANUAL TRANSMISSION | 100-149 |
| 1B | AUTOMATIC TRANSMISSION | 150-189 |
| 1C | DIFFERENTIAL & PROPELLER SHAFT | 190-199 |
| 2A | SUSPENSION, AXLE & BRAKE | 200-299 |
| 3A | STEERING SYSTEM & CABLE | 300-399 |
| 4A | ENGINE MOUNTING & COOLING | 400-499 |
| 5A | BODY, KEY KIT & BUMPER | 500-599 |
| 6A | DOOR PARTS | 600-639 |
| 6B | SEAT & INSTRUMENT PANEL | 640-699 |
| 7A | HEATER & AIR CONDITIONER | 700-799 |
| 8A | BODY ELECTRICAL PARTS (1) | 800-839 |
| 8B | BODY ELECTRICAL PARTS (2) | 840-899 |
| 9A | OUTER ACCESSORIES | 900-929 |
| 9B | INNER ACCESSORIES | 930-999 |

**Validation:** Match to top-level menu in the app. Enter group code (e.g., "9B") to jump to category.

---

## 6. FIGNODT.TXT - Figure-to-Block Node Mapping

**Location:** `SFCDUS*/fignodt.txt`
**Size:** ~11 KB
**Format:** ASCII, figure code + block references

### Structure - **TO VALIDATE**

```
[FIGURE_CODE]  [BLOCK1]  [BLOCK2]  [BLOCK3]  ...

Example:
001  B6800002  B6801003  B6802004  B6803005  ...
```

**Block ID format:** Letter prefix (B,C,D,E,F,G,H,I) + 4-5 digits

**Validation:** When viewing figure 001 in app, check if multiple diagram pages exist matching block count.

---

## 7. SOURCE_DATA_US.TXT - US Market Flags

**Location:** `SFCDUS*/source_data_us.txt`
**Size:** ~126 KB
**Format:** Fixed-width, 9-digit figure + 7-char flags

### Structure - **TO VALIDATE**

```
Offset  Width  Field
------  -----  -----
0       9      Figure Number
9       7      Model Flags (spaces or digits 1,2,3)
```

### Flag Meanings - **SPECULATIVE**

| Flag | Possible Meaning |
|------|------------------|
| (blank) | Universal - all models |
| 1 | Model Set A |
| 2 | Model Set B |
| 3 | Model Set C (possibly turbo/STI) |

**Validation:** Compare figures with flag 3 to STI-specific diagrams in app.

---

## 8. PCDNAME.TXT - Part Name Descriptions

**Location:** `SFCDUS*/sffastpg/win/pcdname.txt`
**Size:** ~1.3 MB
**Format:** Part code prefix + description

### Structure

```
0003SX BOLT & WASHER ASSEMBLY
14411  TURBOCHARGER ASSEMBLY
26296  PAD KIT-FRONT DISK BRAKE
```

**Validation:** Match to part descriptions shown in app search results.

---

## 9. SFMESSDT - UI Messages

**Location:** `SFCDUS*/SFMESSDT`
**Size:** ~59 KB
**Format:** Binary (structure unknown)

**Validation:** Not critical for parser - contains UI strings.

---

## Validation Checklist

Please verify the following in the Windows app:

### VIN Lookup
- [ ] Enter VIN `JF1GD70655L510047` - What model code does it show?
- [ ] Enter VIN `4S3BK6350T7301234` - Does it find a range?
- [ ] Is there a "Model Code" display anywhere (B11, W10, etc.)?

### Parts Search
- [ ] Search for part `14411AA471` - What supersession chain shows?
- [ ] Search for part `26296AA000` - What figure code displays?
- [ ] What status codes appear (active, superseded, discontinued)?

### Figure Browser
- [ ] Navigate to figure 040 - Is it "TURBO CHARGER"?
- [ ] Navigate to figure 001 - How many diagram pages?
- [ ] What are the top-level categories in the menu?

### Language
- [ ] Can you switch to German/French/Spanish?
- [ ] Do part names change when language changes?

---

## Confidence Levels

### Official Documentation (From FAST2 Manual)
- **itca_data.txt** record format (87 bytes, field offsets)
- **ITCA condition codes** (1-9 meanings)
- **FIG group codes** and number ranges (0A-9B → 000-999)
- **SF_PRICE.DAT** format (46 bytes)
- **SF_ORDER.DAT** format (19 bytes)
- **Part numbers** are 15 characters
- **Part codes** are 7 characters

### High Confidence (Validated in Scripts)
- Block pointer encoding: `(b1 - 4 + b0 * 60) * 75 + b2` (verified across all 3 versions, all 10 models)
- Figure data pointer encoding: `((b1 - 4 + marker * 60) * 75 + b2) * 2048 + b3 * 8` (verified 704 G11 records)
- File header structure (50 bytes, all section pointers decoded)
- Model index block index array: 30 block pointers + 15 count pairs (verified all 10 SFCDUS2 models, 29/30 counts match)
- Body model range index (18-byte records, verified pointer targets)
- Contiguous file layout (header → US VIN → model index → range index → JDM VIN → body model → VIN detail → per-model catalog data)
- tekious.txt structure (256-byte records at 0x800)
- figname.txt / figgname.txt format
- XOR 0x44 encoding for figure primitives
- 183-byte figure record size

### Medium Confidence (Pattern Matching)
- VIN record structure (38 bytes)
- Multilingual record format (33 bytes)
- Header catalog descriptors (3-level pointer encoding)
- Entry [38] high uint16 meaning (NOT a block count — may be image count or total byte count)

### Speculative (Needs Validation)
- source_data_us.txt flag meanings
- SFMESSDT internal structure
