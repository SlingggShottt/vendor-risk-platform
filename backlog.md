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
- [x] `data/seed_db.py`: loads CSVs into SQLite via `api/db.py` models — updated to match real api/db.py API, inserts 440 rows clean

### Stretch
- [x] `extraction/sample_contracts/`: 5 synthetic contract texts covering LOW/MEDIUM/HIGH, expired contract, under-investigation, missing GDPR DPA
- [x] `extraction/extract_contract.py`: LLM-assisted extraction via claude-opus-4-8 + structured output, returns dict for normalize_raw_vendor()
- [x] Wire extracted fields back into registry as an optional override source (`extraction/merge_extracted.py`)

### Docs contribution
- [x] Write the "data generation methodology + edge cases" section (`docs/data_methodology.md`)

## Jatin — Scoring, Monitoring, API, Dashboard

### Core
- [x] `scoring/rules.py`: individual rule functions, each returning (triggered: bool, factor_description: str, severity contribution)
- [x] `scoring/risk_engine.py`: applies hard floors first, then weighted rubric (PRD §5), outputs `ScoredVendor`
- [x] `scoring/recommend.py`: generates the `recommendation` string from risk_level + top risk_factors
- [x] Engine runs clean against H0 fixtures, producing sane output (manual eyeball check before touching real data)
- [x] `eval/evaluate.py`: precision/recall overall + CRITICAL/HIGH-specific recall, against `vendor_labels.csv`
- [x] Tune rubric weights if CRITICAL recall is below ~95% — no tuning needed, achieved 100% precision + recall on all 430 vendors on first run
- [x] `monitoring/alerts.py`: cert expiry (30/60/90 day windows), contract expiry + active access check, breach-recency flag
- [x] `monitoring/emailer.py`: monthly summary email + expiry alert email, swappable backend (real SMTP if creds available, console/log fallback otherwise — must not block other work on missing credentials)
- [x] `api/db.py`: SQLAlchemy models + engine (agreed shape from H0)
- [x] `api/main.py` + `api/routes/vendors.py`: list/filter/get vendor + score
- [x] `api/routes/reports.py`: portfolio report endpoint (mirrors the brief's report format: risk summary, red-flag vendors, compliance stats) + CSV export endpoint
- [x] `dashboard/`: vendor list (sortable/filterable), alert indicators, risk-level bar chart (Chart.js), "is vendor X compliant" search/lookup, export-to-CSV button

### Stretch
- [ ] Postgres swap (only if SQLite is somehow insufficient — unlikely)

### Docs contribution
- [x] Write the "scoring algorithm rationale" and "API/UI architecture" sections for the documentation deliverable → `docs/scoring_architecture.md`

## Upgrade Sprint (post-deployment)

### Divyansh — PDF + Bulk Ingest
- [x] `extraction/parse_pdf.py`: PDF → text using pdfplumber; expose as `extract_text_from_pdf(path) -> str`
- [x] Update `extraction/extract_contract.py`: detect if input is a file path ending in `.pdf`, call `parse_pdf.py` first, then send text to Groq as normal
- [x] Update `POST /api/extract` in `api/routes/extract.py`: accept `multipart/form-data` with optional `file` field (PDF upload) alongside existing `contract_text` field
- [x] Update `/extract` page (coordinate with Jatin): add file upload input alongside the textarea
- [x] `data/bulk_ingest.py`: parse an uploaded CSV of vendors, run each row through `normalize_csv_row()`, return list of `Vendor` objects ready to score
- [ ] New API endpoint `POST /api/vendors/bulk-upload` (Jatin wires it, Divyansh writes the parsing function it calls)

### Jatin — Monitoring, Charts, PDF Report, Bulk Upload endpoint
- [ ] `monitoring/scheduler.py`: APScheduler job that runs daily at 08:00, calls `check_alerts()` on all store vendors, sends email via `get_emailer()` if any CRITICAL/HIGH alerts found — auto-monitoring, no manual button press needed
- [ ] Wire scheduler into `api/main.py` startup (start in background thread)
- [ ] `api/routes/vendors.py`: add `GET /api/vendors/{id}/history` — returns 6-point mock score history (seed deterministically from vendor_id hash so it's consistent across reloads)
- [ ] `dashboard/templates/vendor_detail.html`: add sparkline chart (Chart.js line) showing 6-month score trend in the vendor detail hero section
- [ ] `api/routes/reports.py`: add `GET /api/reports/pdf` — generate PDF portfolio report using WeasyPrint or ReportLab; full scored vendor table + compliance stats + red-flag section
- [ ] Add "Download PDF Report" button in `dashboard/templates/reports.html` next to existing Download CSV
- [ ] `POST /api/vendors/bulk-upload`: accepts CSV file upload, calls Divyansh's `bulk_ingest.py`, scores each vendor, returns JSON array of scored results; also adds them to the in-memory store so dashboard reflects them immediately

## Enterprise Sprint (Société Générale focus — SG placement differentiation)

**Why**: SG is a tier-1 bank with strict compliance/audit requirements. These features demonstrate enterprise thinking and are table-stakes for fintech platforms.

### Divyansh — Data Layer & Schema Support

1. **Compliance Export Infrastructure**
   - [ ] Update `common/schema.py`: add `AuditLog` model (id, timestamp, actor, action, resource_type, resource_id, old_state, new_state, reason)
   - [ ] `data/compliance_export.py` (new): functions to format vendor compliance data for export (CSV, JSON, XLSX-ready dicts)
   - [ ] `data/audit_helper.py` (new): structured audit event builder (standardize event creation across the app)

### Jatin — API, Scoring, & Monitoring (all 7 features)

**PRIORITY 1 — Audit + Explainability (SG's #1 ask: "why is this vendor CRITICAL?")**
- [ ] `monitoring/audit_logger.py` (new): in-memory audit log (structure as DB-backed for production)
- [ ] `api/routes/audit.py` (new): `GET /api/audit-log?date_from=...&date_to=...&actor=...&action=...&vendor_id=...`
- [ ] `scoring/explainer.py` (new): breaks down risk_score into rule-by-rule contributions
- [ ] `api/routes/vendors.py`: add `GET /api/vendors/{id}/risk-explainer` → `{ risk_score, risk_level, contributing_factors: [{rule_name, weight, impact, description}], remediation_actions: [...] }`
- [ ] `api/routes/reports.py`: add `GET /api/reports/compliance-export?format=csv|json` → vendor compliance summary + audit events

**PRIORITY 2 — Trends + OpenAPI (SG needs integration capability + visibility)**
- [ ] `api/routes/vendors.py`: enhance `GET /api/vendors/{id}/history` with predictive trend (linear regression on 6 points; return `trend_direction`, `projected_level_in_3mo`)
- [ ] `api/routes/vendors.py`: add trend-up alert → if trending CRITICAL, flag in alerts
- [ ] `api/main.py`: generate OpenAPI 3.1.0 schema at `GET /api/openapi.json`; wire Swagger UI to `/api/docs`
- [ ] `dashboard/templates/base.html`: add "API Docs" link (routes to Swagger UI)

**PRIORITY 3 — Security + Bulk Ops (table-stakes)**
- [ ] `api/main.py`: add rate limiting (100 req/min per IP via `slowapi`)
- [ ] `api/main.py`: CORS: restrict to `["http://localhost", "https://vendor-risk-platform.onrender.com"]`
- [ ] `api/main.py`: security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`)
- [ ] `api/routes/bulk.py` (new): `POST /api/vendors/bulk-remediate { vendor_ids, action, reason }` → updates all, logs audit
- [ ] `api/routes/jobs.py` (new): async job tracking (`POST /api/jobs/bulk-export`, `GET /api/jobs/{id}`)
- [ ] `api/routes/reports.py`: `GET /api/reports/bulk-export?format=xlsx` → stream XLSX file

**PRIORITY 4 — Slack Integration (ops teams live in Slack)**
- [ ] `monitoring/emailer.py`: add Slack backend (posts to webhook with rich formatting)
- [ ] Env var: `SLACK_WEBHOOK_URL`
- [ ] `api/routes/alerts.py`: integrate Slack into `POST /api/alerts/send-expiry` and `/send-monthly`
- [ ] Dashboard: show "Slack ✓" status badge on `/reports` if webhook configured
