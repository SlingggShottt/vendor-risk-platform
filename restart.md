# Restart — Fast Resume

Read this if you're a fresh Claude Code session picking up mid-project, or if context got long and was reset. This is the 60-second version; full detail lives in the other docs.

## What this is
48-hour hackathon build: vendor/third-party risk management platform. Rule-based, explainable risk scoring engine (not ML, not a manual-dropdown CRUD app) over vendor data, with monitoring/alerts, email notifications, a dashboard, and audit reports. Two people, two isolated tracks (Divyansh: data/normalization/extraction, Jatin: scoring/monitoring/API/dashboard), connected only through `common/schema.py`.

## Current status (as of last session)
**Jatin's track is fully complete — core + stretch.** All backlog items checked.
- Scoring engine, eval (100% recall), monitoring, API, dashboard: done.
- Stretch: `POST /api/extract` + `/extract` dashboard page + `docs/scoring_architecture.md`: done.
- Run with: `uvicorn api.main:app --reload --port 8000`
- Divyansh's track: data/normalize/extraction core is done; stretch checkboxes in backlog.md not yet ticked (stay in your lane — don't update his section).

## Read in this order
1. `CLAUDE.md` — rules of engagement
2. `divyansh.md` or `jatin.md` — figure out which one applies to this session (ask the user if unclear)
3. `backlog.md` — see what's checked off already, that's your real status
4. `memory.md` — last 5-10 entries especially, to catch recent decisions

## Then check
- Does `common/schema.py` exist yet? If not, that's the very first blocking task (see `plan.md` H0-H1).
- What hour-block are we roughly in (`plan.md`)? Don't start H30 work if H1-H16 core tasks are still unchecked in `backlog.md`.
- Any uncommitted changes / has the repo been pushed recently? Check `git status` / `git log` before assuming a clean slate.

## Do not
- Re-derive the scoring rubric from scratch — it's frozen in `PRD.md` §5. Propose changes, don't silently redo it.
- Touch the other person's owned directories (`tech-stack.md` has the ownership map).
- Spend time on anything marked stretch-goal (Postgres, PDF extraction) unless `backlog.md` shows core tasks are fully checked.
