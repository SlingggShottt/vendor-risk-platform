"""
common/schema.py — THE SHARED CONTRACT

Divyansh produces data conforming to `Vendor`. Jatin consumes `Vendor` and
produces `ScoredVendor`. Edit this file only with explicit agreement between
both people (see CLAUDE.md). Log any change in memory.md.

This file intentionally also includes a small set of FIXTURE_VENDORS — written
together at H0 — so Jatin can build/test the scoring engine immediately,
without waiting on Divyansh's real generator.
"""

from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ---------- Enums (use these everywhere — never hardcode the string literal) ----------

class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AccessType(str, Enum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    NONE = "none"


class DataSensitivity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AnomalyType(str, Enum):
    BREACHED_VENDOR_HIGH_ACCESS = "BREACHED_VENDOR_HIGH_ACCESS"
    VENDOR_UNDER_INVESTIGATION = "VENDOR_UNDER_INVESTIGATION"
    HIGH_RISK_SCORE = "HIGH_RISK_SCORE"
    EXPIRED_CERTIFICATION = "EXPIRED_CERTIFICATION"
    RECENTLY_BREACHED_VENDOR = "RECENTLY_BREACHED_VENDOR"
    CONTRACT_EXPIRED_ACTIVE_ACCESS = "CONTRACT_EXPIRED_ACTIVE_ACCESS"
    ELEVATED_RISK_VENDOR = "ELEVATED_RISK_VENDOR"
    NONE = "NONE"  # clean vendor, nothing flagged


# ---------- Input model (Divyansh's output shape) ----------

class BreachEvent(BaseModel):
    date: date
    severity: Severity
    description: str


class DataAccess(BaseModel):
    systems: list[str] = Field(default_factory=list)
    data_sensitivity: DataSensitivity
    access_type: AccessType


class Compliance(BaseModel):
    soc2_type2: bool = False
    soc2_expiry: Optional[date] = None
    iso27001: bool = False
    gdpr_dpa: bool = False


class Vendor(BaseModel):
    """Canonical vendor record. All data, anywhere in the system, normalizes to this."""
    vendor_id: str  # format: "VND-XXXX"
    name: str
    category: str
    contract_start: date
    contract_end: date
    data_access: DataAccess
    compliance: Compliance
    breach_history: list[BreachEvent] = Field(default_factory=list)
    financial_rating: str  # "A", "A-", "B", "C", "D" etc.
    annual_spend: Optional[float] = None
    under_investigation: bool = False
    handles_eu_data: bool = False  # drives whether missing GDPR DPA is penalized

    # NOTE: do NOT set use_enum_values=True — under pydantic v2 it does not reliably
    # flatten enums in model_dump()/CSV export (confirmed: leaves "DataSensitivity.LOW"
    # instead of "LOW"). Since all enums here subclass `str`, use
    # `vendor.model_dump(mode="json")` anywhere you write to CSV/JSON — confirmed this
    # correctly flattens to plain strings ("LOW", not "DataSensitivity.LOW").
    # Plain str(enum_value) does NOT do this correctly — always use mode="json".


# ---------- Output model (Jatin's output shape) ----------

class ScoredVendor(BaseModel):
    """Output of the risk engine. Matches the target shape from the original brief example."""
    vendor_id: str
    risk_score: float  # 0-100
    risk_level: RiskLevel
    risk_factors: list[str]  # human-readable, each tied to a specific triggered rule
    recommendation: str
    anomaly_type: AnomalyType = AnomalyType.NONE
    severity: Severity = Severity.LOW


# ---------- Label model (for eval ground truth, Divyansh produces this too) ----------

class VendorLabel(BaseModel):
    vendor_id: str
    is_anomaly: bool
    anomaly_type: AnomalyType
    severity: Severity
    expired_certifications: list[str] = Field(default_factory=list)
    explanation: str


# ---------- H0 fixtures — hand-write together, covering the key rule paths ----------
# Jatin: import these and run risk_engine against them before real data exists.
# Divyansh: these are your reference for what "messy edge cases" should stress-test.

FIXTURE_VENDORS: list[Vendor] = [
    # 1. Clean vendor — should score LOW, sanity check the happy path
    Vendor(
        vendor_id="VND-0001",
        name="CleanCo Analytics",
        category="Analytics",
        contract_start=date(2024, 1, 1),
        contract_end=date(2027, 1, 1),
        data_access=DataAccess(systems=["Analytics_DB"], data_sensitivity=DataSensitivity.LOW, access_type=AccessType.READ_ONLY),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2027, 1, 1), iso27001=True, gdpr_dpa=True),
        breach_history=[],
        financial_rating="A",
        under_investigation=False,
        handles_eu_data=False,
    ),
    # 2. Breach <12mo + HIGH access -> must hit CRITICAL hard floor
    Vendor(
        vendor_id="VND-0285",
        name="CyberBackup Solutions",
        category="Backup & Disaster Recovery",
        contract_start=date(2023, 6, 1),
        contract_end=date(2026, 6, 1),
        data_access=DataAccess(systems=["Database_Primary", "FileServer_Corporate"], data_sensitivity=DataSensitivity.HIGH, access_type=AccessType.READ_WRITE),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2026, 9, 15), iso27001=False, gdpr_dpa=False),
        breach_history=[BreachEvent(date=date(2026, 1, 15), severity=Severity.MEDIUM, description="Unencrypted backup exposed on S3")],
        financial_rating="B",
        under_investigation=False,
        handles_eu_data=True,
    ),
    # 3. Under investigation -> CRITICAL hard floor
    Vendor(
        vendor_id="VND-0099",
        name="ShadyConsulting LLC",
        category="Consulting",
        contract_start=date(2025, 1, 1),
        contract_end=date(2026, 12, 31),
        data_access=DataAccess(systems=["HR_System"], data_sensitivity=DataSensitivity.MEDIUM, access_type=AccessType.READ_WRITE),
        compliance=Compliance(soc2_type2=False, iso27001=False, gdpr_dpa=False),
        breach_history=[],
        financial_rating="C",
        under_investigation=True,
        handles_eu_data=False,
    ),
    # 4. Cert expiring boundary case (60 days) — alert boundary test
    Vendor(
        vendor_id="VND-0150",
        name="MidTier SaaS Co",
        category="SaaS",
        contract_start=date(2024, 6, 1),
        contract_end=date(2027, 6, 1),
        data_access=DataAccess(systems=["CRM"], data_sensitivity=DataSensitivity.MEDIUM, access_type=AccessType.READ_WRITE),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2026, 8, 18), iso27001=False, gdpr_dpa=True),  # ~60 days from 2026-06-19
        breach_history=[],
        financial_rating="B",
        under_investigation=False,
        handles_eu_data=True,
    ),
    # 5. Orphaned access — contract expired, data_access still populated
    Vendor(
        vendor_id="VND-0200",
        name="LegacyIntegration Corp",
        category="Integration",
        contract_start=date(2021, 1, 1),
        contract_end=date(2025, 12, 31),  # expired relative to "today" 2026-06-19
        data_access=DataAccess(systems=["FileServer_Corporate"], data_sensitivity=DataSensitivity.MEDIUM, access_type=AccessType.READ_ONLY),
        compliance=Compliance(soc2_type2=False, iso27001=False, gdpr_dpa=False),
        breach_history=[],
        financial_rating="C",
        under_investigation=False,
        handles_eu_data=False,
    ),
    # 6. Low financial rating, otherwise fine
    Vendor(
        vendor_id="VND-0310",
        name="ShakyFinance MSP",
        category="Managed Services",
        contract_start=date(2025, 1, 1),
        contract_end=date(2027, 1, 1),
        data_access=DataAccess(systems=["Monitoring_Tools"], data_sensitivity=DataSensitivity.LOW, access_type=AccessType.READ_ONLY),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2027, 1, 1), iso27001=False, gdpr_dpa=True),
        breach_history=[],
        financial_rating="D",
        under_investigation=False,
        handles_eu_data=False,
    ),
    # 7. Missing GDPR DPA despite handling EU data, otherwise clean
    Vendor(
        vendor_id="VND-0420",
        name="EuroPay Processing",
        category="Payment Processor",
        contract_start=date(2024, 3, 1),
        contract_end=date(2027, 3, 1),
        data_access=DataAccess(systems=["Payment_Gateway"], data_sensitivity=DataSensitivity.HIGH, access_type=AccessType.READ_WRITE),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2027, 3, 1), iso27001=True, gdpr_dpa=False),
        breach_history=[],
        financial_rating="A-",
        under_investigation=False,
        handles_eu_data=True,
    ),
    # 8. Ambiguous middle case — old breach (>12mo), expired cert, low sensitivity access
    Vendor(
        vendor_id="VND-0512",
        name="OldIncidentVendor Inc",
        category="Software",
        contract_start=date(2022, 1, 1),
        contract_end=date(2026, 12, 31),
        data_access=DataAccess(systems=["Ticketing_System"], data_sensitivity=DataSensitivity.LOW, access_type=AccessType.READ_ONLY),
        compliance=Compliance(soc2_type2=True, soc2_expiry=date(2025, 1, 1), iso27001=False, gdpr_dpa=True),  # expired
        breach_history=[BreachEvent(date=date(2023, 3, 1), severity=Severity.LOW, description="Minor config exposure, no data accessed")],
        financial_rating="B",
        under_investigation=False,
        handles_eu_data=False,
    ),
]

