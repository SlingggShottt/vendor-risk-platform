# Plan — 48 Hour Build

Hour-blocks, not calendar weeks. Times are elapsed hours from kickoff (H0). Adjust live in this file as reality diverges — this is a living doc, not a contract.

## H0–H1: Together (blocking, do not skip)

- [ ] Both read `PRD.md` fully
- [ ] Agree + freeze `common/schema.py` (Vendor, ScoredVendor models)
- [ ] Agree on `api/db.py` table shape (or defer DB, start with CSV per `tech-stack.md`)
- [ ] Hand-write 5-8 fixture vendors together (covering: clean vendor, breached+high-access, expired cert, expired contract+active access, low financial rating, missing GDPR DPA, a genuinely ambiguous case) — these unblock Jatin immediately without waiting on the generator
- [ ] Set up git repo, branches `divyansh` / `jatin`, `.gitignore`, push empty skeleton to `main`
- [ ] Split: confirm both read `divyansh.md` / `jatin.md` respectively from here on

## H1–H16: Parallel build, core

**Divyansh** (see `divyansh.md` for detail):
- [ ] `data/generate_vendors.py` — bulk synthetic generator
- [ ] `data/edge_cases.py` — hand-scripted edge cases on top
- [ ] Output `vendor_registry.csv` + `vendor_labels.csv`
- [ ] `data/normalize.py` — schema reconciliation logic

**Jatin** (see `jatin.md` for detail):
- [ ] `scoring/rules.py` + `scoring/risk_engine.py` against the H0 fixtures
- [ ] `scoring/recommend.py`
- [ ] `eval/evaluate.py` skeleton (runs against fixtures first, real CSVs later)

**Checkpoint at H16:** quick sync (15 min, async is fine). Divyansh's CSVs should exist; Jatin's engine should run against fixtures. Swap: Jatin starts running the engine against A's real CSVs.

## H16–H30: Parallel build, surface

**Divyansh:**
- [ ] Polish/expand edge cases based on what Jatin's eval reveals as weak spots
- [ ] If ahead of schedule: start `extraction/` stretch goal
- [ ] Help write the documentation deliverable's "data & architecture" section

**Jatin:**
- [ ] `monitoring/alerts.py` (cert/contract expiry windows)
- [ ] `monitoring/emailer.py` (monthly summary + expiry alerts, swappable SMTP backend)
- [ ] `api/main.py` + routes (`vendors`, `reports`)
- [ ] `dashboard/` — vendor list, alert indicators, bar chart, CSV export
- [ ] Run full `eval/evaluate.py` against real labels, tune rubric weights if CRITICAL recall is weak (log changes in `memory.md`)

**Checkpoint at H30:** integration. Both pull latest, merge into `main`, run the whole pipeline end-to-end once (generate → normalize → score → dashboard). Fix integration breakage now, not at H45.

## H30–H40: Integration + stretch goals

- [ ] End-to-end smoke test: fresh clone, `pip install -r requirements.txt`, run seed + server, dashboard loads, reports generate, eval passes
- [ ] Stretch (only if on schedule): PDF contract extraction (Divyansh), Postgres swap (skip unless trivial)
- [ ] Bug fixes, edge case polish

## H40–H48: Deliverables (do not skip — these are graded independently of the code)

- [ ] **Documentation**: architecture diagram + scoring algorithm rationale + UI walkthrough — compile from PRD.md + person docs, don't write from scratch
- [ ] **Presentation**: problem → solution slides, reuse PRD.md §1-2 as the spine
- [ ] **Solution video**: short screen-recorded demo (dashboard, a CRITICAL vendor drill-down, a generated report, an alert email)
- [ ] **Git repo**: clean README, both branches merged to main, final force-push, confirm repo link works from a logged-out view

## Risk register for the plan itself

- If generator/scoring integration slips past H20, cut PDF extraction immediately — don't wait until H30 to decide
- If SQLite/API integration is fighting at H28, fall back to dashboard reading CSVs directly via pandas (uglier, but ships) — document as known limitation
- Reserve the last 4 hours hard for deliverables regardless of code state — a half-working demo with a great video beats a fully-working demo with no presentation
