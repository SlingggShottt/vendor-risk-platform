"""
monitoring/emailer.py — Email notifications for risk alerts and monthly summaries.

Two backends:
  - SMTPBackend: sends real email via smtplib (needs SMTP_HOST, SMTP_PORT,
    SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO in .env)
  - ConsoleBackend: prints the full email content to stdout (clearly labeled
    "WOULD HAVE SENT:") — active when SMTP credentials are absent.

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


# ── Factory ───────────────────────────────────────────────────────────────────

def get_emailer() -> ConsoleBackend | SMTPBackend:
    """
    Return the appropriate email backend.
    Uses SMTP if SMTP_HOST, SMTP_USER, SMTP_PASS are all set in environment.
    Falls back to ConsoleBackend (prints to stdout) if any credential is missing.
    """
    host     = os.getenv("SMTP_HOST", "")
    port_str = os.getenv("SMTP_PORT", "587")
    user     = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASS", "")
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
        except Exception as e:
            print(f"[emailer] SMTP setup failed ({e}), falling back to console.", file=sys.stderr)

    return ConsoleBackend()
