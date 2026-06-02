The goal of this project is to reverse engineer data formats in "Subaru FAST 2" software which is a subaru proprietary software to retrieve parts by VIN

NEVER ever read tekious.txt as a text file it has no CR or CRLF so head or tail or cat end up hanging claude process

There are 3 data directories SFCDUS1, SFCDUS2, SFCDUS3 they are updates of each other

NEVER write anything into SFCDUS* data directories

The main binary data file is at SFCDUS2/sffastus (not in a subdirectory)

Use local .venv to run python: `.venv/bin/python` (has Pillow, wand, etc.)

Use unittest module for testing (not pytest): `.venv/bin/python -m unittest test_sffastus`

All tests MUST pass - any failure is a regression.

NEVER use `os.path.exists` to skip tests when data files are missing. If a required file does not exist, the test MUST fail with a fatal error (FileNotFoundError), not silently pass.

NEVER add a `Co-Authored-By: Claude` (or any Claude/AI co-author) trailer to commit messages.

## Data Format Documentation

See `DATA_FORMAT_SPEC.md` for all decoded data formats (block pointers, record types, field layouts, callout coordinates, etc.)

## Region support (US / JDM)

The parser auto-detects the market region at `SffastDatabase.open()` and carries it in a
`RegionProfile` (`sffastus_parser.py`). US is the default; modern JDM discs (20710SF,
30804SF) are supported. The profile carries: model-record size (288 US / 420 JDM),
text encoding (cp437 / cp932), language-field count (4 EN/DE/FR/ES / 1 JP), count-region
start slot, catalog record size (466 / 496), and VIN/chassis record sizes. Detection
keys on the model-record size (date-anchored). Unknown sizes raise `ValueError` (e.g.
10710SF/402 is intentionally unsupported). See the "JDM Region Variant" section of
`DATA_FORMAT_SPEC.md` for all deltas.

- JDM test data lives at `SFCDJDM/sffasta` (converted from `subaru_08_04/30804SF.mdf`;
  gitignored). The `.mdf`/`.mds` discs are Alcohol 120% images — convert with
  `iat -i <disc>.mdf -o <disc>.iso --iso` then `hdiutil attach`.
- When threading region behavior, pass `profile` through `parse_model_index`,
  `iter_model_blocks`, `get_model_block_section`; decode text via `clean(b, encoding)`;
  multilingual records use `read_langs(...)` + `num_languages`.

## Code Architecture

- `sffastus_parser.py` — core parser module
  - `SffastusBlockParser` class: all block detection (`is_*_block_*`) and parsing (`parse_*_records_*`) methods; constructor takes `figure_codes: set` for disambiguating 22-byte record types
  - Module-level: dataclasses for all record types, utility functions (`decode_block_pointer`, `is_valid_model_code`, `is_valid_subaru_vin`), `parse_figname_txt`, `parse_itca_data`
- `parsers_common.py` — shared constants, parser creation, VIN resolution helpers
- `figure_parts_map.py` — extract figure image + draw callout boxes for a VIN (combines PartGroup185 + Inventory199 coords with Cat466 parts)
- `vin_figures.py` — find applicable figures for a VIN via EngineSpecRecord230 spec logic
- `test_sffastus.py` — unit tests; uses a module-level `parser` instance created with figure codes from `SFCDUS2/sffastpg/win/figname.txt`
