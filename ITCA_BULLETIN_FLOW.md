# I&S Bulletin (ITCA Bulletin) Access Flow

## Overview

Pages 40+ in the EngineSpecRecord230 / FIGIllustrationPage89 data are **I&S Bulletin** (Installation & Service Bulletin) illustrations. They are NOT accessible through the normal figure browser — they are only reachable through the ITCA part interchangeability chain.

## Access Flow in Windows App

1. Look up a **part code** (e.g., `91121` = FRONT GRILLE ASSEMBLY)
2. App resolves to a **part number** for your VIN (e.g., `91121FE190`)
3. An **[Exist]** button appears (ITCA interchangeability)
4. Clicking shows interchangeable parts (e.g., `93013FE120` and `91121FE110`)
5. On a part with ITCA codes 4, 6, 7, or 8, a secondary **[Exist]** button appears in the **"ITCA Bltn"** column
6. Clicking opens the I&S Bulletin illustration page (e.g., page `911-41` "FRONT GRILLE")

## Data Structure

In EngineSpecRecord230, bulletin pages have:
- `figure_page` >= 40
- `applicable_model` = `"ALL"` followed by a part number (space-padded)

Example:
```
page=41 spec="ALL                                     91121FE190" dates=200009-
```

The embedded part number (`91121FE190`) is the part that triggers the bulletin display through the ITCA chain.

## FIGIllustrationPage89 Labels

Bulletin pages are labeled with `I&SBULLETIN` (with spelling variants `I & S BULLTIN`, `I & S BLLETIN`):
```
page=41 fig=911 label="I&SBULLETIN         FRONT GRILLE"
page=40 fig=921 label="I&SBULLETIN         REAR SPOILER"
```

## Color-Coded Bulletins

Some bulletins have color-specific part numbers (2-letter paint code suffix):
```
page=40 spec="ALL                                     96061FE020PG"
page=41 spec="ALL                                     96061FE020TG"
page=42 spec="ALL                                     96061FE020BW"
page=43 spec="ALL                                     96061FE020WG"
...
```

The suffix (PG, TG, BW, WG, BH, HD, IU, MJ, RQ, VO, VW) corresponds to paint color codes. Only the bulletin matching the vehicle's paint code would be relevant.

## Verified Example (G11 STI, VIN JF1GD70655L510047)

**Works:** Part code 91121 -> 91121FE190 -> ITCA chain -> 91121FE110 -> [Exist] in ITCA Bltn -> opens page 911-41

**No bulletin:** Part code 96061 -> 96061FE200WG -> ITCA chain -> 96061FE201WG -> no [Exist] in ITCA Bltn column (the bulletin references `96061FE020WG`, a different part number)

## Statistics (G11 in SFCDUS2)

- Regular illustration pages (01-39): 568
- I&S Bulletin pages (40+): 136
- Total: 704

## Filtering in vin_figures.py

Bulletin pages are excluded from the main figure listing (page >= 40) and reported separately as a summary line at the end.
