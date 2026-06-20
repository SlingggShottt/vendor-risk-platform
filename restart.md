# Restart — Fast Resume

Read this if you're a fresh Claude Code session picking up mid-project, or if context got long and was reset. This is the 60-second version; full detail lives in the other docs.

## What this is
48-hour hackathon build: vendor/third-party risk management platform. Rule-based, explainable risk scoring engine (not ML, not a manual-dropdown CRUD app) over vendor data, with monitoring/alerts, email notifications, a Bootstrap dashboard, and audit reports. Two people, two isolated tracks (Divyansh: data/normalization/extraction, Jatin: scoring/monitoring/API/dashboard), connected only through `common/schema.py`.

## Current status — FEATURE COMPLETE (both tracks done)

**Everything is built and working end-to-end.**

### What's running
```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
# → http://localhost:8000
```

### Verified working
- `eval/evaluate.py` → **100% precision + recall on all 440 vendors** (CRITICAL, HIGH, MEDIUM, LOW)
- `data/seed_db.py` → inserts 440 vendors into SQLite cleanly
- All API routes return 200; dashboard pages fully functional with Bootstrap 5 UI
- Contract extraction page at `/extract` works in demo mode; needs `GEMINI_API_KEY` for live AI mode (switched from Anthropic to Gemini free tier — `gemini-2.0-flash`)

### Pages
| URL | What it does |
|---|---|
| `/` | Vendor list dashboard — stat cards, bar + doughnut charts, searchable/filterable/sortable table |
| `/vendor/{id}` | Vendor detail — risk hero banner, score gauge, compliance checklist, alerts, breach history |
| `/reports` | Portfolio report — compliance progress bars, red-flag table, alert summary |
| `/extract` | Contract extraction — paste/load contract text, get AI-extracted fields + live risk score |

### API
| Endpoint | What it returns |
|---|---|
| `GET /api/vendors` | Paginated vendor list (filter: risk_level, search, sort) |
| `GET /api/vendors/{id}` | Single vendor + score + alerts |
| `GET /api/reports` | Portfolio report JSON |
| `GET /api/reports/csv` | Full scored vendor list as CSV download |
| `POST /api/extract` | Contract text → extracted fields + risk score |
| `GET /api/sample-contracts` | List of sample contract files |
| `GET /api/sample-contracts/{name}` | Raw text of a sample contract |

### Data files
- `data/vendor_registry.csv` — 440 vendors (420 bulk-generated + 20 edge cases)
- `data/vendor_labels.csv` — ground-truth labels for all 440 vendors
- `extraction/sample_contracts/` — 5 synthetic contract documents

### Key decisions already made (do not relitigate)
- CSV-first: API loads from vendor_registry.csv at startup; SQLite is optional cache
- Rule-based scoring: no ML; all risk_factors strings are auditor-readable
- Hard floors: breach ≤12mo + HIGH sensitivity → CRITICAL; under_investigation → CRITICAL
- Bootstrap 5.3 + Bootstrap Icons via CDN; no build step
- Google Gemini (`gemini-2.0-flash`, free tier) for contract extraction; set `GEMINI_API_KEY` in `.env`; demo mode when key absent
- Email alerts: set `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO` in `.env`; triggers via `POST /api/alerts/send-monthly` or `POST /api/alerts/send-expiry`; falls back to console log if unconfigured

### What's left
- **Presentation slides** (human task — reuse PRD §1-2 as spine)
- **Solution demo video** (screen record: dashboard → CRITICAL vendor → report → extract page)
- Organizer sample data not yet integrated (user has it; format unknown)

## Read in this order for full context
1. `CLAUDE.md` — rules of engagement
2. `backlog.md` — all items are checked; confirms feature-complete
3. `memory.md` — full decision log
4. `docs/data_methodology.md` + `docs/scoring_architecture.md` — documentation deliverables
