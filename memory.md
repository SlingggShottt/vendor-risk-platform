# Memory — Decision Log (append-only, newest at bottom)

Format: `[HH:MM elapsed] [D/J/Both] decision — why`

Don't edit or delete past entries, even if a decision is later reversed — append a new entry noting the reversal instead. This file is how a fresh Claude Code session (or the other person) understands *why* something is the way it is without re-deriving it.

---

- `[H0:00] [Both] Chose rule-based/weighted scoring engine over ML classifier — labels file provides anomaly_type/severity/explanation, signaling an explainable rules system is the intended design; also makes risk_factors generation tractable.`
- `[H0:00] [Both] Chose SQLite over Postgres for the hackathon — zero setup time, schema kept portable via SQLAlchemy in case migration is ever wanted. Not revisited unless explicitly blocking.`
- `[H0:00] [Both] Chose plain HTML/Jinja2/Chart.js over React — no build step, faster to ship in 48h.`
- `[H0:00] [Both] PDF contract extraction is stretch-only, attempted after core pipeline + dashboard + eval are working, not before.`
- `[H0:00] [Both] Email notifications are core (not stretch) per explicit decision — must work, but with a swappable backend so missing SMTP credentials never blocks other work.`
- `[H0:00] [Both] common/schema.py and api/db.py are the only two files either track may edit, and only with mutual agreement — everything else is owned exclusively by one track.`

