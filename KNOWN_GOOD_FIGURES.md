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

## Output

| File | Script | Description |
|------|--------|-------------|
| `known_good/g11_index_table.png` | `known_good_figures.py` | G11 illustration index table (1280x640) |
| `known_good/g11_fig001.png` | `known_good_fig001.py` | G11 fig001 illustration (1280x640, matches app) |

## Open Questions

- **Image height**: Both index table and fig001 are 640 pixels tall (verified
  against app). All figures likely use 1280x640. Height is not stored in the
  89-byte records — it appears to be a fixed constant.

- **s2 field**: The 2-byte value at record bytes [85:87] is 4520 for fig001,
  which matches the byte count of raw G4 data. But for fig002/01, s2=15831
  exceeds the gap to the next ptr3 (14336 bytes), suggesting either s2 is not
  a simple byte count or the data is stored as a continuous stream.

- **Continuous stream**: Evidence suggests figure pages may be stored as one
  continuous G4 bitstream. Individual ptr3 pointers may land mid-stream rather
  than at standalone image boundaries.
