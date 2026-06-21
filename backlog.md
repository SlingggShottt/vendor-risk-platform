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

### Enterprise Sprint — Data Layer
- [x] Update `common/schema.py`: add `AuditLog` + `ComplianceSummary` models
- [x] `data/compliance_export.py`: format vendor compliance data for export (CSV, JSON)
- [x] `data/audit_helper.py`: structured audit event builder

## Jatin — Scoring, Monitoring, API, Dashboard

### Core
- [x] `scoring/rules.py`: individual rule functions, each returning (triggered: bool, factor_description: str, severity contribution)
- [x] `scoring/risk_engine.py`: applies hard floors first, then weighted rubric (PRD §5), outputs `ScoredVendor`
- [x] `scoring/recommend.py`: generates the `recommendation` string from risk_level + top risk_factors
- [x] Engine runs clean against H0 fixtures, producing sane output (manual eyeball check before touching real data)
- [x] `eval/evaluate.py`: precision/recall overall + CRITICAL/HIGH-specific recall, against `vendor_labels.csv`
- [x] Tune rubric weights — CRITICAL recall 1.000, HIGH recall 1.000 (100% after boundary fix)
- [x] `monitoring/alerts.py`: cert expiry (30/60/90 day windows), contract expiry + active access check, breach-recency flag; `triggered_at` datetime on each alert
- [x] `monitoring/emailer.py`: monthly summary + expiry alert + EOD digest emails; swappable SMTP/console backend
- [x] `monitoring/scheduler.py`: daily 08:00 UTC alert check + 17:00 IST EOD digest; wired into startup
- [x] `api/db.py`: SQLAlchemy models + engine
- [x] `api/main.py` + `api/routes/vendors.py`: list/filter/sort/get + `POST /api/vendors` (add vendor, immediate alert email)
- [x] `api/routes/reports.py`: portfolio report + CSV export + PDF export + compliance-export (JSON/CSV)
- [x] `api/routes/audit.py`: `GET /api/audit-log` with date/actor/action/vendor filters
- [x] `api/routes/bulk.py`: `POST /api/vendors/bulk-upload` CSV ingestion
- [x] `dashboard/`: vendor list (sortable/filterable), vendor detail, reports, contract extraction, add-vendor form

### Enterprise Sprint — Scoring & API
- [x] `scoring/risk_engine.py`: `explain_vendor_score()` — rule-by-rule contribution breakdown
- [x] `GET /api/vendors/{id}/risk-explainer` — weight, raw_score, contribution, descriptions per rule
- [x] `GET /api/reports/compliance-export?format=json|csv` — portfolio compliance summary + per-vendor rows
- [x] `monitoring/audit_logger.py`: in-memory audit log with `log_event()` + `query_log()` helpers
- [x] `GET /api/audit-log` — filterable audit trail (actor, action, resource_type, vendor_id, date range)
- [x] FastAPI auto-generates OpenAPI schema at `/openapi.json`; Swagger UI at `/docs` — nav link added
- [x] Rate limiting: 100 req/min per IP via `slowapi`
- [x] CORS: restricted to localhost + onrender.com
- [x] Security headers: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`

### Stretch (all shipped)
- [x] Postgres swap — N/A, CSV-first confirmed sufficient
- [x] `POST /api/vendors/bulk-remediate` — mass acknowledge / renew-cert / require-DPA, audit-logged
- [x] `GET /api/reports/bulk-export` — XLSX streaming (2 sheets: vendor list + compliance summary)
- [x] Resend backend for emailer (primary; replaces SMTP as recommended path; free, no config friction)
- [x] Slack backend for emailer
- [x] Predictive score trend — `GET /api/vendors/{id}/history` returns 6-month history + linear regression + projected level in 3 months
- [x] `POST /api/reports/email` — dashboard button sends monthly portfolio summary via configured backend
- [x] `POST /api/reports/email-alerts` — dashboard button sends CRITICAL/HIGH alert digest
- [x] `sample_inputs/` — full demo input library: CSV (10 vendors + labels + bulk), add-vendor JSON (6 levels), API JSON (nested/flat/alt fields + bulk-remediate), contract .txt files (4 scenarios)
- [x] `docs/technical_report.md` — full research paper for hackathon judges
- [x] `docs/demo_script.md` + `docs/demo_script_full.md` — timed SAY/DO scripts for presentation
- [x] `docs/vendor_risk_platform_deck.pptx` — 16-slide corporate deck (dark navy + amber)
