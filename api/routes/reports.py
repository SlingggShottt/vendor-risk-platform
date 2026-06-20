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
from fastapi.responses import Response, StreamingResponse

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


@router.get("/pdf")
def export_pdf():
    """Generate and download a PDF portfolio report using WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="weasyprint not installed — run: pip install weasyprint")

    store = _get_store()
    entries = list(store.values())
    today = date.today()

    level_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for e in entries:
        level_counts[e["scored"].risk_level.value] += 1

    red_flags = sorted(
        [e for e in entries if e["scored"].risk_level.value in ("CRITICAL", "HIGH")],
        key=lambda e: e["scored"].risk_score, reverse=True
    )

    total = len(entries)
    vendors = [e["vendor"] for e in entries]
    n_soc2 = sum(1 for v in vendors if v.compliance.soc2_type2
                 and (not v.compliance.soc2_expiry or v.compliance.soc2_expiry >= today))
    n_iso  = sum(1 for v in vendors if v.compliance.iso27001)
    n_gdpr = sum(1 for v in vendors if not v.handles_eu_data or v.compliance.gdpr_dpa)

    LEVEL_COLOR = {"CRITICAL": "#c53030", "HIGH": "#c05621", "MEDIUM": "#975a16", "LOW": "#276749"}

    rows_html = ""
    for e in red_flags[:50]:
        v, sv = e["vendor"], e["scored"]
        color = LEVEL_COLOR.get(sv.risk_level.value, "#333")
        rows_html += f"""
        <tr>
          <td>{v.vendor_id}</td>
          <td>{v.name}</td>
          <td>{v.category}</td>
          <td style="color:{color}; font-weight:700">{sv.risk_level.value}</td>
          <td>{sv.risk_score:.1f}</td>
          <td style="font-size:10px">{sv.risk_factors[0] if sv.risk_factors else '—'}</td>
        </tr>"""

    html = f"""
    <!DOCTYPE html><html><head><meta charset="UTF-8">
    <style>
      body {{ font-family: Arial, sans-serif; font-size: 12px; color: #1a202c; margin: 40px; }}
      h1 {{ font-size: 20px; color: #1a202c; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
      h2 {{ font-size: 14px; color: #2d3748; margin-top: 24px; }}
      .stats {{ display: flex; gap: 24px; margin: 16px 0; }}
      .stat {{ text-align: center; padding: 12px 20px; border-radius: 6px; }}
      .critical {{ background: #fff5f5; color: #c53030; }}
      .high {{ background: #fffaf0; color: #c05621; }}
      .medium {{ background: #fffff0; color: #975a16; }}
      .low {{ background: #f0fff4; color: #276749; }}
      .stat-num {{ font-size: 28px; font-weight: 800; }}
      .stat-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
      th {{ background: #f7f8fa; text-align: left; padding: 8px; font-size: 10px;
            text-transform: uppercase; letter-spacing: 0.4px; color: #718096; }}
      td {{ padding: 8px; border-top: 1px solid #edf2f7; font-size: 11px; }}
      .compliance {{ display: flex; gap: 24px; margin: 12px 0; }}
      .comp-item {{ padding: 10px 16px; background: #f7f8fa; border-radius: 6px; }}
      .comp-val {{ font-size: 20px; font-weight: 700; color: #2d3748; }}
      .comp-label {{ font-size: 10px; color: #718096; }}
      .footer {{ margin-top: 32px; font-size: 10px; color: #a0aec0; border-top: 1px solid #e2e8f0; padding-top: 8px; }}
    </style></head><body>
    <h1>Vendor Risk Portfolio Report</h1>
    <p style="color:#718096">Generated: {today.isoformat()} &nbsp;|&nbsp; {total} vendors tracked</p>

    <h2>Risk Distribution</h2>
    <div class="stats">
      <div class="stat critical"><div class="stat-num">{level_counts["CRITICAL"]}</div><div class="stat-label">Critical</div></div>
      <div class="stat high"><div class="stat-num">{level_counts["HIGH"]}</div><div class="stat-label">High</div></div>
      <div class="stat medium"><div class="stat-num">{level_counts["MEDIUM"]}</div><div class="stat-label">Medium</div></div>
      <div class="stat low"><div class="stat-num">{level_counts["LOW"]}</div><div class="stat-label">Low</div></div>
    </div>

    <h2>Compliance Coverage</h2>
    <div class="compliance">
      <div class="comp-item"><div class="comp-val">{round(100*n_soc2/total)}%</div><div class="comp-label">SOC 2 Type II</div></div>
      <div class="comp-item"><div class="comp-val">{round(100*n_iso/total)}%</div><div class="comp-label">ISO 27001</div></div>
      <div class="comp-item"><div class="comp-val">{round(100*n_gdpr/total)}%</div><div class="comp-label">GDPR DPA</div></div>
    </div>

    <h2>Critical & High Risk Vendors (top {min(50, len(red_flags))})</h2>
    <table>
      <thead><tr><th>ID</th><th>Vendor</th><th>Category</th><th>Risk</th><th>Score</th><th>Top Factor</th></tr></thead>
      <tbody>{rows_html}</tbody>
    </table>

    <div class="footer">Vendor Risk Platform &nbsp;|&nbsp; Confidential &nbsp;|&nbsp; {today.isoformat()}</div>
    </body></html>"""

    pdf_bytes = HTML(string=html).write_pdf()
    filename = f"vendor_risk_report_{today.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
