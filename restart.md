# Restart — Fast Resume

Read this if you're a fresh Claude Code session picking up mid-project, or if context got long and was reset. This is the 60-second version; full detail lives in the other docs.

## What this is
48-hour hackathon build: vendor/third-party risk management platform. Rule-based, explainable risk scoring engine (not ML, not a manual-dropdown CRUD app) over vendor data, with monitoring/alerts, email notifications, a Bootstrap 5 dashboard, and audit reports. Two people, two isolated tracks (Divyansh: data/normalization/extraction, Jatin: scoring/monitoring/API/dashboard), connected only through `common/schema.py`.

## Current status — DEPLOYED + UPGRADE SPRINT IN PROGRESS

**Core platform is complete and live at https://vendor-risk-platform.onrender.com**

```bash
# Run locally
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
# → http://localhost:8000
```

### What's done
- `eval/evaluate.py` → **100% precision + recall on all 440 vendors**
- All API routes working, Bootstrap 5.3 dashboard fully functional
- Contract extraction at `/extract` — live mode via Groq (`GROQ_API_KEY`), demo fallback when unset
- Email alerts via Resend (`RESEND_API_KEY`) with HTML emails — manual trigger on /reports page
- Docker image (175MB), GitHub Actions CI/CD (eval + docker build gate → Render auto-deploy)

### Environment variables needed
```
GROQ_API_KEY=gsk_...         # Free at console.groq.com
RESEND_API_KEY=re_...        # Free at resend.com
ALERT_EMAIL_TO=you@email.com
```

### Pages
| URL | What it does |
|---|---|
| `/` | Vendor list — stat cards, charts, searchable/filterable table |
| `/vendor/{id}` | Vendor detail — risk score, compliance checklist, alerts |
| `/reports` | Portfolio report — compliance stats, red-flag table, email triggers |
| `/extract` | Contract extraction — paste text or upload PDF (upgrade), get AI risk score |

### API endpoints
| Endpoint | What it returns |
|---|---|
| `GET /api/vendors` | Paginated vendor list |
| `GET /api/vendors/{id}` | Single vendor + score + alerts |
| `GET /api/vendors/{id}/history` | 6-month score trend (upgrade — Jatin) |
| `GET /api/reports` | Portfolio report JSON |
| `GET /api/reports/csv` | CSV download |
| `GET /api/reports/pdf` | PDF download (upgrade — Jatin) |
| `POST /api/extract` | Contract text/PDF → extracted fields + risk score |
| `POST /api/vendors/bulk-upload` | CSV file → scored vendor list (upgrade — Jatin) |
| `POST /api/alerts/send-monthly` | Trigger monthly summary email |
| `POST /api/alerts/send-expiry` | Trigger expiry alerts email |

## Upgrade sprint — what's next

**Divyansh** (extraction/, data/):
- [x] `extraction/parse_pdf.py` — PDF → text via pdfplumber (done)
- [x] Update `extraction/extract_contract.py` to accept PDF path input (Groq rewrite done)
- [x] `data/bulk_ingest.py` — CSV bytes → list[Vendor] with per-row error handling (done)

**Jatin** (monitoring/, api/, dashboard/):
- [ ] `monitoring/scheduler.py` — APScheduler daily auto-alert job
- [ ] `GET /api/vendors/{id}/history` — 6-point mock score history
- [ ] Sparkline chart on vendor detail page
- [ ] `GET /api/reports/pdf` — WeasyPrint PDF portfolio report
- [ ] `POST /api/vendors/bulk-upload` — wire Divyansh's bulk_ingest into API

Full task detail in `backlog.md` (Upgrade Sprint section) and `divyansh.md` / `jatin.md`.

## Read in this order
1. `CLAUDE.md` — rules of engagement
2. `divyansh.md` or `jatin.md` — whichever matches this session
3. `backlog.md` — Upgrade Sprint section for open tasks
4. `memory.md` — last 5 entries for recent decisions

## Do not
- Re-derive the scoring rubric — frozen in `PRD.md` §5
- Touch the other person's owned directories
- Force push to `main` directly — branch protection is being set up; always push to your own branch first
