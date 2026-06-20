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
- `[H30+] [D] requirements.txt: added anthropic>=0.111.0. anthropic SDK installed in .venv.`
- `[H40+] [D] Switched contract extraction AI from Anthropic (claude-opus-4-8) to Google Gemini (gemini-2.0-flash) — free API key available for demo. Env var changed from ANTHROPIC_API_KEY to GEMINI_API_KEY. Package: google-generativeai. extract_contract.py rewritten.`
- `[H40+] [D] Email alerts wired up: added POST /api/alerts/send-monthly and POST /api/alerts/send-expiry endpoints in api/routes/alerts.py. emailer.py (Jatin) already written; endpoints just call get_emailer(). UI buttons added to /reports page. .env.example created with all required vars.`
