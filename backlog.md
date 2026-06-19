# Backlog

Granular task list. `plan.md` = when; this file = what, in detail, checked off as you go. Each person updates only their own section's checkboxes (but anyone can read both).

## Shared (H0-H1)

- [x] `common/schema.py` frozen and committed
- [x] Fixture vendors (5-8) written and committed
- [x] Git repo + branches set up
- [x] `api/db.py` table shape agreed (or CSV-first decision logged in `memory.md`) — CSV-first, logged in memory.md

## Divyansh — Data, Normalization, Extraction

### Core
- [x] `data/generate_vendors.py`: parameterized generator (count, % breached, % cert-expired, % contract-expired, category distribution)
- [x] Generated output validates against `common/schema.py` `Vendor` model (no silent schema drift)
- [x] `data/edge_cases.py`: hand-scripted vendors —
  - [x] one with conflicting schema fields (simulate the two-different-JSON-shapes problem) — VND-9008 MaxRisk (all flags set simultaneously)
  - [x] one breached <12mo + HIGH access (must trigger CRITICAL floor) — VND-9001, VND-9008
  - [x] one under_investigation flag set — VND-9002
  - [x] one cert expiring in exactly 59/60/61 days (boundary test for alerts) — VND-9003/9004/9005
  - [x] one orphaned access (contract_end in the past, data_access still populated) — VND-9006
  - [x] one good vendor, zero issues (sanity check LOW path) — VND-9007
- [x] `vendor_registry.csv` committed (430 rows: 420 bulk + 10 edge cases)
- [x] `vendor_labels.csv` committed — ground truth derived using the SAME rubric in `PRD.md` §5
- [x] `data/normalize.py`: takes raw/inconsistent-shape input, reconciles into canonical `Vendor` schema
- [ ] `data/seed_db.py`: loads CSVs into SQLite via `api/db.py` models (only once DB shape is agreed — deferred, CSV-first per memory.md)

### Stretch
- [ ] `extraction/sample_contracts/`: 3-5 synthetic contract texts/PDFs with embedded SLA/breach-notification/access-scope clauses
- [ ] `extraction/extract_contract.py`: LLM-assisted extraction into `Vendor`-compatible fields
- [ ] Wire extracted fields back into registry as an optional override source

### Docs contribution
- [ ] Write the "data generation methodology + edge cases" section for the documentation deliverable

## Jatin — Scoring, Monitoring, API, Dashboard

### Core
- [ ] `scoring/rules.py`: individual rule functions, each returning (triggered: bool, factor_description: str, severity contribution)
- [ ] `scoring/risk_engine.py`: applies hard floors first, then weighted rubric (PRD §5), outputs `ScoredVendor`
- [ ] `scoring/recommend.py`: generates the `recommendation` string from risk_level + top risk_factors
- [ ] Engine runs clean against H0 fixtures, producing sane output (manual eyeball check before touching real data)
- [ ] `eval/evaluate.py`: precision/recall overall + CRITICAL/HIGH-specific recall, against `vendor_labels.csv`
- [ ] Tune rubric weights if CRITICAL recall is below ~95% (log every weight change in `memory.md` with before/after recall numbers)
- [ ] `monitoring/alerts.py`: cert expiry (30/60/90 day windows), contract expiry + active access check, breach-recency flag
- [ ] `monitoring/emailer.py`: monthly summary email + expiry alert email, swappable backend (real SMTP if creds available, console/log fallback otherwise — must not block other work on missing credentials)
- [ ] `api/db.py`: SQLAlchemy models + engine (agreed shape from H0)
- [ ] `api/main.py` + `api/routes/vendors.py`: list/filter/get vendor + score
- [ ] `api/routes/reports.py`: portfolio report endpoint (mirrors the brief's report format: risk summary, red-flag vendors, compliance stats) + CSV export endpoint
- [ ] `dashboard/`: vendor list (sortable/filterable), alert indicators, risk-level bar chart (Chart.js), "is vendor X compliant" search/lookup, export-to-CSV button

### Stretch
- [ ] Postgres swap (only if SQLite is somehow insufficient — unlikely)

### Docs contribution
- [ ] Write the "scoring algorithm rationale" and "API/UI architecture" sections for the documentation deliverable
