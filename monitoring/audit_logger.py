"""
monitoring/audit_logger.py — In-memory audit log.

Appends AuditLog entries to app.state.audit_log (a list).
Provides query helpers used by GET /api/audit-log.

For production, swap the list for a DB-backed table; the interface stays the same.
"""

from __future__ import annotations

from datetime import datetime, date
from typing import Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.audit_helper import create_audit_event


def _get_log() -> list[dict]:
    from api.main import app
    if not hasattr(app.state, "audit_log"):
        app.state.audit_log = []
    return app.state.audit_log


def log_event(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    old_state: dict | None = None,
    new_state: dict | None = None,
    reason: str | None = None,
) -> dict:
    """Create and append an audit event to the in-memory log. Returns the event dict."""
    event = create_audit_event(
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_state=old_state,
        new_state=new_state,
        reason=reason,
    )
    _get_log().append(event)
    return event


def query_log(
    date_from: date | None = None,
    date_to: date | None = None,
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    vendor_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[int, list[dict]]:
    """
    Filter the audit log and return (total_count, page).
    All filters are ANDed together.
    """
    log = _get_log()
    results = log

    if date_from:
        dt_from = datetime.combine(date_from, datetime.min.time())
        results = [e for e in results if e["timestamp"] >= dt_from]

    if date_to:
        dt_to = datetime.combine(date_to, datetime.max.time())
        results = [e for e in results if e["timestamp"] <= dt_to]

    if actor:
        results = [e for e in results if e["actor"] == actor]

    if action:
        results = [e for e in results if e["action"] == action]

    if resource_type:
        results = [e for e in results if e["resource_type"] == resource_type]

    if vendor_id:
        results = [e for e in results if e["resource_id"] == vendor_id]

    # newest first
    results = sorted(results, key=lambda e: e["timestamp"], reverse=True)
    total = len(results)
    return total, results[offset: offset + limit]


def _serialize_event(event: dict) -> dict:
    """Make an audit event JSON-serializable."""
    out = dict(event)
    if isinstance(out.get("timestamp"), datetime):
        out["timestamp"] = out["timestamp"].isoformat()
    return out
