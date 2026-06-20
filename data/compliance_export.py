"""
data/compliance_export.py — Format vendor compliance data for exports.

Provides utilities to convert vendor + scored vendor data into CSV/JSON/XLSX-ready formats.
Used by api/routes/reports.py for compliance exports.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import ComplianceSummary, Vendor, ScoredVendor


def format_vendor_for_compliance_export(vendor: Vendor, scored: ScoredVendor) -> dict[str, Any]:
    """
    Format a vendor + its score into a compliance export row (dict).

    Args:
        vendor: The Vendor object (Divyansh's data).
        scored: The ScoredVendor object (Jatin's scoring output).

    Returns:
        Dict with fields suitable for CSV/JSON/XLSX export.
    """
    return {
        "vendor_id": vendor.vendor_id,
        "name": vendor.name,
        "category": vendor.category,
        "contract_start": vendor.contract_start.isoformat(),
        "contract_end": vendor.contract_end.isoformat(),
        "risk_score": scored.risk_score,
        "risk_level": scored.risk_level.value,
        "financial_rating": vendor.financial_rating,
        "data_sensitivity": vendor.data_access.data_sensitivity.value,
        "access_type": vendor.data_access.access_type.value,
        "soc2_type2": "Yes" if vendor.compliance.soc2_type2 else "No",
        "soc2_expiry": vendor.compliance.soc2_expiry.isoformat() if vendor.compliance.soc2_expiry else "",
        "iso27001": "Yes" if vendor.compliance.iso27001 else "No",
        "gdpr_dpa": "Yes" if vendor.compliance.gdpr_dpa else "No",
        "handles_eu_data": "Yes" if vendor.handles_eu_data else "No",
        "under_investigation": "Yes" if vendor.under_investigation else "No",
        "latest_breach_date": (
            max(b.date for b in vendor.breach_history).isoformat()
            if vendor.breach_history
            else ""
        ),
        "top_risk_factor": scored.risk_factors[0] if scored.risk_factors else "",
    }


def build_compliance_summary(
    vendors: list[Vendor], scored_vendors: list[ScoredVendor], today: date
) -> ComplianceSummary:
    """
    Calculate compliance statistics from vendor list.

    Args:
        vendors: List of Vendor objects.
        scored_vendors: Corresponding ScoredVendor objects (same order/count).
        today: Reference date for expiry calculations.

    Returns:
        ComplianceSummary with coverage % and counts.
    """
    if not vendors:
        return ComplianceSummary(
            total_vendors=0,
            soc2_coverage_pct=0.0,
            iso27001_coverage_pct=0.0,
            gdpr_compliance_pct=0.0,
            soc2_expiring_60d=0,
            orphaned_access_count=0,
            under_investigation_count=0,
            recently_breached_count=0,
        )

    total = len(vendors)

    # SOC2 valid: has cert AND (no expiry OR expiry >= today)
    soc2_valid = sum(
        1
        for v in vendors
        if v.compliance.soc2_type2 and (v.compliance.soc2_expiry is None or v.compliance.soc2_expiry >= today)
    )

    # ISO27001 valid: has cert
    iso_valid = sum(1 for v in vendors if v.compliance.iso27001)

    # GDPR compliant: doesn't handle EU data OR has DPA
    gdpr_compliant = sum(1 for v in vendors if not v.handles_eu_data or v.compliance.gdpr_dpa)

    # SOC2 expiring within 60 days
    soc2_expiring = sum(
        1
        for v in vendors
        if v.compliance.soc2_type2
        and v.compliance.soc2_expiry
        and 0 <= (v.compliance.soc2_expiry - today).days <= 60
    )

    # Orphaned access: contract_end in past + data_access still populated
    orphaned = sum(1 for v in vendors if v.contract_end < today and bool(v.data_access.systems))

    # Under investigation
    investigating = sum(1 for v in vendors if v.under_investigation)

    # Recently breached: last breach within 12 months
    recently_breached = sum(
        1
        for v in vendors
        if v.breach_history and (today - max(b.date for b in v.breach_history)).days / 30.44 <= 12
    )

    return ComplianceSummary(
        total_vendors=total,
        soc2_coverage_pct=round(100 * soc2_valid / total, 1) if total else 0,
        iso27001_coverage_pct=round(100 * iso_valid / total, 1) if total else 0,
        gdpr_compliance_pct=round(100 * gdpr_compliant / total, 1) if total else 0,
        soc2_expiring_60d=soc2_expiring,
        orphaned_access_count=orphaned,
        under_investigation_count=investigating,
        recently_breached_count=recently_breached,
    )


def export_to_csv(rows: list[dict[str, Any]]) -> str:
    """
    Convert list of vendor export dicts to CSV string.

    Args:
        rows: List of dicts from format_vendor_for_compliance_export().

    Returns:
        CSV-formatted string (header + rows).
    """
    if not rows:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return output.getvalue()


def export_to_json(rows: list[dict[str, Any]]) -> str:
    """
    Convert list of vendor export dicts to JSON string.

    Args:
        rows: List of dicts from format_vendor_for_compliance_export().

    Returns:
        JSON-formatted string.
    """
    import json
    return json.dumps(rows, indent=2, default=str)
