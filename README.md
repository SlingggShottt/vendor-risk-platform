# Vendor & Third-Party Risk Management Platform

> Enterprise-grade vendor risk scoring, monitoring, and compliance reporting — built in 48 hours.

**Live Demo:** https://vendor-risk-platform.onrender.com


---

## What this is

Enterprises work with hundreds of vendors — cloud providers, SaaS tools, payment processors, contractors. 60% of data breaches involve a third party. Most teams track vendor risk in spreadsheets and can't answer *"Is this vendor compliant right now?"* without scheduling a meeting.

This platform answers that question in under 5 seconds:

- Ingest vendor data (certifications, breach history, contract dates, data access scope)
- Run it through a **deterministic, explainable risk-scoring engine** with 100% CRITICAL/HIGH recall
- Surface results via a **live dashboard**, **audit-ready reports**, **predictive alerts**, and **email/Slack notifications**
- Provide a full **compliance audit trail** for every state change — built for financial-services audit committees

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/SlingggShottt/vendor-risk-platform
cd vendor-risk-platform
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Generate vendor data (440 vendors + ground-truth labels)
python data/generate_vendors.py
python data/edge_cases.py

# 3. (Optional) Load into SQLite
python data/seed_db.py

# 4. Run evaluation — confirms 100% precision + recall
python eval/evaluate.py --today 2026-06-19

# 5. Start the server
uvicorn api.main:app --reload --port 8000
# Open http://localhost:8000
```

Copy `.env.example` to `.env` and fill in credentials for email/Slack alerts (all optional — the platform degrades gracefully to console output if unconfigured).

---

## Features

### Core Platform
| Capability | Detail |
|---|---|
| **Risk Scoring Engine** | Deterministic, rule-based. Hard floors for CRITICAL cases. Weighted rubric for everything else. 100% recall on 440-vendor ground truth. |
| **Vendor Dashboard** | Sortable/filterable list; per-vendor detail with compliance status, breach history, and alert indicators. |
| **Portfolio Reports** | One-click JSON, CSV, and PDF reports — risk summary, compliance stats, red-flag vendors, top recommendations. |
| **Expiry Alerts** | Cert and contract expiry alerts at 30/60/90-day windows. Fires via email, Slack, or console. |
| **Contract Extraction** | LLM-assisted PDF/text contract extraction via Claude API → auto-populates vendor fields. |

### Enterprise Sprint
| Capability | Detail |
|---|---|
| **Compliance Audit Trail** | Append-only log of every state change (startup, bulk upload, remediation, export). Filterable by date, actor, action, and vendor. |
| **Risk Explainer** | Rule-by-rule breakdown of every score: which rule fired, how many points it contributed, and a specific remediation action with deadlines. |
| **Predictive Trends** | 6-month score history with linear regression. Returns `trend_direction`, `projected_score_3mo`, and `projected_risk_level_in_3mo`. Emits a `RISK_TRENDING_CRITICAL` alert if heading toward HIGH/CRITICAL. |
| **OpenAPI / Swagger UI** | Full OpenAPI 3.1.0 spec at `/api/openapi.json`. Interactive Swagger UI at `/api/docs`. |
| **Bulk Remediation** | `POST /api/vendors/bulk-remediate` — mass acknowledge / renew-cert / require-DPA across any vendor list; every change logged to audit trail. |
| **XLSX Export** | Streamed multi-sheet XLSX: all vendors + compliance summary stats. Async job variant via `/api/jobs/bulk-export`. |
| **Slack Integration** | Rich block-message alerts for monthly summaries and expiry events. Priority chain: Slack → SMTP → Console. |
| **Security Hardening** | Rate limiting (200 req/min via slowapi), CORS restrictions, and security headers (`X-Frame-Options`, HSTS, `X-Content-Type-Options`). |

---

## Risk Scoring Rubric

### Hard Floors (guarantee CRITICAL regardless of weighted score)
- Breach within the last 12 months **and** data sensitivity is HIGH → **CRITICAL**
- Vendor flagged `under_investigation` → **CRITICAL**

### Weighted Factors (0–100)

| Factor | Weight | Logic |
|---|---|---|
| Breach recency + sensitivity | **35%** | Recency decays linearly over 36 months; scaled by data sensitivity (HIGH=1.0, MED=0.6, LOW=0.3) |
| Certification status | **25%** | Missing SOC 2 = +0.7; expired SOC 2 = +0.8; expiring ≤60 days = +0.3; no ISO 27001 = +0.3; HIGH sensitivity multiplies by 1.3 |
| Contract status | **15%** | Expired contract + active system access (orphaned) = full weight; expired + no access = partial |
| Financial rating | **10%** | A+ = 0, D = 1.0; C/D ratings signal viability risk |
| Data access scope | **10%** | READ_WRITE + HIGH sensitivity = full weight; READ_WRITE only = 0.3 |
| GDPR DPA missing | **5%** | Flat penalty if vendor handles EU data but no DPA on file |

**Risk levels:** `0–39` LOW · `40–64` MEDIUM · `65–79` HIGH · `80–100` CRITICAL

---

## Evaluation Results

```
Vendors scored:     440  (420 bulk-generated + 20 hand-crafted edge cases)
Binary precision:   1.000
Binary recall:      1.000
CRITICAL recall:    1.000  (70/70)   ← primary metric
HIGH recall:        1.000  (40/40)   ← primary metric
```

The labels file is derived using the same PRD §5 rubric as the engine — so the eval measures *"does the engine implement the rubric correctly?"* not gut-feel agreement.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Data Layer                  Core Engine               Surface Layer │
│                                                                      │
│  generate_vendors.py   ──>   scoring/rules.py    ──>  dashboard/    │
│  edge_cases.py               scoring/risk_engine.py   api/routes/   │
│  normalize.py                scoring/recommend.py     reports (CSV  │
│  vendor_registry.csv         scoring/explainer.py      / PDF / XLSX)│
│  vendor_labels.csv           monitoring/alerts.py                   │
│  extraction/ (LLM)           monitoring/emailer.py    Slack/Email   │
│                              monitoring/scheduler.py  Alerts        │
│                              monitoring/audit_logger.py             │
│                              eval/evaluate.py                       │
└─────────────────────────────────────────────────────────────────────┘
```

