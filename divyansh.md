# Divyansh — Working Doc (Data, Normalization, Extraction)

You own everything under `data/` and `extraction/`. You do not touch `scoring/`, `monitoring/`, `api/`, or `dashboard/` — that's Jatin's lane. Your only shared-edit files are `common/schema.py` and `api/db.py`, and only with explicit agreement (see `CLAUDE.md`).

## Your job, in one sentence
Produce vendor data — realistic, messy in the right places, schema-conformant — that Jatin's scoring engine can consume, and prove it covers the edge cases the rubric needs to be tested against.

## Your task list
Full detail in `backlog.md` under "Divyansh" — work through it top to bottom, core before stretch. Update checkboxes as you go.

## Key things to get right

**1. The generator must produce data that *exercises* every rule in the rubric (`PRD.md` §5), not just plausible-looking random data.** If nothing in your dataset has `under_investigation=true`, Jatin's hard-floor rule for it is untestable. Deliberately control the distribution:
- Some % recently breached + HIGH access (should hit CRITICAL floor)
- Some % expired certs on sensitive-access vendors
- Some % expired contracts with still-populated data_access
- Some % low financial rating
- Some % missing GDPR DPA
- A meaningful LOW-risk baseline (don't make everything scary — see PRD §"~80% flagged" note, but that still leaves a real LOW population)

**2. `vendor_labels.csv` ground truth must be derived using the exact same rubric in `PRD.md` §5 — not your own independent judgment call.** If you hand-label based on vibes, Jatin's eval numbers measure agreement with your vibes, not the rubric. Write a small reference implementation of the rubric (even a rough one) to generate labels, or coordinate directly with Jatin's `scoring/risk_engine.py` logic once it exists — ideally these converge, with eval measuring "does the implemented engine match the intended rubric," not "does the engine match arbitrary labels."

**3. The schema-inconsistency problem is a deliberate feature, not noise.** The original brief showed the same vendor (VND-0285) represented two different ways — nested vs flat, different field names, even contradicting values. Your `normalize.py` should take a "messy" input shape and reconcile it into the canonical `common/schema.py` shape. Build a couple of intentionally-inconsistent raw records to prove normalize.py actually does something (don't let "normalization" be a no-op because your generator only ever produces already-clean data).

**4. Validate against the schema as you go.** Every record in `vendor_registry.csv` should be loadable into the `Vendor` Pydantic model without errors. If `common/schema.py` is missing a field you need, that's a "stop and discuss" moment, not a "just add an extra column" moment — Jatin is depending on that file too.

## Suggested internal order (within your H1-H16 block)
1. Write the rubric reference logic (rough is fine) — you need this to generate honest labels anyway
2. Build the bulk generator with controlled distributions
3. Run the rubric over generated data to produce `vendor_labels.csv`
4. Hand-write edge cases (`edge_cases.py`), append to both CSVs
5. Build `normalize.py` against 2-3 intentionally inconsistent raw shapes
6. Validate everything against `common/schema.py`, fix drift
7. Commit, push to your branch, ping Jatin that real CSVs are ready

## When you're done with core
Check `backlog.md` — if Jatin's checkpoint (H16) hasn't happened yet, use spare time polishing edge case variety based on what would actually stress-test a risk engine, rather than jumping straight to the PDF extraction stretch goal. More/better edge cases are higher value than a half-built stretch feature.

## Upgrade Sprint tasks (your lane)

### 1. PDF contract extraction
Add PDF support to the existing extraction pipeline — do NOT rewrite it, just add a pre-processing step.

- Create `extraction/parse_pdf.py` with a single function `extract_text_from_pdf(path: str | Path) -> str` using `pdfplumber`. Install: `pip install pdfplumber`.
- In `extraction/extract_contract.py`, update `extract_from_contract()` to also accept a file path: if a string ends in `.pdf`, call `parse_pdf.extract_text_from_pdf()` first, then pass the resulting text to Groq as normal. The existing contract text path stays unchanged.
- Coordinate with Jatin: he updates `POST /api/extract` to accept `multipart/form-data` with an optional `file` field. You just need your extraction function to handle both text and PDF path inputs.

### 2. Bulk CSV upload — parsing layer
Write the data parsing function that the bulk upload API endpoint will call.

- Create `data/bulk_ingest.py` with `ingest_csv_bytes(raw_bytes: bytes) -> list[Vendor]`. It should:
  - Parse the bytes as a CSV (use `csv.DictReader` on `io.StringIO(raw_bytes.decode())`)
  - Run each row through `normalize_csv_row(row)` from `data/normalize.py`
  - Collect errors per-row without crashing (return partial results + error list)
  - Return `(vendors: list[Vendor], errors: list[dict])` tuple
- Jatin wires this into `POST /api/vendors/bulk-upload` — you just need to export the function cleanly.
- Add `requirements.txt` entry: `pdfplumber>=0.11.0`
