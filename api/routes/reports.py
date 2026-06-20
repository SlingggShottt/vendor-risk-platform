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
from data.compliance_export import build_compliance_summary, export_to_csv as _build_compliance_csv, export_to_json as _build_compliance_json, format_vendor_for_compliance_export

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


@router.get("/compliance-export")
def compliance_export(format: str = "json"):
    """
    Export vendor compliance summary + per-vendor compliance rows.
    ?format=json (default) or ?format=csv
    """
    store = _get_store()
    entries = list(store.values())
    today = date.today()

    vendors  = [e["vendor"]  for e in entries]
    scored   = [e["scored"]  for e in entries]

    summary = build_compliance_summary(vendors, scored, today)
    rows    = [format_vendor_for_compliance_export(v, sv) for v, sv in zip(vendors, scored)]
    rows.sort(key=lambda r: r["risk_score"], reverse=True)

    if format.lower() == "csv":
        csv_str = _build_compliance_csv(rows)
        filename = f"compliance_export_{today.isoformat()}.csv"
        return Response(
            content=csv_str,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return {
        "generated_at": today.isoformat(),
        "summary": summary.model_dump(mode="json"),
        "vendors": rows,
    }


@router.get("/pdf")
def export_pdf():
    """Generate and download a PDF portfolio report using fpdf2 (pure Python, no system deps)."""
    from fpdf import FPDF

    store = _get_store()
    entries = list(store.values())
    today = date.today()
    total = len(entries)

    level_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for e in entries:
        level_counts[e["scored"].risk_level.value] += 1

    vendors = [e["vendor"] for e in entries]
    n_soc2 = sum(1 for v in vendors if v.compliance.soc2_type2
                 and (not v.compliance.soc2_expiry or v.compliance.soc2_expiry >= today))
    n_iso  = sum(1 for v in vendors if v.compliance.iso27001)
    n_gdpr = sum(1 for v in vendors if not v.handles_eu_data or v.compliance.gdpr_dpa)

    red_flags = sorted(
        [e for e in entries if e["scored"].risk_level.value in ("CRITICAL", "HIGH")],
        key=lambda e: e["scored"].risk_score, reverse=True,
    )

    LEVEL_COLOR = {
        "CRITICAL": (197, 48, 48),
        "HIGH":     (192, 86, 33),
        "MEDIUM":   (151, 90, 22),
        "LOW":      (39, 103, 73),
    }

    pdf = FPDF()
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    # ── Title ─────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(26, 32, 44)
    pdf.cell(0, 10, "Vendor Risk Portfolio Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(113, 128, 150)
    pdf.cell(0, 6, f"Generated: {today.isoformat()}    |    {total} vendors tracked",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(6)

    # ── Risk Distribution ─────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(26, 32, 44)
    pdf.cell(0, 8, "Risk Distribution", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    box_w = 42
    for level, count in level_counts.items():
        r, g, b = LEVEL_COLOR[level]
        pdf.set_fill_color(r, g, b)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(box_w, 12, str(count), align="C", fill=True)
        pdf.set_font("Helvetica", "", 8)
        x = pdf.get_x() - box_w
        pdf.set_xy(x, pdf.get_y() + 12)
        pdf.set_text_color(r, g, b)
        pdf.cell(box_w, 5, level, align="C")
        pdf.set_xy(pdf.get_x(), pdf.get_y() - 12)

    pdf.ln(20)

    # ── Compliance Coverage ───────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(26, 32, 44)
    pdf.cell(0, 8, "Compliance Coverage", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    comp_items = [
        (f"{round(100*n_soc2/total) if total else 0}%", "SOC 2 Type II"),
        (f"{round(100*n_iso/total) if total else 0}%",  "ISO 27001"),
        (f"{round(100*n_gdpr/total) if total else 0}%", "GDPR DPA"),
    ]
    for val, label in comp_items:
        pdf.set_fill_color(247, 248, 250)
        pdf.set_text_color(45, 55, 72)
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(55, 10, val, align="C", fill=True)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(113, 128, 150)
        x = pdf.get_x() - 55
        pdf.set_xy(x, pdf.get_y() + 10)
        pdf.cell(55, 5, label, align="C")
        pdf.set_xy(pdf.get_x(), pdf.get_y() - 10)

    pdf.ln(18)

    # ── Red-Flag Vendors table ────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(26, 32, 44)
    pdf.cell(0, 8, f"Critical & High Risk Vendors (top {min(50, len(red_flags))})",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Header row
    col_w = [22, 48, 32, 20, 18, 40]
    headers = ["ID", "Vendor", "Category", "Risk", "Score", "Top Risk Factor"]
    pdf.set_fill_color(247, 248, 250)
    pdf.set_text_color(113, 128, 150)
    pdf.set_font("Helvetica", "B", 7)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h.upper(), border="B", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for e in red_flags[:50]:
        v, sv = e["vendor"], e["scored"]
        r, g, b = LEVEL_COLOR.get(sv.risk_level.value, (51, 51, 51))
        top_factor = (sv.risk_factors[0][:45] + "...") if sv.risk_factors and len(sv.risk_factors[0]) > 45 else (sv.risk_factors[0] if sv.risk_factors else "-")

        pdf.set_text_color(45, 55, 72)
        pdf.cell(col_w[0], 6, v.vendor_id, border="B")
        name = (v.name[:26] + "...") if len(v.name) > 26 else v.name
        pdf.cell(col_w[1], 6, name, border="B")
        cat = (v.category[:20] + "...") if len(v.category) > 20 else v.category
        pdf.cell(col_w[2], 6, cat, border="B")
        pdf.set_text_color(r, g, b)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(col_w[3], 6, sv.risk_level.value, border="B")
        pdf.set_text_color(45, 55, 72)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(col_w[4], 6, f"{sv.risk_score:.1f}", border="B")
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(col_w[5], 6, top_factor, border="B")
        pdf.set_font("Helvetica", "", 8)
        pdf.ln()

        if pdf.get_y() > 270:  # new page before overflow
            pdf.add_page()
            pdf.set_font("Helvetica", "", 8)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.ln(8)
    pdf.set_draw_color(226, 232, 240)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(160, 174, 192)
    pdf.cell(0, 5, f"Vendor Risk Platform  |  Confidential  |  {today.isoformat()}", align="C")

    pdf_bytes = bytes(pdf.output())
    filename = f"vendor_risk_report_{today.isoformat()}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
