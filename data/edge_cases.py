"""
data/edge_cases.py — Hand-scripted edge case vendors.

These complement the bulk generator by hitting exact boundary conditions and
intentionally ambiguous scenarios that random sampling might miss.

Every vendor here is also included in vendor_registry.csv and vendor_labels.csv
(via the append step in generate_vendors.py's write_csvs call, or by running
this file standalone to append to existing CSVs).

IDs: VND-9000 to VND-9999 (reserved range, won't collide with bulk or fixtures).
"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import (
    AccessType,
    AnomalyType,
    BreachEvent,
    Compliance,
    DataAccess,
    DataSensitivity,
    Severity,
    Vendor,
    VendorLabel,
)
from data.generate_vendors import (
    LABEL_FIELDS,
    VENDOR_FIELDS,
    TODAY,
    _label_row,
    _vendor_row,
    compute_label,
)

# ── Edge case definitions ─────────────────────────────────────────────────────

EDGE_CASE_VENDORS: list[Vendor] = [

    # EC-1: Breach exactly 12 months ago + HIGH access — sits on the CRITICAL floor boundary.
    # One day earlier would be CRITICAL; scorer must handle "exactly 12 months" correctly.
    Vendor(
        vendor_id="VND-9001",
        name="BoundaryBreach Corp",
        category="Cloud Infrastructure",
        contract_start=date(2023, 1, 1),
        contract_end=date(2027, 6, 19),
        data_access=DataAccess(
            systems=["Database_Primary"],
            data_sensitivity=DataSensitivity.HIGH,
            access_type=AccessType.READ_WRITE,
        ),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2027, 1, 1), iso27001=True, gdpr_dpa=True),
        breach_history=[BreachEvent(
            date=TODAY - timedelta(days=365),  # exactly 12 months ago
            severity=Severity.HIGH,
            description="Major data exfiltration — exactly at the 12-month boundary",
        )],
        financial_rating="B",
        under_investigation=False,
        handles_eu_data=False,
    ),

    # EC-2: Under investigation — CRITICAL regardless of everything else looking clean.
    Vendor(
        vendor_id="VND-9002",
        name="InvestigatedCleanCo",
        category="SaaS",
        contract_start=date(2024, 1, 1),
        contract_end=date(2027, 1, 1),
        data_access=DataAccess(
            systems=["Analytics_DB"],
            data_sensitivity=DataSensitivity.LOW,
            access_type=AccessType.READ_ONLY,
        ),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2028, 1, 1), iso27001=True, gdpr_dpa=True),
        breach_history=[],
        financial_rating="A",
        under_investigation=True,  # clean otherwise, but this flag = CRITICAL
        handles_eu_data=False,
    ),

    # EC-3: SOC2 expiring in exactly 59 days — should trigger the ≤60-day partial penalty.
    Vendor(
        vendor_id="VND-9003",
        name="NearExpirySaaS Ltd",
        category="SaaS",
        contract_start=date(2024, 3, 1),
        contract_end=date(2027, 3, 1),
        data_access=DataAccess(
            systems=["CRM", "HR_System"],
            data_sensitivity=DataSensitivity.MEDIUM,
            access_type=AccessType.READ_WRITE,
        ),
        compliance=Compliance(
            soc2_type2=True,
            soc2_expiry=TODAY + timedelta(days=59),  # exactly 59 days — inside the ≤60 window
            iso27001=False,
            gdpr_dpa=True,
        ),
        breach_history=[],
        financial_rating="B",
        under_investigation=False,
        handles_eu_data=True,
    ),

    # EC-4: SOC2 expiring in exactly 60 days — right at the boundary.
    Vendor(
        vendor_id="VND-9004",
        name="ExactBoundaryCert Inc",
        category="Analytics",
        contract_start=date(2024, 3, 1),
        contract_end=date(2027, 3, 1),
        data_access=DataAccess(
            systems=["Analytics_DB"],
            data_sensitivity=DataSensitivity.MEDIUM,
            access_type=AccessType.READ_ONLY,
        ),
        compliance=Compliance(
            soc2_type2=True,
            soc2_expiry=TODAY + timedelta(days=60),  # exactly 60 days — on the boundary
            iso27001=True,
            gdpr_dpa=True,
        ),
        breach_history=[],
        financial_rating="A-",
        under_investigation=False,
        handles_eu_data=True,
    ),

    # EC-5: SOC2 expiring in exactly 61 days — just outside the alert window, no partial penalty.
    Vendor(
        vendor_id="VND-9005",
        name="JustOutsideAlert Co",
        category="Analytics",
        contract_start=date(2024, 3, 1),
        contract_end=date(2027, 3, 1),
        data_access=DataAccess(
            systems=["Analytics_DB"],
            data_sensitivity=DataSensitivity.MEDIUM,
            access_type=AccessType.READ_ONLY,
        ),
        compliance=Compliance(
            soc2_type2=True,
            soc2_expiry=TODAY + timedelta(days=61),  # 61 days — outside the alert window
            iso27001=True,
            gdpr_dpa=True,
        ),
        breach_history=[],
        financial_rating="A-",
        under_investigation=False,
        handles_eu_data=True,
    ),

    # EC-6: Orphaned access — contract expired 180 days ago, data_access still fully populated.
    Vendor(
        vendor_id="VND-9006",
        name="OrphanedAccess Corp",
        category="Integration",
        contract_start=date(2020, 1, 1),
        contract_end=TODAY - timedelta(days=180),  # expired 6 months ago
        data_access=DataAccess(
            systems=["Database_Primary", "FileServer_Corporate", "Identity_Provider"],
            data_sensitivity=DataSensitivity.MEDIUM,
            access_type=AccessType.READ_WRITE,
        ),
        compliance=Compliance(soc2_type2=False, iso27001=False, gdpr_dpa=False),
        breach_history=[],
        financial_rating="C",
        under_investigation=False,
        handles_eu_data=False,
    ),

    # EC-7: Perfectly clean vendor — zero issues, should score LOW and produce NONE anomaly.
    Vendor(
        vendor_id="VND-9007",
        name="PerfectScore Vendor",
        category="Security",
        contract_start=date(2025, 1, 1),
        contract_end=date(2028, 1, 1),
        data_access=DataAccess(
            systems=["Monitoring_Tools"],
            data_sensitivity=DataSensitivity.LOW,
            access_type=AccessType.READ_ONLY,
        ),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2028, 6, 1), iso27001=True, gdpr_dpa=True),
        breach_history=[],
        financial_rating="A+",
        under_investigation=False,
        handles_eu_data=False,
        annual_spend=50_000.00,
    ),

    # EC-8: Conflicting-schema simulation — vendor with many flags simultaneously set.
    # In real messy data this would be two overlapping records; here it's the reconciled output.
    # Scorer must handle: recent breach + expiring cert + orphaned contract + D rating.
    Vendor(
        vendor_id="VND-9008",
        name="MaxRisk Everything LLC",
        category="Managed Services",
        contract_start=date(2019, 1, 1),
        contract_end=TODAY - timedelta(days=90),  # expired contract
        data_access=DataAccess(
            systems=["Database_Primary", "Payment_Gateway", "Identity_Provider"],
            data_sensitivity=DataSensitivity.HIGH,
            access_type=AccessType.READ_WRITE,
        ),
        compliance=Compliance(
            soc2_type2=True,
            soc2_expiry=TODAY - timedelta(days=30),  # expired 30 days ago
            iso27001=False,
            gdpr_dpa=False,
        ),
        breach_history=[BreachEvent(
            date=TODAY - timedelta(days=60),  # ~2 months ago — CRITICAL floor triggered
            severity=Severity.CRITICAL,
            description="Full database dump exfiltrated; ransom paid",
        )],
        financial_rating="D",
        under_investigation=False,
        handles_eu_data=True,
        annual_spend=1_200_000.00,
    ),

    # EC-9: EU data handler, missing GDPR DPA, otherwise clean — tests the 5% flat penalty alone.
    Vendor(
        vendor_id="VND-9009",
        name="EUHandler NoDPA Ltd",
        category="Payment Processor",
        contract_start=date(2024, 1, 1),
        contract_end=date(2027, 1, 1),
        data_access=DataAccess(
            systems=["Payment_Gateway"],
            data_sensitivity=DataSensitivity.LOW,
            access_type=AccessType.READ_ONLY,
        ),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2027, 1, 1), iso27001=True, gdpr_dpa=False),
        breach_history=[],
        financial_rating="A",
        under_investigation=False,
        handles_eu_data=True,  # handles EU data but no DPA — small penalty only
    ),

    # EC-10: Genuinely ambiguous — old breach (18mo), medium sensitivity, expiring cert (45 days),
    # B- rating. Should land in MEDIUM. Tests that weighted scoring doesn't over-fire.
    Vendor(
        vendor_id="VND-9010",
        name="AmbiguousMiddleGround Co",
        category="Software",
        contract_start=date(2023, 1, 1),
        contract_end=date(2026, 12, 31),
        data_access=DataAccess(
            systems=["Ticketing_System", "CRM"],
            data_sensitivity=DataSensitivity.MEDIUM,
            access_type=AccessType.READ_WRITE,
        ),
        compliance=Compliance(
            soc2_type2=True,
            soc2_expiry=TODAY + timedelta(days=45),
            iso27001=False,
            gdpr_dpa=True,
        ),
        breach_history=[BreachEvent(
            date=TODAY - timedelta(days=548),  # ~18 months ago — decayed, no floor
            severity=Severity.LOW,
            description="Minor config exposure, no confirmed data exfiltration",
        )],
        financial_rating="B-",
        under_investigation=False,
        handles_eu_data=False,
    ),
]


def append_edge_cases_to_csvs(out_dir: Path) -> None:
    """Append edge case vendors to existing CSVs (or create them if missing)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    registry_path = out_dir / "vendor_registry.csv"
    labels_path = out_dir / "vendor_labels.csv"

    reg_exists = registry_path.exists()
    lbl_exists = labels_path.exists()

    with open(registry_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=VENDOR_FIELDS)
        if not reg_exists:
            w.writeheader()
        for v in EDGE_CASE_VENDORS:
            w.writerow(_vendor_row(v))

    with open(labels_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LABEL_FIELDS)
        if not lbl_exists:
            w.writeheader()
        for v in EDGE_CASE_VENDORS:
            w.writerow(_label_row(compute_label(v)))

    print(f"[edge_cases] Appended {len(EDGE_CASE_VENDORS)} edge case vendors to {registry_path}")
    print(f"[edge_cases] Appended {len(EDGE_CASE_VENDORS)} edge case labels to {labels_path}")

    # print expected labels for review
    print("\n[edge_cases] Expected labels:")
    for v in EDGE_CASE_VENDORS:
        lbl = compute_label(v)
        print(f"  {v.vendor_id} ({v.name[:30]:<30}) → {lbl.severity.value:10s} {lbl.anomaly_type.value}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Append edge case vendors to CSVs.")
    parser.add_argument("--out-dir", type=str, default=".", help="Directory containing CSVs")
    args = parser.parse_args()
    append_edge_cases_to_csvs(Path(args.out_dir))
