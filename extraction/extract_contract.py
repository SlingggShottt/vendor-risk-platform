#!/usr/bin/env python3
"""
extraction/extract_contract.py — LLM-assisted vendor contract field extractor.

Uses Groq (llama-3.3-70b-versatile, free tier) with JSON-mode output to extract
structured vendor fields from plaintext or PDF contract documents.

Usage (single file — .txt or .pdf):
    python extraction/extract_contract.py <path/to/contract.txt>
    python extraction/extract_contract.py <path/to/contract.pdf>

Usage (batch — all .txt and .pdf files in a directory):
    python extraction/extract_contract.py --batch extraction/sample_contracts/

Usage (round-trip validation — extract then normalize):
    python extraction/extract_contract.py --validate <path/to/contract.txt|.pdf>

Environment:
    GROQ_API_KEY  — required (free key at https://console.groq.com, no credit card)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from groq import Groq
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

class ContractExtraction(BaseModel):
    vendor_id: Optional[str] = Field(None)
    vendor_name: str
    category: str
    contract_start: Optional[str] = Field(None)
    contract_end: Optional[str] = Field(None)
    systems: list[str] = Field(default_factory=list)
    data_sensitivity: str
    access_type: str
    soc2_type2: bool
    soc2_expiry: Optional[str] = Field(None)
    iso27001: bool
    gdpr_dpa: bool
    handles_eu_data: bool
    financial_rating: str
    annual_spend: Optional[float] = Field(None)
    under_investigation: bool


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a precision contract analyst. Extract vendor fields from the contract and return ONLY a valid JSON object — no explanation, no markdown, no preamble.

Required JSON keys and rules:
- vendor_id: derive from the contract reference number's 4-digit segment (MSA-2023-0285 → "VND-0285"). Null if absent.
- vendor_name: legal name of the vendor company
- category: short category e.g. "Backup & DR", "Payment Processing", "Consulting"
- contract_start / contract_end: ISO 8601 dates YYYY-MM-DD, null if absent
- systems: array of system names the vendor accesses
- data_sensitivity: exactly one of LOW / MEDIUM / HIGH
- access_type: exactly one of READ_ONLY / READ_WRITE / NONE
- soc2_type2: true only if vendor holds a VALID SOC 2 Type II cert (false if NOT HELD or expired)
- soc2_expiry: expiry date YYYY-MM-DD or null
- iso27001: true only if vendor holds a VALID ISO 27001 cert
- gdpr_dpa: true ONLY if DPA is confirmed SIGNED/EXECUTED ("Pending" / "not executed" → false)
- handles_eu_data: true if vendor processes EU personal data ("NOT APPLICABLE" → false)
- financial_rating: letter grade only — A, A-, B, C, C-, or D
- annual_spend: USD number only (null if not stated)
- under_investigation: true if vendor is flagged UNDER INVESTIGATION or active investigation"""


# ---------------------------------------------------------------------------
# PDF support
# ---------------------------------------------------------------------------

def _read_contract(path: Path) -> str:
    """Read contract text from a .txt or .pdf file."""
    if path.suffix.lower() == ".pdf":
        from extraction.parse_pdf import extract_text_from_pdf
        return extract_text_from_pdf(path)
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_from_contract(contract_text: str) -> dict:
    """
    Call Groq and return a dict passable to normalize_raw_vendor().

    Args:
        contract_text: Raw contract text (already extracted from PDF if needed).

    Raises:
        EnvironmentError: if GROQ_API_KEY is not set.
        Exception: on any API or parsing failure.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY environment variable is not set")

    client = Groq(api_key=api_key)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Extract all fields from this vendor contract:\n\n{contract_text}"},
        ],
        temperature=0,
    )

    raw_json = json.loads(response.choices[0].message.content)
    extraction = ContractExtraction(**raw_json)

    return {
        "vendor_id":           extraction.vendor_id,
        "vendor_name":         extraction.vendor_name,
        "category":            extraction.category,
        "contract_start":      extraction.contract_start,
        "contract_end":        extraction.contract_end,
        "systems":             "|".join(extraction.systems),
        "data_sensitivity":    extraction.data_sensitivity,
        "access_type":         extraction.access_type,
        "soc2_type2":          extraction.soc2_type2,
        "soc2_expiry":         extraction.soc2_expiry,
        "iso27001":            extraction.iso27001,
        "gdpr_dpa":            extraction.gdpr_dpa,
        "handles_eu_data":     extraction.handles_eu_data,
        "financial_rating":    extraction.financial_rating,
        "annual_spend":        extraction.annual_spend,
        "under_investigation": extraction.under_investigation,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _validate(contract_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from data.normalize import normalize_raw_vendor

    text = _read_contract(contract_path)
    raw = extract_from_contract(text)
    print(f"\n=== Extracted raw dict from {contract_path.name} ===")
    print(json.dumps(raw, indent=2, default=str))
    vendor = normalize_raw_vendor(raw)
    print(f"\n=== Normalized Vendor ===")
    print(json.dumps(vendor.model_dump(mode="json"), indent=2))


def _batch(directory: Path) -> None:
    files = sorted(list(directory.glob("*.txt")) + list(directory.glob("*.pdf")))
    if not files:
        print(f"No .txt or .pdf files found in {directory}", file=sys.stderr)
        sys.exit(1)
    results = []
    for f in files:
        print(f"  Extracting {f.name} ...", file=sys.stderr)
        raw = extract_from_contract(_read_contract(f))
        raw["_source_file"] = f.name
        results.append(raw)
    print(json.dumps(results, indent=2, default=str))


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    if args[0] == "--batch":
        if len(args) < 2:
            print("Usage: extract_contract.py --batch <directory>", file=sys.stderr)
            sys.exit(1)
        _batch(Path(args[1]))
        return

    if args[0] == "--validate":
        if len(args) < 2:
            print("Usage: extract_contract.py --validate <file.txt|.pdf>", file=sys.stderr)
            sys.exit(1)
        _validate(Path(args[1]))
        return

    contract_path = Path(args[0])
    if not contract_path.exists():
        print(f"Error: file not found: {contract_path}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(extract_from_contract(_read_contract(contract_path)),
                     indent=2, default=str))


if __name__ == "__main__":
    main()
