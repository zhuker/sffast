# Plan: Support the JDM (Japan-market) Subaru FAST2 database

## Context

The parser today (`sffastus_parser.py`, `sffastus_database.py`, `parsers_common.py`) only
handles the US-market `sffastus` binary. We obtained the JDM discs (`subaru_08_04/*.mdf`,
converted to ISO and mounted — e.g. `/Volumes/30804SF/SFFASTA`). Investigation showed the JDM
file is the **same format family** (same magic `00 04 01 00`, same block-pointer encoding,
**same `MODEL_BLOCK_INDEX` slot→type map**), but differs in four concrete, now-understood ways:

1. **Model-index record size is per-file**: US = 288 B (45-slot pointer array), modern JDM
   (20710SF/30804SF) = 420 B (78-slot array). Records are fixed-size *within* a file; the array
   is wider because JDM carries more figure-image pointer slots. The 102-byte text trailer is
   byte-identical; size = `6 + array_len + 102`.
2. **Text encoding**: JDM text fields are **Shift-JIS / cp932** (half-width katakana mixed with
   ASCII), vs US `cp437`. Decoding everything as `cp932` is correct for both JP and ASCII content.
3. **Multilingual collapse**: US records carry **4 language fields** (EN/DE/FR/ES); JDM carries
   **1** (Japanese). This fully explains every differing record size: `US_size − JDM_size =
   3 × field_width`. The record dataclasses already model the 4 fields explicitly
   (`desc_en/de/fr/es`, `color_name_en/de/fr/es`, `name_en/de/fr/es`).
4. **Catalog record reorganized**: `CatalogApplicabilityRecord466` → **496 B** in JDM, and the
   internal layout is *re-arranged* (not just a tail append) — `spec_logic`, `figure_ref`,
   `fig_page` move. Needs a real JDM field map.
5. **VIN/chassis lookup differs**: JDM VIN-range records are **22 B** (`chassis_start(9) +
   chassis_end(9) + ptr(4)`) keyed by 9-char chassis numbers (`BE5002001`), vs US 38-B/17-char.

**Approved scope:** Core parsing **+ VIN(chassis) resolution**; target **modern clean discs
only** (20710SF + 30804SF, 420-B profile); **reverse-engineer Cat496 now**. Older `10710SF`
(402-B, unresolved 2-byte anomaly) is explicitly out of scope.

**Outcome:** `SffastDatabase.open("…/SFFASTA")` auto-detects region, and `get_model`,
figure/category/part-group/inventory/parts accessors, descriptions, and `resolve_vin(chassis)`
all work for JDM — while US behavior is unchanged (region auto-detected, US is the default).

---

## Approach: a detected `RegionProfile` threaded through the parser

Introduce one profile object, detected once at `open()`, that carries every region-varying
constant. Select it from a small **registry keyed by detected model-record size** (we only
support two known profiles; an unknown size raises a clear error rather than guessing).

```python
@dataclass(frozen=True)
class RegionProfile:
    name: str                 # 'US' | 'JDM'
    model_record_size: int    # 288 | 420
    model_array_len: int      # model_record_size - 108  (180 | 312)
    encoding: str             # 'cp437' | 'cp932'
    num_languages: int        # 4 | 1
    count_region_start: int   # first count-pair slot: 30 | 52
    cat_size: int             # 466 | 496
    vin_record_size: int      # 38 | 22
    vin_id_len: int           # 17 | 9
    record_sizes: dict        # record_id -> size for THIS region (built from base + lang math)
```

- `count_region_start` makes `MODEL_BLOCK_COUNTS` derivable by the existing formula
  (`count_slot = count_region_start + idx//2`, `'hi' if idx even else 'lo'`), which already
  matches the hardcoded US map — so the count map becomes region-parameterized, not duplicated.
- `record_sizes` is built once: same-size types keep their class `RECORD_SIZE`; the multilingual
  types are `head + num_languages × field_width + trailer`; `catalog_applicability` = `cat_size`.

**Detection at open()** (logic already prototyped during investigation):
- `model_record_size`: read first model block, find the trailer's `sdate+edate` (12 ASCII digits
  after the pointer array via regex), `size = date_offset + 85`.
- `encoding`/region: high-byte scan of the model-name field → `cp932` (JDM) else `cp437` (US);
  `num_languages` and the rest come from the matching registry profile.
