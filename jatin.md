# Jatin — Working Doc (Scoring, Monitoring, API, Dashboard)

You own everything under `scoring/`, `monitoring/`, `eval/`, `api/`, and `dashboard/`. You do not touch `data/` or `extraction/` — that's Divyansh's lane. Your only shared-edit files are `common/schema.py` and `api/db.py`, and only with explicit agreement (see `CLAUDE.md`).

## Your job, in one sentence
Turn a `Vendor` into a `ScoredVendor` with honest, explainable reasoning, watch for things changing (expiry, breaches), and put all of it in front of a human through a dashboard, reports, CSV export, and email — fast enough to answer "is vendor X compliant?" in under 5 minutes.

## Your task list
Full detail in `backlog.md` under "Jatin" — work through it top to bottom, core before stretch. Update checkboxes as you go.

## Key things to get right

**1. Build and test against the H0 fixtures first — do not wait for Divyansh's real CSVs.** The fixture vendors written together at kickoff are designed to cover the interesting cases. Get `risk_engine.py` producing sane, explainable output against those before touching real data. This is what makes the two tracks genuinely parallel instead of you blocked on A.

**2. Hard floors must be checked before weighted scoring, not blended into it.** Per `PRD.md` §5: a recent breach + HIGH access vendor is CRITICAL *full stop*, even if other factors would pull the weighted average down. Implement this as an early-return, not as a heavily-weighted factor — averaging can still let a CRITICAL case slip to HIGH, which fails the CRITICAL-recall priority from the brief.

**3. `risk_factors` must be genuinely derived from which rules fired, not a templated restatement of risk_level.** Look at the target shape again:
   - "Recent breach (Jan 2024): Unencrypted data exposed, potentially including backups"
   - "SOC 2 expires in 60 days: Certification gap risk"
   - "Missing GDPR DPA agreement despite processing EU data"
   - "High-sensitivity data access (backups = full database copies)"

   Each is a specific, readable sentence tied to a specific triggered rule, with enough context for an auditor to act on it. `scoring/rules.py` should make each rule function return both a boolean and a ready-to-display description string — don't generate generic strings like "Risk factor: certification" after the fact.

**4. `eval/evaluate.py` reports overall precision/recall AND CRITICAL+HIGH-specific recall separately.** Don't let a good overall number hide a bad CRITICAL recall number — surface both, and treat CRITICAL recall as the number that decides whether you tune rubric weights further. Log every weight change with before/after numbers in `memory.md`.

**5. The dashboard needs to actually answer the brief's stated time targets**, not just look nice:
   - Search/filter to find a specific vendor and see its compliance status — must be fast/obvious, this is the "5 min to answer is vendor X compliant" requirement
   - A one-click/one-route report generation — "15 min to generate vendor risk report" requirement, should take far less
   - Visible alert indicators (expiring certs/contracts) on the vendor list itself, not buried in a separate page

**6. Email backend must degrade gracefully.** If there's no SMTP credential available during the hackathon, `monitoring/emailer.py` should fall back to writing the email content to console/log (clearly labeled "would have sent:") rather than crashing or silently doing nothing. This keeps the feature demonstrably "core, working" even without real credentials in hand.

## Suggested internal order (within your H1-H16 block)
1. `scoring/rules.py` — write each rule as an isolated, testable function
2. `scoring/risk_engine.py` — hard floors first, then weighted rubric, wire rules together
3. Manually eyeball output against the H0 fixtures — does the CRITICAL/breached fixture actually come out CRITICAL with sensible risk_factors?
4. `scoring/recommend.py`
5. `eval/evaluate.py` skeleton, run against fixtures (numbers will be meaningless with 5-8 rows, but confirms the script runs)
6. Once Divyansh's CSVs land (~H16): rerun eval for real, tune weights if CRITICAL recall is weak
7. Move to monitoring/alerts, then API, then dashboard, then email

## When you're done with core
Check `backlog.md` — polish the dashboard's clarity/speed-to-answer before reaching for the Postgres stretch goal, which is low value. If genuinely ahead of schedule, help Divyansh test the PDF extraction stretch goal output against your scoring engine (does extracted contract data actually flow into a sensible score?)

## Upgrade Sprint tasks (your lane)

### 1. Scheduled monitoring (auto-alerts)
Make the monitoring actually automatic — right now alerts only fire when a user clicks a button.

- Create `monitoring/scheduler.py`. Use `apscheduler` (`pip install apscheduler`). Write a function `start_scheduler(app)` that schedules a daily job at 08:00 UTC: loads all vendors from `app.state.store`, calls `check_alerts()`, calls `get_emailer().send_expiry_alerts()` if any CRITICAL/HIGH alerts exist.
- In `api/main.py` startup event, call `start_scheduler(app)` after the store is built.
- The job should never crash the server — wrap in try/except and log errors.

### 2. Vendor risk trend chart (sparkline)
Show 6 months of score history per vendor on the detail page.

- In `api/routes/vendors.py`, add `GET /api/vendors/{id}/history`. Generate 6 deterministic monthly data points by seeding a random number generator with `hash(vendor_id)` — this way the same vendor always shows the same "history" across restarts. Final point is always the current `risk_score`.
- In `dashboard/templates/vendor_detail.html`, add a small Chart.js line chart in the vendor hero section showing the 6-month trend. Fetch from the new endpoint on page load.

### 3. PDF report download
Add a proper PDF download of the portfolio report.

- Install `weasyprint` (preferred, CSS-to-PDF) or `reportlab` (programmatic). WeasyPrint: `pip install weasyprint`.
- In `api/routes/reports.py`, add `GET /api/reports/pdf`. Build an HTML string with the same data as the JSON report (risk summary table, red-flag vendor table, compliance stats), pass through WeasyPrint, return as `Response(content=pdf_bytes, media_type="application/pdf")`.
- In `dashboard/templates/reports.html`, add a "Download PDF Report" button next to the existing Download CSV.

### 4. Bulk CSV upload endpoint
Wire Divyansh's `bulk_ingest.py` into an API endpoint.

- Add `POST /api/vendors/bulk-upload` in a new file `api/routes/bulk.py`. Accept `UploadFile` via `python-multipart`. Call `bulk_ingest.ingest_csv_bytes(await file.read())`. Score each returned vendor with `score_vendor()`, add to `app.state.store`, return scored results as JSON.
- Register the router in `api/main.py`.
- Add an "Upload Vendor CSV" button to the dashboard home page (`dashboard/templates/vendors.html`) with a simple file input modal..
