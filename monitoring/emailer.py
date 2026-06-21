"""
monitoring/emailer.py — Email notifications for risk alerts and monthly summaries.

Backends (priority order):
  - ResendBackend: sends real email via Resend REST API (needs RESEND_API_KEY
    and ALERT_EMAIL_TO in .env — free tier at resend.com)
  - SMTPBackend: sends real email via smtplib (needs SMTP_HOST, SMTP_PORT,
    SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO in .env)
  - ConsoleBackend: prints the full email content to stdout (clearly labeled
    "WOULD HAVE SENT:") — active when no credentials are configured.

Use get_emailer() to get the right backend automatically — it never blocks.

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

_LEVEL_COLOR = {
    "CRITICAL": {"bg": "#dc2626", "light": "#fef2f2", "border": "#fca5a5"},
    "HIGH":     {"bg": "#ea580c", "light": "#fff7ed", "border": "#fdba74"},
    "MEDIUM":   {"bg": "#d97706", "light": "#fffbeb", "border": "#fcd34d"},
    "LOW":      {"bg": "#16a34a", "light": "#f0fdf4", "border": "#86efac"},
}

_BASE_STYLE = """
  body{margin:0;padding:0;background:#f3f4f6;font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2937}
  .wrap{max-width:680px;margin:24px auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.1)}
  .hdr{background:#0f172a;padding:24px 32px}
  .hdr h1{margin:0;color:#fff;font-size:20px;font-weight:700;letter-spacing:.5px}
  .hdr p{margin:6px 0 0;color:#94a3b8;font-size:13px}
  .body{padding:28px 32px}
  .section-title{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:#6b7280;margin:24px 0 10px}
  .stat-row{display:flex;gap:12px;margin-bottom:20px}
  .stat{flex:1;border-radius:6px;padding:14px 10px;text-align:center}
  .stat-num{font-size:28px;font-weight:700;line-height:1}
  .stat-lbl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;margin-top:4px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{background:#f8fafc;padding:9px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#6b7280;border-bottom:2px solid #e2e8f0}
  td{padding:10px 12px;border-bottom:1px solid #f1f5f9;vertical-align:top}
  tr:last-child td{border-bottom:none}
  .badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;color:#fff}
  .vid{font-size:12px;color:#6b7280}
  .footer{padding:16px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#9ca3af;text-align:center}
"""

def _html_wrap(title: str, subtitle: str, body_html: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{_BASE_STYLE}</style></head><body>
<div class="wrap">
  <div class="hdr">
    <h1>&#x1F6E1; Vendor Risk Platform</h1>
    <p>{title} &nbsp;·&nbsp; {subtitle}</p>
  </div>
  <div class="body">{body_html}</div>
  <div class="footer">Generated automatically &nbsp;·&nbsp; Vendor Risk Platform &nbsp;·&nbsp; Do not reply</div>
</div></body></html>"""


def _badge(level: str) -> str:
    c = _LEVEL_COLOR.get(level, {})
    bg = c.get("bg", "#6b7280")
    return f'<span class="badge" style="background:{bg}">{level}</span>'


def _monthly_summary_html(scored: list[ScoredVendor], today: date) -> str:
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for sv in scored:
        counts[sv.risk_level.value] = counts.get(sv.risk_level.value, 0) + 1

    stat_html = '<div class="stat-row">'
    for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        c = _LEVEL_COLOR[lvl]
        stat_html += (
            f'<div class="stat" style="background:{c["light"]};border:1px solid {c["border"]}">'
            f'<div class="stat-num" style="color:{c["bg"]}">{counts[lvl]}</div>'
            f'<div class="stat-lbl" style="color:{c["bg"]}">{lvl}</div></div>'
        )
    stat_html += f'</div><p style="color:#6b7280;font-size:13px">Total vendors tracked: <strong>{len(scored)}</strong></p>'

    critical_vendors = [sv for sv in scored if sv.risk_level == RiskLevel.CRITICAL]
    high_vendors     = [sv for sv in scored if sv.risk_level == RiskLevel.HIGH]

    table_html = ""
    if critical_vendors:
        table_html += '<div class="section-title" style="color:#dc2626">&#x26A0; Critical Vendors — Immediate Action Required</div>'
        table_html += """<table><thead><tr>
          <th>Vendor ID</th><th>Score</th><th>Risk Level</th><th>Top Risk Factor</th><th>Recommended Action</th>
        </tr></thead><tbody>"""
        for sv in critical_vendors[:20]:
            c = _LEVEL_COLOR["CRITICAL"]
            factor = (sv.risk_factors[0][:90] + "…") if sv.risk_factors and len(sv.risk_factors[0]) > 90 else (sv.risk_factors[0] if sv.risk_factors else "—")
            rec = (sv.recommendation[:100] + "…") if len(sv.recommendation) > 100 else sv.recommendation
            table_html += (
                f'<tr style="background:{c["light"]}">'
                f'<td><strong>{sv.vendor_id}</strong></td>'
                f'<td><strong style="color:{c["bg"]}">{sv.risk_score:.0f}</strong></td>'
                f'<td>{_badge("CRITICAL")}</td>'
                f'<td class="vid">{factor}</td>'
                f'<td class="vid">{rec}</td></tr>'
            )
        table_html += "</tbody></table>"

    if high_vendors:
        table_html += '<div class="section-title" style="color:#ea580c;margin-top:28px">High Priority Vendors</div>'
        table_html += """<table><thead><tr>
          <th>Vendor ID</th><th>Score</th><th>Risk Level</th><th>Top Risk Factor</th><th>Recommended Action</th>
        </tr></thead><tbody>"""
        for sv in high_vendors[:15]:
            c = _LEVEL_COLOR["HIGH"]
            factor = (sv.risk_factors[0][:90] + "…") if sv.risk_factors and len(sv.risk_factors[0]) > 90 else (sv.risk_factors[0] if sv.risk_factors else "—")
            rec = (sv.recommendation[:100] + "…") if len(sv.recommendation) > 100 else sv.recommendation
            table_html += (
                f'<tr>'
                f'<td><strong>{sv.vendor_id}</strong></td>'
                f'<td><strong style="color:{c["bg"]}">{sv.risk_score:.0f}</strong></td>'
                f'<td>{_badge("HIGH")}</td>'
                f'<td class="vid">{factor}</td>'
                f'<td class="vid">{rec}</td></tr>'
            )
        table_html += "</tbody></table>"

    return stat_html + table_html


def _alert_table_html(alerts: list, label: str, level: str) -> str:
    if not alerts:
        return ""
    c = _LEVEL_COLOR.get(level, _LEVEL_COLOR["HIGH"])
    html = (
        f'<div class="section-title" style="color:{c["bg"]};margin-top:24px">'
        f'&#x1F6A8; {label} ({len(alerts)})</div>'
        '<table><thead><tr>'
        '<th>Vendor</th><th>Severity</th><th>Alert Type</th><th>Message</th>'
        '</tr></thead><tbody>'
    )
    for a in alerts:
        ac = _LEVEL_COLOR.get(a.severity, _LEVEL_COLOR["MEDIUM"])
        html += (
            f'<tr style="background:{ac["light"]}">'
            f'<td><strong>{a.vendor_id}</strong><br><span class="vid">{a.vendor_name}</span></td>'
            f'<td>{_badge(a.severity)}</td>'
            f'<td class="vid">{a.alert_type}</td>'
            f'<td class="vid">{a.message}</td></tr>'
        )
    return html + "</tbody></table>"


def _expiry_alert_html(alerts: list[Alert], today: date) -> str:
    critical = [a for a in alerts if a.severity == "CRITICAL"]
    high     = [a for a in alerts if a.severity == "HIGH"]
    others   = [a for a in alerts if a.severity not in ("CRITICAL", "HIGH")]
    summary = (
        f'<p style="margin:0 0 16px;font-size:13px;color:#374151">'
        f'<strong>{len(alerts)}</strong> active alert(s) — '
        f'<span style="color:#dc2626;font-weight:700">{len(critical)} CRITICAL</span>, '
        f'<span style="color:#ea580c;font-weight:700">{len(high)} HIGH</span>, '
        f'{len(others)} other</p>'
    )
    return (
        summary
        + _alert_table_html(critical, "Critical Alerts", "CRITICAL")
        + _alert_table_html(high, "High Alerts", "HIGH")
        + _alert_table_html(others, "Other Alerts", "MEDIUM")
    )


def _eod_digest_html(alerts: list[Alert], today: date) -> str:
    return _expiry_alert_html(alerts, today)


# ── Plain-text fallbacks (used by SMTP/Console backends) ─────────────────────

def _monthly_summary_text(scored: list[ScoredVendor], today: date) -> tuple[str, str]:
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for sv in scored:
        counts[sv.risk_level.value] = counts.get(sv.risk_level.value, 0) + 1
    critical_vendors = [sv for sv in scored if sv.risk_level == RiskLevel.CRITICAL]
    high_vendors     = [sv for sv in scored if sv.risk_level == RiskLevel.HIGH]
    subject = f"[Vendor Risk] Monthly Summary — {today.strftime('%B %Y')} | {counts['CRITICAL']} CRITICAL, {counts['HIGH']} HIGH"
    lines = [
        "VENDOR RISK MANAGEMENT — MONTHLY SUMMARY",
        f"Period: {today.strftime('%B %Y')}   |   Generated: {today.isoformat()}",
        "=" * 60, "",
        "PORTFOLIO OVERVIEW",
        f"  Total vendors tracked : {len(scored)}",
        f"  CRITICAL              : {counts['CRITICAL']}",
        f"  HIGH                  : {counts['HIGH']}",
        f"  MEDIUM                : {counts['MEDIUM']}",
        f"  LOW                   : {counts['LOW']}", "",
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
    lines += ["—", "Vendor Risk Platform — automated report."]
    return subject, "\n".join(lines)


def _expiry_alert_text(alerts: list[Alert], today: date) -> tuple[str, str]:
    critical = [a for a in alerts if a.severity == "CRITICAL"]
    high     = [a for a in alerts if a.severity == "HIGH"]
    others   = [a for a in alerts if a.severity not in ("CRITICAL", "HIGH")]
    subject = f"[Vendor Risk ALERT] {len(critical)} CRITICAL, {len(high)} HIGH alerts — {today.isoformat()}"
    lines = ["VENDOR RISK — EXPIRY & BREACH ALERTS", f"Date: {today.isoformat()}   |   Total: {len(alerts)}", "=" * 60, ""]
    for group, header in [(critical, "CRITICAL"), (high, "HIGH"), (others, "OTHER")]:
        if group:
            lines.append(f"{header} ALERTS")
            for a in group:
                lines += [f"  [{a.vendor_id}] {a.vendor_name}", f"  Type: {a.alert_type}", f"  {a.message}", ""]
    lines += ["—", "Vendor Risk Platform — automated alert."]
    return subject, "\n".join(lines)


def _eod_digest_text(alerts: list[Alert], today: date) -> tuple[str, str]:
    subject = f"[Vendor Risk] EOD Digest — {len(alerts)} new alert(s) today ({today.isoformat()})"
    body = _expiry_alert_text(alerts, today)[1]
    return subject, body


# ── Backend protocol ──────────────────────────────────────────────────────────

class EmailBackend(Protocol):
    def send_monthly_summary(self, scored: list[ScoredVendor], today: date | None) -> None: ...
    def send_expiry_alerts(self, alerts: list[Alert], today: date | None) -> None: ...
    def send_eod_digest(self, alerts: list[Alert], today: date | None) -> None: ...


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

    def send_eod_digest(
        self,
        alerts: list[Alert],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        if not alerts:
            print("[emailer] EOD digest: no new alerts today.", flush=True)
            return
        subject, body = _eod_digest_text(alerts, today)
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

    def send_eod_digest(
        self,
        alerts: list[Alert],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        if not alerts:
            return
        subject, body = _eod_digest_text(alerts, today)
        self._send(subject, body)


# ── Slack backend ─────────────────────────────────────────────────────────────

class SlackBackend:
    """Posts rich alert messages to a Slack incoming webhook.
    Set SLACK_WEBHOOK_URL in .env to activate.
    Gracefully falls back to ConsoleBackend if requests is not installed or webhook fails.
    """

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url
        self._console = ConsoleBackend()

    def _post(self, payload: dict) -> None:
        try:
            import requests
            resp = requests.post(self.webhook_url, json=payload, timeout=5)
            resp.raise_for_status()
            print("[emailer/slack] Message posted to Slack.", flush=True)
        except Exception as exc:
            print(f"[emailer/slack] Webhook failed ({exc}); falling back to console.", file=sys.stderr)
            self._console._print(
                str(payload.get("text", "Vendor Risk Alert")),
                str(payload.get("blocks", "")),
            )

    def send_monthly_summary(
        self,
        scored: list[ScoredVendor],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        counts = {lvl: 0 for lvl in ("CRITICAL", "HIGH", "MEDIUM", "LOW")}
        for sv in scored:
            counts[sv.risk_level.value] = counts.get(sv.risk_level.value, 0) + 1

        payload = {
            "text": f"Vendor Risk Monthly Summary — {today.strftime('%B %Y')}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"Vendor Risk Monthly Summary — {today.strftime('%B %Y')}"},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Total Vendors:* {len(scored)}"},
                        {"type": "mrkdwn", "text": f"*CRITICAL:* {counts['CRITICAL']}"},
                        {"type": "mrkdwn", "text": f"*HIGH:* {counts['HIGH']}"},
                        {"type": "mrkdwn", "text": f"*MEDIUM:* {counts['MEDIUM']}"},
                        {"type": "mrkdwn", "text": f"*LOW:* {counts['LOW']}"},
                    ],
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "_Generated automatically by Vendor Risk Platform. Contact security team for action items._",
                    },
                },
            ],
        }
        self._post(payload)

    def send_expiry_alerts(
        self,
        alerts: list[Alert],
        today: date | None = None,
    ) -> None:
        today = today or date.today()
        if not alerts:
            return

        critical = [a for a in alerts if a.severity == "CRITICAL"]
        high = [a for a in alerts if a.severity == "HIGH"]

        alert_lines = []
        for a in (critical + high)[:10]:
            alert_lines.append(f"• *[{a.vendor_id}] {a.vendor_name}* — {a.message}")

        payload = {
            "text": f"Vendor Risk ALERT: {len(critical)} CRITICAL, {len(high)} HIGH alerts — {today.isoformat()}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"Vendor Risk Alerts — {today.isoformat()}"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":red_circle: *CRITICAL:* {len(critical)}   "
                            f":large_orange_circle: *HIGH:* {len(high)}   "
                            f"*Total:* {len(alerts)}"
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(alert_lines) or "_No critical/high alerts_"},
                },
            ],
        }
        self._post(payload)

    def send_eod_digest(
        self,
        alerts: list[Alert],
        today: date | None = None,
    ) -> None:
        self.send_expiry_alerts(alerts, today)


# ── Resend backend ────────────────────────────────────────────────────────────

class ResendBackend:
    """Sends email via the Resend REST API (https://resend.com).

    Required env vars:
      RESEND_API_KEY   — API key from resend.com
      ALERT_EMAIL_TO   — recipient address (must match your Resend account email
                         if using the shared onboarding@resend.dev sender)
    Optional:
      ALERT_EMAIL_FROM — override sender (needs a verified domain on Resend)
    """

    def __init__(self, api_key: str, to_addr: str, from_addr: str) -> None:
        self.api_key = api_key
        self.to_addr = to_addr
        self.from_addr = from_addr

    def _send(self, subject: str, text: str, html: str) -> None:
        import resend as resend_sdk
        resend_sdk.api_key = self.api_key
        result = resend_sdk.Emails.send({
            "from": self.from_addr,
            "to": [self.to_addr],
            "subject": subject,
            "html": html,
            "text": text,
        })
        print(f"[emailer] Resend: sent '{subject}' → id={getattr(result, 'id', result)}", flush=True)

    def send_monthly_summary(self, scored: list[ScoredVendor], today: date | None = None) -> None:
        today = today or date.today()
        subject, text = _monthly_summary_text(scored, today)
        html_body = _monthly_summary_html(scored, today)
        html = _html_wrap(f"Monthly Summary — {today.strftime('%B %Y')}", f"Generated {today.isoformat()}", html_body)
        self._send(subject, text, html)

    def send_expiry_alerts(self, alerts: list[Alert], today: date | None = None) -> None:
        today = today or date.today()
        if not alerts:
            return
        subject, text = _expiry_alert_text(alerts, today)
        html_body = _expiry_alert_html(alerts, today)
        html = _html_wrap("Expiry &amp; Breach Alerts", f"{today.isoformat()}", html_body)
        self._send(subject, text, html)

    def send_eod_digest(self, alerts: list[Alert], today: date | None = None) -> None:
        today = today or date.today()
        if not alerts:
            return
        subject, text = _eod_digest_text(alerts, today)
        html_body = _eod_digest_html(alerts, today)
        html = _html_wrap("End-of-Day Alert Digest", f"{today.isoformat()}", html_body)
        self._send(subject, text, html)


# ── Factory ───────────────────────────────────────────────────────────────────

def get_emailer() -> ResendBackend | SlackBackend | SMTPBackend | ConsoleBackend:
    """
    Return the best available notification backend.
    Priority: Resend > Slack > SMTP > Console.
    """
    # Priority 1: Resend
    resend_key = os.getenv("RESEND_API_KEY", "")
    resend_to  = os.getenv("ALERT_EMAIL_TO", "")
    if resend_key and resend_to:
        from_addr = os.getenv("ALERT_EMAIL_FROM", "Vendor Risk Platform <onboarding@resend.dev>")
        return ResendBackend(api_key=resend_key, to_addr=resend_to, from_addr=from_addr)

    # Priority 2: Slack
    slack_url = os.getenv("SLACK_WEBHOOK_URL", "")
    if slack_url:
        return SlackBackend(slack_url)

    # Priority 2: SMTP
    host      = os.getenv("SMTP_HOST", "")
    port_str  = os.getenv("SMTP_PORT", "587")
    user      = os.getenv("SMTP_USER", "")
    password  = os.getenv("SMTP_PASS", "")
    from_addr = os.getenv("ALERT_EMAIL_FROM", user)
    to_addr   = os.getenv("ALERT_EMAIL_TO", "")

    if host and user and password and to_addr:
        try:
            port = int(port_str)
            return SMTPBackend(
                host=host,
                port=port,
                user=user,
                password=password,
                from_addr=from_addr,
                to_addr=to_addr,
            )
        except Exception as exc:
            print(f"[emailer] SMTP setup failed ({exc}), falling back to console.", file=sys.stderr)

    return ConsoleBackend()


def slack_configured() -> bool:
    """Return True if a Slack webhook URL is set in the environment."""
    return bool(os.getenv("SLACK_WEBHOOK_URL", ""))
