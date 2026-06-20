"""
monitoring/scheduler.py — Scheduled daily alert job.

Starts a background APScheduler that fires daily at 08:00 UTC.
Job: check all vendors in the in-memory store, email any CRITICAL/HIGH alerts.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def _run_daily_alerts(app) -> None:
    try:
        store = app.state.store
        from monitoring.alerts import Alert
        from monitoring.emailer import get_emailer

        all_alerts: list[Alert] = [
            a for entry in store.values() for a in entry["alerts"]
        ]
        critical_high = [a for a in all_alerts if a.severity in ("CRITICAL", "HIGH")]

        if critical_high:
            emailer = get_emailer()
            emailer.send_expiry_alerts(critical_high)
            logger.info("[scheduler] Sent alert email for %d CRITICAL/HIGH alerts", len(critical_high))
        else:
            logger.info("[scheduler] Daily check complete — no CRITICAL/HIGH alerts")
    except Exception as e:
        logger.error("[scheduler] Daily job failed: %s", e)


def start_scheduler(app) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _run_daily_alerts,
        trigger=CronTrigger(hour=8, minute=0, timezone="UTC"),
        args=[app],
        id="daily_alerts",
        name="Daily vendor alert check",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[scheduler] Started — daily alerts job at 08:00 UTC")
    return scheduler
