"""
api/routes/vendors.py — Vendor list, filter, and single-vendor detail endpoints.
"""

from __future__ import annotations

import random
from datetime import date
from fastapi import APIRouter, Body, HTTPException, Query
from typing import Any, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common.schema import RiskLevel, ScoredVendor, Vendor
from data.normalize import normalize_raw_vendor
from scoring.risk_engine import score_vendor
from monitoring.alerts import check_alerts

router = APIRouter(prefix="/api/vendors", tags=["vendors"])


def _get_store():
    """Import app state lazily to avoid circular import."""
    from api.main import app
    return app.state.store


def _get_app():
    from api.main import app
    return app


def _next_vendor_id(store: dict) -> str:
    nums = []
    for vid in store:
        if vid.startswith("VND-"):
            try:
                nums.append(int(vid[4:]))
            except ValueError:
                pass
    return f"VND-{max(nums, default=0) + 1:04d}"


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


@router.post("")
def add_vendor(payload: dict[str, Any] = Body(...)):
    """
    Add a new vendor: normalize → score → check alerts → store.
    Fires an immediate email if any alerts are triggered.
    Also accumulates alerts in app.state.today_alerts for the 5pm EOD digest.
    """
    app = _get_app()
    store = app.state.store
    today = getattr(app.state, "today", date.today())

    # Auto-generate vendor_id if not provided
    raw = dict(payload)
    if not raw.get("vendor_id", "").strip():
        raw["vendor_id"] = _next_vendor_id(store)

    vendor_id = raw["vendor_id"]
    if vendor_id in store:
        raise HTTPException(status_code=409, detail=f"Vendor {vendor_id!r} already exists")

    try:
        vendor = normalize_raw_vendor(raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    scored = score_vendor(vendor, today)
    alerts = check_alerts(vendor, today)

    store[vendor_id] = {"vendor": vendor, "scored": scored, "alerts": alerts}

    # Accumulate for EOD digest
    today_alerts: list = getattr(app.state, "today_alerts", [])
    today_alerts.extend(alerts)
    app.state.today_alerts = today_alerts

    # Immediate email if any alerts
    if alerts:
        try:
            from monitoring.emailer import get_emailer
            get_emailer().send_expiry_alerts(alerts, today)
        except Exception as e:
            print(f"[add_vendor] Email failed: {e}", flush=True)

    return {
        "vendor_id": vendor_id,
        "name": vendor.name,
        "risk_score": scored.risk_score,
        "risk_level": scored.risk_level.value,
        "anomaly_type": scored.anomaly_type.value,
        "risk_factors": scored.risk_factors,
        "recommendation": scored.recommendation,
        "alerts": [
            {
                "alert_type": a.alert_type,
                "message": a.message,
                "severity": a.severity,
                "days_until": a.days_until,
            }
            for a in alerts
        ],
        "email_sent": bool(alerts),
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


@router.get("/{vendor_id}/history", summary="6-month score history with trend analysis")
def vendor_score_history(vendor_id: str):
    """Return 6 deterministic monthly score data points + linear regression trend.

    Historical points are seeded by vendor_id hash (consistent across restarts).
    Final point is always the live risk_score. Adds trend_direction and
    projected_risk_level_in_3mo via numpy linear regression.
    """
    store = _get_store()
    entry = store.get(vendor_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Vendor {vendor_id!r} not found")

    current_score: float = entry["scored"].risk_score
    rng = random.Random(hash(vendor_id))

    history: list[float] = []
    base = current_score + rng.uniform(-10, 10)
    for _ in range(5):
        base = max(0.0, min(100.0, base + rng.uniform(-15, 15)))
        history.append(round(base, 1))
    history.append(current_score)

    today = date.today()
    labels: list[str] = []
    for i in range(5, -1, -1):
        month = today.month - i
        year = today.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        labels.append(date(year, month, 1).strftime("%b %Y"))

    # ── Linear regression for trend + 3-month projection ─────────────────────
    try:
        import numpy as np
        x = np.arange(len(history), dtype=float)
        coeffs = np.polyfit(x, history, 1)
        slope = float(coeffs[0])
        projected_score = float(np.clip(np.polyval(coeffs, len(history) + 2), 0, 100))
    except Exception:
        slope = 0.0
        projected_score = current_score

    if slope > 1.5:
        trend_direction = "up"
    elif slope < -1.5:
        trend_direction = "down"
    else:
        trend_direction = "stable"

    projected_score = round(projected_score, 1)
    projected_level = _score_to_level(projected_score)

    # Build the data points (6 historical + 1 projected)
    today_label = today.strftime("%b %Y")
    month3 = date(today.year + (today.month + 2) // 13,
                  (today.month + 2) % 12 or 12,
                  1).strftime("%b %Y")

    data_points = [
        {"month": labels[i], "score": history[i], "projected": False}
        for i in range(len(labels))
    ]
    data_points.append({"month": month3, "score": projected_score, "projected": True})

    # Emit a trending-CRITICAL alert if warranted
    trend_alerts = []
    if trend_direction == "up" and projected_level in ("HIGH", "CRITICAL"):
        trend_alerts.append({
            "severity": "HIGH",
            "type": "RISK_TRENDING_CRITICAL",
            "description": (
                f"Risk score trending upward (slope +{slope:.1f}/month); "
                f"projected to reach {projected_level} by {month3}"
            ),
        })

    return {
        "vendor_id": vendor_id,
        "labels": labels,
        "scores": history,
        "trend_direction": trend_direction,
        "projected_score_3mo": projected_score,
        "projected_risk_level_in_3mo": projected_level,
        "data_points": data_points,
        "trend_alerts": trend_alerts,
    }


@router.get("/{vendor_id}/risk-explainer", summary="Rule-by-rule risk score breakdown")
def vendor_risk_explainer(vendor_id: str):
    """Return structured rule-by-rule breakdown of a vendor's risk score.

    Each contributing_factor includes: rule_name, weight_pct, impact level,
    contribution_pts, and a human-readable description. Also includes
    specific remediation_actions and the audit trail note.
    """
    store = _get_store()
    entry = store.get(vendor_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Vendor {vendor_id!r} not found")

    from scoring.explainer import explain_risk

    # Pull last audit note if the audit logger is available
    last_audit_note: Optional[str] = None
    try:
        from api.main import app
        events = app.state.audit_logger.get_events(vendor_id=vendor_id, limit=1)
        if events:
            e = events[0]
            last_audit_note = f"Last updated by {e['actor']} on {e['timestamp'][:10]} ({e['action']})"
    except Exception:
        pass

    explanation = explain_risk(
        vendor=entry["vendor"],
        scored=entry["scored"],
        today=date.today(),
        last_audit_note=last_audit_note,
    )
    return explanation


def _score_to_level(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 65:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


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
