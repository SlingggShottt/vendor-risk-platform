"""
api/routes/reports.py — Portfolio risk report and CSV export endpoints.

Report format mirrors the brief's example:
  - Risk summary (counts per level)
  - Red-flag vendors (CRITICAL + HIGH)
  - Compliance stats (cert coverage, orphaned access, etc.)
  - Actionable recommendations

CSV export returns all scored vendors as a flat CSV.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from common.schema import RiskLevel, ScoredVendor, Vendor

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _get_store():
    from api.main import app
    return app.state.store


@router.get("")
def portfolio_report():
    """
    Full portfolio risk report. Matches the brief's report format:
    risk summary, red-flag vendors, compliance stats.
    """
    store = _get_store()
    entries = list(store.values())
    today = date.today()

    vendors:  list[Vendor]       = [e["vendor"]  for e in entries]
    scored:   list[ScoredVendor] = [e["scored"]  for e in entries]

    # ── Risk level counts ─────────────────────────────────────────────────────
    level_counts = {lvl.value: 0 for lvl in RiskLevel}
    for sv in scored:
        level_counts[sv.risk_level.value] += 1

    # ── Compliance stats ──────────────────────────────────────────────────────
    total = len(vendors)
    n_soc2_ok  = sum(1 for v in vendors
                     if v.compliance.soc2_type2
                     and (v.compliance.soc2_expiry is None or v.compliance.soc2_expiry >= today))
    n_iso      = sum(1 for v in vendors if v.compliance.iso27001)
    n_gdpr_ok  = sum(1 for v in vendors if not v.handles_eu_data or v.compliance.gdpr_dpa)
    n_soc2_expiring = sum(
        1 for v in vendors
        if v.compliance.soc2_type2
        and v.compliance.soc2_expiry
        and 0 <= (v.compliance.soc2_expiry - today).days <= 60
    )
    n_orphaned = sum(
        1 for v in vendors
        if v.contract_end < today and bool(v.data_access.systems)
    )
    n_under_inv = sum(1 for v in vendors if v.under_investigation)
    n_breached_recent = sum(
        1 for v in vendors
        if v.breach_history
        and (today - max(b.date for b in v.breach_history)).days / 30.44 <= 12
    )

    # ── Red-flag vendors (CRITICAL + HIGH) ────────────────────────────────────
    red_flags = [
        {
            "vendor_id": e["vendor"].vendor_id,
            "name": e["vendor"].name,
            "category": e["vendor"].category,
            "risk_level": e["scored"].risk_level.value,
            "risk_score": e["scored"].risk_score,
            "anomaly_type": e["scored"].anomaly_type.value,
            "top_risk_factor": e["scored"].risk_factors[0] if e["scored"].risk_factors else "",
            "recommendation": e["scored"].recommendation,
        }
        for e in entries
        if e["scored"].risk_level in (RiskLevel.CRITICAL, RiskLevel.HIGH)
    ]
    red_flags.sort(key=lambda x: x["risk_score"], reverse=True)

    # ── Alert counts ──────────────────────────────────────────────────────────
    all_alerts = [a for e in entries for a in e.get("alerts", [])]
    alert_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for a in all_alerts:
        alert_counts[a.severity] = alert_counts.get(a.severity, 0) + 1

    return {
        "generated_at": today.isoformat(),
        "total_vendors": total,
        "risk_summary": level_counts,
        "compliance_stats": {
            "soc2_coverage_pct": round(100 * n_soc2_ok / total, 1) if total else 0,
            "iso27001_coverage_pct": round(100 * n_iso / total, 1) if total else 0,
            "gdpr_compliance_pct": round(100 * n_gdpr_ok / total, 1) if total else 0,
            "soc2_expiring_60d": n_soc2_expiring,
            "orphaned_access_count": n_orphaned,
            "under_investigation_count": n_under_inv,
            "recently_breached_count": n_breached_recent,
        },
        "alert_summary": alert_counts,
        "red_flag_vendors": red_flags,
        "top_recommendations": [
            "Immediately review all CRITICAL vendors with the CISO.",
            "Revoke access for vendors with expired contracts (orphaned access).",
            f"Renew SOC 2 certifications for {n_soc2_expiring} vendor(s) expiring within 60 days.",
            "Require GDPR Data Processing Agreements from all EU-data vendors.",
        ],
    }


@router.get("/csv")
def export_csv():
    """Export all scored vendors as a flat CSV download."""
    store = _get_store()
    entries = list(store.values())
    entries.sort(key=lambda e: e["scored"].risk_score, reverse=True)

    output = io.StringIO()
    fieldnames = [
        "vendor_id", "name", "category",
        "risk_score", "risk_level", "anomaly_type", "severity",
        "contract_end", "financial_rating",
        "data_sensitivity", "access_type",
        "soc2_type2", "soc2_expiry", "iso27001", "gdpr_dpa",
        "under_investigation", "handles_eu_data",
        "breach_count",
        "top_risk_factor", "recommendation",
        "alert_count",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    today = date.today()
    for e in entries:
        v: Vendor       = e["vendor"]
        sv: ScoredVendor = e["scored"]
        alerts = e.get("alerts", [])
        writer.writerow({
            "vendor_id": v.vendor_id,
            "name": v.name,
            "category": v.category,
            "risk_score": sv.risk_score,
            "risk_level": sv.risk_level.value,
            "anomaly_type": sv.anomaly_type.value,
            "severity": sv.severity.value,
            "contract_end": v.contract_end.isoformat(),
            "financial_rating": v.financial_rating,
            "data_sensitivity": v.data_access.data_sensitivity.value,
            "access_type": v.data_access.access_type.value,
            "soc2_type2": v.compliance.soc2_type2,
            "soc2_expiry": v.compliance.soc2_expiry.isoformat() if v.compliance.soc2_expiry else "",
            "iso27001": v.compliance.iso27001,
            "gdpr_dpa": v.compliance.gdpr_dpa,
            "under_investigation": v.under_investigation,
            "handles_eu_data": v.handles_eu_data,
            "breach_count": len(v.breach_history),
            "top_risk_factor": sv.risk_factors[0] if sv.risk_factors else "",
            "recommendation": sv.recommendation,
            "alert_count": len(alerts),
        })

    output.seek(0)
    filename = f"vendor_risk_report_{today.isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
