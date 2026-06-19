"""
data/normalize.py — Schema reconciliation.

Takes "messy" raw vendor records (flat dicts, alternate field names, inconsistent
date formats, stringified booleans, pipe-separated lists) and reconciles them
into canonical `common/schema.py` Vendor objects.

The original brief showed VND-0285 represented two different ways — nested vs flat,
different field names, even contradicting values. This module handles all those
cases so downstream code always sees a clean Vendor.

Usage:
  from data.normalize import normalize_raw_vendor

  vendor = normalize_raw_vendor(raw_dict)  # raises ValueError on unrecoverable issues

Intentionally inconsistent raw shapes supported:
  - Flat CSV row (all nested fields promoted to top level with underscores)
  - Nested JSON (data_access / compliance as sub-objects)
  - Alternate field names (sensitivity → data_sensitivity, cert_soc2 → soc2_type2, etc.)
  - ISO date strings, "DD/MM/YYYY", "MM-DD-YYYY", YYYY date objects
  - Stringified booleans ("true", "True", "1", "yes", True, 1)
  - Systems as pipe-separated string, comma-separated string, or list
  - Missing optional fields default to safe values
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import (
    AccessType,
    BreachEvent,
    Compliance,
    DataAccess,
    DataSensitivity,
    Severity,
    Vendor,
)

# ── Date parsing ──────────────────────────────────────────────────────────────

_DATE_FORMATS = [
    "%Y-%m-%d",   # ISO 8601 — canonical
    "%d/%m/%Y",   # UK/EU format
    "%m/%d/%Y",   # US format
    "%d-%m-%Y",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%d %b %Y",   # "19 Jun 2026"
    "%d %B %Y",   # "19 June 2026"
]


def _parse_date(value: Any) -> date | None:
    if value is None or value == "" or value != value:  # None / empty / NaN
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {value!r}")


def _require_date(value: Any, field: str) -> date:
    d = _parse_date(value)
    if d is None:
        raise ValueError(f"Required date field '{field}' is missing or unparseable: {value!r}")
    return d


# ── Boolean parsing ───────────────────────────────────────────────────────────

_TRUTHY = {"true", "1", "yes", "y", "on"}
_FALSY = {"false", "0", "no", "n", "off", ""}


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if value is None or value != value:
        return default
    s = str(value).strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    return default


# ── Enum parsing ──────────────────────────────────────────────────────────────

_SENSITIVITY_MAP: dict[str, DataSensitivity] = {
    "high": DataSensitivity.HIGH,
    "medium": DataSensitivity.MEDIUM,
    "med": DataSensitivity.MEDIUM,
    "low": DataSensitivity.LOW,
    "pii": DataSensitivity.HIGH,
    "financial": DataSensitivity.HIGH,
    "confidential": DataSensitivity.HIGH,
    "internal": DataSensitivity.MEDIUM,
    "public": DataSensitivity.LOW,
}

_ACCESS_MAP: dict[str, AccessType] = {
    "read_write": AccessType.READ_WRITE,
    "readwrite": AccessType.READ_WRITE,
    "rw": AccessType.READ_WRITE,
    "write": AccessType.READ_WRITE,
    "read_only": AccessType.READ_ONLY,
    "readonly": AccessType.READ_ONLY,
    "read": AccessType.READ_ONLY,
    "ro": AccessType.READ_ONLY,
    "none": AccessType.NONE,
    "no_access": AccessType.NONE,
    "": AccessType.NONE,
}

_SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "med": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.LOW,
}


def _parse_sensitivity(value: Any) -> DataSensitivity:
    if isinstance(value, DataSensitivity):
        return value
    s = str(value).strip().lower().replace("-", "_")
    result = _SENSITIVITY_MAP.get(s)
    if result is None:
        raise ValueError(f"Cannot parse DataSensitivity: {value!r}")
    return result


def _parse_access_type(value: Any) -> AccessType:
    if isinstance(value, AccessType):
        return value
    s = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    result = _ACCESS_MAP.get(s)
    if result is None:
        raise ValueError(f"Cannot parse AccessType: {value!r}")
    return result


def _parse_severity(value: Any) -> Severity:
    if isinstance(value, Severity):
        return value
    if value is None or str(value).strip() == "":
        return Severity.LOW
    s = str(value).strip().lower()
    result = _SEVERITY_MAP.get(s)
    if result is None:
        return Severity.MEDIUM  # safe default for unknown severity strings
    return result


# ── Systems list parsing ──────────────────────────────────────────────────────

def _parse_systems(value: Any) -> list[str]:
    if value is None or value != value or str(value).strip() == "":
        return []
    if isinstance(value, list):
        return [str(s).strip() for s in value if str(s).strip()]
    s = str(value).strip()
    # detect separator
    if "|" in s:
        return [p.strip() for p in s.split("|") if p.strip()]
    if "," in s:
        return [p.strip() for p in s.split(",") if p.strip()]
    if s:
        return [s]
    return []


# ── Alternate field name resolution ──────────────────────────────────────────

# Maps non-canonical field names → canonical name
_FIELD_ALIASES: dict[str, str] = {
    # top-level
    "id": "vendor_id",
    "vendor_name": "name",
    "company": "name",
    "company_name": "name",
    "type": "category",
    "vendor_type": "category",
    "start_date": "contract_start",
    "end_date": "contract_end",
    "expiry_date": "contract_end",
    "contract_expiry": "contract_end",
    "rating": "financial_rating",
    "credit_rating": "financial_rating",
    "spend": "annual_spend",
    "yearly_spend": "annual_spend",
    # data_access (flat form)
    "sensitivity": "data_sensitivity",
    "data_classification": "data_sensitivity",
    "access": "access_type",
    "access_level": "access_type",
    "system_access": "systems",
    "accessed_systems": "systems",
    # compliance (flat form)
    "cert_soc2": "soc2_type2",
    "soc2": "soc2_type2",
    "has_soc2": "soc2_type2",
    "soc2_cert": "soc2_type2",
    "soc2_valid_until": "soc2_expiry",
    "soc2_renewal": "soc2_expiry",
    "cert_iso": "iso27001",
    "iso": "iso27001",
    "has_iso27001": "iso27001",
    "dpa": "gdpr_dpa",
    "has_dpa": "gdpr_dpa",
    "gdpr": "gdpr_dpa",
    # misc
    "eu_data": "handles_eu_data",
    "processes_eu_data": "handles_eu_data",
    "investigation": "under_investigation",
    "flagged": "under_investigation",
    # breach
    "breach_date": "latest_breach_date",
    "last_breach": "latest_breach_date",
    "breach_severity": "latest_breach_severity",
    "breach_description": "latest_breach_description",
    "breach_details": "latest_breach_description",
    "num_breaches": "breach_count",
    "breaches": "breach_count",
}


def _resolve_aliases(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict with non-canonical keys renamed to canonical equivalents."""
    out: dict[str, Any] = {}
    for k, v in raw.items():
        canonical = _FIELD_ALIASES.get(k.lower().strip(), k.lower().strip())
        out[canonical] = v
    return out


