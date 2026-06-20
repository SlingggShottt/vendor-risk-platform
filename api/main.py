"""
api/main.py — FastAPI application entry point.

Startup: loads vendor_registry.csv → normalizes → scores all vendors → caches
in app.state.store so all routes read from the same in-memory dict.

Routes:
  /                  → vendor list dashboard (HTML)
  /vendor/{id}       → vendor detail page (HTML)
  /reports                   → portfolio report page (HTML)
  /extract                   → contract extraction page (HTML)
  /api/vendors               → JSON vendor list + filter
  /api/vendors/{id}          → JSON vendor detail
  /api/reports               → JSON portfolio report
  /api/reports/csv           → CSV download
  /api/extract               → POST contract text → extracted fields + risk score
  /api/sample-contracts      → list sample contracts
  /api/sample-contracts/{n}  → get sample contract text

Run with:
  uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from data.normalize import normalize_csv_row
from scoring.risk_engine import score_vendor
from monitoring.alerts import check_alerts
from api.routes.vendors import router as vendors_router
from api.routes.reports import router as reports_router
from api.routes.extract import router as extract_router
from api.routes.alerts import router as alerts_router
from api.routes.bulk import router as bulk_router
from api.routes.audit import router as audit_router
from monitoring.scheduler import start_scheduler

_REGISTRY_CSV = Path(__file__).parent.parent / "data" / "vendor_registry.csv"
_TEMPLATES_DIR = Path(__file__).parent.parent / "dashboard" / "templates"
_STATIC_DIR    = Path(__file__).parent.parent / "dashboard" / "static"

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(title="Vendor Risk Platform", version="1.0.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_ALLOWED_ORIGINS = [
    "http://localhost",
    "http://localhost:8000",
    "https://vendor-risk-platform.onrender.com",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

app.include_router(vendors_router)
app.include_router(reports_router)
app.include_router(extract_router)
app.include_router(alerts_router)
app.include_router(bulk_router)
app.include_router(audit_router)


# ── Startup: load + score all vendors ────────────────────────────────────────

@app.on_event("startup")
def startup_event() -> None:
    today = date.today()
    store: dict[str, dict] = {}

    with open(_REGISTRY_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                vendor = normalize_csv_row(row)
                scored = score_vendor(vendor, today)
                alerts = check_alerts(vendor, today)
                store[vendor.vendor_id] = {
                    "vendor": vendor,
                    "scored": scored,
                    "alerts": alerts,
                }
            except Exception as e:
                print(f"[startup] Skipping {row.get('vendor_id', '?')}: {e}", flush=True)

    app.state.store = store
    app.state.today = today
    app.state.today_alerts = []
    app.state.audit_log = []
    print(f"[startup] Loaded {len(store)} vendors (today={today})", flush=True)

    # Seed the audit log with the startup load event
    from data.audit_helper import create_audit_event
    app.state.audit_log.append(create_audit_event(
        actor="system",
        action="startup_load",
        resource_type="portfolio",
        resource_id="all",
        new_state={"vendor_count": len(store)},
        reason=f"Application startup — loaded {len(store)} vendors from registry CSV",
    ))

    start_scheduler(app)


# ── Dashboard HTML routes ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request):
    store = app.state.store
    entries = list(store.values())

    level_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for e in entries:
        level_counts[e["scored"].risk_level.value] += 1

    all_alerts = [a for e in entries for a in e["alerts"]]
    alert_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for a in all_alerts:
        alert_counts[a.severity] = alert_counts.get(a.severity, 0) + 1

    return templates.TemplateResponse(request, "vendors.html", {
        "total_vendors": len(entries),
        "level_counts": level_counts,
        "alert_counts": alert_counts,
        "today": app.state.today.isoformat(),
    })


@app.get("/vendor/{vendor_id}", response_class=HTMLResponse)
def vendor_detail_page(request: Request, vendor_id: str):
    store = app.state.store
    entry = store.get(vendor_id)
    if not entry:
        return HTMLResponse("<h1>Vendor not found</h1>", status_code=404)

    v = entry["vendor"]
    sv = entry["scored"]
    alerts = entry["alerts"]

    return templates.TemplateResponse(request, "vendor_detail.html", {
        "v": v,
        "sv": sv,
        "alerts": alerts,
        "today": app.state.today.isoformat(),
    })


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html", {
        "today": app.state.today.isoformat(),
    })


@app.get("/extract", response_class=HTMLResponse)
def extract_page(request: Request):
    return templates.TemplateResponse(request, "extract.html", {
        "today": app.state.today.isoformat(),
    })


@app.get("/add-vendor", response_class=HTMLResponse)
def add_vendor_page(request: Request):
    return templates.TemplateResponse(request, "add_vendor.html", {
        "today": app.state.today.isoformat(),
    })
