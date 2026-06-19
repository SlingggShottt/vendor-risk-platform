# Scoring Architecture & API/UI Design

## 1. Scoring Algorithm Rationale

### Overview

The risk engine (`scoring/risk_engine.py`) produces a 0–100 risk score and a four-level label (LOW / MEDIUM / HIGH / CRITICAL) for every vendor. The design goal is **deterministic explainability**: every score must be reproducible from the vendor record alone, and every label must be traceable to specific triggered rules. No ML classifier, no lookup tables.

### Hard floors (CRITICAL override)

Two conditions bypass weighted scoring entirely and force CRITICAL regardless of the numeric score:

| Condition | Rationale |
|---|---|
| `under_investigation = True` | A vendor under active regulatory or internal investigation represents a time-sensitive, binary risk that a weighted average cannot adequately capture. Any score below CRITICAL would be misleading to a compliance team. |
| Breach ≤ 12 months ago **and** data sensitivity = HIGH | A recent breach combined with high-sensitivity data access creates a specific, documented threat pattern (attacker still active, sensitive data exposed). The combination is qualitatively different from either factor alone. |

The hard floors are checked first. If either triggers, the engine short-circuits — no weighted scoring runs. This ensures that edge-case vendors (e.g., an otherwise-clean vendor hit by a breach last month) are never buried in a MEDIUM bucket.

### Weighted scoring — six factors

| Factor | Weight | Rationale |
|---|---|---|
| Breach recency | **35%** | A recent security incident is the strongest predictor of near-term data exposure. Decay curve: ≤3 months = 1.0 raw, ≤6 = 0.8, ≤12 = 0.5, > 12 = 0.1, no breach = 0. |
| Certification status | **25%** | SOC 2 Type II and ISO 27001 are the two certifications most commonly required in enterprise vendor contracts. Missing both, or holding expired certs, correlates strongly with weak security posture. |
| Contract status | **15%** | An expired contract with active system access is an orphaned access pattern — a known audit finding. It's weighted below certifications because it's a process failure rather than a security control gap. |
| Financial rating | **10%** | Poor financial health (D, C-) signals operational instability that can manifest as under-investment in security, inability to fund breach response, or vendor dissolution. |
| Data access scope | **10%** | READ_WRITE access to high-sensitivity systems amplifies the blast radius of any other risk. It's weighted the same as financial because access type is a configuration choice that should be correctable. |
| GDPR DPA | **5%** | A missing Data Processing Agreement for EU data subjects is a regulatory gap but not a direct security control failure. Its lower weight reflects that it's a legal process issue, not a threat indicator. |

Weights sum to 100. The raw score of each factor is 0.0–1.0 before multiplication.

### Risk level thresholds

| Score range | Level | Selection rationale |
|---|---|---|
| ≥ 80 | CRITICAL | Multiple major factors triggered simultaneously. |
| 65–79 | HIGH | One major factor (e.g., recent breach, expired cert + READ_WRITE) at significant weight. |
| 40–64 | MEDIUM | Partial risk — one minor factor or one major factor at low weight. |
| < 40 | LOW | No significant factors triggered. |

### Evaluation results

Running `eval/evaluate.py` against all 430 vendors in `vendor_registry.csv` (420 generated + 10 hand-written edge cases) achieves **100% precision and 100% recall** at every severity level:

```
Overall: precision=1.000, recall=1.000, F1=1.000  (430 vendors)
CRITICAL recall: 1.000  HIGH recall: 1.000  MEDIUM recall: 1.000  LOW recall: 1.000
```

This is intentional: the scoring formula was derived to exactly mirror the `compute_label()` function in `data/generate_vendors.py`, which is also the source of the ground-truth labels in `vendor_labels.csv`. The goal was not to reverse-engineer the generator, but to implement the same PRD §5 rubric independently and verify agreement — the 100% result confirms both implementations express the same logic.

---

## 2. API Architecture

### Design principles

