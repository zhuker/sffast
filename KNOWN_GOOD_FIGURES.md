# Known Good Figure Extraction

## Overview

Figure illustrations in Subaru FAST 2 are stored as **CCITT Group 4** (T.6)
compressed monochrome (1-bit) images within the `sffastus` binary data file.
The images are used by the IBM Image Browsing Facility (IBF) DLL stack
(IBFIW32.DLL / IBFCW32.DLL / IBFVB32.DLL) for display in the application.

## Verified Parameters

| Parameter | Value | How determined |
|-----------|-------|----------------|
| Image width | **1280 pixels** | Iterative testing: w<900 causes G4 decode errors; w=1000 had content only in left portion; w=1280 decodes without errors and matches app display |
| Image height | **640 pixels** | Verified against app display. Both index table and fig001 fit exactly in 1280x640 (last content at row 638) |
| Compression | CCITT Group 4 (T.6) | Confirmed by IBF DLL analysis (IBFIW32.DLL exports IvtSetIocaData2 etc.) and successful G4 decoding |
| Bit depth | 1 bpp (bilevel) | Monochrome black/white illustrations |
| PhotometricInterpretation | WhiteIsZero (0) | White background, black lines/text |
| Fill order | MSB first (default) | Standard TIFF G4 |

## G11 Index Table

The first verified extraction is the **G11 illustration index table** — a
table listing all figure groups, their names, and page ranges for the G11
(Impreza) model.

### Location in sffastus

- **File**: `SFCDUS2/sffastus`
- **Offset**: `0x1745F800` (start of G11 binary image region)
- **Size**: ~35 blocks (71,680 bytes of raw G4 data)
- **Decoded dimensions**: 1280 x 640 pixels

### How the offset was found

1. The G11 binary image region was identified by scanning sffastus for large
   contiguous non-text data blocks. There are 10 such regions, one per model
   group (B11, B12, B13, C12, G10, G11, S10, S11, S12, W10).

2. 89-byte figure page records at `0x1725E800` contain block pointers to
   individual figure pages. The first figure (fig 001/01) has ptr3 =
   `0x17471000`, which is 35 blocks after the region start.

3. The data at the region start (`0x1745F800`) is NOT referenced by any
   89-byte record — it is a "pre-figure" image containing the index table.

### Width determination process

1. Initial guess w=2339 showed a readable table at the top-left of a wide
   image with garbage below — the table was too small in the corner.

2. Narrowing down: widths below 900 caused G4 decode errors at line 49.
   Width 1000 decoded cleanly but had empty space on the right.

3. User compared the extracted image against the running application and
   noticed an alphanumeric string at the bottom-right extending beyond
   w=1000.

4. Testing w=1280: **zero G4 decode errors**, correct table dimensions,
   bottom-right string visible. Confirmed as the correct width.

### Extraction method

The raw G4 bytes are wrapped in a minimal TIFF container with the correct
width/height tags, then decoded by Pillow (libtiff). See `known_good_figures.py`.

```
sffastus bytes at 0x1745F800 (71,680 bytes)
    ↓
Wrap in TIFF header (Group 4, 1280 wide, 640 tall)
    ↓
PIL/Pillow Image.open() + .load() → decodes G4
    ↓
1280 x 640 PNG
```

## G4 Encoding Variants

Both the index table and figure pages are CCITT Group 4 at 1280x640, but they
differ in one way:

| | Index table | Figure pages (e.g., fig001) |
|--|------------|----------------------------|
| First bytes | `FF FF FF FF FF F2 B9 80` | `FF FF FF FE 5A 02 85 3C` |
| G4 mode | Standard Huffman codes only | Standard + **T.6 uncompressed mode** |
| Decoder | Pillow/libtiff works | Needs ImageMagick |

The T.6 uncompressed mode extension uses escape sequence `0000001111` in the
bitstream to switch from Huffman-coded data to raw uncompressed pixel bits.
This is defined in the T.6 standard but rarely implemented:

- **Pillow/libtiff 4.7.1**: Does NOT support it (`UNCOMPRESSED_SUPPORT` not
  compiled in). Fails with "Uncompressed data (not supported)" at line 8.
- **ImageMagick**: Handles it successfully when given the correct height (640).

