"""
api/routes/bulk.py — Bulk vendor CSV upload endpoint.

POST /api/vendors/bulk-upload
  Accepts a multipart CSV file upload, parses via Divyansh's bulk_ingest.py,
  scores each vendor, adds to in-memory store, returns scored results as JSON.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, HTTPException, UploadFile, File
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
        vendors = ingest_csv_bytes(raw_bytes)
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

    return {"uploaded": len(results), "vendors": results}
