# Tech Stack & Directory Ownership

## Stack

- **Language:** Python 3.11+
- **API:** FastAPI
- **Frontend:** Plain HTML/CSS/JS served via Jinja2 templates from FastAPI (no React, no build step — speed matters at 48h)
- **Database:** SQLite (file-based, zero setup). Schema designed to be Postgres-portable later if desired, but do not spend hackathon hours on Postgres.
- **ORM:** SQLAlchemy (works identically against SQLite/Postgres, keeps the door open)
- **Data validation/contract:** Pydantic v2 (`common/schema.py`)
- **Email:** Python `smtplib` + a free/dev SMTP option (e.g. Mailtrap sandbox or console-output fallback if no SMTP creds available — don't block on getting real credentials, build with a swappable backend)
- **Eval:** pandas + scikit-learn (`precision_score`, `recall_score`)
- **Charts (dashboard):** Chart.js via CDN (simple bar chart of vendors by risk level — no build step needed)

## Repo layout & ownership

```
vendor-risk-platform/
├── CLAUDE.md            [shared, do not edit casually]
├── PRD.md               [shared]
├── plan.md              [shared]
├── backlog.md           [shared — both update own checkboxes]
├── tech-stack.md        [shared, this file]
├── style-guide.md       [shared]
├── memory.md            [shared — append-only decision log]
├── restart.md           [shared — keep updated at session end]
├── divyansh.md          [Divyansh's working doc]
├── jatin.md          [Jatin's working doc]
├── requirements.txt     [shared — both add deps here, communicate via memory.md]
├── .env.example         [shared template, no real secrets]
│
├── common/
│   └── schema.py        [SHARED CONTRACT — Pydantic models. Edit only with explicit agreement.]
│
├── data/                 ◄── DIVYANSH OWNS
│   ├── generate_vendors.py
│   ├── edge_cases.py
│   ├── normalize.py
│   └── seed_db.py        (loads generated data into SQLite via common/schema.py + models)
│
├── extraction/           ◄── DIVYANSH OWNS (stretch goal)
│   ├── sample_contracts/
│   └── extract_contract.py
│
├── scoring/               ◄── JATIN OWNS
│   ├── risk_engine.py
│   ├── rules.py
│   └── recommend.py
│
├── monitoring/             ◄── JATIN OWNS
│   ├── alerts.py
│   └── emailer.py
│
├── eval/                    ◄── JATIN OWNS
│   └── evaluate.py
│
├── api/                      ◄── JATIN OWNS
│   ├── main.py
│   ├── db.py               (SQLAlchemy engine/session — A's seed_db.py and B's API both use this)
│   └── routes/
│       ├── vendors.py
│       └── reports.py
│
├── dashboard/                 ◄── JATIN OWNS
│   ├── templates/
│   └── static/
│
└── tests/
    ├── test_data/            [Divyansh]
    └── test_scoring/         [Jatin]
```

## The one truly shared runtime piece: the database

`api/db.py` defines the SQLAlchemy engine and the `vendors` / `scored_vendors` tables, derived from `common/schema.py`. Divyansh's `data/seed_db.py` writes into it; Jatin's API reads from it. Agree on `api/db.py`'s table shape together at kickoff (15 min), then treat it like `common/schema.py` — shared contract, not freely edited solo.

**Until `api/db.py` exists**, Divyansh should just output `vendor_registry.csv` / `vendor_labels.csv` (matches the original brief's deliverable format anyway) — Jatin can build the scoring engine against the CSVs directly via pandas, and the SQLite load step is a thin adapter added later. This avoids a day-1 blocking dependency.

## Environment

- `.env` for secrets (SMTP creds, etc.) — never commit. `.env.example` shows required keys with placeholder values.
- `requirements.txt` — append-only during the hackathon; run `pip install -r requirements.txt` after every pull in case the other teammate added something.