If libtiff were compiled with `UNCOMPRESSED_SUPPORT`, both could use the same
decoder.

## G11 Fig001 (Figure 001, Page 01)

The first individual figure page for G11 (Impreza). This is a parts
illustration showing engine/body components with numbered callouts.

### Location in sffastus

- **File**: `SFCDUS2/sffastus`
- **Offset**: `0x17471000` (ptr3 from 89-byte record at `0x1725E800`)
- **Size**: 4520 bytes (s2 field from 89-byte record)
- **Decoded dimensions**: 1280 x 640

### Extraction method

Raw G4 bytes are wrapped in a TIFF container with the correct dimensions,
then decoded by ImageMagick (needed for T.6 uncompressed mode support).
See `known_good_fig001.py`.

```
sffastus bytes at 0x17471000 (4520 bytes)
    ↓
Wrap in TIFF header (Group 4, 1280 wide, 640 tall)
    ↓
ImageMagick `magick input.tif output.png`
    ↓
1280 x 640 PNG (matches app display)
```

## Figure Data Pointer Encoding (ptr3)

The 4-byte ptr3 field at record bytes [69:73] encodes a file offset to the
raw G4 image data.

### Decompiled source (SFCOMMON.DLL)

The formula was confirmed by decompiling `FUN_100012f0` (OffsetCalculator) in
`SFCOMMON.DLL` via Ghidra. This function is called by 54 other functions
including `FIG_GET`, `GETFC31`, `BuCD_Get`, etc.

```c
/* SFCOMMON.DLL :: FUN_100012f0 — OffsetCalculator */

int __cdecl FUN_100012f0(char *param_1)
{
  return ((param_1[1] + -4 + *param_1 * 0x3c) * 0x4b + (int)param_1[2]) * 0x800;
}
```

This computes: `offset = ((byte1 - 4 + byte0 * 60) * 75 + byte2) * 2048`

For 3-byte block pointers `[byte0, byte1, byte2]`, this gives a block-aligned
file offset. The same formula extends to 4-byte figure data pointers with
sub-block precision.

### Format

```
ptr3 = [marker] [byte1] [byte2] [byte3]
```

### Decoding formula

```
offset = ((byte1 - 4 + marker * 60) * 75 + byte2) * 2048 + byte3 * 8
```

This is a 4-level hierarchical address — the marker byte IS part of the
address, not a flag:

| Component | Multiplier | Unit size | Role |
|-----------|-----------|-----------|------|
| marker (byte 0) | `60 * 75 * 2048` | 9,216,000 bytes | Mega-section |
| byte1 | `75 * 2048` | 153,600 bytes | Section |
| byte2 | `2048` | 2,048 bytes | Block |
| byte3 | `8` | 8 bytes | Position within block |

The constants 60, 75, and 2048 are shared with the block pointer system.
The `byte1 - 4` offset accounts for the file header (first 4 sections are
reserved).

### Verification

- **704 G11 records**: 490 with marker `0x2A` + 214 with marker `0x2B` —
  ALL decode successfully with **zero errors**
- Sequential consistency: each figure's data starts at `ceil(prev_size / 8) * 8`
  bytes after the previous, with 0-8 bytes of alignment padding
- Data at every computed offset starts with valid G4 bitstream bytes
  (first byte `0xFF` for white-background images)
- The image_size field is confirmed as the **exact byte count** of raw G4 data
- The `0x2B` data region follows immediately after the `0x2A` data region
  (2 bytes of alignment padding between them)

### G11 marker ranges

| Marker | byte1 range | Figure range | Records | File offset range |
|--------|-------------|-------------|---------|-------------------|
| `0x2A` | `0x1A`–`0x1C` | fig001–fig607 | 490 | `0x17471000`–`0x1795A366` |
| `0x2B` | `0x00`–`0x0C` | fig620–fig970 | 214 | `0x1795A368`–`0x17B35FC0` |

### Examples

