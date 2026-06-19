#!/usr/bin/env python3
"""
extraction/extract_contract.py — LLM-assisted vendor contract field extractor.

Reads a plaintext contract file, sends it to Claude (claude-opus-4-8) with
structured output enforcement, and returns a dict compatible with
normalize_raw_vendor() from data/normalize.py.

Usage (single file):
    python extraction/extract_contract.py <path/to/contract.txt>

Usage (batch — all files in a directory):
    python extraction/extract_contract.py --batch extraction/sample_contracts/

Usage (round-trip validation — extract then normalize):
    python extraction/extract_contract.py --validate <path/to/contract.txt>

Environment:
    ANTHROPIC_API_KEY  — required
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import anthropic
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

class ContractExtraction(BaseModel):
    """Fields Claude extracts from a vendor contract."""

    vendor_id: Optional[str] = Field(
        None,
        description=(
            "Vendor ID in VND-NNNN format. Derive from the contract reference number "
            "(e.g. MSA-2023-0285 → VND-0285, CSA-2025-0099 → VND-0099). "
            "Use null only if no numeric ID is present in the document."
        ),
    )
    vendor_name: str = Field(
        description="Legal name of the vendor/contractor company."
    )
    category: str = Field(
        description=(
            "Short vendor category, e.g. 'Backup & DR', 'Payment Processing', "
            "'Consulting', 'Analytics', 'IT Integration', 'SaaS'."
        )
    )
    contract_start: Optional[str] = Field(
        None,
        description="Contract effective / start date in ISO 8601 format YYYY-MM-DD. Null if absent.",
    )
    contract_end: Optional[str] = Field(
        None,
        description="Contract expiry / end date in ISO 8601 format YYYY-MM-DD. Null if absent.",
    )
    systems: list[str] = Field(
        default_factory=list,
        description="List of system names the vendor accesses (e.g. ['Database_Primary', 'HR_System']).",
    )
    data_sensitivity: str = Field(
        description=(
            "Data sensitivity level — exactly one of: LOW, MEDIUM, HIGH. "
            "LOW=anonymised/aggregated/no PII. MEDIUM=internal/employee records. "
            "HIGH=PII/financial/payment/cardholder data."
        )
    )
    access_type: str = Field(
        description=(
            "Access level — exactly one of: READ_ONLY, READ_WRITE, NONE. "
            "Map 'read-write', 'rw', 'write' → READ_WRITE; "
            "'read-only', 'read', 'ro' → READ_ONLY."
        )
    )
    soc2_type2: bool = Field(
        description="True only if vendor currently holds a valid SOC 2 Type II cert. 'NOT HELD' or expired → false."
    )
    soc2_expiry: Optional[str] = Field(
        None,
        description="SOC 2 Type II expiry date in ISO 8601 format YYYY-MM-DD, or null.",
    )
    iso27001: bool = Field(
        description="True only if vendor currently holds a valid ISO/IEC 27001 cert. 'NOT HELD' → false."
    )
    gdpr_dpa: bool = Field(
        description=(
            "True ONLY if a GDPR Data Processing Agreement is confirmed as executed/signed. "
            "'Not executed', 'pending', 'open action item', 'NOT APPLICABLE' → false."
        )
    )
    handles_eu_data: bool = Field(
        description=(
            "True if vendor processes personal data of EU data subjects. "
            "Infer from governing law, EU operations mention, or explicit DPA references. "
            "'NOT APPLICABLE' or US-only context → false."
        )
    )
    financial_rating: str = Field(
        description=(
            "Credit/financial rating letter grade: A, A-, B, C, C-, or D. "
            "Extract the letter grade; ignore descriptors like 'prime' or 'speculative'."
        )
    )
    annual_spend: Optional[float] = Field(
        None,
        description=(
            "Annual contract value in USD as a plain number (no currency symbol). "
            "If stated in EUR with a USD equivalent, use the USD equivalent. "
            "Null if not stated."
        ),
    )
    under_investigation: bool = Field(
        description=(
            "True if vendor is flagged UNDER INVESTIGATION — includes active regulatory "
            "investigations, SEC/legal matters, or internal security review flags."
        )
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a precision contract analyst. Extract the specified fields from vendor
contracts exactly as instructed. Return only valid JSON matching the schema —
no preamble, no explanation.

Key rules:
- All dates MUST be ISO 8601 (YYYY-MM-DD). Parse written dates like "1 March 2024" → "2024-03-01".
- vendor_id: derive from the contract reference number by extracting the 4-digit vendor segment.
  E.g. MSA-2023-0285 → "VND-0285", CSA-2025-0099 → "VND-0099", ASA-2024-0001 → "VND-0001".
  Always zero-pad to 4 digits.
- gdpr_dpa = true ONLY when the DPA is confirmed SIGNED/EXECUTED. "Pending", "not executed",
  "not required", "open action item" all → false.
- soc2_type2 / iso27001 = true only when explicitly stated as VALID/HELD. Otherwise false.
- under_investigation = true for ANY of: "UNDER INVESTIGATION", "active investigation",
  "SEC investigation", or internal security review flagging the vendor at elevated risk.
- financial_rating: extract the raw letter (A, A-, B, C, C-, D) only.
- annual_spend: USD number only; if EUR is given with a USD approximation, use the USD figure.
- handles_eu_data: infer from explicit EU data handling statements; "NOT APPLICABLE" → false.
"""


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------

