"""
data/seed_db.py — Load vendor_registry.csv into SQLite via api/db.py models.

Depends on api/db.py being defined (Jatin's track). Run only after that file exists.
Until then, the scoring engine works directly off the CSVs.

Usage:
  python data/seed_db.py [--csv-dir DIR] [--db-url URL]

Defaults:
  --csv-dir  data/
  --db-url   sqlite:///vendor_risk.db   (same default as api/db.py should use)

What it does:
  1. Creates tables if they don't exist (via api.db.create_all_tables)
  2. Reads vendor_registry.csv row by row, normalizing via data.normalize
  3. Upserts each vendor into the `vendors` table (idempotent — safe to re-run)
  4. Prints a summary: rows inserted, rows skipped (already present), any errors
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# These imports from api/ will fail until Jatin creates api/db.py.
# The guard below makes this file importable (for static analysis) before that happens.
try:
    from api.db import get_session, create_all_tables, VendorORM
    _DB_AVAILABLE = True
except ImportError:
    _DB_AVAILABLE = False

from data.normalize import normalize_csv_row


def seed(csv_dir: Path, db_url: str | None = None) -> None:
    if not _DB_AVAILABLE:
        print(
            "[seed_db] ERROR: api/db.py not found — seed_db.py requires Jatin's api/db.py to exist.\n"
            "          Run scoring engine against CSVs directly until then:\n"
            "          python -m scoring.risk_engine --csv data/vendor_registry.csv"
        )
        sys.exit(1)

    registry_path = csv_dir / "vendor_registry.csv"
    if not registry_path.exists():
        print(f"[seed_db] ERROR: {registry_path} not found. Run data/generate_vendors.py first.")
        sys.exit(1)

    # Pass db_url through if provided; otherwise api/db.py uses its own default
    create_all_tables(db_url=db_url)

    inserted = 0
    skipped = 0
    errors: list[tuple[str, str]] = []

    with get_session(db_url=db_url) as session:
        with open(registry_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                vendor_id = row.get("vendor_id", "?")
                try:
                    vendor = normalize_csv_row(row)

                    # Check if already present (upsert logic)
                    existing = session.get(VendorORM, vendor.vendor_id)
                    if existing is not None:
                        # Update in place so re-runs are idempotent
                        _update_orm(existing, vendor)
                        skipped += 1
                    else:
                        session.add(VendorORM.from_vendor(vendor))
                        inserted += 1
                except Exception as e:
                    errors.append((vendor_id, str(e)))

        session.commit()

    print(f"[seed_db] Done. inserted={inserted}, updated={skipped}, errors={len(errors)}")
    if errors:
        print("[seed_db] Errors (first 10):")
        for vid, msg in errors[:10]:
            print(f"  {vid}: {msg}")


def _update_orm(orm_obj: "VendorORM", vendor: "Vendor") -> None:  # noqa: F821
    """Overwrite an existing ORM row from a fresh Vendor model."""
    data = vendor.model_dump(mode="json")
    for k, v in data.items():
        if hasattr(orm_obj, k):
            setattr(orm_obj, k, v)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed SQLite DB from vendor_registry.csv")
    parser.add_argument("--csv-dir", type=str, default="data", help="Directory containing vendor_registry.csv")
    parser.add_argument("--db-url", type=str, default=None, help="SQLAlchemy DB URL (default: same as api/db.py)")
    args = parser.parse_args()
    seed(Path(args.csv_dir), args.db_url)
