# Plan — 48 Hour Build

Hour-blocks, not calendar weeks. Times are elapsed hours from kickoff (H0). Adjust live in this file as reality diverges — this is a living doc, not a contract.

## H0–H1: Together (blocking, do not skip)

- [x] Both read `PRD.md` fully
- [x] Agree + freeze `common/schema.py` (Vendor, ScoredVendor models)
- [x] Agree on `api/db.py` table shape (or defer DB, start with CSV per `tech-stack.md`)
- [x] Hand-write 5-8 fixture vendors together
- [x] Set up git repo, branches `divyansh` / `jatin`, `.gitignore`, push empty skeleton to `main`
- [x] Split: confirm both read `divyansh.md` / `jatin.md` respectively from here on

## H1–H16: Parallel build, core

**Divyansh:**
- [x] `data/generate_vendors.py` — bulk synthetic generator
- [x] `data/edge_cases.py` — hand-scripted edge cases on top
- [x] Output `vendor_registry.csv` + `vendor_labels.csv`
- [x] `data/normalize.py` — schema reconciliation logic

**Jatin:**
- [x] `scoring/rules.py` + `scoring/risk_engine.py` against the H0 fixtures
- [x] `scoring/recommend.py`
- [x] `eval/evaluate.py` skeleton

## H16–H30: Parallel build, surface

**Divyansh:**
- [x] Polish/expand edge cases
- [x] `extraction/` stretch goal (Groq LLM)
- [x] Data & architecture documentation

**Jatin:**
- [x] `monitoring/alerts.py`
- [x] `monitoring/emailer.py`
- [x] `api/main.py` + routes (`vendors`, `reports`)
- [x] `dashboard/` — vendor list, detail, reports, extract, add-vendor
- [x] 100% CRITICAL/HIGH recall confirmed

## H30–H40: Integration + stretch goals

- [x] End-to-end smoke test — 440 vendors, all routes 200, eval 100% precision+recall
- [x] PDF contract extraction (Divyansh via Groq)
- [x] Bug fixes, edge case polish

## H40–H48: Deliverables

- [x] **Documentation**: `docs/technical_report.md` (research paper), `docs/scoring_architecture.md`, `docs/data_methodology.md`
- [x] **Presentation**: `docs/vendor_risk_platform_deck.pptx` (16-slide deck, python-pptx)
- [x] **Demo scripts**: `docs/demo_script.md` (SAY/DO timed guide) + `docs/demo_script_full.md` (word-for-word)
- [x] **Sample inputs**: `sample_inputs/` — CSV, add-vendor JSON, API JSON, contract .txt files
- [x] **Git repo**: clean README, branches merged to main, live on Render

## Risk register for the plan itself

- If generator/scoring integration slips past H20, cut PDF extraction immediately — don't wait until H30 to decide
- If SQLite/API integration is fighting at H28, fall back to dashboard reading CSVs directly via pandas (uglier, but ships) — document as known limitation
- Reserve the last 4 hours hard for deliverables regardless of code state — a half-working demo with a great video beats a fully-working demo with no presentation
