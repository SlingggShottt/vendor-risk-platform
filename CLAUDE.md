# CLAUDE.md — Entry Point

This is a **48-hour hackathon project** built by **two people working in parallel, isolated tracks**, each likely running their own Claude Code session. Read this file first in every session — it tells you which other files to load and how to behave.

## Project in one paragraph

We're building a Vendor/Third-Party Risk Management platform: ingest vendor data (certs, breach history, contract dates, data access scope), run it through a deterministic, explainable risk-scoring engine, monitor for changes (cert/contract expiry, new breaches), and surface it via a dashboard + audit-ready reports + email alerts. NOT a CRUD form with manual risk dropdowns — the scoring has to be a real rule-based engine with recall-weighted evaluation against ground truth labels, because that's what's actually being graded.

## Who you are in this session

Each Claude Code session belongs to **one person, one track**. Before doing anything:
1. Read `PRD.md` (what we're building and why — shared, full picture)
2. Read `tech-stack.md` (shared — stack, conventions, file layout)
3. Read `style-guide.md` (shared — code/commit conventions)
4. Read **either** `divyansh.md` **or** `jatin.md` — whichever matches who you're working for. **Ask the user which one if it's not obvious from context** (e.g. if they mention a filename inside `data/` or `extraction/`, you're Divyansh; if `scoring/`, `monitoring/`, `api/`, `dashboard/`, you're Jatin).
5. Read `plan.md` and `backlog.md` for the current hour-by-hour status and your open tasks.
6. Check `memory.md` for decisions already made — don't relitigate them.

## Hard rule: stay in your lane

The two tracks are isolated on purpose so both people can work simultaneously without merge conflicts. **Only shared file either track may edit is `common/schema.py`**, and only after explicit confirmation from the user that a schema change is needed (it affects the other person's in-progress work). Never touch files under the other person's owned directories (see `tech-stack.md` for the directory ownership map). If a task seems to require it, stop and tell the user instead of doing it.

## Git setup (do this if not already done)

If asked to set up the repo, or if `.git` doesn't exist yet:
1. `git init`, create `.gitignore` (Python, `.env`, `*.db`, `__pycache__`, `node_modules` if any)
2. Create two branches off main: `divyansh` and `jatin` (use real names if known — check `memory.md`)
3. Each person works exclusively on their own branch, committing freely
4. **Force-push workflow** (as agreed): when a person's track is in a working state, they `git pull --rebase origin main` first, resolve anything, then merge/force-push their branch into `main`. Never force-push without pulling latest first.
5. Remind the user to create the actual GitHub remote (`gh repo create` if `gh` CLI is available and they want it, otherwise they add the remote manually) — don't assume credentials are configured.

## Session hygiene

- This is a 48-hour clock. Don't gold-plate. If a task isn't in `backlog.md` under the current hour-block, flag it as scope creep before building it.
- When you make a non-trivial decision (schema field, scoring weight, library choice), append one line to `memory.md` so the other person's session — and your own next session — has it.
- If context is getting long or you're starting a fresh session mid-project, read `restart.md` first — it's the fast-resume summary.
- Update `backlog.md` checkboxes as you complete tasks. This is the source of truth both people check to see where the other stands.