The contract between the data track and the scoring track is `common/schema.py` — `Vendor` (input) and `ScoredVendor` (output). Neither track depends on the other's internals.

---

## API Reference

Interactive docs available at `/api/docs` (Swagger UI) and `/api/redoc`.

### Vendors
```
GET  /api/vendors                   List vendors — filter: risk_level, search, anomaly_type, sort_by, limit, offset
POST /api/vendors                   Add a new vendor (normalize → score → alert → store)
GET  /api/vendors/{id}              Full vendor detail: score, compliance, breach history, alerts
GET  /api/vendors/{id}/history      6-month score history + trend direction + 3-month projection
GET  /api/vendors/{id}/risk-explainer  Rule-by-rule score breakdown + remediation actions
```

### Bulk Operations
```
POST /api/vendors/bulk-upload       CSV upload → normalize → score → add to store (returns scored results)
POST /api/vendors/bulk-remediate    Mass action: acknowledge | renew_cert | require_dpa; logs to audit trail
```

### Reports
```
GET  /api/reports                   Portfolio report: risk summary, compliance stats, red-flag vendors (JSON)
GET  /api/reports/csv               All vendors as flat CSV download
GET  /api/reports/pdf               Portfolio report as formatted PDF
GET  /api/reports/bulk-export       All vendors as XLSX (2 sheets: vendor list + compliance summary)
GET  /api/reports/compliance-export Full compliance snapshot + audit log (?format=json|csv)
```

### Alerts
```
POST /api/alerts/send-expiry        Trigger expiry alert batch (fires via Slack/email/console)
POST /api/alerts/send-monthly       Trigger monthly risk summary
```

### Audit Trail
```
GET  /api/audit-log                 Compliance audit log — filter: date_from, date_to, actor, action, resource_type, vendor_id
```

### Async Jobs
```
POST /api/jobs/bulk-export          Start async XLSX export job → returns job_id
GET  /api/jobs/{job_id}             Poll job status: pending | running | complete | failed
GET  /api/jobs/{job_id}/download    Download completed XLSX
```

### Contract Extraction
```
POST /api/extract                   Extract fields from contract text or PDF upload via Claude API
GET  /api/sample-contracts          List built-in sample contracts
GET  /api/sample-contracts/{n}      Fetch sample contract text
```

### OpenAPI
```
GET  /api/openapi.json              OpenAPI 3.1.0 schema
GET  /api/docs                      Swagger UI
GET  /api/redoc                     ReDoc UI
```

---

## Project Structure

