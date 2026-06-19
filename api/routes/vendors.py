"""
api/routes/vendors.py — Vendor list, filter, and single-vendor detail endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common.schema import RiskLevel, ScoredVendor, Vendor

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


def _get_store():
    """Import app state lazily to avoid circular import."""
    from api.main import app
    return app.state.store


@router.get("")
def list_vendors(
    risk_level: Optional[str] = Query(None, description="Filter by risk level: LOW|MEDIUM|HIGH|CRITICAL"),
    search: Optional[str] = Query(None, description="Search vendor name or ID (case-insensitive)"),
    anomaly_type: Optional[str] = Query(None, description="Filter by anomaly type"),
    sort_by: str = Query("risk_score", description="Sort field: risk_score|name|vendor_id"),
    sort_dir: str = Query("desc", description="Sort direction: asc|desc"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Return scored vendor list with optional filtering and sorting."""
    store = _get_store()
    results = list(store.values())

    # Filter
    if risk_level:
        rl = risk_level.upper()
        results = [r for r in results if r["scored"].risk_level.value == rl]

    if anomaly_type:
        at = anomaly_type.upper()
        results = [r for r in results if r["scored"].anomaly_type.value == at]

    if search:
        q = search.lower()
        results = [
            r for r in results
            if q in r["vendor"].name.lower() or q in r["vendor"].vendor_id.lower()
        ]

    # Sort
    reverse = sort_dir.lower() == "desc"
    if sort_by == "risk_score":
        results.sort(key=lambda r: r["scored"].risk_score, reverse=reverse)
    elif sort_by == "name":
        results.sort(key=lambda r: r["vendor"].name.lower(), reverse=reverse)
    else:
        results.sort(key=lambda r: r["vendor"].vendor_id, reverse=reverse)

    total = len(results)
    page = results[offset: offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "vendors": [_vendor_summary(r) for r in page],
    }


@router.get("/{vendor_id}")
def get_vendor(vendor_id: str):
    """Return full detail for a single vendor."""
    store = _get_store()
    entry = store.get(vendor_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Vendor {vendor_id!r} not found")

    v: Vendor = entry["vendor"]
    sv: ScoredVendor = entry["scored"]
    alerts = entry.get("alerts", [])

    return {
        **_vendor_summary(entry),
        "category": v.category,
        "contract_start": v.contract_start.isoformat(),
        "contract_end": v.contract_end.isoformat(),
        "financial_rating": v.financial_rating,
        "annual_spend": v.annual_spend,
        "under_investigation": v.under_investigation,
        "handles_eu_data": v.handles_eu_data,
        "data_access": {
            "systems": v.data_access.systems,
            "data_sensitivity": v.data_access.data_sensitivity.value,
            "access_type": v.data_access.access_type.value,
        },
        "compliance": {
            "soc2_type2": v.compliance.soc2_type2,
            "soc2_expiry": v.compliance.soc2_expiry.isoformat() if v.compliance.soc2_expiry else None,
            "iso27001": v.compliance.iso27001,
            "gdpr_dpa": v.compliance.gdpr_dpa,
        },
        "breach_history": [
            {
                "date": b.date.isoformat(),
                "severity": b.severity.value,
                "description": b.description,
            }
            for b in v.breach_history
        ],
        "risk_factors": sv.risk_factors,
        "recommendation": sv.recommendation,
        "alerts": [
            {
                "alert_type": a.alert_type,
                "message": a.message,
                "severity": a.severity,
                "days_until": a.days_until,
            }
            for a in alerts
        ],
    }


def _vendor_summary(entry: dict) -> dict:
    v: Vendor = entry["vendor"]
    sv: ScoredVendor = entry["scored"]
    alerts = entry.get("alerts", [])
    return {
        "vendor_id": v.vendor_id,
        "name": v.name,
        "risk_score": sv.risk_score,
        "risk_level": sv.risk_level.value,
        "anomaly_type": sv.anomaly_type.value,
        "severity": sv.severity.value,
        "alert_count": len(alerts),
        "has_critical_alert": any(a.severity == "CRITICAL" for a in alerts),
    }
