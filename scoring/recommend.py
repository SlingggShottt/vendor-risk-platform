"""
scoring/recommend.py — Generate recommendation strings from risk_level + context.

Recommendations are action-oriented: who should act, on what timeline, what action.
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import RiskLevel


def generate_recommendation(
    vendor_name: str,
    risk_level: RiskLevel,
    risk_factors: list[str],
) -> str:
    first_factor = risk_factors[0] if risk_factors else "multiple risk factors"

    if risk_level == RiskLevel.CRITICAL:
        return (
            f"IMMEDIATE ACTION REQUIRED: Escalate {vendor_name} to CISO within 24 hours. "
            "Suspend non-essential data sharing pending investigation. "
            "Require a formal remediation plan within 48 hours. "
            f"Primary driver: {first_factor}"
        )

    if risk_level == RiskLevel.HIGH:
        return (
            f"HIGH PRIORITY: Schedule remediation review with {vendor_name} within 2 weeks. "
            "Restrict access to minimum necessary scope until open issues are resolved. "
            "Escalate to department head if no remediation plan is provided within 10 business days. "
            f"Key issue: {first_factor}"
        )

    if risk_level == RiskLevel.MEDIUM:
        return (
            f"MONITOR: Request updated compliance documentation from {vendor_name} within 30 days. "
            "Include in next quarterly vendor review. "
            "No immediate access restriction required unless issues escalate. "
            f"Focus area: {first_factor}"
        )

    return (
        f"{vendor_name} meets current risk thresholds. "
        "Conduct standard annual vendor review as scheduled. "
        "No immediate action required."
    )
