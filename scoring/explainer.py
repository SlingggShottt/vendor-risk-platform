"""
scoring/explainer.py — Rule-by-rule risk score breakdown for audit committees.

explain_risk() returns a structured dict with:
  - contributing_factors: each fired rule with weight, impact, description
  - remediation_actions: specific, time-bound actions per fired rule
  - audit_trail: last-change note from the audit log
  - eval_passed: sanity flag (always True if at least one factor fired or score < 40)

Called from GET /api/vendors/{id}/risk-explainer.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import DataSensitivity, ScoredVendor, Vendor
from scoring.rules import (
    RuleResult,
    check_breach_recency,
    check_certification_status,
    check_contract_status,
    check_data_access_scope,
    check_financial_rating,
    check_gdpr_dpa,
    floor_breach_high_access,
    floor_under_investigation,
)
from scoring.risk_engine import WEIGHTS


def explain_risk(
    vendor: Vendor,
    scored: ScoredVendor,
    today: Optional[date] = None,
    last_audit_note: Optional[str] = None,
) -> dict:
    """Return structured rule-by-rule explanation of a vendor's risk score."""
    if today is None:
        today = date.today()

    contributing_factors: list[dict] = []
    remediation_actions: list[str] = []

    # ── Hard floors (checked first — these override everything) ───────────────
    inv_hit, inv_desc = floor_under_investigation(vendor)
    breach_floor_hit, breach_floor_desc = floor_breach_high_access(vendor, today)

    if inv_hit:
        contributing_factors.append({
            "rule_name": "Under Investigation (Hard Floor)",
            "weight_pct": 100,
            "impact": "CRITICAL",
            "contribution_pts": 95.0,
            "description": inv_desc,
        })
        remediation_actions.append(
            f"Escalate {vendor.name} to Legal and CISO immediately; suspend vendor access pending investigation outcome"
        )
        remediation_actions.append(
            "Document all data shared with this vendor for potential breach notification obligations"
        )

    if breach_floor_hit:
        contributing_factors.append({
            "rule_name": "Breach + HIGH Sensitivity Access (Hard Floor)",
            "weight_pct": 100,
            "impact": "CRITICAL",
            "contribution_pts": 85.0,
            "description": breach_floor_desc,
        })
        remediation_actions.append(
            f"Require post-incident report and remediation plan from {vendor.name} within 30 days"
        )
        remediation_actions.append(
            "Temporarily restrict HIGH-sensitivity system access pending remediation confirmation"
        )

    # ── Weighted rule contributions ────────────────────────────────────────────
    rule_specs: list[tuple[str, str, RuleResult]] = [
        ("Breach Recency",      "breach",    check_breach_recency(vendor, today)),
        ("Certification Status","cert",      check_certification_status(vendor, today)),
        ("Contract Status",     "contract",  check_contract_status(vendor, today)),
        ("Financial Rating",    "financial", check_financial_rating(vendor)),
        ("Data Access Scope",   "access",    check_data_access_scope(vendor)),
        ("GDPR DPA",            "gdpr",      check_gdpr_dpa(vendor)),
    ]

    for rule_name, weight_key, result in rule_specs:
        weight = WEIGHTS[weight_key]
        contribution = round(weight * result.raw_score, 1)
        impact = _impact_label(contribution)

        if result.triggered:
            for desc in result.descriptions:
                contributing_factors.append({
                    "rule_name": rule_name,
                    "weight_pct": int(weight),
                    "impact": impact,
                    "contribution_pts": contribution,
                    "description": desc,
                })
            remediation_actions.extend(_remediation_for(rule_name, vendor, result, today))

    if not remediation_actions:
        remediation_actions.append(
            "No immediate remediation required — continue standard quarterly review cycle"
        )

    audit_note = last_audit_note or f"Last scored by system on {today.isoformat()}"

    return {
        "vendor_id": scored.vendor_id,
        "vendor_name": vendor.name,
        "risk_score": scored.risk_score,
        "risk_level": scored.risk_level.value,
        "contributing_factors": contributing_factors,
        "remediation_actions": remediation_actions,
        "audit_trail": audit_note,
        "eval_passed": bool(contributing_factors) or scored.risk_score < 40,
    }


def _impact_label(contribution_pts: float) -> str:
    if contribution_pts >= 20:
        return "CRITICAL"
    if contribution_pts >= 10:
        return "HIGH"
    if contribution_pts >= 5:
        return "MEDIUM"
    return "LOW"


def _remediation_for(
    rule_name: str,
    vendor: Vendor,
    result: RuleResult,
    today: date,
) -> list[str]:
    actions: list[str] = []

    if rule_name == "Breach Recency":
        actions.append(
            f"Request post-incident root-cause report from {vendor.name} detailing security improvements made since the breach"
        )
    elif rule_name == "Certification Status":
        if not vendor.compliance.soc2_type2:
            actions.append(
                f"Require {vendor.name} to obtain SOC 2 Type II certification within 90 days or reduce data access scope to LOW sensitivity"
            )
        elif vendor.compliance.soc2_expiry and (vendor.compliance.soc2_expiry - today).days < 60:
            days_left = (vendor.compliance.soc2_expiry - today).days
            actions.append(
                f"Follow up with {vendor.name} on SOC 2 renewal — certification lapses in {days_left} days ({vendor.compliance.soc2_expiry})"
            )
        if not vendor.compliance.iso27001:
            actions.append(
                f"Request ISO 27001 certification roadmap from {vendor.name}; set 12-month target"
            )
    elif rule_name == "Contract Status":
        actions.append(
            f"Immediately renew or terminate contract with {vendor.name}; revoke all system access until contract is in place"
        )
    elif rule_name == "Financial Rating":
        actions.append(
            f"Conduct vendor viability review for {vendor.name}; establish contingency plan for service continuity if vendor fails"
        )
    elif rule_name == "Data Access Scope":
        actions.append(
            f"Review whether {vendor.name} requires read/write access; downgrade to read-only where technically feasible"
        )
    elif rule_name == "GDPR DPA":
        actions.append(
            f"Obtain signed GDPR Data Processing Agreement from {vendor.name} before next scheduled data transfer"
        )

    return actions
