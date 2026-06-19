"""
data/generate_vendors.py — Bulk synthetic vendor generator.

Controlled distributions so every scoring rule in PRD.md §5 is exercised:
  - ~10% recently breached + HIGH data sensitivity  → CRITICAL floor
  - ~5%  under_investigation                        → CRITICAL floor
  - ~12% expired/missing certs on sensitive vendors → HIGH
  - ~10% orphaned access (contract expired, access still populated)
  - ~8%  low financial rating (C/D)
  - ~15% missing GDPR DPA with EU data             → partial penalty
  - ~40% clean/low-risk baseline

Outputs:
  vendor_registry.csv  — all Vendor fields, one row per vendor
  vendor_labels.csv    — VendorLabel fields (ground truth for eval)

Usage:
  python data/generate_vendors.py [--count N] [--seed S] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

# allow running from repo root or from data/ itself
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import (
    AccessType,
    AnomalyType,
    BreachEvent,
    Compliance,
    DataAccess,
    DataSensitivity,
    RiskLevel,
    Severity,
    Vendor,
    VendorLabel,
)

# ── Reference rubric (mirrors PRD.md §5) ───────────────────────────────────────
TODAY = date(2026, 6, 19)  # fixed for reproducibility — matches CLAUDE.md currentDate


def _breach_months_ago(v: Vendor) -> float | None:
    """Months since the most recent breach, or None."""
    if not v.breach_history:
        return None
    most_recent = max(b.date for b in v.breach_history)
    return (TODAY - most_recent).days / 30.44


def _soc2_days_to_expiry(v: Vendor) -> int | None:
    if v.compliance.soc2_type2 and v.compliance.soc2_expiry:
        return (v.compliance.soc2_expiry - TODAY).days
    return None


def compute_label(v: Vendor) -> VendorLabel:
    """
    Deterministic label using the EXACT rubric in PRD.md §5.
    This is the ground truth — not a vibe — so eval measures rubric fidelity.
    """
    is_high_sensitivity = v.data_access.data_sensitivity == DataSensitivity.HIGH
    months_since_breach = _breach_months_ago(v)
    contract_expired = v.contract_end < TODAY
    has_active_access = bool(v.data_access.systems)

    # ── Hard floors (guarantee CRITICAL) ─────────────────────────────────────
    if v.under_investigation:
        return VendorLabel(
            vendor_id=v.vendor_id,
            is_anomaly=True,
            anomaly_type=AnomalyType.VENDOR_UNDER_INVESTIGATION,
            severity=Severity.CRITICAL,
            explanation="Vendor is flagged under_investigation — hard-floor CRITICAL.",
        )

    if months_since_breach is not None and months_since_breach <= 12 and is_high_sensitivity:
        return VendorLabel(
            vendor_id=v.vendor_id,
            is_anomaly=True,
            anomaly_type=AnomalyType.BREACHED_VENDOR_HIGH_ACCESS,
            severity=Severity.CRITICAL,
            explanation=(
                f"Breach {months_since_breach:.1f} months ago with HIGH data sensitivity "
                "— hard-floor CRITICAL."
            ),
        )

    # ── Weighted scoring ──────────────────────────────────────────────────────
    score = 0.0

    # 35% — breach recency + access sensitivity
    if months_since_breach is not None:
        recency_factor = max(0.0, 1.0 - months_since_breach / 36)  # decays over 36 months
        sensitivity_mult = {"HIGH": 1.0, "MEDIUM": 0.6, "LOW": 0.3}[
            v.data_access.data_sensitivity.value
        ]
        score += 35 * recency_factor * sensitivity_mult

    # 25% — certification status
    cert_penalty = 0.0
    expired_certs: list[str] = []
    soc2_days = _soc2_days_to_expiry(v)
    if not v.compliance.soc2_type2:
        cert_penalty += 0.7
        expired_certs.append("SOC2_TYPE2_MISSING")
    elif soc2_days is not None and soc2_days < 0:
        cert_penalty += 0.8
        expired_certs.append("SOC2_TYPE2_EXPIRED")
    elif soc2_days is not None and soc2_days <= 60:
        cert_penalty += 0.3
        expired_certs.append("SOC2_TYPE2_EXPIRING_SOON")

    if not v.compliance.iso27001:
        cert_penalty += 0.3
    if is_high_sensitivity:
        cert_penalty = min(cert_penalty * 1.3, 1.0)
    score += 25 * cert_penalty

    # 15% — contract status
    if contract_expired and has_active_access:
        score += 15
        expired_certs.append("CONTRACT_EXPIRED_ACTIVE_ACCESS")
    elif contract_expired:
        score += 5

    # 10% — financial rating
    rating_penalty = {"A": 0, "A+": 0, "A-": 0.1, "B+": 0.15, "B": 0.2, "B-": 0.3,
                      "C+": 0.5, "C": 0.6, "C-": 0.7, "D": 1.0}.get(v.financial_rating, 0.2)
    score += 10 * rating_penalty

    # 10% — data access scope
    rw_high = (
        v.data_access.access_type == AccessType.READ_WRITE
        and v.data_access.data_sensitivity == DataSensitivity.HIGH
    )
    score += 10 * (1.0 if rw_high else 0.3 if v.data_access.access_type == AccessType.READ_WRITE else 0.0)

    # 5% — missing GDPR DPA when EU data is involved
    if v.handles_eu_data and not v.compliance.gdpr_dpa:
        score += 5

    score = min(score, 100.0)

    # ── Map score to risk level ───────────────────────────────────────────────
    if score >= 80:
        risk_level = RiskLevel.CRITICAL
        anomaly = AnomalyType.HIGH_RISK_SCORE
        severity = Severity.CRITICAL
        is_anomaly = True
    elif score >= 65:
        risk_level = RiskLevel.HIGH
        anomaly = AnomalyType.ELEVATED_RISK_VENDOR
        severity = Severity.HIGH
        is_anomaly = True
    elif score >= 40:
        risk_level = RiskLevel.MEDIUM
        severity = Severity.MEDIUM
        is_anomaly = True
        # pick most specific anomaly
        if expired_certs:
            anomaly = AnomalyType.EXPIRED_CERTIFICATION
        elif months_since_breach is not None:
            anomaly = AnomalyType.RECENTLY_BREACHED_VENDOR
        elif contract_expired and has_active_access:
            anomaly = AnomalyType.CONTRACT_EXPIRED_ACTIVE_ACCESS
        else:
            anomaly = AnomalyType.ELEVATED_RISK_VENDOR
    else:
        risk_level = RiskLevel.LOW
        anomaly = AnomalyType.NONE
        severity = Severity.LOW
        is_anomaly = False

    explanation = (
        f"Score={score:.1f} → {risk_level.value}. "
        f"Breach: {f'{months_since_breach:.1f}mo ago' if months_since_breach is not None else 'none'}. "
        f"Certs: {expired_certs or 'OK'}. "
        f"Contract expired: {contract_expired}. "
        f"Rating: {v.financial_rating}."
    )

    return VendorLabel(
        vendor_id=v.vendor_id,
        is_anomaly=is_anomaly,
        anomaly_type=anomaly,
        severity=severity,
        expired_certifications=expired_certs,
        explanation=explanation,
    )


# ── Generator internals ────────────────────────────────────────────────────────

CATEGORIES = [
    "Cloud Infrastructure", "SaaS", "Managed Services", "Payment Processor",
    "Analytics", "Consulting", "Integration", "Security",
    "Backup & Disaster Recovery", "HR Technology", "Software", "Legal",
    "Marketing Technology", "DevOps Tooling", "Data Warehousing",
]

SYSTEMS = [
    "Database_Primary", "FileServer_Corporate", "HR_System", "CRM", "ERP",
    "Analytics_DB", "Payment_Gateway", "Identity_Provider", "Email_Platform",
    "Ticketing_System", "Monitoring_Tools", "CI_CD_Pipeline", "S3_Buckets",
    "Backup_Storage", "Data_Warehouse", "Audit_Logs",
]

FINANCIAL_RATINGS = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D"]

VENDOR_NAME_PREFIXES = [
    "Apex", "Nova", "Titan", "Vantage", "Stellar", "Nexus", "Prime", "Quantum",
    "Pinnacle", "Summit", "Horizon", "Fusion", "Atlas", "Core", "Cascade",
    "Vertex", "Echo", "Stratum", "Relay", "Orbit",
]
VENDOR_NAME_SUFFIXES = [
    "Systems", "Solutions", "Technologies", "Group", "Services", "Analytics",
    "Platforms", "Networks", "Dynamics", "Integrations", "Partners", "Cloud",
    "Labs", "Works", "Global",
]


def _random_date(rng: random.Random, start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, max(delta, 0)))


def _make_vendor_id(index: int) -> str:
    return f"VND-{index:04d}"


def _vendor_name(rng: random.Random) -> str:
    return f"{rng.choice(VENDOR_NAME_PREFIXES)} {rng.choice(VENDOR_NAME_SUFFIXES)}"


def _make_breach(rng: random.Random, months_ago: float, is_high: bool) -> BreachEvent:
    breach_date = TODAY - timedelta(days=int(months_ago * 30.44))
    severity = rng.choice([Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]) if is_high else rng.choice([Severity.LOW, Severity.MEDIUM])
    descs = [
        "Unencrypted data exposed on cloud storage",
        "Credential stuffing attack on admin portal",
        "SQL injection led to partial DB dump",
        "Phishing campaign compromised employee accounts",
        "Third-party library supply-chain compromise",
        "Misconfigured API exposed internal records",
        "Ransomware encrypted backup files",
        "Insider threat — unauthorized data export",
    ]
    return BreachEvent(date=breach_date, severity=severity, description=rng.choice(descs))


def _make_compliance(
    rng: random.Random,
    *,
    has_soc2: bool,
    soc2_expired: bool,
    soc2_expiring_soon: bool,
    has_iso: bool,
    has_gdpr: bool,
) -> Compliance:
    soc2_expiry = None
    if has_soc2:
        if soc2_expired:
            soc2_expiry = TODAY - timedelta(days=rng.randint(1, 400))
        elif soc2_expiring_soon:
            soc2_expiry = TODAY + timedelta(days=rng.randint(1, 59))
        else:
            soc2_expiry = TODAY + timedelta(days=rng.randint(90, 730))
    return Compliance(soc2_type2=has_soc2, soc2_expiry=soc2_expiry, iso27001=has_iso, gdpr_dpa=has_gdpr)


def generate_vendors(count: int = 420, seed: int = 42) -> list[Vendor]:
    """
    Generate `count` vendors with distributions that exercise every PRD §5 rule.
    Start IDs from 1001 to avoid collisions with FIXTURE_VENDORS (VND-0001 to VND-0512).
    """
    rng = random.Random(seed)

    # Target distribution (counts approximate, not exact)
    n_critical_breach = int(count * 0.10)   # recently breached + HIGH access → CRITICAL
    n_under_inv = int(count * 0.05)          # under_investigation → CRITICAL
    n_expired_cert = int(count * 0.08)       # expired/missing cert on sensitive vendor → MEDIUM
    n_orphaned = int(count * 0.08)           # contract expired + active access → MEDIUM
    n_low_rating = int(count * 0.05)         # C/D financial rating, otherwise mediocre
    n_eu_no_dpa = int(count * 0.06)          # handles EU data, missing GDPR DPA
    n_old_breach = int(count * 0.06)         # breach >12mo ago (no CRITICAL floor, some risk)
    n_expiring_cert = int(count * 0.03)      # cert expiring within 60 days
    # Multi-factor vendors landing in HIGH range (score 65-79): expired cert + orphaned + poor rating
    n_high_multi = int(count * 0.10)         # combined risk → HIGH
    # remaining are clean/low-risk
    n_clean = count - (n_critical_breach + n_under_inv + n_expired_cert + n_orphaned +
                       n_low_rating + n_eu_no_dpa + n_old_breach + n_expiring_cert + n_high_multi)

    vendors: list[Vendor] = []
    idx = 1001

    def _base(
        sensitivity: DataSensitivity = DataSensitivity.MEDIUM,
        access_type: AccessType = AccessType.READ_ONLY,
        systems: list[str] | None = None,
        financial_rating: str = "B",
        handles_eu_data: bool = False,
        under_investigation: bool = False,
        breach_history: list[BreachEvent] | None = None,
        compliance: Compliance | None = None,
        contract_end_offset_days: int = 365,
    ) -> Vendor:
        nonlocal idx
        v = Vendor(
            vendor_id=_make_vendor_id(idx),
            name=_vendor_name(rng),
            category=rng.choice(CATEGORIES),
            contract_start=_random_date(rng, date(2021, 1, 1), date(2024, 12, 31)),
            contract_end=TODAY + timedelta(days=contract_end_offset_days),
            data_access=DataAccess(
                systems=systems if systems is not None else rng.sample(SYSTEMS, k=rng.randint(1, 3)),
                data_sensitivity=sensitivity,
                access_type=access_type,
            ),
            compliance=compliance or Compliance(
                soc2_type2=True,
                soc2_expiry=TODAY + timedelta(days=365),
                iso27001=True,
                gdpr_dpa=handles_eu_data,
            ),
            breach_history=breach_history or [],
            financial_rating=financial_rating,
            under_investigation=under_investigation,
            handles_eu_data=handles_eu_data,
            annual_spend=round(rng.uniform(10_000, 2_000_000), 2),
        )
        idx += 1
        return v

    # 1. Recently breached + HIGH sensitivity → must hit CRITICAL hard floor
    for _ in range(n_critical_breach):
        months_ago = rng.uniform(0.5, 11.9)
        vendors.append(_base(
            sensitivity=DataSensitivity.HIGH,
            access_type=rng.choice([AccessType.READ_WRITE, AccessType.READ_ONLY]),
            financial_rating=rng.choice(["A", "B", "C"]),
            breach_history=[_make_breach(rng, months_ago, is_high=True)],
            compliance=_make_compliance(rng, has_soc2=rng.random() > 0.3, soc2_expired=False,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.5, has_gdpr=rng.random() > 0.5),
        ))

    # 2. Under investigation → CRITICAL hard floor regardless of everything else
    for _ in range(n_under_inv):
        vendors.append(_base(
            sensitivity=rng.choice([DataSensitivity.LOW, DataSensitivity.MEDIUM, DataSensitivity.HIGH]),
            under_investigation=True,
            financial_rating=rng.choice(["B", "C", "D"]),
            compliance=_make_compliance(rng, has_soc2=rng.random() > 0.5, soc2_expired=False,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.5, has_gdpr=rng.random() > 0.5),
        ))

    # 3. Expired/missing SOC2 → MEDIUM range. Need READ_WRITE + HIGH sensitivity + poor rating
    # to reliably cross the 40-point threshold (expired SOC2 alone scores ~25, below MEDIUM).
    for _ in range(n_expired_cert):
        has_soc2 = rng.random() > 0.4  # 40% missing entirely, 60% expired
        vendors.append(_base(
            sensitivity=DataSensitivity.HIGH,       # high sensitivity multiplier on cert penalty
            access_type=AccessType.READ_WRITE,      # rw+high = +10 pts, gets total to 40+
            financial_rating=rng.choice(["B-", "C+", "C"]),  # slight negative → +3-6 pts
            handles_eu_data=rng.random() > 0.5,
            compliance=_make_compliance(rng, has_soc2=has_soc2, soc2_expired=True,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.6,
                                         has_gdpr=rng.random() > 0.5),
        ))

    # 4. Orphaned access — contract expired, data_access still populated
    for _ in range(n_orphaned):
        days_expired = rng.randint(1, 400)
        vendors.append(_base(
            sensitivity=rng.choice([DataSensitivity.LOW, DataSensitivity.MEDIUM]),
            access_type=rng.choice([AccessType.READ_WRITE, AccessType.READ_ONLY]),
            financial_rating=rng.choice(["B", "C"]),
            contract_end_offset_days=-days_expired,
            compliance=_make_compliance(rng, has_soc2=rng.random() > 0.4, soc2_expired=rng.random() > 0.7,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.5, has_gdpr=rng.random() > 0.5),
        ))

    # 5. Low financial rating, otherwise mediocre
    for _ in range(n_low_rating):
        vendors.append(_base(
            sensitivity=rng.choice([DataSensitivity.LOW, DataSensitivity.MEDIUM]),
            financial_rating=rng.choice(["C", "C-", "D"]),
            compliance=_make_compliance(rng, has_soc2=rng.random() > 0.3, soc2_expired=rng.random() > 0.6,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.5, has_gdpr=rng.random() > 0.4),
        ))

    # 6. EU data, no GDPR DPA
    for _ in range(n_eu_no_dpa):
        vendors.append(_base(
            sensitivity=rng.choice([DataSensitivity.MEDIUM, DataSensitivity.HIGH]),
            handles_eu_data=True,
            financial_rating=rng.choice(["A-", "B+", "B", "B-"]),
            compliance=_make_compliance(rng, has_soc2=rng.random() > 0.3, soc2_expired=False,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.5, has_gdpr=False),
        ))

    # 7. Old breach (>12 months ago) — no hard floor, decayed risk
    for _ in range(n_old_breach):
        months_ago = rng.uniform(13, 36)
        vendors.append(_base(
            sensitivity=rng.choice([DataSensitivity.LOW, DataSensitivity.MEDIUM, DataSensitivity.HIGH]),
            breach_history=[_make_breach(rng, months_ago, is_high=False)],
            financial_rating=rng.choice(["A-", "B+", "B", "B-", "C"]),
            compliance=_make_compliance(rng, has_soc2=rng.random() > 0.3, soc2_expired=False,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.5, has_gdpr=rng.random() > 0.5),
        ))

    # 8. Cert expiring in 1-59 days (alert boundary zone)
    for _ in range(n_expiring_cert):
        vendors.append(_base(
            sensitivity=rng.choice([DataSensitivity.MEDIUM, DataSensitivity.HIGH]),
            financial_rating=rng.choice(["A", "A-", "B"]),
            compliance=_make_compliance(rng, has_soc2=True, soc2_expired=False,
                                         soc2_expiring_soon=True, has_iso=rng.random() > 0.5,
                                         has_gdpr=rng.random() > 0.5),
        ))

    # 9. Multi-factor HIGH risk (score 65-79) — no CRITICAL hard floor but combined penalties stack.
    # Guaranteed formula: expired SOC2 (25) + orphaned contract (15) + D rating (10)
    #                     + RW+HIGH scope (10) + EU no DPA (5) = 65 → HIGH.
    # Variant with old breach: swap D rating for C, add >12mo breach (+17pts) → also HIGH.
    for i in range(n_high_multi):
        days_expired = rng.randint(10, 200)
        has_soc2 = rng.random() > 0.3
        if i % 4 == 0:
            # variant: C rating + old breach (18-30 months ago) → also lands in HIGH
            breach_months = rng.uniform(13, 30)
            extra_breaches = [_make_breach(rng, breach_months, is_high=False)]
            fin_rating = "C"
        else:
            extra_breaches = []
            fin_rating = "D"
        vendors.append(_base(
            sensitivity=DataSensitivity.HIGH,   # HIGH scope penalty to push score ≥65
            access_type=AccessType.READ_WRITE,
            financial_rating=fin_rating,
            handles_eu_data=True,
            contract_end_offset_days=-days_expired,
            breach_history=extra_breaches,
            compliance=_make_compliance(
                rng,
                has_soc2=has_soc2,
                soc2_expired=True,
                soc2_expiring_soon=False,
                has_iso=False,
                has_gdpr=False,
            ),
        ))

    # 10. Clean/low-risk baseline
    for _ in range(n_clean):
        vendors.append(_base(
            sensitivity=rng.choice([DataSensitivity.LOW, DataSensitivity.MEDIUM]),
            access_type=rng.choice([AccessType.READ_ONLY, AccessType.READ_WRITE]),
            financial_rating=rng.choice(["A+", "A", "A-", "B+", "B"]),
            handles_eu_data=rng.random() > 0.7,
            compliance=_make_compliance(rng, has_soc2=True, soc2_expired=False,
                                         soc2_expiring_soon=False, has_iso=rng.random() > 0.3,
                                         has_gdpr=rng.random() > 0.3),
        ))

    rng.shuffle(vendors)
    return vendors


# ── CSV writers ────────────────────────────────────────────────────────────────

VENDOR_FIELDS = [
    "vendor_id", "name", "category",
    "contract_start", "contract_end",
    "data_sensitivity", "access_type", "systems",
    "soc2_type2", "soc2_expiry", "iso27001", "gdpr_dpa",
    "breach_count", "latest_breach_date", "latest_breach_severity", "latest_breach_description",
    "financial_rating", "annual_spend",
    "under_investigation", "handles_eu_data",
]

LABEL_FIELDS = [
    "vendor_id", "is_anomaly", "anomaly_type", "severity",
    "expired_certifications", "explanation",
]


def _vendor_row(v: Vendor) -> dict:
    latest = max(v.breach_history, key=lambda b: b.date) if v.breach_history else None
    d = v.model_dump(mode="json")
    return {
        "vendor_id": v.vendor_id,
        "name": v.name,
        "category": v.category,
        "contract_start": d["contract_start"],
        "contract_end": d["contract_end"],
        "data_sensitivity": d["data_access"]["data_sensitivity"],
        "access_type": d["data_access"]["access_type"],
        "systems": "|".join(v.data_access.systems),
        "soc2_type2": v.compliance.soc2_type2,
        "soc2_expiry": d["compliance"]["soc2_expiry"] or "",
        "iso27001": v.compliance.iso27001,
        "gdpr_dpa": v.compliance.gdpr_dpa,
        "breach_count": len(v.breach_history),
        "latest_breach_date": latest.date.isoformat() if latest else "",
        "latest_breach_severity": latest.severity.value if latest else "",
        "latest_breach_description": latest.description if latest else "",
        "financial_rating": v.financial_rating,
        "annual_spend": v.annual_spend or "",
        "under_investigation": v.under_investigation,
        "handles_eu_data": v.handles_eu_data,
    }


def _label_row(lbl: VendorLabel) -> dict:
    d = lbl.model_dump(mode="json")
    return {
        "vendor_id": lbl.vendor_id,
        "is_anomaly": lbl.is_anomaly,
        "anomaly_type": d["anomaly_type"],
        "severity": d["severity"],
        "expired_certifications": "|".join(lbl.expired_certifications),
        "explanation": lbl.explanation,
    }


def write_csvs(vendors: list[Vendor], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    registry_path = out_dir / "vendor_registry.csv"
    labels_path = out_dir / "vendor_labels.csv"

    with open(registry_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=VENDOR_FIELDS)
        w.writeheader()
        for v in vendors:
            w.writerow(_vendor_row(v))

    with open(labels_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
        w.writeheader()
        for v in vendors:
            w.writerow(_label_row(compute_label(v)))

    print(f"[generate_vendors] Wrote {len(vendors)} rows to {registry_path}")
    print(f"[generate_vendors] Wrote {len(vendors)} labels to {labels_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic vendor data.")
    parser.add_argument("--count", type=int, default=420, help="Number of bulk vendors to generate")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--out-dir", type=str, default=".", help="Output directory for CSVs")
    args = parser.parse_args()

    vendors = generate_vendors(count=args.count, seed=args.seed)
    write_csvs(vendors, Path(args.out_dir))

    # distribution summary
    from collections import Counter
    labels = [compute_label(v) for v in vendors]
    sev_counts = Counter(lbl.severity.value for lbl in labels)
    anom_counts = Counter(lbl.anomaly_type.value for lbl in labels)
    print("\n[generate_vendors] Severity distribution:")
    for sev, cnt in sorted(sev_counts.items()):
        print(f"  {sev:10s}: {cnt:4d}  ({100*cnt/len(vendors):.1f}%)")
    print("[generate_vendors] Anomaly type distribution:")
    for anom, cnt in sorted(anom_counts.items(), key=lambda x: -x[1]):
        print(f"  {anom:40s}: {cnt:4d}")


if __name__ == "__main__":
    main()
