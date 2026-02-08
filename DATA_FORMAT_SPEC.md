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

### File Layout

| Section | Offset Range | Size | Purpose |
|---------|-------------|------|---------|
| Header | 0x00-0x32 | 50 bytes | Metadata, format markers |
| Model Table | 0x32-0x9A | 104 bytes | 10 model codes with pointers |
| Padding | 0x9A-0x800 | ~1.8 KB | Null padding |
| US VIN Index | 0x800-0x260400 | 2.4 MB | US VINs (4S3...) |
| JDM VIN Data | 0x260400-0x0F000000 | ~238 MB | JDM VINs (JF1...) |
| Parts/Model Map | 0x0F000000-0x1F000000 | ~256 MB | Model-to-parts records |
| Multilingual | 0x1F000000+ | ~14.6 MB | DE/FR/ES part names |
| Diagrams | 0x10234800-0x10946000 | ~7.1 MB | Binary diagram data |

### Model Table (0x32-0x9A) - **TO VALIDATE**

**Entry size:** 10 bytes each (6-byte model code + 4-byte LE pointer)

| Offset | Model | Description |
|--------|-------|-------------|
| 0x32 | B11 | Legacy/Outback |
| 0x3C | B12 | Legacy/Outback |
| 0x46 | B13 | Legacy/Outback |
| 0x50 | C12 | Impreza |
| 0x5A | G10 | Impreza 1992-2000 |
| 0x64 | G11 | Impreza 2001-2007 |
| 0x6E | S10 | Forester |
| 0x78 | S11 | Forester |
| 0x82 | S12 | Forester |
| 0x8C | W10 | WRX/STI |

4-byte LE pointer meaning still unknown
```
Extracted from SFCDUS1/sffastus
=== Model Code Table (0x32) ===
  A10    -> 0x000B0400
  A11    -> 0x000B0400
  B10    -> 0x000B0400
  C10    -> 0x000B0400
  C11    -> 0x000B0400
  J10    -> 0x000B0400

Extracted from SFCDUS2/sffastus
=== Model Code Table (0x32) ===
  B11    -> 0x00260400
  B12    -> 0x00260400
  B13    -> 0x00260400
  C12    -> 0x00260400
  G10    -> 0x00260400
  G11    -> 0x00260400
  S10    -> 0x00260400
  S11    -> 0x00270400
  S12    -> 0x00270400
  W10    -> 0x00270400

Extracted from SFCDUS3/sffastus
=== Model Code Table (0x32) ===
  B14    -> 0x00350400
  B15    -> 0x00350400
  G12    -> 0x00350400
  G13    -> 0x00350400
  G23    -> 0x00350400
  G33    -> 0x00350400
  G14    -> 0x00350400
  G24    -> 0x00360400
  S13    -> 0x00360400
  V10    -> 0x00360400
```

**Validation:** Check if these model codes appear in the Windows app vehicle selection.
### Model Table (0x32 - 0x200)

This region acts as a primary index, mapping Model Codes (6 chars) to a **32-bit File Pointer**.
*   **Entry size:** 10 bytes (6-byte ASCII Code + 4-byte LE Pointer)
*   The pointer often targets the **JDM VIN Data** section (e.g., `0x00260400`).

### Model Index Records (0x13000 - 0x14000) - **VALIDATED ✓**

**Record size:** 288 bytes
**Encoding:** CP437

Located at offset `0x13000`, this section contains metadata and block references for each model series.
The records are aligned to **2KB blocks** (similar to VIN blocks).
*   **Block 0:** `0x13000` (Contains B11...S10)
*   **Block 1:** `0x13800` (Contains S11...W10)

**Record Structure (288 bytes)**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g., `B11   `, `W10   ` |
| 0x06 | 180 | Block Index Array | Array of 4-byte entries (struct `{ u16 unknown; u16 block_idx }`) |
| 0xBA | 2 | Series Code | Single letter (`B `, `G `, etc.) |
| 0xBC | 15 | Model Name | e.g., `LEGACY         `, `TRIBECA        ` |
| 0xCB | 6 | Start Date | `YYYYMM` (ASCII, e.g., "199310") |
| 0xD1 | 6 | End Date | `YYYYMM` (ASCII, e.g., "199905") |
| 0xD7 | 14 | Features | Flags (`12345...`) |
| 0xE5 | 8 | Category 1 | `ENGINE  ` |
| 0xED | 8 | Category 2 | `TRAIN   ` |
| 0xF5 | 8 | Category 3 | `MISSIO  ` (MISSION truncated) |
| 0xFD | 8 | Category 4 | `GRADE   ` |
| 0x105 | 8 | Category 5 | (varies) |
| 0x10D | 8 | Category 6 | (varies) |
| 0x115 | 11 | Trailer | Padding/Reserved |

