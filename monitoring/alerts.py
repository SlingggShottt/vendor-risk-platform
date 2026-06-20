"""
monitoring/alerts.py — Expiry and breach alert generation.

Checks each vendor against:
  - SOC2 expiry (30 / 60 / 90 day windows)
  - Contract expiry when vendor still has active system access (orphaned access)
  - Breach recency flag (breach within last 12 months)

Usage:
  from monitoring.alerts import get_all_alerts, Alert
  alerts = get_all_alerts(vendors)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import Vendor


@dataclass
class Alert:
    vendor_id: str
    vendor_name: str
    alert_type: str   # one of the ALERT_TYPE_* constants below
    message: str
    severity: str     # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    days_until: int | None  # negative = already past
    triggered_at: datetime = field(default_factory=datetime.utcnow)


ALERT_CERT_EXPIRED       = "CERT_EXPIRED"
ALERT_CERT_EXPIRY_30     = "CERT_EXPIRY_30"
ALERT_CERT_EXPIRY_60     = "CERT_EXPIRY_60"
ALERT_CERT_EXPIRY_90     = "CERT_EXPIRY_90"
ALERT_CONTRACT_ORPHANED  = "CONTRACT_ORPHANED"
ALERT_CONTRACT_EXPIRY_30 = "CONTRACT_EXPIRY_30"
ALERT_BREACH_RECENT      = "BREACH_RECENT"


def check_alerts(vendor: Vendor, today: date | None = None) -> list[Alert]:
    """Return all active alerts for a single vendor."""
    if today is None:
        today = date.today()

    alerts: list[Alert] = []

    # ── SOC2 certification expiry ─────────────────────────────────────────────
    if vendor.compliance.soc2_type2 and vendor.compliance.soc2_expiry:
        soc2_days = (vendor.compliance.soc2_expiry - today).days

        if soc2_days < 0:
            alerts.append(Alert(
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.name,
                alert_type=ALERT_CERT_EXPIRED,
                message=(
                    f"SOC 2 Type II expired {abs(soc2_days)} days ago "
                    f"({vendor.compliance.soc2_expiry}). Immediate renewal required."
                ),
                severity="HIGH",
                days_until=soc2_days,
            ))
        elif soc2_days <= 30:
            alerts.append(Alert(
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.name,
                alert_type=ALERT_CERT_EXPIRY_30,
                message=(
                    f"SOC 2 Type II expires in {soc2_days} days "
                    f"({vendor.compliance.soc2_expiry}). Urgent renewal required."
                ),
                severity="HIGH",
                days_until=soc2_days,
            ))
        elif soc2_days <= 60:
            alerts.append(Alert(
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.name,
                alert_type=ALERT_CERT_EXPIRY_60,
                message=(
                    f"SOC 2 Type II expires in {soc2_days} days "
                    f"({vendor.compliance.soc2_expiry}). Renewal should be initiated now."
                ),
                severity="MEDIUM",
                days_until=soc2_days,
            ))
        elif soc2_days <= 90:
            alerts.append(Alert(
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.name,
                alert_type=ALERT_CERT_EXPIRY_90,
                message=(
                    f"SOC 2 Type II expires in {soc2_days} days "
                    f"({vendor.compliance.soc2_expiry}). Plan renewal within 30 days."
                ),
                severity="LOW",
                days_until=soc2_days,
            ))

    # ── Contract expiry with active access ────────────────────────────────────
    contract_expired = vendor.contract_end < today
    has_active_access = bool(vendor.data_access.systems)

    if contract_expired and has_active_access:
        days_since = (today - vendor.contract_end).days
        systems_preview = ", ".join(vendor.data_access.systems[:2])
        if len(vendor.data_access.systems) > 2:
            systems_preview += f" +{len(vendor.data_access.systems)-2} more"
        alerts.append(Alert(
            vendor_id=vendor.vendor_id,
            vendor_name=vendor.name,
            alert_type=ALERT_CONTRACT_ORPHANED,
            message=(
                f"Contract expired {days_since} days ago ({vendor.contract_end}) "
                f"but vendor still has system access ({systems_preview}). "
                "Revoke access or renew contract immediately."
            ),
            severity="CRITICAL",
            days_until=-days_since,
        ))
    elif not contract_expired:
        contract_days = (vendor.contract_end - today).days
        if contract_days <= 30:
            alerts.append(Alert(
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.name,
                alert_type=ALERT_CONTRACT_EXPIRY_30,
                message=(
                    f"Contract expires in {contract_days} days ({vendor.contract_end}). "
                    "Begin renewal or offboarding process."
                ),
                severity="HIGH",
                days_until=contract_days,
            ))

    # ── Recent breach flag ────────────────────────────────────────────────────
    if vendor.breach_history:
        most_recent = max(b.date for b in vendor.breach_history)
        months_ago = (today - most_recent).days / 30.44
        if months_ago <= 12:
            breach = max(vendor.breach_history, key=lambda b: b.date)
            alerts.append(Alert(
                vendor_id=vendor.vendor_id,
                vendor_name=vendor.name,
                alert_type=ALERT_BREACH_RECENT,
                message=(
                    f"Breach reported {months_ago:.1f} months ago ({breach.date}): "
                    f"{breach.description}. Review incident status and remediation."
                ),
                severity="CRITICAL",
                days_until=None,
            ))

    return alerts


def get_all_alerts(
    vendors: list[Vendor],
    today: date | None = None,
) -> list[Alert]:
    """Return all alerts across all vendors, sorted by severity then vendor name."""
    if today is None:
        today = date.today()

    _SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    all_alerts: list[Alert] = []
    for v in vendors:
        all_alerts.extend(check_alerts(v, today))

    all_alerts.sort(key=lambda a: (_SEV_ORDER.get(a.severity, 9), a.vendor_name))
    return all_alerts


def alerts_summary(alerts: list[Alert]) -> dict[str, int]:
    """Count alerts by severity."""
    counts: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for a in alerts:
        counts[a.severity] = counts.get(a.severity, 0) + 1
    return counts


if __name__ == "__main__":
    from common.schema import FIXTURE_VENDORS
    today = date(2026, 6, 19)
    alerts = get_all_alerts(FIXTURE_VENDORS, today)
    print(f"Alerts for fixture vendors (today={today}):\n")
    for a in alerts:
        print(f"  [{a.severity:8s}] {a.vendor_id} {a.vendor_name}")
        print(f"           {a.alert_type}: {a.message[:90]}")
