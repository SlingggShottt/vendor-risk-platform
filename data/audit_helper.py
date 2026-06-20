"""
data/audit_helper.py — Audit event standardization.

Provides a single factory function for creating audit log entries with consistent
timestamps, IDs, and field structure. Used by all endpoints that trigger state changes.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4
from typing import Optional


def create_audit_event(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    old_state: Optional[dict] = None,
    new_state: Optional[dict] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Create a standardized audit log entry.

    Args:
        actor: Username or "system" (who triggered the action).
        action: Action type (e.g., "score_updated", "bulk_remediate", "vendor_created").
        resource_type: Type of resource affected (e.g., "vendor", "alert", "report").
        resource_id: ID of the resource (e.g., vendor_id).
        old_state: Previous values (dict), for change tracking.
        new_state: New values (dict), for change tracking.
        reason: Why the change occurred (e.g., "Q2 compliance review").

    Returns:
        Dict ready for storage by AuditLogger or database.
    """
    return {
        "id": str(uuid4()),
        "timestamp": datetime.utcnow(),
        "actor": actor,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "old_state": old_state,
        "new_state": new_state,
        "reason": reason,
    }