# ── Nested sub-object extraction ──────────────────────────────────────────────

def _extract_data_access(raw: dict[str, Any]) -> tuple[DataSensitivity, AccessType, list[str]]:
    """Handle both flat and nested data_access representation."""
    nested = raw.get("data_access")
    if isinstance(nested, dict):
        sensitivity = _parse_sensitivity(nested.get("data_sensitivity") or nested.get("sensitivity", "MEDIUM"))
        access_type = _parse_access_type(nested.get("access_type") or nested.get("access", "read_only"))
        systems = _parse_systems(nested.get("systems", []))
    else:
        sensitivity = _parse_sensitivity(raw.get("data_sensitivity", "MEDIUM"))
        access_type = _parse_access_type(raw.get("access_type", "read_only"))
        systems = _parse_systems(raw.get("systems", raw.get("system_access", "")))
    return sensitivity, access_type, systems


def _extract_compliance(raw: dict[str, Any]) -> tuple[bool, date | None, bool, bool]:
    """Return (soc2_type2, soc2_expiry, iso27001, gdpr_dpa) from flat or nested."""
    nested = raw.get("compliance")
    if isinstance(nested, dict):
        soc2 = _parse_bool(nested.get("soc2_type2", nested.get("soc2", False)))
        soc2_exp = _parse_date(nested.get("soc2_expiry") or nested.get("soc2_valid_until"))
        iso = _parse_bool(nested.get("iso27001", nested.get("iso", False)))
        dpa = _parse_bool(nested.get("gdpr_dpa", nested.get("dpa", False)))
    else:
        soc2 = _parse_bool(raw.get("soc2_type2", False))
        soc2_exp = _parse_date(raw.get("soc2_expiry"))
        iso = _parse_bool(raw.get("iso27001", False))
        dpa = _parse_bool(raw.get("gdpr_dpa", False))
    return soc2, soc2_exp, iso, dpa


