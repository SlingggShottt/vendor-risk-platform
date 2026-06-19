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