# ---------- Enterprise Sprint: Audit & Compliance Models ----------

class AuditLog(BaseModel):
    """Immutable audit trail entry. Created by monitoring/audit_logger.py."""
    id: str  # unique ID per event (UUID or timestamp-based)
    timestamp: datetime
    actor: str  # username or "system"
    action: str  # "score_updated", "bulk_remediate", "vendor_created", "compliance_export", etc.
    resource_type: str  # "vendor", "alert", "report", etc.
    resource_id: str  # vendor_id or other resource identifier
    old_state: Optional[dict] = None  # previous values (for diffs), as JSON-serializable dict
    new_state: Optional[dict] = None  # new values
    reason: Optional[str] = None  # why the change (from bulk-remediate request, manual update, etc.)


class ComplianceSummary(BaseModel):
    """Portfolio-level compliance statistics. Computed on-demand by reporting endpoints."""
    total_vendors: int
    soc2_coverage_pct: float  # % of vendors with valid SOC2 Type II
    iso27001_coverage_pct: float  # % with valid ISO 27001
    gdpr_compliance_pct: float  # % compliant (no EU data OR has DPA)
    soc2_expiring_60d: int  # count of vendors with SOC2 expiring within 60 days
    orphaned_access_count: int  # count with expired contract + active data_access
    under_investigation_count: int  # count flagged for investigation
    recently_breached_count: int  # count breached within 12 months