def _extract_breaches(raw: dict[str, Any]) -> list[BreachEvent]:
    """Parse breach history from nested list or flat single-breach fields."""
    nested = raw.get("breach_history")
    if isinstance(nested, list) and nested:
        events = []
        for b in nested:
            if not isinstance(b, dict):
                continue
            d = _parse_date(b.get("date") or b.get("breach_date"))
            if d is None:
                continue
            events.append(BreachEvent(
                date=d,
                severity=_parse_severity(b.get("severity", "MEDIUM")),
                description=str(b.get("description", b.get("details", "Unknown"))),
            ))
        return events

    # flat single-breach fields
    breach_count = int(float(str(raw.get("breach_count", 0) or 0)))
    breach_date = _parse_date(raw.get("latest_breach_date") or raw.get("breach_date"))
    if breach_count > 0 and breach_date is not None:
        return [BreachEvent(
            date=breach_date,
            severity=_parse_severity(raw.get("latest_breach_severity") or raw.get("breach_severity", "MEDIUM")),
            description=str(raw.get("latest_breach_description") or raw.get("breach_description", "Historical breach")),
        )]
    return []


# ── Public API ────────────────────────────────────────────────────────────────

def normalize_raw_vendor(raw: dict[str, Any]) -> Vendor:
    """
    Normalize a raw vendor dict (from CSV row, JSON blob, or any messy source)
    into a canonical Vendor Pydantic object.

    Raises ValueError if required fields (vendor_id, name, contract_start/end) are
    missing or unparseable. All other fields default safely.
    """
    # 1. Resolve alternate field names
    r = _resolve_aliases(raw)

    # 2. Required fields
    vendor_id = str(r.get("vendor_id", "")).strip()
    if not vendor_id:
        raise ValueError(f"vendor_id is required but missing in: {raw}")
    name = str(r.get("name", "")).strip()
    if not name:
        name = vendor_id  # last resort fallback

    # 3. Sub-objects
    sensitivity, access_type, systems = _extract_data_access(r)
    soc2, soc2_exp, iso, dpa = _extract_compliance(r)
    breaches = _extract_breaches(r)

    # 4. Dates
    contract_start = _require_date(r.get("contract_start"), "contract_start")
    contract_end = _require_date(r.get("contract_end"), "contract_end")

    # 5. Scalars with safe defaults
    category = str(r.get("category", "Unknown")).strip() or "Unknown"
    financial_rating = str(r.get("financial_rating", "B")).strip() or "B"
    annual_spend_raw = r.get("annual_spend")
    annual_spend: float | None = None
    if annual_spend_raw is not None and str(annual_spend_raw).strip() not in ("", "nan"):
        try:
            annual_spend = float(str(annual_spend_raw).replace(",", ""))
        except (ValueError, TypeError):
            annual_spend = None

    under_investigation = _parse_bool(r.get("under_investigation", False))
    handles_eu_data = _parse_bool(r.get("handles_eu_data", False))

    return Vendor(
        vendor_id=vendor_id,
        name=name,
        category=category,
        contract_start=contract_start,
        contract_end=contract_end,
        data_access=DataAccess(
            systems=systems,
            data_sensitivity=sensitivity,
            access_type=access_type,
        ),
        compliance=Compliance(
            soc2_type2=soc2,
            soc2_expiry=soc2_exp,
            iso27001=iso,
            gdpr_dpa=dpa,
        ),
        breach_history=breaches,
        financial_rating=financial_rating,
        annual_spend=annual_spend,
        under_investigation=under_investigation,
        handles_eu_data=handles_eu_data,
    )