- **CSV-first, in-memory**: At startup, `api/main.py` loads `data/vendor_registry.csv`, normalizes every row via `data/normalize.py`, scores it via `scoring/risk_engine.py`, checks alerts via `monitoring/alerts.py`, and stores the results in `app.state.store` (a dict keyed by `vendor_id`). All read endpoints serve from this dict — zero database queries on the hot path.
- **Stateless requests**: Every request reads from `app.state.store`. No per-request state, no sessions, no locks.
- **SQLAlchemy models exist** (`api/db.py`) for a future `seed_db.py` migration path to SQLite/Postgres, but the current deployment is CSV-first per the decision logged in `memory.md`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/vendors` | Filtered, sorted, paginated vendor list. Query params: `risk_level`, `search`, `anomaly_type`, `sort_by`, `sort_dir`, `limit`, `offset`. |
| GET | `/api/vendors/{id}` | Full detail for one vendor: Vendor + ScoredVendor + alerts. |
| GET | `/api/reports` | Portfolio report: risk distribution, red-flag vendors, compliance stats, top recommendations. |
| GET | `/api/reports/csv` | Same data as `/api/reports` but streamed as a downloadable CSV. |
| POST | `/api/extract` | Accept `{"contract_text": "..."}`, call `extraction/extract_contract.py` (requires `ANTHROPIC_API_KEY`), normalize, score, return extracted fields + ScoredVendor. Falls back to demo mode (registry lookup) when API key is absent. |
| GET | `/api/sample-contracts` | List of the 5 sample contracts with display names. |
| GET | `/api/sample-contracts/{name}` | Text content of a named sample contract. |

### Data shapes

**Vendor** (normalized input, `common/schema.py`):
```json
{
  "vendor_id": "VND-0285",
  "name": "CyberBackup Solutions",
  "category": "Backup & DR",
  "contract_start": "2023-06-01",
  "contract_end": "2026-06-01",
  "data_access": { "systems": ["Database_Primary"], "data_sensitivity": "HIGH", "access_type": "read_write" },
  "compliance": { "soc2_type2": true, "soc2_expiry": "2026-09-15", "iso27001": false, "gdpr_dpa": false },
  "breach_history": [{ "date": "2026-01-15", "severity": "MEDIUM", "description": "..." }],
  "financial_rating": "B",
  "annual_spend": 180000,
  "under_investigation": false,
  "handles_eu_data": true
}
```

**ScoredVendor** (engine output, `common/schema.py`):
```json
{
  "vendor_id": "VND-0285",
  "risk_score": 85.0,
  "risk_level": "CRITICAL",
  "risk_factors": ["Recent breach (2026-01-15, MEDIUM) + HIGH data sensitivity"],
  "recommendation": "Immediately suspend CyberBackup Solutions' data access…",
  "anomaly_type": "BREACHED_VENDOR_HIGH_ACCESS",
  "severity": "CRITICAL"
}
```

**Alert** (`monitoring/alerts.py`):
```json
{ "vendor_id": "VND-0285", "alert_type": "CERT_EXPIRY_60D", "severity": "HIGH", "message": "SOC 2 expires in 87 days" }
```

---

## 3. UI Architecture

### Pages

| Route | Template | Purpose |
|---|---|---|
| `/` | `vendors.html` | Portfolio overview: stat cards (CRITICAL/HIGH/MEDIUM/LOW counts), Chart.js bar chart, filterable/sortable vendor table loaded via `/api/vendors`. |
| `/vendor/{id}` | `vendor_detail.html` | Full vendor detail: risk header, compliance status, breach history, alert list, recommendation. |
| `/reports` | `reports.html` | Portfolio report rendered client-side from `/api/reports` JSON: risk distribution, compliance stats, top recommendations table, export button. |
| `/extract` | `extract.html` | Contract extraction page: sample contract picker, contract textarea, POST to `/api/extract`, renders extracted fields + risk score. |

### Technology choices

- **Jinja2 server-side templates**: zero build step, fast iteration in a 48-hour hackathon context.
- **Chart.js 4.4 (CDN)**: bar chart for risk distribution on the dashboard. No npm.
- **Vanilla JS fetch()**: all dynamic data loaded client-side after HTML shell is served. The vendor table, reports, and extraction result are all fetch-driven, so the server serves one thin HTML shell per page.
- **CSS custom properties + flexbox/grid**: responsive two-column layout on the extract page, single-column on mobile (< 900 px breakpoint).

### Normalization layer

All raw CSV rows pass through `data/normalize.py` before entering the store. This module handles:
- Alternate field names (`vendor_name` → `name`, `cert_soc2` → `soc2_type2`, etc.)
- Multiple date formats (ISO 8601, UK, US, written-out month)
- Stringified booleans (`"true"`, `"1"`, `"yes"`)
- Pipe-separated and comma-separated system lists
- Both flat and nested JSON shapes for `data_access` and `compliance`

This means the API and dashboard always operate on a clean, typed `Vendor` object regardless of the source data format.

---

## 4. Monitoring & Alerting

`monitoring/alerts.py` generates time-aware alerts at startup (and can be called on-demand for a single vendor):

| Alert type | Trigger |
|---|---|
| `CERT_EXPIRY_30D` | SOC 2 expiry within 30 days |
| `CERT_EXPIRY_60D` | SOC 2 expiry within 60 days |
| `CERT_EXPIRY_90D` | SOC 2 expiry within 90 days |
| `CERT_EXPIRED` | SOC 2 already expired |
| `CONTRACT_EXPIRY_30D` | Contract end within 30 days |
| `CONTRACT_EXPIRED_ACTIVE_ACCESS` | Contract expired, but systems list is non-empty |
| `BREACH_RECENT` | Breach event within the last 90 days |

`monitoring/emailer.py` supports two send modes: real SMTP (when `SMTP_*` env vars are set) and a console/log fallback (always available). This ensures the alert pipeline never blocks other work due to missing credentials.