<!-- Add new entries below this line -->
- `[H1:00] [J] Switched to jatin branch. scoring/, eval/, monitoring/, api/, dashboard/ all built and smoke-tested.`
- `[H1:00] [J] eval/evaluate.py run against all 430 vendors: 100% precision + recall at every severity level (CRITICAL/HIGH/MEDIUM/LOW). No weight tuning needed — formula directly mirrors generate_vendors.py::compute_label.`
- `[H1:00] [J] Starlette 1.3.1 installed — TemplateResponse signature changed to (request, name, context) vs old (name, context). All three dashboard routes updated accordingly.`
- `[H1:00] [J] API is CSV-first (vendor_registry.csv loaded at startup, scored in-memory). api/db.py has SQLAlchemy models ready for future seed_db.py integration.`
- `[H0:30] [Both] api/db.py deferred — going CSV-first (vendor_registry.csv + vendor_labels.csv) per tech-stack.md recommendation. Avoids day-1 blocking dependency. seed_db.py added later once scoring engine shape is stable.`
- `[H0:30] [D] Switched to divyansh branch. H0-H1 shared tasks (schema.py + fixtures + git branches) confirmed complete. Starting data/ build.`
- `[Stretch] [J] Built contract extraction endpoint (POST /api/extract) + dashboard Extract page (/extract). Live mode calls extraction/extract_contract.py when ANTHROPIC_API_KEY is set; demo mode parses vendor ref ID from contract text and returns fixture/store data. anthropic SDK installed.`
- `[Stretch] [J] Sample contract vendor IDs (VND-0001/0099/0200/0285/0420) are NOT in vendor_registry.csv — they exist only as fixtures in common/schema.py::FIXTURE_VENDORS. Demo fallback checks store first, then FIXTURE_VENDORS.`
- `[Stretch] [J] docs/scoring_architecture.md created — covers scoring rationale (hard floors, weights, eval results), all API endpoints + data shapes, UI page map, and monitoring/alerting. Required graded deliverable per PRD §2.`
- `[H30+] [D] data/seed_db.py rewritten to match Jatin's actual api/db.py exports (create_tables/SessionLocal/VendorRow). Old stub imported non-existent symbols. Tested: inserts 440 rows clean.`
- `[H30+] [D] Full UI redesign: Bootstrap 5.3 + Bootstrap Icons added via CDN. All 4 dashboard pages rebuilt (vendors, vendor_detail, reports, extract). No build step — CDN only. style.css cleared; all CSS in base.html <style> block.`
- `[H30+] [Both] End-to-end pipeline smoke-tested: eval/evaluate.py → 100% precision+recall (440 vendors); uvicorn startup → 440 vendors loaded; all API routes 200; seed_db.py → 440 rows SQLite. Platform is feature-complete.`
- `[H30+] [D] README.md created. docs/data_methodology.md + docs/scoring_architecture.md both written. All graded documentation deliverables complete.`
- `[H40+] [D] Switched contract extraction AI: Anthropic (claude-opus-4-8) → Gemini (quota=0 issue) → Groq (llama-3.3-70b-versatile, free, no credit card). Env var: GROQ_API_KEY. Package: groq>=1.4.0.`
- `[H40+] [D] Switched email backend: SMTP (complex setup) → Resend API (simple, free). monitoring/emailer.py now has ResendBackend with HTML emails; get_emailer() priority: Resend > SMTP > Console. Env vars: RESEND_API_KEY, ALERT_EMAIL_TO.`
- `[H40+] [D] Deployed to Render free tier: https://vendor-risk-platform.onrender.com. Docker image 175MB, tested locally before deploy. CI/CD via GitHub Actions: eval + docker build gate every push to main → auto-deploy via RENDER_DEPLOY_HOOK_URL secret.`
- `[H48+] [Both] Upgrade sprint started. Divyansh: PDF extraction (extraction/parse_pdf.py + pdfplumber) + bulk CSV parsing (data/bulk_ingest.py). Jatin: scheduled auto-monitoring (monitoring/scheduler.py + APScheduler), vendor trend chart (GET /api/vendors/{id}/history + sparkline), PDF report (GET /api/reports/pdf + WeasyPrint), bulk upload endpoint (POST /api/vendors/bulk-upload). Full task breakdown in divyansh.md and jatin.md.`
- `[H48+] [Both] Enterprise Sprint (SG placement focus) planned with 7 differentiation features. Divyansh: compliance export schema (common/schema.py + data/compliance_export.py + data/audit_helper.py). Jatin: audit logging, risk explainability (scoring/explainer.py), trend prediction, OpenAPI docs, security posture (rate limit, CORS, CSP), bulk remediate+jobs, Slack integration. Why: SG is tier-1 bank; audit/compliance/explainability are table-stakes. Priority: (1) Audit+Explainer (SG's core ask), (2) Trends+OpenAPI, (3) Security+BulkOps, (4) Slack. Detailed specs in backlog.md Enterprise Sprint section; divyansh.md and jatin.md updated with per-person task breakdowns.`
- `[H50+] [D] Enterprise Sprint Phase 1 complete: AuditLog + ComplianceSummary added to common/schema.py; data/compliance_export.py created with format/build/export functions; data/audit_helper.py created with create_audit_event() factory. All pushed to divyansh branch. Jatin can now proceed independently on Priority 1 (audit logging + explainer) — no blocking dependencies.`
- `[Post-H50] [Both] Submission deliverables complete: docs/technical_report.md (898-line research paper), docs/vendor_risk_platform_deck.pptx (16-slide deck via python-pptx), docs/demo_script.md (timed SAY/DO guide), docs/demo_script_full.md (word-for-word narration + pronunciation guide), sample_inputs/ (full input library: 3 CSVs, 6 add-vendor JSONs, 5 API JSONs, 4 contract .txt files).`
- `[Post-H50] [J] ResendBackend in monitoring/emailer.py was originally implemented with stdlib urllib — Cloudflare on api.resend.com blocks Python-urllib User-Agent with 403 error code 1010. Fixed by switching to the official resend Python SDK (resend>=2.0.0, already in requirements.txt). get_emailer() priority is now: Resend > Slack > SMTP > Console.`
- `[Post-H50] [J] Added POST /api/reports/email (monthly portfolio summary) and POST /api/reports/email-alerts (CRITICAL/HIGH alert digest) endpoints. Both wired to buttons on the reports page dashboard. Both log sends to the audit trail. Tested live — email delivered to divyansh.p.m.126@gmail.com via Resend.`
- `[Post-H50] [J] Removed "Slack ⚠ not configured" badge from reports.html — was showing as a warning for all users who don't have Slack set up. Badge only renders now when Slack is actually connected ({% if slack_connected %} only, no else branch).`