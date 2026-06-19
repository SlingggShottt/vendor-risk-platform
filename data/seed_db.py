"""
data/seed_db.py — Load vendor_registry.csv into SQLite via api/db.py models.

Usage:
  python data/seed_db.py [--csv-dir DIR] [--db-url URL]

Defaults:
  --csv-dir  data/
  --db-url   sqlite:///vendor_risk.db

What it does:
  1. Creates tables if they don't exist (via api.db.create_tables)
  2. Reads vendor_registry.csv row by row
  3. Upserts each vendor into the `vendors` table (idempotent — safe to re-run)
  4. Prints a summary: rows inserted, rows updated, any errors
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.db import SessionLocal, VendorRow, create_tables


# ── Type coercions for flat CSV → VendorRow ───────────────────────────────────

_DATE_FMTS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]


def _parse_date(val: str) -> date | None:
    if not val or val.strip() == "":
        return None
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_bool(val: str) -> bool:
    return str(val).strip().lower() in {"true", "1", "yes"}


def _parse_float(val: str) -> float | None:
    s = str(val).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(val: str) -> int:
    try:
        return int(float(str(val).strip() or "0"))
    except ValueError:
        return 0


def _row_to_vendor_row(row: dict[str, str]) -> VendorRow:
    """Convert a flat CSV dict to a VendorRow ORM object."""
    return VendorRow(
        vendor_id=row["vendor_id"],
        name=row.get("name", row.get("vendor_name", "")),
        category=row.get("category", ""),
        contract_start=_parse_date(row.get("contract_start", "")),
        contract_end=_parse_date(row.get("contract_end", "")),
        data_sensitivity=row.get("data_sensitivity", "MEDIUM"),
        access_type=row.get("access_type", "read_only"),
        systems=row.get("systems", ""),
        soc2_type2=_parse_bool(row.get("soc2_type2", "false")),
        soc2_expiry=_parse_date(row.get("soc2_expiry", "")),
        iso27001=_parse_bool(row.get("iso27001", "false")),
        gdpr_dpa=_parse_bool(row.get("gdpr_dpa", "false")),
        breach_count=_parse_int(row.get("breach_count", "0")),
        latest_breach_date=_parse_date(row.get("latest_breach_date", "")),
        latest_breach_severity=row.get("latest_breach_severity") or None,
        latest_breach_description=row.get("latest_breach_description") or None,
        financial_rating=row.get("financial_rating", "B"),
        annual_spend=_parse_float(row.get("annual_spend", "")),
        under_investigation=_parse_bool(row.get("under_investigation", "false")),
        handles_eu_data=_parse_bool(row.get("handles_eu_data", "false")),
    )


def _update_orm(existing: VendorRow, row: dict[str, str]) -> None:
    """Overwrite an existing VendorRow from a fresh CSV row."""
    fresh = _row_to_vendor_row(row)
    for col in VendorRow.__table__.columns.keys():
        if col != "vendor_id":
            setattr(existing, col, getattr(fresh, col))


# ── Main seed function ────────────────────────────────────────────────────────

def seed(csv_dir: Path, db_url: str | None = None) -> None:
    registry_path = csv_dir / "vendor_registry.csv"
    if not registry_path.exists():
        print(f"[seed_db] ERROR: {registry_path} not found. Run data/generate_vendors.py first.")
        sys.exit(1)

    # Apply custom DB URL if provided (override the module-level engine)
    if db_url:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from api.db import Base
        _engine = create_engine(db_url, connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=_engine)
        _Session = sessionmaker(bind=_engine)
        session = _Session()
    else:
        create_tables()
        session = SessionLocal()

    inserted = 0
    updated = 0
    errors: list[tuple[str, str]] = []

    try:
        with open(registry_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                vendor_id = row.get("vendor_id", "?")
                try:
                    existing = session.get(VendorRow, vendor_id)
                    if existing is not None:
                        _update_orm(existing, row)
                        updated += 1
                    else:
                        session.add(_row_to_vendor_row(row))
                        inserted += 1
                except Exception as e:
                    errors.append((vendor_id, str(e)))

        session.commit()
    finally:
        session.close()

    print(f"[seed_db] Done. inserted={inserted}, updated={updated}, errors={len(errors)}")
    if errors:
        print("[seed_db] Errors (first 10):")
        for vid, msg in errors[:10]:
            print(f"  {vid}: {msg}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed SQLite DB from vendor_registry.csv")
    parser.add_argument("--csv-dir", type=str, default="data", help="Directory containing vendor_registry.csv")
    parser.add_argument("--db-url", type=str, default=None, help="SQLAlchemy DB URL")
    args = parser.parse_args()
    seed(Path(args.csv_dir), args.db_url)