def normalize_csv_row(row: dict[str, str]) -> Vendor:
    """Thin wrapper for CSV DictReader rows (all values are strings)."""
    return normalize_raw_vendor(row)


# ── Intentionally inconsistent raw shapes (for testing normalize.py) ──────────

# These prove normalize.py does something non-trivial — they're messy inputs
# that the generator would never produce.

RAW_MESSY_EXAMPLES: list[dict[str, Any]] = [
    # Shape A: flat with alternate field names, UK date format, pipe-separated systems
    {
        "id": "VND-M001",
        "company_name": "MessyFlat Corp",
        "type": "Cloud Infrastructure",
        "start_date": "01/06/2023",
        "contract_expiry": "30/06/2027",
        "sensitivity": "HIGH",
        "access": "read_write",
        "system_access": "Database_Primary|FileServer_Corporate",
        "cert_soc2": "yes",
        "soc2_valid_until": "2027-01-01",
        "iso": "no",
        "dpa": "false",
        "breach_count": "1",
        "breach_date": "15/01/2026",
        "breach_severity": "medium",
        "breach_description": "Backup exposed",
        "rating": "B",
        "eu_data": "1",
        "investigation": "0",
    },
    # Shape B: nested JSON-style with some fields contradicting (take nested as authoritative)
    {
        "vendor_id": "VND-M002",
        "vendor_name": "NestedJSON Ltd",
        "category": "SaaS",
        "start_date": "2024-01-01",
        "end_date": "2027-01-01",
        "data_access": {
            "data_sensitivity": "medium",
            "access_type": "read_only",
            "systems": ["CRM", "Analytics_DB"],
        },
        "compliance": {
            "soc2_type2": True,
            "soc2_expiry": "2028-06-01",
            "iso27001": False,
            "gdpr_dpa": True,
        },
        "breach_history": [],
        "financial_rating": "A-",
        "annual_spend": "250000",
        "under_investigation": False,
        "handles_eu_data": True,
    },
    # Shape C: breach_history as nested list, comma-separated systems, US date format
    {
        "vendor_id": "VND-M003",
        "name": "BreachList Vendor",
        "category": "Managed Services",
        "contract_start": "06/15/2022",
        "contract_end": "06/15/2026",
        "data_sensitivity": "HIGH",
        "access_type": "rw",
        "systems": "HR_System, Identity_Provider, ERP",
        "soc2_type2": "True",
        "soc2_expiry": "2025-01-01",  # expired
        "iso27001": "1",
        "gdpr_dpa": "no",
        "breach_history": [
            {"date": "2026-02-10", "severity": "HIGH", "description": "Credential breach"},
        ],
        "financial_rating": "C",
        "annual_spend": "1,200,000",
        "under_investigation": "false",
        "handles_eu_data": "yes",
    },
]


if __name__ == "__main__":
    print("normalize.py — testing messy input reconciliation\n")
    for raw in RAW_MESSY_EXAMPLES:
        try:
            v = normalize_raw_vendor(raw)
            print(f"OK  {v.vendor_id}: {v.name}")
            print(f"    sensitivity={v.data_access.data_sensitivity.value}, "
                  f"access={v.data_access.access_type.value}, systems={v.data_access.systems}")
            print(f"    soc2={v.compliance.soc2_type2}, expiry={v.compliance.soc2_expiry}, "
                  f"iso={v.compliance.iso27001}, dpa={v.compliance.gdpr_dpa}")
            print(f"    breaches={len(v.breach_history)}, rating={v.financial_rating}, "
                  f"eu={v.handles_eu_data}")
            # Validate round-trip through Pydantic
            v.model_validate(v.model_dump(mode="json"))
            print(f"    [schema OK]\n")
        except Exception as e:
            print(f"ERR {raw.get('vendor_id', raw.get('id', '?'))}: {e}\n")
