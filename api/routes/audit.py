"""
api/routes/audit.py — Compliance audit trail endpoints.

GET /api/audit-log
  Returns timestamped events for every state change in the platform.
  Supports filtering by date range, actor, action type, and vendor ID.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/audit-log", tags=["audit"])


def _get_audit_logger():
    from api.main import app
    return app.state.audit_logger


@router.get("", summary="Fetch compliance audit log", description="Returns timestamped audit events for every state change (score updates, bulk remediations, exports). Filter by date range, actor, action, or vendor.")
def get_audit_log(
    date_from: Optional[str] = Query(None, description="ISO datetime lower bound, e.g. 2026-06-01T00:00:00"),
    date_to: Optional[str] = Query(None, description="ISO datetime upper bound, e.g. 2026-06-30T23:59:59"),
    actor: Optional[str] = Query(None, description="Filter by actor (substring match)"),
    action: Optional[str] = Query(None, description="Filter by action type (substring match)"),
    vendor_id: Optional[str] = Query(None, description="Filter to a specific vendor ID"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum events to return (most recent first)"),
):
    audit_logger = _get_audit_logger()
    events = audit_logger.get_events(
        date_from=date_from,
        date_to=date_to,
        actor=actor,
        action=action,
        vendor_id=vendor_id,
        limit=limit,
    )
    return {
        "total_returned": len(events),
        "total_events_in_log": audit_logger.event_count(),
        "events": events,
    }
