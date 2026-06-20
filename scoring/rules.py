"""
scoring/rules.py — Atomic rule checks for the risk engine.

Each function returns a RuleResult:
  triggered     — whether this rule fired
  raw_score     — 0.0-N.N contribution before the factor weight is applied
                  (matches exactly the partial-score logic in generate_vendors.py compute_label)
  descriptions  — human-readable strings for risk_factors list (auditor-ready)

Hard-floor checks return (bool, str) — they bypass scoring entirely when True.

Scoring formula is locked to PRD.md §5 / generate_vendors.py compute_label.
Do NOT change weights here without logging the change in memory.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import AccessType, DataSensitivity, Vendor

# ── Shared lookup tables (mirrors generate_vendors.py constants) ───────────────

_RATING_PENALTY: dict[str, float] = {
    "A+": 0.0, "A": 0.0, "A-": 0.1,
    "B+": 0.15, "B": 0.2, "B-": 0.3,
    "C+": 0.5, "C": 0.6, "C-": 0.7,
    "D": 1.0,
}

_SENSITIVITY_MULT: dict[str, float] = {
    "HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3,
}


@dataclass
class RuleResult:
    triggered: bool
    raw_score: float               # partial score before weight multiplication
    descriptions: list[str] = field(default_factory=list)


# ── Hard floors (return early from engine, no weighted scoring) ───────────────

def floor_under_investigation(vendor: Vendor) -> tuple[bool, str]:
    """CRITICAL floor: vendor flagged under active investigation."""
    if vendor.under_investigation:
        return True, (
            "Vendor is under active regulatory or security investigation: "
            "mandatory CRITICAL escalation regardless of other factors"
        )
    return False, ""


def floor_breach_high_access(vendor: Vendor, today: date) -> tuple[bool, str]:
    """CRITICAL floor: breach within 12 months AND HIGH data sensitivity."""
    if not vendor.breach_history:
        return False, ""
    most_recent = max(b.date for b in vendor.breach_history)
    months_ago = (today - most_recent).days / 30.44
    # Use < 12.1 (not <= 12) to absorb the 30.44-day-per-month approximation at the
    # exact 12-month boundary (366 days in a non-leap year = 12.025 months).
    if months_ago < 12.1 and vendor.data_access.data_sensitivity == DataSensitivity.HIGH:
        breach = max(vendor.breach_history, key=lambda b: b.date)
        return True, (
            f"Breach {months_ago:.1f} months ago ({breach.date.strftime('%b %Y')}): "
            f"{breach.description} — combined with HIGH data sensitivity access, "
            "mandatory CRITICAL escalation"
        )
    return False, ""


# ── Weighted factors ──────────────────────────────────────────────────────────

def check_breach_recency(vendor: Vendor, today: date) -> RuleResult:
    """
    Factor weight: 35%.
    raw_score = recency_factor * sensitivity_mult  (0.0–1.0)
    Mirrors: score += 35 * recency_factor * sensitivity_mult
    """
    if not vendor.breach_history:
        return RuleResult(triggered=False, raw_score=0.0)

    most_recent = max(b.date for b in vendor.breach_history)
    months_ago = (today - most_recent).days / 30.44
    recency_factor = max(0.0, 1.0 - months_ago / 36.0)
    sensitivity_mult = _SENSITIVITY_MULT.get(
        vendor.data_access.data_sensitivity.value, 0.5
    )
    raw = recency_factor * sensitivity_mult

    if raw < 0.01:
        return RuleResult(triggered=False, raw_score=0.0)

    breach = max(vendor.breach_history, key=lambda b: b.date)
    months_int = int(months_ago)
    desc = (
        f"Breach {months_int} month{'s' if months_int != 1 else ''} ago "
        f"({breach.date.strftime('%b %Y')}): {breach.description} "
        f"[{vendor.data_access.data_sensitivity.value} sensitivity, "
        f"recency weight {recency_factor:.2f}]"
    )
    return RuleResult(triggered=True, raw_score=raw, descriptions=[desc])


def check_certification_status(vendor: Vendor, today: date) -> RuleResult:
    """
    Factor weight: 25%.
    raw_score = cert_penalty (accumulated, 0.0–~1.3 for LOW/MED; capped at 1.0 for HIGH)
    Mirrors compute_label cert block exactly.
    """
    cert_penalty = 0.0
    descriptions: list[str] = []

    soc2_days: int | None = None
    if vendor.compliance.soc2_type2 and vendor.compliance.soc2_expiry:
        soc2_days = (vendor.compliance.soc2_expiry - today).days

    if not vendor.compliance.soc2_type2:
        cert_penalty += 0.7
        descriptions.append(
            "SOC 2 Type II certification missing: no evidence of third-party security audit"
        )
    elif soc2_days is not None and soc2_days < 0:
        cert_penalty += 0.8
        descriptions.append(
            f"SOC 2 Type II expired {abs(soc2_days)} days ago "
            f"({vendor.compliance.soc2_expiry}): active certification lapse"
        )
    elif soc2_days is not None and soc2_days <= 60:
        cert_penalty += 0.3
        descriptions.append(
            f"SOC 2 Type II expires in {soc2_days} days "
            f"({vendor.compliance.soc2_expiry}): certification gap risk within 60-day window"
        )

    if not vendor.compliance.iso27001:
        cert_penalty += 0.3
        descriptions.append(
            "ISO 27001 not certified: missing information security management standard"
        )

    if vendor.data_access.data_sensitivity == DataSensitivity.HIGH and cert_penalty > 0:
        cert_penalty = min(cert_penalty * 1.3, 1.0)

    triggered = cert_penalty > 0.0
    return RuleResult(triggered=triggered, raw_score=cert_penalty, descriptions=descriptions)


def check_contract_status(vendor: Vendor, today: date) -> RuleResult:
    """
    Factor weight: 15%.
    raw_score: 1.0 (orphaned active access) or 5/15 (expired, no access)
    Mirrors: score += 15 if orphaned, else score += 5 if expired
    """
    contract_expired = vendor.contract_end < today
    has_active_access = bool(vendor.data_access.systems)

    if not contract_expired:
        return RuleResult(triggered=False, raw_score=0.0)

    days_expired = (today - vendor.contract_end).days
    if has_active_access:
        systems_preview = ", ".join(vendor.data_access.systems[:3])
        if len(vendor.data_access.systems) > 3:
            systems_preview += f" (+{len(vendor.data_access.systems) - 3} more)"
        desc = (
            f"Contract expired {days_expired} days ago ({vendor.contract_end}) "
            f"but vendor retains active system access ({systems_preview}): orphaned access risk"
        )
        return RuleResult(triggered=True, raw_score=1.0, descriptions=[desc])
    else:
        desc = (
            f"Contract expired {days_expired} days ago ({vendor.contract_end}): "
            "administrative gap (no active system access recorded)"
        )
        return RuleResult(triggered=True, raw_score=5.0 / 15.0, descriptions=[desc])


def check_financial_rating(vendor: Vendor) -> RuleResult:
    """
    Factor weight: 10%.
    raw_score = rating_penalty (0.0–1.0)
    Mirrors: score += 10 * rating_penalty
    """
    penalty = _RATING_PENALTY.get(vendor.financial_rating, 0.2)
    if penalty < 0.1:
        return RuleResult(triggered=False, raw_score=penalty)

    if penalty >= 0.6:
        qualifier = "poor financial viability, elevated counterparty risk"
    elif penalty >= 0.3:
        qualifier = "below-average financial stability"
    else:
        qualifier = "slightly below-average financial rating"

    desc = f"Financial rating {vendor.financial_rating}: {qualifier}"
    return RuleResult(triggered=True, raw_score=penalty, descriptions=[desc])


def check_data_access_scope(vendor: Vendor) -> RuleResult:
    """
    Factor weight: 10%.
    raw_score: 1.0 for RW+HIGH, 0.3 for RW (non-HIGH), 0.0 otherwise
    Mirrors: score += 10 * (1.0 if rw_high else 0.3 if rw else 0.0)
    """
    is_rw = vendor.data_access.access_type == AccessType.READ_WRITE
    is_high = vendor.data_access.data_sensitivity == DataSensitivity.HIGH

    if is_rw and is_high:
        systems_preview = ", ".join(vendor.data_access.systems[:3])
        desc = (
            f"Read/write access to high-sensitivity systems ({systems_preview}): "
            "broad data modification and exfiltration risk"
        )
        return RuleResult(triggered=True, raw_score=1.0, descriptions=[desc])
    elif is_rw:
        desc = (
            f"Read/write access granted "
            f"({vendor.data_access.data_sensitivity.value} sensitivity)"
        )
        return RuleResult(triggered=True, raw_score=0.3, descriptions=[desc])

    return RuleResult(triggered=False, raw_score=0.0)


def check_gdpr_dpa(vendor: Vendor) -> RuleResult:
    """
    Factor weight: 5%.
    raw_score: 1.0 if EU data + missing DPA, else 0.0
    Mirrors: score += 5 if handles_eu_data and not gdpr_dpa
    """
    if vendor.handles_eu_data and not vendor.compliance.gdpr_dpa:
        desc = (
            "Missing GDPR Data Processing Agreement despite handling EU personal data: "
            "regulatory non-compliance risk"
        )
        return RuleResult(triggered=True, raw_score=1.0, descriptions=[desc])
    return RuleResult(triggered=False, raw_score=0.0)