**Example Records:**
- B11 (LEGACY): 199310 to 199905
- B12 (LEGACY): 199902 to 200604
- G10 (IMPREZA): 199206 to 200011
- C12 (SVX): 199308 to 199611

**Validation Status:** ✓ Structure validated by parsing records from 0x13000

### Body Model Map (0x3E1800 - 0x3E5000) - **CONFIRMED**

This region maps specific **Body Model Codes** (7 chars) to the **Model Code** (e.g., B11) and a specific configuration index.
*   **Block Alignment:** 2KB blocks.
*   **Records per Block:** 120 records (2040 bytes) + 8 bytes padding.
*   **Range:** 7 blocks total.

**Record Structure (17 bytes)**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 7 | Body Model | e.g., `BD6AY1G`, `GGEEY6R` |
| 0x07 | 2 | Unknown 1 | Always `0x0001` (Big Endian) in samples |
| 0x09 | 6 | Model Code | e.g., `B11   `, `G11   ` |
| 0x0F | 2 | Config Index | Index into the Model's Block List? (Big Endian) |

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

### Part Detail Records (466-byte Type) (0x0CE04000+) - **NEW**

**Record size:** 466 bytes
**Encoding:** CP437

Detailed part information including part numbers, date ranges, and specifications.
Located in blocks around `0x0CE04000`.

**Preliminary Structure:**
```
Offset  Size  Field
------  ----  -----
0x00    6     Model Code (e.g., "B11   ")
0x06    ~20   Part Number Fields (e.g., "10103  10103AA810")
0x1A    ~20   Date Range (e.g., "D1996070119980331")
0x2E    ~20   Engine/Spec (e.g., "EJ25D")
...     ~400  Additional metadata, padding, and delimiters
```

**Notes:**
- Contains extensive padding with null bytes and delimiter characters (@, *)
- Multiple part number references within single record
- Date ranges appear in YYYYMMDDYYYYMMDD format
- Further analysis needed to determine exact field boundaries

**Validation:** Parse records and verify part numbers match known Subaru part catalogs.

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

