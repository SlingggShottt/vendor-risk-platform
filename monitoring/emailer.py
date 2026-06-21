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


def _eod_digest_text(alerts: list[Alert], today: date) -> tuple[str, str]:
    """Return (subject, body) for the 5pm EOD digest of alerts raised today."""
    critical = [a for a in alerts if a.severity == "CRITICAL"]
    high     = [a for a in alerts if a.severity == "HIGH"]
    others   = [a for a in alerts if a.severity not in ("CRITICAL", "HIGH")]

    subject = (
        f"[Vendor Risk] EOD Digest — {len(alerts)} new alert(s) today ({today.isoformat()})"
    )

    lines = [
        "VENDOR RISK — END-OF-DAY ALERT DIGEST",
        f"Date: {today.isoformat()}   |   New alerts raised today: {len(alerts)}",
        "=" * 60,
        "",
    ]

    def _render(alert_list: list[Alert], header: str) -> None:
        if not alert_list:
            return
        lines.append(header)
        for a in alert_list:
            lines.append(f"  [{a.vendor_id}] {a.vendor_name}  (added {a.triggered_at.strftime('%H:%M UTC')})")
            lines.append(f"  Type    : {a.alert_type}")
            lines.append(f"  Message : {a.message}")
            lines.append("")

    _render(critical, "CRITICAL ALERTS")
    _render(high,     "HIGH ALERTS")
    _render(others,   "OTHER ALERTS")

    lines += [
        "—",
        "Vendor Risk Platform — automated EOD digest. Contact security team for action items.",
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

    def _send(self, subject: str, body: str) -> None:
        import resend as resend_sdk
        resend_sdk.api_key = self.api_key
        result = resend_sdk.Emails.send({
            "from": self.from_addr,
            "to": [self.to_addr],
            "subject": subject,
            "text": body,
        })
        print(f"[emailer] Resend: sent '{subject}' → id={getattr(result, 'id', result)}", flush=True)

    def send_monthly_summary(self, scored: list[ScoredVendor], today: date | None = None) -> None:
        today = today or date.today()
        subject, body = _monthly_summary_text(scored, today)
        self._send(subject, body)

    def send_expiry_alerts(self, alerts: list[Alert], today: date | None = None) -> None:
        today = today or date.today()
        if not alerts:
            return
        subject, body = _expiry_alert_text(alerts, today)
        self._send(subject, body)

    def send_eod_digest(self, alerts: list[Alert], today: date | None = None) -> None:
        today = today or date.today()
        if not alerts:
            return
        subject, body = _eod_digest_text(alerts, today)
        self._send(subject, body)


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
