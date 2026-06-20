"""
api/routes/extract.py — Contract extraction endpoints.

POST /api/extract  (multipart/form-data)
  Fields (at least one required):
    contract_text  — raw contract text
    file           — PDF or .txt file upload
  Falls back to demo mode when GROQ_API_KEY is not set.

GET /api/sample-contracts
  Lists available sample contract files with display names.

GET /api/sample-contracts/{name}
  Returns the text content of a named sample contract.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

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


def _get_store() -> dict:
    from api.main import app
    return app.state.store


def _get_today() -> date:
    from api.main import app
    return app.state.today


def _parse_vendor_id(text: str) -> str | None:
    m = re.search(r'\bVND-(\d{4})\b', text, re.IGNORECASE)
    if m:
        return f"VND-{m.group(1)}"
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
async def extract_contract(
    contract_text: str = Form(default=None),
    file: UploadFile = File(default=None),
):
    # ── Resolve input: file takes priority over pasted text ──────────────────
    source_name: str | None = None

    if file is not None and file.filename:
        raw_bytes = await file.read()
        suffix = Path(file.filename).suffix.lower()
        source_name = file.filename

        if suffix == ".pdf":
            # Write to a temp file so pdfplumber can open it
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            try:
                tmp.write(raw_bytes)
                tmp.flush()
                tmp.close()
                from extraction.parse_pdf import extract_text_from_pdf
                contract_text = extract_text_from_pdf(tmp.name)
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"PDF extraction failed: {e}")
            finally:
                os.unlink(tmp.name)
        else:
            contract_text = raw_bytes.decode("utf-8", errors="replace")

    if not contract_text or not contract_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Provide contract_text (form field) or upload a PDF / text file.",
        )

    contract_text = contract_text.strip()
    today = _get_today()
    live_error: str | None = None

    # ── Attempt live Groq extraction ──────────────────────────────────────────
    try:
        from extraction.extract_contract import extract_from_contract
        raw = extract_from_contract(contract_text)
        vendor = normalize_raw_vendor(raw)
        scored = score_vendor(vendor, today)
        return {
            "mode": "live",
            "source": source_name,
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

    # ── Demo fallback: look up vendor ID from contract text ───────────────────
    vendor_id = _parse_vendor_id(contract_text)
    if vendor_id:
        entry = _get_store().get(vendor_id)
        if entry:
            v = entry["vendor"]
            sv = entry["scored"]
        else:
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
                "source": source_name,
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
            "No recognisable vendor reference found in the contract for demo fallback."
        ),
    )
