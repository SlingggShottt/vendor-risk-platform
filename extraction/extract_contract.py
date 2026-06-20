#!/usr/bin/env python3
"""
extraction/extract_contract.py — LLM-assisted vendor contract field extractor.

Uses Google Gemini (gemini-2.0-flash, free tier) with JSON-mode output to extract
structured vendor fields from plaintext contract documents.

Usage (single file):
    python extraction/extract_contract.py <path/to/contract.txt>

Usage (batch — all files in a directory):
    python extraction/extract_contract.py --batch extraction/sample_contracts/

Usage (round-trip validation — extract then normalize):
    python extraction/extract_contract.py --validate <path/to/contract.txt>

Environment:
    GEMINI_API_KEY  — required (free key at https://aistudio.google.com/apikey)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured output schema — Gemini fills every field as JSON
# ---------------------------------------------------------------------------

class ContractExtraction(BaseModel):
    vendor_id: Optional[str] = Field(
        None,
        description=(
            "Vendor ID in VND-NNNN format. Derive from the contract reference number "
            "(e.g. MSA-2023-0285 → VND-0285, CSA-2025-0099 → VND-0099). "
            "Null only if no numeric ID present."
        ),
    )
    vendor_name: str = Field(description="Legal name of the vendor/contractor company.")
    category: str = Field(
        description="Short vendor category e.g. 'Backup & DR', 'Payment Processing', 'Consulting', 'Analytics'."
    )
    contract_start: Optional[str] = Field(
        None, description="Contract effective/start date in ISO 8601 format YYYY-MM-DD. Null if absent."
    )
    contract_end: Optional[str] = Field(
        None, description="Contract expiry/end date in ISO 8601 format YYYY-MM-DD. Null if absent."
    )
    systems: list[str] = Field(
        default_factory=list,
        description="List of system names the vendor accesses e.g. ['Database_Primary', 'HR_System'].",
    )
    data_sensitivity: str = Field(
        description="Exactly one of: LOW, MEDIUM, HIGH. LOW=anonymised/no PII. MEDIUM=internal records. HIGH=PII/financial/payment data."
    )
    access_type: str = Field(
        description="Exactly one of: READ_ONLY, READ_WRITE, NONE. Map 'read-write'/'rw'/'write' → READ_WRITE; 'read-only'/'read'/'ro' → READ_ONLY."
    )
    soc2_type2: bool = Field(
        description="True only if vendor currently holds a valid SOC 2 Type II cert. 'NOT HELD' or expired → false."
    )
    soc2_expiry: Optional[str] = Field(
        None, description="SOC 2 Type II expiry date YYYY-MM-DD, or null."
    )
    iso27001: bool = Field(
        description="True only if vendor currently holds a valid ISO/IEC 27001 cert. 'NOT HELD' → false."
    )
    gdpr_dpa: bool = Field(
        description="True ONLY if GDPR DPA is confirmed SIGNED/EXECUTED. 'Pending', 'not executed', 'not required' → false."
    )
    handles_eu_data: bool = Field(
        description="True if vendor processes personal data of EU data subjects. 'NOT APPLICABLE' or US-only → false."
    )
    financial_rating: str = Field(
        description="Credit/financial rating letter grade: A, A-, B, C, C-, or D. Extract letter grade only."
    )
    annual_spend: Optional[float] = Field(
        None,
        description="Annual contract value in USD as a plain number. If EUR with USD equivalent given, use the USD figure. Null if not stated.",
    )
    under_investigation: bool = Field(
        description="True if vendor is flagged UNDER INVESTIGATION — includes active regulatory/legal/security-review flags."
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a precision contract analyst. Extract the specified fields from the vendor contract below.

Return ONLY a valid JSON object with these exact keys. No explanation, no preamble.

Key rules:
- All dates MUST be ISO 8601 (YYYY-MM-DD). Parse written dates like "1 March 2024" → "2024-03-01".
- vendor_id: derive from the contract reference number by extracting the 4-digit vendor segment.
  E.g. MSA-2023-0285 → "VND-0285", CSA-2025-0099 → "VND-0099", ASA-2024-0001 → "VND-0001". Zero-pad to 4 digits.
- gdpr_dpa = true ONLY when DPA is confirmed SIGNED/EXECUTED. "Pending", "not executed", "not required", "open action item" → false.
- soc2_type2 / iso27001 = true only when explicitly VALID/HELD. Otherwise false.
- under_investigation = true for ANY of: "UNDER INVESTIGATION", "active investigation", "SEC investigation", internal security review flagging the vendor.
- financial_rating: extract the raw letter (A, A-, B, C, C-, D) only.
- annual_spend: USD number only; if EUR given with USD approximation, use the USD figure.
- handles_eu_data: "NOT APPLICABLE" or US-only context → false.

Required JSON keys:
vendor_id, vendor_name, category, contract_start, contract_end, systems (array),
data_sensitivity, access_type, soc2_type2 (bool), soc2_expiry, iso27001 (bool),
gdpr_dpa (bool), handles_eu_data (bool), financial_rating, annual_spend, under_investigation (bool)
"""


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_from_contract(contract_text: str) -> dict:
    """
    Call Gemini and return a dict passable to normalize_raw_vendor().

    Raises:
        EnvironmentError: if GEMINI_API_KEY is not set.
        Exception: on any API-level failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{_SYSTEM_PROMPT}\n\nExtract all fields from this vendor contract:\n\n{contract_text}",
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    raw_json = json.loads(response.text)
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

    text = contract_path.read_text(encoding="utf-8")
    raw = extract_from_contract(text)
    print(f"\n=== Extracted raw dict from {contract_path.name} ===")
    print(json.dumps(raw, indent=2, default=str))
    vendor = normalize_raw_vendor(raw)
    print(f"\n=== Normalized Vendor ===")
    print(json.dumps(vendor.model_dump(mode="json"), indent=2))


def _batch(directory: Path) -> None:
    files = sorted(directory.glob("*.txt"))
    if not files:
        print(f"No .txt files found in {directory}", file=sys.stderr)
        sys.exit(1)
    results = []
    for f in files:
        print(f"  Extracting {f.name} ...", file=sys.stderr)
        raw = extract_from_contract(f.read_text(encoding="utf-8"))
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
            print("Usage: extract_contract.py --validate <file.txt>", file=sys.stderr)
            sys.exit(1)
        _validate(Path(args[1]))
        return

    contract_path = Path(args[0])
    if not contract_path.exists():
        print(f"Error: file not found: {contract_path}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(extract_from_contract(contract_path.read_text(encoding="utf-8")),
                     indent=2, default=str))


if __name__ == "__main__":
    main()