def extract_from_contract(contract_text: str) -> dict:
    """
    Call Claude and return a dict passable to normalize_raw_vendor().

    Raises:
        EnvironmentError: if ANTHROPIC_API_KEY is not set.
        anthropic.APIError: on any API-level failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.parse(
        model="claude-opus-4-8",
        max_tokens=2048,
        thinking={"type": "adaptive"},
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Extract all fields from this vendor contract:\n\n{contract_text}",
            }
        ],
        output_format=ContractExtraction,
    )

    extraction: ContractExtraction = response.parsed

    return {
        "vendor_id": extraction.vendor_id,
        "vendor_name": extraction.vendor_name,   # aliased → name by normalize.py
        "category": extraction.category,
        "contract_start": extraction.contract_start,
        "contract_end": extraction.contract_end,
        "systems": "|".join(extraction.systems),  # normalize.py handles pipe-sep strings
        "data_sensitivity": extraction.data_sensitivity,
        "access_type": extraction.access_type,
        "soc2_type2": extraction.soc2_type2,
        "soc2_expiry": extraction.soc2_expiry,
        "iso27001": extraction.iso27001,
        "gdpr_dpa": extraction.gdpr_dpa,
        "handles_eu_data": extraction.handles_eu_data,
        "financial_rating": extraction.financial_rating,
        "annual_spend": extraction.annual_spend,  # canonical field name in schema.py
        "under_investigation": extraction.under_investigation,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _validate(contract_path: Path) -> None:
    """Extract then run through normalize_raw_vendor for round-trip validation."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from data.normalize import normalize_raw_vendor  # noqa: PLC0415

    text = contract_path.read_text(encoding="utf-8")
    raw = extract_from_contract(text)
    print(f"\n=== Extracted raw dict from {contract_path.name} ===")
    print(json.dumps(raw, indent=2, default=str))

    vendor = normalize_raw_vendor(raw)
    print(f"\n=== Normalized Vendor object ===")
    print(json.dumps(vendor.model_dump(mode="json"), indent=2))


def _batch(directory: Path) -> None:
    """Process every *.txt file in directory, print JSON array of raw dicts."""
    files = sorted(directory.glob("*.txt"))
    if not files:
        print(f"No .txt files found in {directory}", file=sys.stderr)
        sys.exit(1)

    results = []
    for f in files:
        print(f"  Extracting {f.name} ...", file=sys.stderr)
        text = f.read_text(encoding="utf-8")
        raw = extract_from_contract(text)
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

    # Default: single file, print raw dict
    contract_path = Path(args[0])
    if not contract_path.exists():
        print(f"Error: file not found: {contract_path}", file=sys.stderr)
        sys.exit(1)

    text = contract_path.read_text(encoding="utf-8")
    result = extract_from_contract(text)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
