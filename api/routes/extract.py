"""
api/routes/extract.py — Contract extraction endpoints.

POST /api/extract
  Accepts {"contract_text": "..."}, calls Divyansh's extract_from_contract() when
  ANTHROPIC_API_KEY is set, otherwise falls back to demo mode (registry store lookup
  by vendor ref ID parsed from the contract text).

GET /api/sample-contracts
  Lists available sample contract files with display names.

GET /api/sample-contracts/{name}
  Returns the text content of a named sample contract.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data.normalize import normalize_raw_vendor
from scoring.risk_engine import score_vendor
from common.schema import FIXTURE_VENDORS

router = APIRouter(tags=["extract"])

_SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "extraction" / "sample_contracts"

_SAMPLES = [
    {
        "id": "VND-0001",
        "filename": "contract_VND0001_cleanco.txt",
        "display": "CleanCo Analytics (LOW risk)",
    },
    {
        "id": "VND-0099",
        "filename": "contract_VND0099_shadyconsulting.txt",
        "display": "ShadyConsulting (CRITICAL – under investigation)",
    },
    {
        "id": "VND-0200",
        "filename": "contract_VND0200_legacyintegration.txt",
        "display": "LegacyIntegration Corp (MEDIUM – expired contract)",
    },
    {
        "id": "VND-0285",
        "filename": "contract_VND0285_cyberbackup.txt",
        "display": "CyberBackup Solutions (CRITICAL – breach + HIGH access)",
    },
    {
        "id": "VND-0420",
        "filename": "contract_VND0420_europay.txt",
        "display": "EuroPay Processing (HIGH – missing GDPR DPA)",
    },
]


class ExtractRequest(BaseModel):
    contract_text: str


def _get_store() -> dict:
    from api.main import app
    return app.state.store


def _get_today() -> date:
    from api.main import app
    return app.state.today


def _parse_vendor_id(text: str) -> str | None:
    """Parse a VND-NNNN vendor ID from contract text."""
    m = re.search(r'\bVND-(\d{4})\b', text, re.IGNORECASE)
    if m:
        return f"VND-{m.group(1)}"
    # Contract reference numbers like ASA-2024-0001, MSA-2023-0285, VSA-2024-0420
    m = re.search(r'\b[A-Z]{2,4}-\d{4}-(\d{4})\b', text)
    if m:
        return f"VND-{m.group(1)}"
    return None


@router.get("/api/sample-contracts")
def list_sample_contracts():
    return _SAMPLES


@router.get("/api/sample-contracts/{name}")
def get_sample_contract(name: str):
    allowed = {s["filename"] for s in _SAMPLES}
    if name not in allowed:
        raise HTTPException(status_code=404, detail="Sample not found")
    path = _SAMPLE_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return {"filename": name, "text": path.read_text(encoding="utf-8")}


@router.post("/api/extract")
def extract_contract(req: ExtractRequest):
    contract_text = req.contract_text.strip()
    if not contract_text:
        raise HTTPException(status_code=422, detail="contract_text is required")

    today = _get_today()
    live_error: str | None = None

    # ── Attempt live AI extraction ─────────────────────────────────────────────
    try:
        from extraction.extract_contract import extract_from_contract
        raw = extract_from_contract(contract_text)
        vendor = normalize_raw_vendor(raw)
        scored = score_vendor(vendor, today)
        return {
            "mode": "live",
            "message": None,
            "extracted": raw,
            "vendor": vendor.model_dump(mode="json"),
            "scored": scored.model_dump(mode="json"),
        }
    except EnvironmentError as e:
        live_error = f"GROQ_API_KEY not set ({e})"
    except ImportError:
        live_error = "groq package not installed"
    except Exception as e:
        live_error = f"Extraction failed: {e}"

    # ── Demo fallback: look up parsed vendor ID in store or fixtures ──────────
    vendor_id = _parse_vendor_id(contract_text)
    if vendor_id:
        # 1. Check in-memory store (generated registry vendors)
        entry = _get_store().get(vendor_id)
        if entry:
            v = entry["vendor"]
            sv = entry["scored"]
        else:
            # 2. Fall back to fixture vendors (the 5 sample contracts use VND-000X IDs)
            fixture = next((f for f in FIXTURE_VENDORS if f.vendor_id == vendor_id), None)
            if fixture:
                v = fixture
                sv = score_vendor(fixture, today)
            else:
                v = sv = None

        if v is not None:
            extracted = {
                "vendor_id": v.vendor_id,
                "vendor_name": v.name,
                "category": v.category,
                "contract_start": str(v.contract_start),
                "contract_end": str(v.contract_end),
                "systems": v.data_access.systems,
                "data_sensitivity": v.data_access.data_sensitivity.value,
                "access_type": v.data_access.access_type.value,
                "soc2_type2": v.compliance.soc2_type2,
                "soc2_expiry": str(v.compliance.soc2_expiry) if v.compliance.soc2_expiry else None,
                "iso27001": v.compliance.iso27001,
                "gdpr_dpa": v.compliance.gdpr_dpa,
                "handles_eu_data": v.handles_eu_data,
                "financial_rating": v.financial_rating,
                "annual_spend": v.annual_spend,
                "under_investigation": v.under_investigation,
            }
            return {
                "mode": "demo",
                "message": (
                    f"Demo mode ({live_error}). "
                    f"Showing pre-scored fixture data for {vendor_id}."
                ),
                "extracted": extracted,
                "vendor": v.model_dump(mode="json"),
                "scored": sv.model_dump(mode="json"),
            }

    raise HTTPException(
        status_code=503,
        detail=(
            f"Cannot extract: {live_error}. "
            "No recognisable vendor reference found in the contract text for demo fallback."
        ),
    )
