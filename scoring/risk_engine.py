"""
scoring/risk_engine.py — Core risk scoring engine.

Applies PRD.md §5 rubric:
  1. Hard floors (CRITICAL override regardless of weighted score)
  2. Weighted scoring (6 factors, weights sum to 100)
  3. Risk level from thresholds + anomaly type selection
  4. Recommendation text

Formula is intentionally identical to generate_vendors.py::compute_label so that
eval/evaluate.py can achieve high recall against vendor_labels.csv ground truth.

Changing weights here requires logging before/after recall in memory.md.
"""

from __future__ import annotations

from datetime import date

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import (
    AnomalyType,
    DataSensitivity,
    RiskLevel,
    Severity,
    ScoredVendor,
    Vendor,
)
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
from scoring.recommend import generate_recommendation

# Factor weights (must sum to 100)
WEIGHTS: dict[str, float] = {
    "breach":    35.0,
    "cert":      25.0,
    "contract":  15.0,
    "financial": 10.0,
    "access":    10.0,
    "gdpr":       5.0,
}


def score_vendor(vendor: Vendor, today: date | None = None) -> ScoredVendor:
    """Score a single Vendor and return a ScoredVendor."""
    if today is None:
        today = date.today()

    # ── Hard floor: under investigation ───────────────────────────────────────
    inv_hit, inv_desc = floor_under_investigation(vendor)
    if inv_hit:
        factors = [inv_desc]
        rec = generate_recommendation(vendor.name, RiskLevel.CRITICAL, factors)
        return ScoredVendor(
            vendor_id=vendor.vendor_id,
            risk_score=95.0,
            risk_level=RiskLevel.CRITICAL,
            risk_factors=factors,
            recommendation=rec,
            anomaly_type=AnomalyType.VENDOR_UNDER_INVESTIGATION,
            severity=Severity.CRITICAL,
        )

    # ── Check the other hard floor (breach + HIGH) — may override level later ─
    breach_floor_hit, breach_floor_desc = floor_breach_high_access(vendor, today)

    # ── Weighted scoring ───────────────────────────────────────────────────────
    breach_r    = check_breach_recency(vendor, today)
    cert_r      = check_certification_status(vendor, today)
    contract_r  = check_contract_status(vendor, today)
    financial_r = check_financial_rating(vendor)
    access_r    = check_data_access_scope(vendor)
    gdpr_r      = check_gdpr_dpa(vendor)

    score = (
        WEIGHTS["breach"]    * breach_r.raw_score +
        WEIGHTS["cert"]      * cert_r.raw_score +
        WEIGHTS["contract"]  * contract_r.raw_score +
        WEIGHTS["financial"] * financial_r.raw_score +
        WEIGHTS["access"]    * access_r.raw_score +
        WEIGHTS["gdpr"]      * gdpr_r.raw_score
    )
    score = min(score, 100.0)

    # ── Collect human-readable risk factors ───────────────────────────────────
    risk_factors: list[str] = []
    for result in (breach_r, cert_r, contract_r, financial_r, access_r, gdpr_r):
        if result.triggered:
            risk_factors.extend(result.descriptions)

    # ── Apply breach+HIGH hard floor if triggered ──────────────────────────────
    if breach_floor_hit:
        # Prepend the hard-floor description, keep other factors as context
        risk_factors = [breach_floor_desc] + [f for f in risk_factors if f != breach_floor_desc]
        score = max(score, 85.0)
        risk_level = RiskLevel.CRITICAL
        anomaly_type = AnomalyType.BREACHED_VENDOR_HIGH_ACCESS
        severity = Severity.CRITICAL
    else:
        risk_level, anomaly_type, severity = _classify(score, vendor, today, cert_r, breach_r)

    if not risk_factors:
        risk_factors = ["No significant risk factors identified"]

    rec = generate_recommendation(vendor.name, risk_level, risk_factors)

    return ScoredVendor(
        vendor_id=vendor.vendor_id,
        risk_score=round(score, 1),
        risk_level=risk_level,
        risk_factors=risk_factors,
        recommendation=rec,
        anomaly_type=anomaly_type,
        severity=severity,
    )


def _classify(
    score: float,
    vendor: Vendor,
    today: date,
    cert_r: RuleResult,
    breach_r: RuleResult,
) -> tuple[RiskLevel, AnomalyType, Severity]:
    """Map numeric score to risk level + most-specific anomaly type."""
    if score >= 80:
        return RiskLevel.CRITICAL, AnomalyType.HIGH_RISK_SCORE, Severity.CRITICAL

    if score >= 65:
        return RiskLevel.HIGH, AnomalyType.ELEVATED_RISK_VENDOR, Severity.HIGH

    if score >= 40:
        # Pick the most specific MEDIUM anomaly (mirrors compute_label priority)
        contract_expired = vendor.contract_end < today
        has_active = bool(vendor.data_access.systems)
        has_breach = bool(vendor.breach_history)

        if cert_r.triggered:
            anomaly = AnomalyType.EXPIRED_CERTIFICATION
        elif has_breach:
            anomaly = AnomalyType.RECENTLY_BREACHED_VENDOR
        elif contract_expired and has_active:
            anomaly = AnomalyType.CONTRACT_EXPIRED_ACTIVE_ACCESS
        else:
            anomaly = AnomalyType.ELEVATED_RISK_VENDOR
        return RiskLevel.MEDIUM, anomaly, Severity.MEDIUM

    return RiskLevel.LOW, AnomalyType.NONE, Severity.LOW


def explain_vendor_score(vendor: Vendor, today: date | None = None) -> dict:
    """
    Return a full rule-by-rule breakdown for a single vendor.
    Used by GET /api/vendors/{id}/risk-explainer.
    """
    if today is None:
        today = date.today()

    hard_floors = []

    inv_hit, inv_desc = floor_under_investigation(vendor)
    if inv_hit:
        hard_floors.append({"floor": "under_investigation", "description": inv_desc})

    breach_floor_hit, breach_floor_desc = floor_breach_high_access(vendor, today)
    if breach_floor_hit:
        hard_floors.append({"floor": "breach_high_access", "description": breach_floor_desc})

    rule_results = {
        "breach":    check_breach_recency(vendor, today),
        "cert":      check_certification_status(vendor, today),
        "contract":  check_contract_status(vendor, today),
        "financial": check_financial_rating(vendor),
        "access":    check_data_access_scope(vendor),
        "gdpr":      check_gdpr_dpa(vendor),
    }

    contributing_factors = []
    for rule_name, result in rule_results.items():
        weight = WEIGHTS[rule_name]
        contribution = round(weight * result.raw_score, 2)
        contributing_factors.append({
            "rule_name": rule_name,
            "weight_pct": weight,
            "raw_score": round(result.raw_score, 3),
            "contribution": contribution,
            "triggered": result.triggered,
            "descriptions": result.descriptions,
        })

    sv = score_vendor(vendor, today)

    return {
        "vendor_id": vendor.vendor_id,
        "risk_score": sv.risk_score,
        "risk_level": sv.risk_level.value,
        "anomaly_type": sv.anomaly_type.value,
        "hard_floors_triggered": hard_floors,
        "contributing_factors": contributing_factors,
        "recommendation": sv.recommendation,
        "remediation_actions": sv.risk_factors,
    }


def score_vendors(vendors: list[Vendor], today: date | None = None) -> list[ScoredVendor]:
    """Batch-score a list of vendors."""
    if today is None:
        today = date.today()
    return [score_vendor(v, today) for v in vendors]
