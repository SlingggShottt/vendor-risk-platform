# Style Guide

## Code

- Python: follow PEP8, type-hint function signatures (Pydantic models make this natural), docstrings on public functions only (skip for tiny helpers — time is scarce).
- No premature abstraction. A 48-hour hackathon rewards working code over elegant code. If something works inline, leave it inline.
- All vendor-shaped data, anywhere in the codebase, must conform to `common/schema.py`. If a field doesn't exist on the model, add it there first (with a note in `memory.md`) rather than passing around loose dicts.
- File/function naming: `snake_case` throughout (Python convention).

## API conventions (Jatin owns, Divyansh should know the shape)

- REST-ish: `GET /vendors`, `GET /vendors/{id}`, `GET /vendors/{id}/score`, `GET /reports/portfolio`, `GET /reports/portfolio.csv` (export)
- JSON responses match `ScoredVendor` / `Vendor` Pydantic shapes directly — don't invent parallel response shapes
- Errors: standard FastAPI `HTTPException` with a clear `detail` message

## Commits

- Format: `[D] short description` or `[J] short description` so history is scannable across two parallel branches
- Commit early and often on your own branch — squashing isn't necessary for a hackathon
- Before merging into `main`: `git pull --rebase origin main`, resolve conflicts, run whatever smoke test exists, then push

## Data/schema field naming

- Dates: ISO 8601 strings (`YYYY-MM-DD`) everywhere, no exceptions — this is exactly the kind of inconsistency (see PRD §"data reality") we're supposed to be solving, not reproducing
- Enums (risk_level, severity, anomaly_type): UPPER_SNAKE_CASE strings, defined once in `common/schema.py`, imported everywhere — never hardcode the string literal elsewhere
- IDs: `VND-XXXX` format (matches original brief examples)

## Docs

- Keep `backlog.md` checkboxes current — it's how the other person knows your status without asking
- One-line decision entries in `memory.md`, append-only, newest at bottom, format: `[HH:MM] [D/J] decision — why`
