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

## Enterprise Sprint tasks (your lane) — Société Générale focus

**Why SG cares about these**: SG is a tier-1 bank with audit/compliance as core business. These features show you understand enterprise risk platforms and are table-stakes for financial services deployments.

### PRIORITY 1: Audit Trail + Risk Explainability (SG's #1 ask)

**1. Compliance Audit Logging**
- Create `monitoring/audit_logger.py`:
  - `AuditLogger` singleton class with in-memory list (append-only)
  - Methods: `log_event(actor, action, resource_type, resource_id, old_state, new_state, reason)` → creates timestamped entry
  - `get_events(date_from=None, date_to=None, actor=None, action=None, vendor_id=None)` → filters and returns
  - Example: `audit_logger.log_event("system", "score_updated", "vendor", "VND-0001", {"risk_score": 65}, {"risk_score": 72}, "bulk_remediate")`
- Integrate into startup: initialize in `api/main.py` as `app.state.audit_logger`
- Populate on every state change:
  - `POST /api/vendors/bulk-remediate` logs each vendor change
  - `POST /api/vendors/bulk-upload` logs each added vendor
  - Bulk export also logs "compliance_export" event with count

**2. Risk Explainer (tie-breaker for SG's risk committees)**
- Create `scoring/explainer.py` (new module):
  - `explain_risk(vendor: Vendor, scored: ScoredVendor) -> dict`:
    ```python
    {
      "risk_score": 78.5,
      "risk_level": "HIGH",
      "contributing_factors": [
        {
          "rule_name": "Recent breach (Jan 2024)",
          "weight_pct": 30,
          "impact": "CRITICAL",
          "description": "Unencrypted data exposed; vendor has HIGH-sensitivity access"
        },
        {
          "rule_name": "Missing GDPR DPA",
          "weight_pct": 5,
          "impact": "MEDIUM",
          "description": "No DPA on file despite processing EU personal data"
        },
      ],
      "remediation_actions": [
        "Require incident report + remediation plan by 2026-02-28",
        "Request updated DPA by 2026-01-31"
      ],
      "eval_passed": true  # all rules passed validation
    }
    ```
  - Call this from `scoring/risk_engine.py` when computing `ScoredVendor` (add `explainer: dict` field)
  
- Add `GET /api/vendors/{id}/risk-explainer` endpoint in `api/routes/vendors.py`:
  - Returns the explainer dict for a specific vendor
  - Include audit trail snippet: "Last updated by system on 2026-06-20 (bulk_remediate)"

**3. Compliance Export Endpoint**
- Add `GET /api/reports/compliance-export?format=csv|json` in `api/routes/reports.py`:
  - Returns vendor compliance summary (all 440 vendors with: vendor_id, name, risk_score, risk_level, soc2, iso, gdpr_dpa, contract_end, latest_breach_date)
  - Plus audit log (last 100 events with actor, action, timestamp)
  - Jatin calls Divyansh's `data/compliance_export.py` functions for formatting

### PRIORITY 2: Trends + Predictive Alert + OpenAPI

**4. Vendor Risk Trends with Prediction**
- Enhance `GET /api/vendors/{id}/history` to add trend analysis:
  - Keep the 6 historical points
  - Add linear regression: fit line to points, return `trend_direction: "up"|"down"|"stable"`
  - Add `projected_risk_level_in_3mo` (predict where score will be)
  - Return structure: `[{month, score, projected: false}, ..., {month, score_3mo_projected, projected: true}]`
  - Scipy or numpy for linear regression (already in requirements)
  
- Add alert: if `trend_direction == "up"` AND `projected_risk_level_in_3mo in ("HIGH", "CRITICAL")`:
  - Include in `alerts` response: `{ severity: "HIGH", type: "RISK_TRENDING_CRITICAL", description: "Risk trending toward CRITICAL; projected CRITICAL by 2026-09" }`

**5. OpenAPI / Integration Readiness**
- Install/add to requirements: `python-openapi-parser` or use `fastapi.openapi.utils` (built-in)
- In `api/main.py`:
  - Call `app.openapi_schema = ...` after all routes registered
  - Add `@app.get("/api/openapi.json")` route that returns the OpenAPI 3.1.0 schema
  - Ensure all routes have `tags`, `description`, `responses` documented
- In `dashboard/templates/base.html`:
  - Add link in nav: "API Docs" → `<a href="/api/docs">Swagger UI</a>` (use Swagger UI library)
  - Or just link to `/api/openapi.json` directly for raw spec

### PRIORITY 3: Security + Bulk Ops

**6. Security Posture (rate limiting, CORS, headers)**
- Install: `pip install slowapi` (FastAPI rate limiter)
- In `api/main.py` at startup:
  ```python
  from slowapi import Limiter
  from slowapi.util import get_remote_address
  limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
  app.state.limiter = limiter
  app.add_middleware(SlowAPIMiddleware)
  ```
- Add rate limit decorator to: `POST /api/vendors/bulk-remediate`, `GET /api/vendors` (public endpoints)
- CORS: Update `api/main.py`:
  ```python
  from fastapi.middleware.cors import CORSMiddleware
  app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "https://vendor-risk-platform.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
  )
  ```
- Security headers in `api/main.py` startup or middleware:
  ```python
  @app.middleware("http")
  async def add_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
  ```

**7. Bulk Operations Done Right**
- Create `api/routes/bulk.py`:
  - `POST /api/vendors/bulk-remediate`: 
    ```json
    { "vendor_ids": ["VND-0001", "VND-0002"], "action": "acknowledge|renew_cert|require_dpa", "reason": "Q2 compliance review" }
    ```
    - Update each vendor status, log audit event for each
    - Return: `{ "updated_count": 2, "errors": [], "summary": "2 vendors updated; expiry alerts cleared" }`
  
  - `GET /api/reports/bulk-export?format=xlsx`:
    - Stream XLSX file (use `openpyxl` — add to requirements)
    - Include: vendor_id, name, risk_score, risk_level, soc2, iso, gdpr_dpa, contract_end, latest_breach_date
    - Plus: compliance summary stats (coverage %, counts)
    
  - Register router in `api/main.py`

- Create `api/routes/jobs.py` (async job tracking):
  - `POST /api/jobs/bulk-export?format=xlsx`:
    - Async task (for now, use `threading.Thread`; production would use Celery)
    - Returns: `{ "job_id": "job_abc123", "status": "pending" }`
  
  - `GET /api/jobs/{job_id}`:
    - Returns: `{ "job_id": "job_abc123", "status": "complete|pending", "progress": 100, "result_url": "/files/export_20260620.xlsx" }`

### PRIORITY 4: Slack Integration

**8. Slack Backend for Alerts**
- Update `monitoring/emailer.py`:
  - Add `SlackBackend` class:
    ```python
    class SlackBackend(EmailBackend):
      def send_monthly_summary(self, ...):
        """Post rich message to Slack webhook."""
        payload = {
          "text": "Monthly Vendor Risk Summary",
          "blocks": [
            { "type": "section", "text": { "type": "mrkdwn", "text": f"🔴 CRITICAL: {critical_count}" } },
            ...
          ]
        }
        requests.post(os.environ["SLACK_WEBHOOK_URL"], json=payload)
    ```
  - Update `get_emailer()`:
    - Priority: Slack (if `SLACK_WEBHOOK_URL`) > Resend > SMTP > Console
  
- Env var: `SLACK_WEBHOOK_URL` (from Slack workspace's incoming webhook)
- Test: `/api/alerts/send-expiry` now posts to Slack if configured
- Dashboard: On `/reports`, show status badge: "Slack ✓ connected" or "Slack ⚠ not configured"

---

## Implementation notes

**Shared context**: Divyansh will update `common/schema.py` with audit models. Use those in your endpoint responses.

**Database state**: For hackathon, audit log lives in `app.state.audit_logger` (in-memory, append-only list). In production, this goes to a dedicated audit table with indexes on (timestamp, actor, resource_id).

**Testing in priority order**:
1. Audit trail: manually call bulk-remediate, check `GET /api/audit-log` returns the events
2. Risk explainer: `GET /api/vendors/VND-0001/risk-explainer` — does each factor have a clear description?
3. Trends: `GET /api/vendors/VND-0001/history` — does projected_level_in_3mo look sensible?
4. OpenAPI: hit `/api/openapi.json` → should return valid OpenAPI schema
5. Security: test rate limiting with `ab -n 150 http://localhost:8000/api/vendors`
6. Bulk remediate: `POST /api/vendors/bulk-remediate` with 5 vendors → check store updated + audit logged
7. Slack: set `SLACK_WEBHOOK_URL`, call `/api/alerts/send-expiry` → should post to Slack

**Time estimates** (if 4 hours available):
- Audit trail: 60 min
- Risk explainer: 45 min
- Trends + OpenAPI: 60 min
- Security + bulk ops: 75 min
- Slack: 30 min
Total: ~4.5 hours (prioritize audit + explainer if time is tight — those are SG's core asks)