```
vendor-risk-platform/
├── common/
│   └── schema.py                   Shared Pydantic models (Vendor, ScoredVendor, BreachEvent, …)
├── data/
│   ├── generate_vendors.py         Bulk synthetic generator (420 vendors, seeded, reproducible)
│   ├── edge_cases.py               20 hand-crafted stress-test scenarios (VND-9001–9020)
│   ├── normalize.py                Schema reconciliation (40+ field aliases, 7 date formats)
│   ├── bulk_ingest.py              CSV bytes → list[Vendor] (called by bulk-upload endpoint)
│   ├── compliance_export.py        Compliance summary formatters (CSV/JSON/XLSX-ready dicts)
│   ├── seed_db.py                  CSV → SQLite loader
│   ├── vendor_registry.csv         440 vendor records
│   └── vendor_labels.csv           Ground-truth labels derived from PRD §5 rubric
├── scoring/
│   ├── rules.py                    Atomic rule functions — each returns (triggered, raw_score, descriptions[])
│   ├── risk_engine.py              Hard floors → weighted rubric → ScoredVendor
│   ├── recommend.py                Generates auditor-ready recommendation text
│   └── explainer.py                Rule-by-rule breakdown + per-rule remediation actions
├── monitoring/
│   ├── alerts.py                   Cert/contract expiry + breach recency alert generation
│   ├── emailer.py                  Notification backends: Slack > SMTP > Console fallback
│   ├── scheduler.py                APScheduler daily job (08:00 UTC) — auto-runs alerts
│   └── audit_logger.py             Append-only in-memory audit log (AuditLogger singleton)
├── api/
│   ├── main.py                     FastAPI app — CORS, security headers, rate limiting, startup
│   ├── db.py                       SQLAlchemy models (optional SQLite persistence)
│   └── routes/
│       ├── vendors.py              /api/vendors — list, detail, history, risk-explainer
│       ├── reports.py              /api/reports — JSON, CSV, PDF, XLSX, compliance-export
│       ├── bulk.py                 /api/vendors/bulk-upload and bulk-remediate
│       ├── alerts.py               /api/alerts — trigger email/Slack alert batches
│       ├── audit.py                /api/audit-log — compliance audit trail
│       ├── jobs.py                 /api/jobs — async job tracking for bulk exports
│       └── extract.py              /api/extract — LLM contract field extraction
├── dashboard/
│   ├── templates/                  Jinja2 HTML (vendors list, detail page, reports, extract, add-vendor)
│   └── static/style.css            Dashboard styles
├── extraction/
│   ├── extract_contract.py         Claude API field extractor (structured output)
│   ├── merge_extracted.py          Merges extraction output back into vendor registry
│   ├── parse_pdf.py                PDF → text via pdfplumber
│   └── sample_contracts/           5 synthetic contract documents for testing
├── eval/
│   └── evaluate.py                 Precision/recall evaluation against vendor_labels.csv
├── docs/
│   ├── data_methodology.md         Data generation methodology + edge case catalogue
│   └── scoring_architecture.md     Scoring algorithm rationale + API/UI architecture
└── requirements.txt
```

---

## Environment Variables

```bash
# LLM (contract extraction)
ANTHROPIC_API_KEY=          # Required for extraction/extract_contract.py

# Database (optional — defaults to CSV-first)
DATABASE_URL=               # SQLAlchemy URL, e.g. sqlite:///vendor_risk.db
USE_SQLITE=true             # Set to "true" to load from SQLite instead of CSV

# Email alerts (optional — falls back to console output)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=

# Slack alerts (optional — takes priority over SMTP if set)
SLACK_WEBHOOK_URL=          # Incoming webhook URL from your Slack workspace

# Resend (alternative email provider)
RESEND_API_KEY=
```

---

## Key Design Decisions

**CSV-first, SQLite optional.** The API loads and scores all vendors from CSV at startup; SQLite is an opt-in cache. This kept the two build tracks fully independent — neither person blocked on the other.

**Deterministic labels.** Ground-truth labels are generated by `compute_label()` in `generate_vendors.py`, which implements the exact PRD rubric. `eval/evaluate.py` measures *"does the engine match the rubric?"* — not the developer's intuition.

**Hard floors guarantee CRITICAL recall.** Regardless of weighted scoring, any vendor with a recent breach + HIGH data sensitivity, or flagged under investigation, is returned as CRITICAL via an early-return path — not an averaged-in weight. This prevents the weighted average from diluting a true positive.

**Every `risk_factors` string maps to the rule that fired it.** There are no generic labels like `"Risk: certifications"`. Each string is generated inside the rule function itself, with enough context for an auditor to act on it immediately.

**Notification priority chain.** `get_emailer()` returns `SlackBackend` if `SLACK_WEBHOOK_URL` is set, `SMTPBackend` if SMTP credentials are set, and `ConsoleBackend` otherwise. The server never crashes on missing credentials.

---

## Built By

| Track | Owner | Owns |
|---|---|---|
| Data & Extraction | **Divyansh** | `data/`, `extraction/`, `docs/data_methodology.md` |
| Scoring, API & Dashboard | **Jatin** | `scoring/`, `monitoring/`, `api/`, `dashboard/`, `eval/`, `docs/scoring_architecture.md` |