- Unknown size → `raise ValueError(f"Unsupported model-record size {n}")`.

---

## Implementation phases & files

### Phase 1 — Profile + model index (gets `get_model()` working for JDM)
**Files:** `sffastus_parser.py`, `sffastus_database.py`, `parsers_common.py`

- Add `RegionProfile`, `REGION_PROFILES` registry, and `detect_region_profile(first_model_block)`
  to `sffastus_parser.py`.
- `SffastusBlockParser.__init__` (sffastus_parser.py:2100): add `profile: RegionProfile = US_PROFILE`
  and store it (it already holds `figure_codes`).
- `parse_model_index(f, header)` (sffastus_parser.py:3322): add `profile` param; replace the
  hardcoded `288` / `BLOCK_SIZE // 288` / `i * 288` with `profile.model_record_size`.
- `ModelIndexRecord288.parse_288` (sffastus_parser.py:1956): take `profile`; slice
  `data[6:6+profile.model_array_len]`; compute trailer-field offsets relative to
  `model_record_size - 102` (the 102-B trailer is shared); decode text with `profile.encoding`.
- `get_model_block_section` (sffastus_parser.py:3346): use `profile.count_region_start` +
  the existing index→count formula instead of the hardcoded `MODEL_BLOCK_COUNTS` slots.
  Keep `MODEL_BLOCK_INDEX` **as-is** (verified shared across regions).
- `SffastDatabase.open` (sffastus_database.py:108): after `SffastusHeader.parse`, read the first
  model block, `detect_region_profile(...)`, pass profile into `SffastusBlockParser(...)` and
  `parse_model_index(...)`, and store `self._profile`.

### Phase 2 — Encoding (Shift-JIS) without breaking US
**Files:** `sffastus_parser.py`

- Give `clean(b, encoding='cp437')` / `clean_nostrip(b, encoding='cp437')` (sffastus_parser.py:24)
  an optional encoding arg, **defaulting to current behavior** (US tests untouched).
- `_parse_fixed_records` (sffastus_parser.py:2461) already takes `record_size` + `parse_fn`;
  pass `profile.encoding` (and `num_languages`, Phase 3) through to `parse_fn`.
- The text-bearing `parse_NNN` static methods get an optional `encoding='cp437'` param and pass
  it into their `clean()` calls. Default = US, so existing callers/tests are unaffected.

### Phase 3 — Per-record size + language-count (the −120/−60 records)
**Files:** `sffastus_parser.py`

- Drive `_parse_fixed_records`'s `record_size` from `profile.record_sizes[record_id]` instead of
  the class `RECORD_SIZE` constant (route via the `parse_*_records_*` wrappers, which are instance
  methods and can read `self._profile`).
- Multilingual `parse_NNN` methods take `num_languages` (default 4): read **one** language field
  at the existing English offset and place the trailer at `english_offset + num_languages ×
  field_width` (US=4 → unchanged; JDM=1 → −3×width). Populate `*_en` with the single field for
  JDM, leave `*_de/_fr/_es` empty. Applies to: `MultilingualPartRecord180/182/192`,
  `FIGGroupCategoryRecord184`, `FIGIllustrationRecord183`, `PartGroupRecord185`,
  `InventoryRecord199`, `ColorRecord91` (the field offsets/widths are already documented in each
  dataclass docstring — EN start + 40-B fields, 20-B for color).
- Same-size, no-language types (`engine_spec_230`, `model_year_44`, `figure_index_22`,
  `spec_mapping_22`, `part_range_24`, `category/version_index_20`, `variant_glossary_81`,
  `fig_illustration_page_89`, `multilingual_part_167`) work once encoding is set — no size change.

### Phase 4 — Catalog 466 → 496 (reverse-engineer the field map)
**Files:** `sffastus_parser.py`

- Rename `CatalogApplicabilityRecord466` → size-agnostic `CatalogApplicabilityRecord` and its
  `ID` `'catalog_applicability_466'` → `'catalog_applicability'` (update `MODEL_BLOCK_INDEX` key,
  `_load`/`get_catalog_parts` callers, and the `is_catalog_applicability_block_*` dispatch).
- Keep `parse_466` as the US layout; **RE and add `parse_496`** for JDM (head fields through 0x2D
  align with US; `dest`/`spec_logic`/`ref_code`/`figure_ref`/`fig_page` are relocated — map them by
  dumping records and matching field semantics, as started in investigation).
