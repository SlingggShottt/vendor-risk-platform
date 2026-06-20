"""
monitoring/audit_logger.py — In-memory append-only compliance audit log.

Every state change (score update, bulk remediation, bulk upload, export) calls
log_event(). On startup, api/main.py attaches an instance to app.state.audit_logger.

In production this would write to a dedicated DB table; for the hackathon the
in-memory list is sufficient and matches the jatin.md spec.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class AuditEvent:
    event_id: str
    timestamp: str  # ISO 8601 UTC
    actor: str
    action: str
    resource_type: str
    resource_id: str
    old_state: dict
    new_state: dict
    reason: str


class AuditLogger:
    """Thread-safe (append is atomic in CPython) in-memory audit log."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def log_event(
        self,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        old_state: dict,
        new_state: dict,
        reason: str = "",
    ) -> AuditEvent:
        event = AuditEvent(
            event_id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            old_state=old_state,
            new_state=new_state,
            reason=reason,
        )
        self._events.append(event)
        return event

    def get_events(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        vendor_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        results = self._events[:]

        if date_from:
            results = [e for e in results if e.timestamp >= date_from]
        if date_to:
            results = [e for e in results if e.timestamp <= date_to + "Z"]
        if actor:
            results = [e for e in results if actor.lower() in e.actor.lower()]
        if action:
            results = [e for e in results if action.lower() in e.action.lower()]
        if resource_type:
            results = [e for e in results if e.resource_type == resource_type]
        if vendor_id:
            results = [e for e in results if e.resource_id == vendor_id]

        # Most-recent first, then paginate
        results.reverse()
        return [_to_dict(e) for e in results[offset: offset + limit]]

    def event_count(self) -> int:
        return len(self._events)


def _to_dict(e: AuditEvent) -> dict:
    return {
        "event_id": e.event_id,
        "timestamp": e.timestamp,
        "actor": e.actor,
        "action": e.action,
        "resource_type": e.resource_type,
        "resource_id": e.resource_id,
        "old_state": e.old_state,
        "new_state": e.new_state,
        "reason": e.reason,
    }
