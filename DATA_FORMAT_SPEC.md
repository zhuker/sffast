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

### Model Index Records (0x13000 - 0x14000) - **CONFIRMED**

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
| 0xCB | 6 | Start Date | `YYYYMM` (ASCII) |
| 0xD1 | 6 | End Date | `YYYYMM` (ASCII) |
| 0xD7 | 14 | Features | Flags (`12345...`) |
| 0xE5 | 8 | Category 1 | `BODY    ` |
| 0xED | 8 | Category 2 | `ENGINE  ` |
| 0xF5 | 8 | Category 3 | `TRAIN   ` |
| 0xFD | 8 | Category 4 | `MISSION ` |
| 0x105 | 8 | Category 5 | `GRADE   ` |
| 0x10D | 8 | Category 6 | `SUS     ` |

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
| 0 | 15 | Part number | Current part number |
| 15 | 1 | Blank | Separator |
| 16 | 1 | Blank | Separator |
| 17 | 1 | ITCA code | Status/type code |
| 18 | 1 | Blank | Separator |
| 19 | 15 | ITCA part number | Supersedes-to part number |
| 34 | 1 | Blank | Separator |
| 35 | 2 | Q'ty | Quantity |
| 37 | 1 | Blank | Separator |
| 38 | 7 | Part code | Figure/category code |
| 45 | 1 | Blank | Separator |
| 46 | 40 | Part name | Description text |
| 86 | 1 | CR.LF | Line terminator |

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

## 4. FIGNAME.TXT - Figure Group Descriptions

**Location:** `SFCDUS*/sffastpg/win/figname.txt`
**Size:** ~15 KB
**Format:** Fixed-width ASCII, 3-char code + description

### Key Codes - **TO VALIDATE**

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
| 262 | FRONT BRAKE | ? |
| 263 | REAR BRAKE | ? |

**Validation:** Compare these codes/names to figure category list in the app.

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
