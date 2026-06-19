# Vendor & Third-Party Risk Management Platform

A deterministic, explainable vendor risk scoring platform built for a 48-hour hackathon. Tracks vendor certifications, contract status, breach history, and data access scope — scores each vendor against a rubric-based engine with 100% CRITICAL/HIGH recall — and surfaces results via a live dashboard, portfolio reports, and alert emails.

## Quick start

```bash
# 1. Clone and set up
git clone https://github.com/SlingggShottt/vendor-risk-platform
cd vendor-risk-platform
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Generate vendor data (440 vendors + ground-truth labels)
python data/generate_vendors.py
python data/edge_cases.py

# 3. (Optional) Load into SQLite
python data/seed_db.py

# 4. Run the evaluation — confirms 100% precision + recall
python eval/evaluate.py --today 2026-06-19

# 5. Start the dashboard
uvicorn api.main:app --reload --port 8000
# Open http://localhost:8000
```

## What it does

| Question | Answer |
|---|---|
| Is vendor X compliant? | Dashboard search → detail page → risk level + cert status in under 5 seconds |
| Which vendors need immediate action? | `/api/vendors?risk_level=CRITICAL` or dashboard CRITICAL filter |
| Full portfolio report | `/api/reports` (JSON) or `/api/reports/csv` (download) |
| Alerts firing before expiry? | `/api/vendors/{id}` → `alerts[]`; monitoring fires 30/60/90 days before cert/contract expiry |

## Architecture

```
[Data Layer]                    [Scoring Engine]              [Surface Layer]
 generate_vendors.py             scoring/rules.py    ──>  dashboard/ (FastAPI + Jinja2)
 edge_cases.py         ──>       scoring/risk_engine.py   api/routes/vendors.py
 normalize.py                    scoring/recommend.py      api/routes/reports.py
 vendor_registry.csv             monitoring/alerts.py      monitoring/emailer.py
 vendor_labels.csv               eval/evaluate.py
 extraction/ (stretch)
```

The contract between the two tracks is `common/schema.py` — `Vendor` (input) and `ScoredVendor` (output).

## Risk scoring rubric (PRD §5)

**Hard floors** (guarantee CRITICAL regardless of weighted score):
- Breach in last 12 months + HIGH data sensitivity → CRITICAL
- Vendor flagged `under_investigation` → CRITICAL

**Weighted factors** (0-100):

| Factor | Weight | What triggers it |
|---|---|---|
| Breach recency + sensitivity | 35% | Recent breach decays over time, scaled by data sensitivity |
| Certification status | 25% | Missing/expired SOC2 or ISO27001 on sensitive-access vendor |
| Contract status | 15% | Expired contract + active system access (orphaned) |
| Financial rating | 10% | C/D ratings signal viability risk |
| Data access scope | 10% | READ_WRITE + HIGH sensitivity |
| GDPR DPA missing | 5% | Missing DPA when vendor handles EU data |

**Risk levels:** 0-39 LOW · 40-64 MEDIUM · 65-79 HIGH · 80-100 CRITICAL

## Evaluation results

```
Vendors scored: 440 (420 bulk-generated + 20 hand-crafted edge cases)
Binary precision:  1.000
Binary recall:     1.000
CRITICAL recall:   1.000  (70/70) ← key metric
HIGH recall:       1.000  (40/40) ← key metric
```

## Project structure

```
common/schema.py              — Shared Pydantic models (Vendor, ScoredVendor, etc.)
data/
  generate_vendors.py         — Bulk synthetic vendor generator (420 vendors, seed=42)
  edge_cases.py               — 20 hand-crafted stress-test scenarios (VND-9001–9020)
  normalize.py                — Schema reconciliation (40+ field aliases, 7 date formats)
  seed_db.py                  — CSV → SQLite loader
  vendor_registry.csv         — 440 vendor records
  vendor_labels.csv           — Ground-truth labels (derived from PRD §5 rubric)
scoring/
  rules.py                    — Atomic rule functions (hard floors + weighted factors)
  risk_engine.py              — Orchestrates rules → ScoredVendor
  recommend.py                — Generates auditor-ready recommendation text
monitoring/
  alerts.py                   — Cert/contract expiry + breach recency alerts
  emailer.py                  — Monthly summary + expiry alerts (SMTP or console fallback)
api/
  db.py                       — SQLAlchemy models (VendorRow, ScoredVendorRow)
  main.py                     — FastAPI app + dashboard HTML routes
  routes/vendors.py           — /api/vendors (list/filter/detail)
  routes/reports.py           — /api/reports (JSON + CSV download)
dashboard/
  templates/                  — Jinja2 HTML (vendors list, detail, reports)
  static/style.css            — Styles
eval/evaluate.py              — Precision/recall evaluation against ground truth
extraction/
  extract_contract.py         — LLM-assisted field extractor (claude-opus-4-8)
  merge_extracted.py          — Merges extraction output back into registry
  sample_contracts/           — 5 synthetic contract documents for testing
docs/
  data_methodology.md         — Data generation methodology + edge case catalogue
  scoring_architecture.md     — Scoring algorithm rationale + API/UI architecture
```

## API reference

```
GET  /                          Dashboard home (HTML)
GET  /vendor/{id}              Vendor detail page (HTML)
GET  /reports                  Portfolio report page (HTML)

GET  /api/vendors              List vendors (filter: risk_level, search, limit, offset)
GET  /api/vendors/{id}         Single vendor detail + score + alerts
GET  /api/reports              Portfolio report (JSON)
GET  /api/reports/csv          Portfolio report (CSV download)
```

## Key design decisions

- **CSV-first, SQLite optional**: the API loads and scores vendors from CSV at startup; SQLite is an opt-in cache, not a hard dependency. This meant both tracks could develop without blocking on each other.
- **Deterministic labels**: ground-truth labels are generated by `compute_label()` in `generate_vendors.py`, which implements the exact PRD §5 rubric — so `eval/evaluate.py` measures "does the engine match the rubric?" not "does the engine match the dev's gut feel?"
- **Hard floors guarantee CRITICAL recall**: regardless of weighted scoring, any vendor with a recent breach + HIGH sensitivity, or under investigation, is guaranteed CRITICAL. This is why CRITICAL recall is 100%.
- **No ML, no manual dropdowns**: the scoring is rule-based and explainable. Every `risk_factors` string maps directly to the rule that fired it.

## Environment variables

```
ANTHROPIC_API_KEY   — Required for extraction/extract_contract.py (LLM extraction)
DATABASE_URL        — SQLAlchemy URL (default: sqlite:///vendor_risk.db)
USE_SQLITE          — Set to "true" to have the API read from SQLite instead of CSV
SMTP_HOST           — SMTP server for email alerts (optional; falls back to console)
SMTP_PORT           — SMTP port (default: 587)
SMTP_USER           — SMTP username
SMTP_PASS           — SMTP password
ALERT_FROM_EMAIL    — Sender address for alert emails
ALERT_TO_EMAIL      — Recipient address for alert emails
```

## Built by

- **Divyansh** — data layer (`data/`, `extraction/`, `docs/data_methodology.md`)
- **Jatin** — scoring engine, monitoring, API, dashboard (`scoring/`, `monitoring/`, `api/`, `dashboard/`, `eval/`)
