"""
api/routes/bulk.py — Bulk vendor operations.

POST /api/vendors/bulk-upload
  CSV upload: parses via bulk_ingest.py, scores, adds to store.

POST /api/vendors/bulk-remediate
  Mass remediation: acknowledge | renew_cert | require_dpa action across
  a list of vendor IDs, logs each change to the audit trail.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Literal, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from scoring.risk_engine import score_vendor
from monitoring.alerts import check_alerts

router = APIRouter(tags=["bulk"])


def _get_store() -> dict:
    from api.main import app
    return app.state.store


def _get_today() -> date:
    from api.main import app
    return app.state.today


@router.post("/api/vendors/bulk-upload")
async def bulk_upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=422, detail="Only CSV files are accepted")

    try:
        from data.bulk_ingest import ingest_csv_bytes
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="bulk_ingest module not available yet — Divyansh's data/bulk_ingest.py is pending",
        )

    raw_bytes = await file.read()
    try:
        vendors, ingest_errors = ingest_csv_bytes(raw_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"CSV parse failed: {e}")

    today = _get_today()
    store = _get_store()
    results = []

    for vendor in vendors:
        try:
            scored = score_vendor(vendor, today)
            alerts = check_alerts(vendor, today)
            store[vendor.vendor_id] = {
                "vendor": vendor,
                "scored": scored,
                "alerts": alerts,
            }
            # Audit log each added vendor
            _log_audit(
                actor="bulk_upload",
                action="vendor_added",
                resource_id=vendor.vendor_id,
                old_state={},
                new_state={"risk_score": scored.risk_score, "risk_level": scored.risk_level.value},
                reason=f"bulk CSV upload: {file.filename}",
            )
            results.append({
                "vendor_id": vendor.vendor_id,
                "name": vendor.name,
                "risk_score": scored.risk_score,
                "risk_level": scored.risk_level.value,
                "risk_factors": scored.risk_factors,
                "recommendation": scored.recommendation,
            })
        except Exception as e:
            results.append({"vendor_id": getattr(vendor, "vendor_id", "?"), "error": str(e)})

    return {
        "uploaded": len(results),
        "parse_errors": len(ingest_errors),
        "vendors": results,
        "errors": ingest_errors,
    }


# ── Bulk remediate ─────────────────────────────────────────────────────────────

class BulkRemediateRequest(BaseModel):
    vendor_ids: list[str]
    action: Literal["acknowledge", "renew_cert", "require_dpa"]
    reason: str = ""


@router.post("/api/vendors/bulk-remediate", summary="Mass remediation action across vendors")
def bulk_remediate(body: BulkRemediateRequest):
    """
    Apply a remediation action to a list of vendors and log each change to the audit trail.

    Actions:
      acknowledge  — mark vendor as reviewed; clears no scores but records the review
      renew_cert   — flags that cert renewal has been requested (sets a note in store)
      require_dpa  — flags that a DPA has been required from the vendor
    """
    store = _get_store()
    updated: list[dict] = []
    errors: list[dict] = []

    for vid in body.vendor_ids:
        entry = store.get(vid)
        if not entry:
            errors.append({"vendor_id": vid, "error": "not found"})
            continue

        old_state = {
            "risk_score": entry["scored"].risk_score,
            "risk_level": entry["scored"].risk_level.value,
        }

        # Apply the action (update store metadata, not the raw score)
        if "meta" not in entry:
            entry["meta"] = {}
        entry["meta"][body.action] = date.today().isoformat()
        entry["meta"]["last_remediation_reason"] = body.reason

        new_state = {**old_state, "remediation": body.action, "reason": body.reason}

        _log_audit(
            actor="bulk_remediate",
            action=body.action,
            resource_id=vid,
            old_state=old_state,
            new_state=new_state,
            reason=body.reason,
        )
        updated.append({
            "vendor_id": vid,
            "name": entry["vendor"].name,
            "action_applied": body.action,
        })

    summary = f"{len(updated)} vendor(s) updated via {body.action}"
    if errors:
        summary += f"; {len(errors)} error(s)"

    return {
        "updated_count": len(updated),
        "error_count": len(errors),
        "summary": summary,
        "updated": updated,
        "errors": errors,
    }


def _log_audit(actor: str, action: str, resource_id: str,
               old_state: dict, new_state: dict, reason: str) -> None:
    try:
        from api.main import app
        app.state.audit_logger.log_event(
            actor=actor,
            action=action,
            resource_type="vendor",
            resource_id=resource_id,
            old_state=old_state,
            new_state=new_state,
            reason=reason,
        )
    except Exception:
        pass