```
fig001/01: ptr3 = 2A 1A 28 00
  block = (0x1A - 4 + 0x2A * 60) * 75 + 0x28 = (22 + 2520) * 75 + 40 = 190690
  offset = 190690 * 2048 + 0 * 8 = 0x17471000  ✓

fig002/05: ptr3 = 2A 1B 02 E9
  block = (0x1B - 4 + 0x2A * 60) * 75 + 0x02 = (23 + 2520) * 75 + 2 = 190727
  offset = 190727 * 2048 + 0xE9 * 8 = 0x17483F48  ✓

fig620/01: ptr3 = 2B 00 04 6D  (first 0x2B record)
  block = (0x00 - 4 + 0x2B * 60) * 75 + 0x04 = (-4 + 2580) * 75 + 4 = 193204
  offset = 193204 * 2048 + 0x6D * 8 = 0x1795A368  ✓
  (immediately after last 0x2A data at 0x1795A366, 8-byte aligned)
```

## All G11 Figures (23 pages)

All 23 G11 figure pages were successfully extracted using the ptr3 decoding
formula. See `known_good_g11_23.py`.

| Fig | Page | Offset | Size | Label |
|-----|------|--------|------|-------|
| 001 | 01 | 0x17471000 | 4,520 | *(index/overview)* |
| 002 | 01 | 0x174721B0 | 15,831 | SHORT BLOCK ENGINE ASSEMBLY |
| 002 | 02 | 0x17475F88 | 17,692 | ENGINE GASKET & SEAL KIT '02MY-'03MY |
| 002 | 03 | 0x1747A4A8 | 19,215 | ENGINE GASKET & SEAL KIT '02MY-'03MY |
| 002 | 04 | 0x1747EFB8 | 20,364 | ENGINE GASKET & SEAL KIT '04MY-'05MY |
| 002 | 05 | 0x17483F48 | 15,762 | ENGINE GASKET & SEAL KIT '04MY-'04MY |
| 002 | 06 | 0x17487CE0 | 20,048 | ENGINE GASKET & SEAL KIT '04MY-'06MY |
| 002 | 07 | 0x1748CB38 | 3,934 | ENGINE GASKET SET '04MY-'04MY |
| 002 | 08 | 0x1748DA98 | 12,914 | ENGINE GASKET & SEAL KIT '05MY-'05MY |
| 002 | 09 | 0x17490D10 | 14,065 | ENGINE GASKET & SEAL KIT '06MY- |
| 002 | 10 | 0x17494408 | 19,347 | ENGINE GASKET & SEAL KIT '06MY- |
| 002 | 11 | 0x17498FA0 | 19,209 | ENGINE GASKET & SEAL KIT '07MY- |
| 004 | 01 | 0x1749DAB0 | 12,514 | SYSTEM |
| 004 | 02 | 0x174A0B98 | 13,648 | BODY |
| 004 | 40 | 0x174A40F0 | 7,761 | I&S BULLETIN COVER-OIL SEPR |
| 005 | 01 | 0x174A5F48 | 9,271 | *(no label)* |
| 006 | 01 | 0x174A8380 | 14,982 | '02MY-'05MY |
| 006 | 02 | 0x174ABE08 | 8,065 | SYSTEM '02MY-'05MY |
| 006 | 03 | 0x174ADD90 | 11,115 | BODY |
| 006 | 04 | 0x174B0900 | 13,521 | SYSTEM '02MY-'06MY |
| 006 | 05 | 0x174B3DD8 | 12,115 | BODY |
| 006 | 06 | 0x174B6D30 | 10,387 | SYSTEM '06MY- |
| 006 | 07 | 0x174B95C8 | 13,012 | SYSTEM 257('07MY- ) |

## Output

| File | Script | Description |
|------|--------|-------------|
| `known_good/g11_index_table.png` | `known_good_figures.py` | G11 illustration index table (1280x640) |
| `known_good/g11_fig001.png` | `known_good_fig001.py` | G11 fig001 illustration (1280x640, matches app) |
| `g11_figures/fig*.png` (23 files) | `known_good_g11_23.py` | All 23 G11 figure pages (1280x640 each) |

## Open Questions

- **Image height**: All 23 G11 figures are 640 pixels tall (confirmed by
  successful decode of every page). Height is not stored in the 89-byte
  records — it is a fixed constant of 640.

- **Ptr3 byte 0**: Always `0x2A` for G11. May differ for other model groups.
  The base offset and ref_byte1 are currently G11-specific constants — need
  to investigate other models to determine if the formula generalizes.
