"""
api/routes/alerts.py — Email alert trigger endpoints.

POST /api/alerts/send-monthly
  Sends a monthly portfolio summary email using all scored vendors in the store.

POST /api/alerts/send-expiry
  Sends per-vendor expiry/breach alert emails for all active alerts in the store.

Email is sent via SMTP when SMTP_HOST/SMTP_USER/SMTP_PASS are set in the environment;
falls back to console logging (ConsoleBackend) when credentials are absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi import APIRouter

router = APIRouter(tags=["alerts"])


def _get_store() -> dict:
    from api.main import app
    return app.state.store


def _get_today():
    from api.main import app
    return app.state.today


@router.post("/api/alerts/send-monthly")
def send_monthly_summary():
    """Send a monthly risk summary email for the full vendor portfolio."""
    from monitoring.emailer import get_emailer

    store = _get_store()
    today = _get_today()

    scored_vendors = [entry["scored"] for entry in store.values()]

    emailer = get_emailer()
    emailer.send_monthly_summary(scored_vendors, today)

    backend = type(emailer).__name__
    return {
        "status": "sent",
        "backend": backend,
        "vendors_included": len(scored_vendors),
        "message": (
            f"Monthly summary sent via {backend} for {len(scored_vendors)} vendors."
            if backend != "ConsoleBackend"
            else "SMTP not configured — email printed to console (ConsoleBackend). "
                 "Set SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO in .env to send real email."
        ),
    }


@router.post("/api/alerts/send-expiry")
def send_expiry_alerts():
    """Send expiry/breach alert emails for all active alerts in the vendor portfolio."""
    from monitoring.emailer import get_emailer

    store = _get_store()
    today = _get_today()

    all_alerts = []
    for entry in store.values():
        all_alerts.extend(entry["alerts"])

    emailer = get_emailer()
    emailer.send_expiry_alerts(all_alerts, today)

    backend = type(emailer).__name__
    return {
        "status": "sent",
        "backend": backend,
        "alerts_included": len(all_alerts),
        "message": (
            f"Expiry alerts sent via {backend} covering {len(all_alerts)} alerts."
            if backend != "ConsoleBackend"
            else "SMTP not configured — alerts printed to console (ConsoleBackend). "
                 "Set SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL_TO in .env to send real email."
        ),
    }