**Common FIG Group Codes (from [WINDOWS_APP_GUIDE.md](file:///Users/zhukov/subaru/SUBARU%20USA%200518/WINDOWS_APP_GUIDE.md)):**
| Code | Category (EN) | Description |
|------|---------------|-------------|
| 0A | ENGINE MAIN | Engine internals, block, heads |
| 1A | MANUAL TRANS | Clutch, gears, casing |
| 1B | AUTO TRANS | Torque converter, planetary gears |
| 5A | BODY/BUMPER | Body panels, bumpers, mirrors |
| 9B | INNER ACCESSORIES | Floor mats, cargo nets, etc. |

**Notes:**
- Group codes are alphanumeric (typically digit + letter)
- Multilingual strings are space-padded to 40 bytes
- Validated by scanning the file and matching codes to application categories

**Validation:** Cross-reference terms with part descriptions and technical documentation.

### FIG Illustration Records (183-byte Type) (0x0DF9B000+) - **VALIDATED ✓**

**Record size:** 183 bytes
**Encoding:** CP437

Contains multilingual descriptions for individual FIG illustrations (e.g., "CYLINDER BLOCK", "PISTON & CRANKSHAFT"). These records are specifically linked to FIG groups.
Located in blocks around `0x0DF9B000`.

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    2     FIG Group Code      Category code (e.g., "0A", "1B")
0x08    5     FIG Group Code 2    Secondary code (e.g., "003  ")
0x0D    40    Description (EN)    Illustration name in English
0x35    40    Description (DE)    Illustration name in German
0x5D    40    Description (FR)    Illustration name in French
0x85    40    Description (ES)    Illustration name in Spanish
0xAD    10    Trailer/Metadata    LE reference pointers or flags
```

**Examples (Model B11, Group 0A):**
- English: `004  CYLINDER BLOCK`
- English: `010  PISTON & CRANKSHAFT`
- English: `005  TIMING HOLE PLUG & TRANSMISSION BOL`

**Notes:**
- Used to populate the illustrated index names in the application.
- Record size (183) is one byte smaller than the FIG Group category records.
- The FIG index (e.g., 004, 010) is typically embedded at the start of the English description.

**Validation:** Matches FIG illustration titles in the illustrated index menu.

### FIG Illustration Page Records (89-byte Type) (0x0DFA5000+) - **NEW**

**Record size:** 89 bytes
**Encoding:** CP437

Contains sub-indexing for FIG illustrations, mapping specific FIG indices to page numbers and labels (e.g., "VALVE", "CYLINDER BLOCK"). These records likely link illustrations to the actual part data.
Located in blocks around `0x0DFA5000`.

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    3     FIG Index           Illustration index (e.g., "002")
0x09    2     Padding             Usually spaces
0x0B    2     Page Index          Page number (e.g., "01", "02")
0x0D    40    Label               ASCII label (e.g., "VALVE")
0x35    36    Trailer/Metadata    Binary data (likely pointers)
```

**Notes:**
- Index numbers are ASCII strings, not 16-bit integers.
- The label field is often padded with spaces.
- The 36-byte trailer contains binary pointers that likely reference block indices in the part data region.

**Validation:** Index numbers and labels match the illustrations documented in the 183-byte records.

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
 
 ### Part Group Records (185-byte Type) (0x0DFD3000+) - **NEW**

**Record size:** 185 bytes
**Encoding:** CP437

Contains descriptive names for part groups (e.g., "ENGINE ASSEMBLY", "GASKET AND SEAL KIT"). These records provide the text for the group-level navigation in the catalog.
Located in blocks around `0x0DFD3000`.

**Structure:**
```
Offset  Size  Field               Description
------  ----  -----               -----------
0x00    6     Model Code          "B11", "G11", etc.
0x06    3     Figure              FIG index (e.g., "001")
0x09    4     Figure Page         Section/Page within figure (e.g., "01  ")
0x0D    8     Part Code           Base part code (e.g., "0110100 ")
0x15    40    Description (EN)    Multilingual English label
0x3D    40    Description (DE)    German label
0x65    40    Description (FR)    French label
0x8D    40    Description (ES)    Spanish label
0xB5    4     Trailer/Metadata    Binary metadata
```

**Notes:**
- Each multilingual field (EN, DE, FR, ES) is exactly 40 bytes.
- The first 12 bytes of the EN field often contain a part base code or reference (e.g., "  0110100   ").
- In other languages, the first 12 bytes are typically spaces, though they may overflow from long descriptions.

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

### Figure Index Records (22-byte Type) (0x0E75D800+) - **VALIDATED ✓**

**Record size:** 22 bytes
**Encoding:** CP437

Maps model-specific figures and item codes to numeric metadata.

**Structure:**

| Offset | Width | Field                    | Description |
|--------|-------|--------------------------|-------------|
| 0x00 | 6 | Model Code               | e.g. `B11   `, `W10   ` |
| 0x06 | 5 | Not Verified Figure      | FIG index (numeric, e.g. `003  `, `010  `) |
| 0x0B | 7 | Not Verified Item Index | Identification sub-code (numeric, e.g. `01004  `) |
| 0x12 | 4 | Metadata                 | Binary metadata (possibly record pointers) |

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

Mapping of model codes and figures to full part numbers and multilingual names.
Located in blocks around `0x0E147000`.

**Structure:**

| Offset | Width | Field | Description |
|--------|-------|-------|-------------|
| 0x00 | 6 | Model Code | e.g. `B11   ` |
| 0x06 | 5 | Figure | FIG index (e.g. `004  `) |
| 0x0B | 2 | Figure Page | Section/Page within figure (e.g. `01`) |
| 0x0D | 15 | Part Number | Full 15-char part number |
| 0x1C | 4 | Unknown | Binary metadata |
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
- tekious.txt structure (256-byte records at 0x800)
- figname.txt / figgname.txt format
- XOR 0x44 encoding for figure primitives
- 183-byte figure record size

### Medium Confidence (Pattern Matching)
- sffastus model table offsets
- VIN record structure (38 bytes)
- Multilingual record format (33 bytes)
- Model-spec record size (~69 bytes)

### Speculative (Needs Validation)
- source_data_us.txt flag meanings
- Diagram compression format
- SFMESSDT internal structure
- Exact coordinate offsets in figure primitives
