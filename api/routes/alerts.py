"""
api/routes/alerts.py — Active alerts endpoints.

GET /api/alerts           All active alerts across all vendors (filterable by severity)
GET /api/alerts/{id}      Alerts for a single vendor
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _get_store() -> dict:
    from api.main import app
    return app.state.store


@router.get("")
def list_alerts(severity: Optional[str] = Query(None, description="Filter: CRITICAL|HIGH|MEDIUM|LOW")):
    store = _get_store()
    alerts = [a for entry in store.values() for a in entry["alerts"]]
    if severity:
        s = severity.upper()
        alerts = [a for a in alerts if a.severity == s]
    alerts.sort(key=lambda a: ({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(a.severity, 4)))
    return [
        {
            "vendor_id": a.vendor_id,
            "vendor_name": a.vendor_name,
            "alert_type": a.alert_type,
            "message": a.message,
            "severity": a.severity,
            "days_until": a.days_until,
        }
        for a in alerts
    ]


@router.get("/{vendor_id}")
def vendor_alerts(vendor_id: str):
    store = _get_store()
    entry = store.get(vendor_id)
    if not entry:
        return []
    return [
        {
            "vendor_id": a.vendor_id,
            "vendor_name": a.vendor_name,
            "alert_type": a.alert_type,
            "message": a.message,
            "severity": a.severity,
            "days_until": a.days_until,
        }
        for a in entry["alerts"]
    ]
