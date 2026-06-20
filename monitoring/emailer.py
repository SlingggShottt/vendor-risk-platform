"""
monitoring/emailer.py — Email notifications for risk alerts and monthly summaries.

Three backends (selected automatically via get_emailer()):
  - ResendBackend: sends HTML email via Resend API (needs RESEND_API_KEY,
    ALERT_EMAIL_TO in .env). Recommended — no domain setup needed for demo.
  - SMTPBackend: sends email via smtplib (needs SMTP_HOST, SMTP_PORT,
    SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO in .env).
  - ConsoleBackend: prints email content to stdout — active when no credentials found.

Priority: Resend > SMTP > Console.

Usage:
  from monitoring.emailer import get_emailer
  emailer = get_emailer()
  emailer.send_monthly_summary(scored_vendors)
  emailer.send_expiry_alerts(alerts)
"""

from __future__ import annotations

import os
import smtplib
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import RiskLevel, ScoredVendor
from monitoring.alerts import Alert


# ── Email content builders ────────────────────────────────────────────────────

def _monthly_summary_text(
    scored: list[ScoredVendor],
    today: date,
) -> tuple[str, str]:
    """Return (subject, body) for a monthly vendor risk summary email."""
    counts = {lvl: 0 for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    for sv in scored:
        counts[sv.risk_level.value] = counts.get(sv.risk_level.value, 0) + 1

    critical_vendors = [sv for sv in scored if sv.risk_level == RiskLevel.CRITICAL]
    high_vendors     = [sv for sv in scored if sv.risk_level == RiskLevel.HIGH]

    subject = f"[Vendor Risk] Monthly Summary — {today.strftime('%B %Y')} | {counts['CRITICAL']} CRITICAL, {counts['HIGH']} HIGH"

    lines = [
        f"VENDOR RISK MANAGEMENT — MONTHLY SUMMARY",
        f"Period: {today.strftime('%B %Y')}   |   Generated: {today.isoformat()}",
        "=" * 60,
        "",
        "PORTFOLIO OVERVIEW",
        f"  Total vendors tracked : {len(scored)}",
        f"  CRITICAL              : {counts['CRITICAL']}",
        f"  HIGH                  : {counts['HIGH']}",
        f"  MEDIUM                : {counts['MEDIUM']}",
        f"  LOW                   : {counts['LOW']}",
        "",
    ]

    if critical_vendors:
        lines += ["CRITICAL VENDORS — IMMEDIATE ACTION REQUIRED", ""]
        for sv in critical_vendors[:15]:
            lines.append(f"  [{sv.vendor_id}] score={sv.risk_score:.0f}  {sv.anomaly_type.value}")
            if sv.risk_factors:
                lines.append(f"    → {sv.risk_factors[0][:80]}")
            lines.append(f"    Action: {sv.recommendation[:100]}")
            lines.append("")

    if high_vendors:
        lines += ["HIGH PRIORITY VENDORS", ""]
        for sv in high_vendors[:10]:
            lines.append(f"  [{sv.vendor_id}] score={sv.risk_score:.0f}  {sv.anomaly_type.value}")
            lines.append("")

    lines += [
        "—",
        "This report was generated automatically by the Vendor Risk Platform.",
        "Do not reply to this email. Contact the security team for questions.",
    ]

    return subject, "\n".join(lines)


def _expiry_alert_text(alerts: list[Alert], today: date) -> tuple[str, str]:
    """Return (subject, body) for a batch of expiry/breach alerts."""
    critical = [a for a in alerts if a.severity == "CRITICAL"]
    high     = [a for a in alerts if a.severity == "HIGH"]
    others   = [a for a in alerts if a.severity not in ("CRITICAL", "HIGH")]

    subject = (
        f"[Vendor Risk ALERT] {len(critical)} CRITICAL, {len(high)} HIGH alerts — {today.isoformat()}"
    )

    lines = [
        "VENDOR RISK — EXPIRY & BREACH ALERTS",
        f"Date: {today.isoformat()}   |   Total alerts: {len(alerts)}",
        "=" * 60,
        "",
    ]

    def _render(alert_list: list[Alert], header: str) -> None:
        if not alert_list:
            return
        lines.append(header)
        for a in alert_list:
            lines.append(f"  [{a.vendor_id}] {a.vendor_name}")
            lines.append(f"  Type    : {a.alert_type}")
            lines.append(f"  Message : {a.message}")
            lines.append("")

    _render(critical, "CRITICAL ALERTS")
    _render(high,     "HIGH ALERTS")
    _render(others,   "OTHER ALERTS")

    lines += [
        "—",
        "Vendor Risk Platform — automated alert. Contact security team for action items.",
    ]
    return subject, "\n".join(lines)


# ── HTML email builders (used by ResendBackend) ───────────────────────────────

def _monthly_summary_html(scored: list[ScoredVendor], today: date) -> str:
    counts = {lvl: 0 for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
    for sv in scored:
        counts[sv.risk_level.value] = counts.get(sv.risk_level.value, 0) + 1

    colors = {"CRITICAL": "#dc3545", "HIGH": "#fd7e14", "MEDIUM": "#ffc107", "LOW": "#198754"}
    critical_vendors = [sv for sv in scored if sv.risk_level == RiskLevel.CRITICAL][:15]
    high_vendors     = [sv for sv in scored if sv.risk_level == RiskLevel.HIGH][:10]

    stat_cells = "".join(
        f'<td style="text-align:center;padding:12px 20px;">'
        f'<div style="font-size:28px;font-weight:700;color:{colors[lvl]}">{counts[lvl]}</div>'
        f'<div style="font-size:11px;color:#64748b;font-weight:600;letter-spacing:.5px">{lvl}</div>'
        f'</td>'
        for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    )

    def vendor_rows(vendor_list: list[ScoredVendor]) -> str:
        rows = ""
        for sv in vendor_list:
            c = colors.get(sv.risk_level.value, "#6c757d")
            reason = sv.risk_factors[0][:90] if sv.risk_factors else "—"
            rows += (
                f'<tr style="border-bottom:1px solid #f1f5f9;">'
                f'<td style="padding:8px 12px;font-size:13px;font-weight:600;color:#1e293b">{sv.vendor_id}</td>'
                f'<td style="padding:8px 12px;"><span style="background:{c};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">{sv.risk_level.value}</span></td>'
                f'<td style="padding:8px 12px;font-size:13px;color:#475569">{reason}…</td>'
                f'</tr>'
            )
        return rows

    critical_section = ""
    if critical_vendors:
        critical_section = f"""
        <h3 style="color:#dc3545;margin:24px 0 8px">⚠ Critical Vendors — Immediate Action Required</h3>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #fee2e2;border-radius:8px;overflow:hidden">
          <thead><tr style="background:#fee2e2;">
            <th style="padding:8px 12px;font-size:11px;color:#7f1d1d;text-align:left">Vendor</th>
            <th style="padding:8px 12px;font-size:11px;color:#7f1d1d;text-align:left">Level</th>
            <th style="padding:8px 12px;font-size:11px;color:#7f1d1d;text-align:left">Top Risk Factor</th>
          </tr></thead>
          <tbody>{vendor_rows(critical_vendors)}</tbody>
        </table>"""

    high_section = ""
    if high_vendors:
        high_section = f"""
        <h3 style="color:#fd7e14;margin:24px 0 8px">High Priority Vendors</h3>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #fff3cd;border-radius:8px;overflow:hidden">
          <thead><tr style="background:#fff3cd;">
            <th style="padding:8px 12px;font-size:11px;color:#6c4a00;text-align:left">Vendor</th>
            <th style="padding:8px 12px;font-size:11px;color:#6c4a00;text-align:left">Level</th>
            <th style="padding:8px 12px;font-size:11px;color:#6c4a00;text-align:left">Top Risk Factor</th>
          </tr></thead>
          <tbody>{vendor_rows(high_vendors)}</tbody>
        </table>"""

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <div style="max-width:640px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
      <div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);padding:28px 32px;">
        <div style="color:#94a3b8;font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase">Vendor Risk Platform</div>
        <h1 style="color:#fff;margin:8px 0 4px;font-size:22px">Monthly Risk Summary</h1>
        <div style="color:#94a3b8;font-size:13px">{today.strftime('%B %Y')} &nbsp;·&nbsp; Generated {today.isoformat()}</div>
      </div>
      <div style="padding:28px 32px;">
        <h2 style="color:#1e293b;font-size:15px;margin:0 0 16px">Portfolio Overview — {len(scored)} vendors tracked</h2>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin-bottom:24px">
          <tr style="background:#f8fafc">{stat_cells}</tr>
        </table>
        {critical_section}
        {high_section}
        <p style="font-size:12px;color:#94a3b8;margin-top:32px;border-top:1px solid #f1f5f9;padding-top:16px">
          Automated report from Vendor Risk Platform. Do not reply.
        </p>
      </div>
    </div></body></html>"""


def _expiry_alert_html(alerts: list[Alert], today: date) -> str:
    colors = {"CRITICAL": "#dc3545", "HIGH": "#fd7e14", "MEDIUM": "#ffc107", "LOW": "#198754"}
    critical = [a for a in alerts if a.severity == "CRITICAL"]
    high     = [a for a in alerts if a.severity == "HIGH"]
    others   = [a for a in alerts if a.severity not in ("CRITICAL", "HIGH")]

    def alert_rows(alert_list: list[Alert]) -> str:
        rows = ""
        for a in alert_list:
            c = colors.get(a.severity, "#6c757d")
            rows += (
                f'<tr style="border-bottom:1px solid #f1f5f9;">'
                f'<td style="padding:8px 12px;font-size:13px;font-weight:600;color:#1e293b">{a.vendor_id}</td>'
                f'<td style="padding:8px 12px;font-size:13px;color:#334155">{a.vendor_name}</td>'
                f'<td style="padding:8px 12px;"><span style="background:{c};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700">{a.severity}</span></td>'
                f'<td style="padding:8px 12px;font-size:12px;color:#64748b">{a.message}</td>'
                f'</tr>'
            )
        return rows

    def section(alert_list: list[Alert], header: str, border_color: str) -> str:
        if not alert_list:
            return ""
        return f"""
        <h3 style="color:{border_color};margin:24px 0 8px">{header}</h3>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {border_color}33;border-radius:8px;overflow:hidden">
          <thead><tr style="background:{border_color}18;">
            <th style="padding:8px 12px;font-size:11px;text-align:left">ID</th>
            <th style="padding:8px 12px;font-size:11px;text-align:left">Vendor</th>
            <th style="padding:8px 12px;font-size:11px;text-align:left">Severity</th>
            <th style="padding:8px 12px;font-size:11px;text-align:left">Detail</th>
          </tr></thead>
          <tbody>{alert_rows(alert_list)}</tbody>
        </table>"""

    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <div style="max-width:640px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
      <div style="background:linear-gradient(135deg,#7f1d1d,#991b1b);padding:28px 32px;">
        <div style="color:#fca5a5;font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase">Vendor Risk Platform</div>
        <h1 style="color:#fff;margin:8px 0 4px;font-size:22px">⚠ Expiry &amp; Breach Alerts</h1>
        <div style="color:#fca5a5;font-size:13px">{today.isoformat()} &nbsp;·&nbsp; {len(alerts)} alerts total</div>
      </div>
      <div style="padding:28px 32px;">
        {section(critical, "Critical Alerts", "#dc3545")}
        {section(high, "High Priority Alerts", "#fd7e14")}
        {section(others, "Other Alerts", "#6c757d")}
        <p style="font-size:12px;color:#94a3b8;margin-top:32px;border-top:1px solid #f1f5f9;padding-top:16px">
          Automated alert from Vendor Risk Platform. Contact the security team for action items.
        </p>
      </div>
    </div></body></html>"""


# ── Backend protocol ──────────────────────────────────────────────────────────

class EmailBackend(Protocol):
    def send_monthly_summary(self, scored: list[ScoredVendor], today: date | None) -> None: ...
    def send_expiry_alerts(self, alerts: list[Alert], today: date | None) -> None: ...


# ── Console backend (always available, never blocks) ─────────────────────────

class ConsoleBackend:
    """Prints email content to stdout. Active when SMTP credentials are missing."""

    def send_monthly_summary(
        self,
        scored: list[ScoredVendor],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        subject, body = _monthly_summary_text(scored, today)
        self._print(subject, body)

    def send_expiry_alerts(
        self,
        alerts: list[Alert],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        if not alerts:
            print("[emailer] No alerts to send.", flush=True)
            return
        subject, body = _expiry_alert_text(alerts, today)
        self._print(subject, body)

    def _print(self, subject: str, body: str) -> None:
        sep = "─" * 60
        print(f"\n{'='*60}")
        print(f"  WOULD HAVE SENT (no SMTP credentials configured):")
        print(f"{'='*60}")
        print(f"  Subject: {subject}")
        print(sep)
        print(body)
        print(f"{'='*60}\n", flush=True)


# ── SMTP backend ──────────────────────────────────────────────────────────────

class SMTPBackend:
    """Sends real emails via SMTP. Reads credentials from environment."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
        to_addr: str,
        use_tls: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.use_tls = use_tls

    def _send(self, subject: str, body: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(self.host, self.port) as server:
            if self.use_tls:
                server.starttls()
            server.login(self.user, self.password)
            server.sendmail(self.from_addr, [self.to_addr], msg.as_string())
        print(f"[emailer] Sent: {subject}", flush=True)

    def send_monthly_summary(
        self,
        scored: list[ScoredVendor],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        subject, body = _monthly_summary_text(scored, today)
        self._send(subject, body)

    def send_expiry_alerts(
        self,
        alerts: list[Alert],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        if not alerts:
            return
        subject, body = _expiry_alert_text(alerts, today)
        self._send(subject, body)


# ── Resend backend ───────────────────────────────────────────────────────────

class ResendBackend:
    """Sends HTML email via Resend API. Needs RESEND_API_KEY + ALERT_EMAIL_TO."""

    def __init__(self, api_key: str, from_addr: str, to_addr: str) -> None:
        import resend as _resend
        self._resend = _resend
        self._resend.api_key = api_key
        self._from = from_addr
        self._to = to_addr

    def _send(self, subject: str, html: str, text: str) -> None:
        self._resend.Emails.send({
            "from": self._from,
            "to": [self._to],
            "subject": subject,
            "html": html,
            "text": text,
        })
        print(f"[emailer/resend] Sent: {subject}", flush=True)

    def send_monthly_summary(
        self,
        scored: list[ScoredVendor],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        subject, text = _monthly_summary_text(scored, today)
        html = _monthly_summary_html(scored, today)
        self._send(subject, html, text)

    def send_expiry_alerts(
        self,
        alerts: list[Alert],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        if not alerts:
            return
        subject, text = _expiry_alert_text(alerts, today)
        html = _expiry_alert_html(alerts, today)
        self._send(subject, html, text)


# ── Factory ───────────────────────────────────────────────────────────────────

def get_emailer() -> ResendBackend | ConsoleBackend | SMTPBackend:
    """
    Return the best available email backend.
    Priority: Resend (RESEND_API_KEY) > SMTP > ConsoleBackend.
    Never raises — always returns something that works.
    """
    to_addr = os.getenv("ALERT_EMAIL_TO", "")

    # 1. Resend (preferred)
    resend_key = os.getenv("RESEND_API_KEY", "")
    if resend_key and to_addr:
        from_addr = os.getenv("ALERT_EMAIL_FROM", "Vendor Risk Platform <onboarding@resend.dev>")
        try:
            return ResendBackend(api_key=resend_key, from_addr=from_addr, to_addr=to_addr)
        except Exception as e:
            print(f"[emailer] Resend setup failed ({e}), trying SMTP.", file=sys.stderr)

    # 2. SMTP
    host     = os.getenv("SMTP_HOST", "")
    port_str = os.getenv("SMTP_PORT", "587")
    user     = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASS", "")
    from_addr = os.getenv("ALERT_EMAIL_FROM", user)

    if host and user and password and to_addr:
        try:
            return SMTPBackend(
                host=host, port=int(port_str), user=user,
                password=password, from_addr=from_addr, to_addr=to_addr,
            )
        except Exception as e:
            print(f"[emailer] SMTP setup failed ({e}), falling back to console.", file=sys.stderr)

    # 3. Console fallback
    return ConsoleBackend()
