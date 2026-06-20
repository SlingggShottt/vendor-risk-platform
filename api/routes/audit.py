"""
api/routes/audit.py — Audit log query endpoint.

GET /api/audit-log
  Returns paginated audit events with optional filters:
    date_from, date_to  (YYYY-MM-DD)
    actor               (exact match)
    action              (exact match, e.g. "score_updated", "vendor_created")
    resource_type       (e.g. "vendor", "report")
    vendor_id           (filters on resource_id)
    limit, offset       (pagination)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from monitoring.audit_logger import query_log, _serialize_event

router = APIRouter(prefix="/api/audit-log", tags=["audit"])


@router.get("")
def get_audit_log(
    date_from:     Optional[str] = Query(None, description="Filter from date (YYYY-MM-DD)"),
    date_to:       Optional[str] = Query(None, description="Filter to date (YYYY-MM-DD)"),
    actor:         Optional[str] = Query(None, description="Filter by actor (username or 'system')"),
    action:        Optional[str] = Query(None, description="Filter by action type"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type (vendor, report, …)"),
    vendor_id:     Optional[str] = Query(None, description="Filter by vendor ID"),
    limit:         int           = Query(100, ge=1, le=500),
    offset:        int           = Query(0, ge=0),
):
    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to)   if date_to   else None

    total, events = query_log(
        date_from=df,
        date_to=dt,
        actor=actor,
        action=action,
        resource_type=resource_type,
        vendor_id=vendor_id,
        limit=limit,
        offset=offset,
    )

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": [_serialize_event(e) for e in events],
    }