- Add `parse_cat(data, offset, profile)` dispatching on `profile.cat_size` to `parse_466`/`parse_496`;
  `_parse_fixed_records` strides by `profile.cat_size`.

### Phase 5 — VIN / chassis resolution
**Files:** `parsers_common.py`, `sffastus_parser.py`

- `get_vehicle_by_vin` (parsers_common.py:222): branch on `profile`. For JDM, parse **22-B**
  chassis-range records (`chassis_start(9) + chassis_end(9) + ptr(4)`) and match a 9-char chassis
  id; follow the pointer to the JDM detail record (map its layout — US `VINModelRecord` is 69 B;
  confirm JDM size/fields during impl).
- Add a JDM chassis parse path (new `parse_chassis_ranges` or parameterize `parse_vin_blocks` by
  `profile.vin_record_size`/`vin_id_len`).
- `is_valid_subaru_vin` (sffastus_parser.py:56): accept JDM chassis ids (3-letter chassis prefix
  + 6 digits) for the JDM profile, or gate the validity check on profile so chassis lookups aren't
  rejected. Prefix routing in `get_vehicle_by_vin` already splits US vs JDM blocks via the header.

### Phase 6 — Tests + docs
**Files:** `test_sffastus.py`, `DATA_FORMAT_SPEC.md`, `CLAUDE.md`

- Add a JDM data path constant and ensure the file is available at a stable location (copy the
  converted `30804SF/SFFASTA` into a repo dir, e.g. `SFCDJDM/sffasta`, or reference the mount).
  Per project rule: missing data must **fail** (FileNotFoundError), not skip.
- Add JDM test classes mirroring US ones: profile detection, `parse_model_index` (expect
  B12/B13/G11/G12…), a same-size record (engine_230), a language-collapsed record
  (fig_group_category 64-B with Japanese desc), Cat496 parse, and a chassis resolve (`BE5002001`).
- Keep all US tests green (defaults preserve US behavior).
- Document the JDM format deltas (profile, language collapse, Cat496 map, chassis records) in
  `DATA_FORMAT_SPEC.md`; note the JDM data location + ISO-mount workflow in `CLAUDE.md`.

---

## Reuse (do not re-implement)
- `MODEL_BLOCK_INDEX` (sffastus_parser.py:3265) — **shared across regions**, reuse unchanged.
- `_parse_fixed_records` (sffastus_parser.py:2461) — already stride-parameterized; the injection point.
- `decode_block_pointer`, the 102-B trailer layout, `is_*_block_*` detectors, `iter_model_blocks`.
- Record dataclasses' existing `*_en/_de/_fr/_es` fields and documented offsets/widths.

## Out of scope (flag, don't build)
- `10710SF` (402-B, 2-byte middle anomaly, 1980s data).
- JDM external text files `FIGNODT.TXT` (figname) / `TEKIO.TXT` (ITCA) — figure-name and
  interchange lookups; `SffastDatabase.open` already accepts `figname`/`itca` kwargs, so these
  can be wired later. `get_figname` / ITCA chain features degrade gracefully until then.

---

## Verification (end-to-end)

1. **Unit tests:** `.venv/bin/python -m unittest test_sffastus` — all US tests still pass; new
   JDM tests pass.
2. **Profile + models:**
   ```python
   db = SffastDatabase.open("SFCDJDM/sffasta")     # or the mounted /Volumes/30804SF/SFFASTA
   assert db._profile.name == 'JDM'
   assert 'B12' in {m for m in db._models}          # Legacy etc.
   ```
3. **Language-collapsed record decodes Japanese:** `get_fig_group_categories(db.get_model('B12'))`
   → records whose `desc_en` holds e.g. `ｴﾝｼﾞﾝ ｼﾕｷ` (cp932), no mojibake.
4. **Parts (Cat496):** `get_catalog_parts(db.get_model('B12'))` returns records with sane
   `part_id` / `figure_ref` / `fig_page` (cross-check a known part like `010108200`).
5. **Chassis resolve:** `db.resolve_vin('BE5002001')` returns a `Vehicle` with the right model.
6. **US regression spot-check:** open `SFCDUS2/sffastus`, confirm `get_model('B11')` and an
   English description (`BELT-TIMING`) are unchanged.
