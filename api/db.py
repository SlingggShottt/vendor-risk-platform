"""
api/db.py — SQLAlchemy models + engine (agreed shape from H0 planning).

Currently operating in CSV-first mode (per memory.md H0:30 decision).
The SQLAlchemy models are defined here so seed_db.py can load them later
without changing the API's query logic.

To switch from CSV-first to SQLite:
  1. Run data/seed_db.py to populate vendor_risk.db
  2. Set USE_SQLITE=true in .env
  3. The API will read from SQLite instead of in-memory CSV load
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

_DB_URL = os.getenv("DATABASE_URL", "sqlite:///./vendor_risk.db")
engine = create_engine(_DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class VendorRow(Base):
    """Flat vendor registry table — mirrors vendor_registry.csv columns."""
    __tablename__ = "vendors"

    vendor_id        = Column(String, primary_key=True, index=True)
    name             = Column(String, nullable=False)
    category         = Column(String)
    contract_start   = Column(Date)
    contract_end     = Column(Date)
    data_sensitivity = Column(String)
    access_type      = Column(String)
    systems          = Column(Text)        # pipe-separated
    soc2_type2       = Column(Boolean, default=False)
    soc2_expiry      = Column(Date, nullable=True)
    iso27001         = Column(Boolean, default=False)
    gdpr_dpa         = Column(Boolean, default=False)
    breach_count     = Column(Integer, default=0)
    latest_breach_date        = Column(Date, nullable=True)
    latest_breach_severity    = Column(String, nullable=True)
    latest_breach_description = Column(Text, nullable=True)
    financial_rating = Column(String)
    annual_spend     = Column(Float, nullable=True)
    under_investigation = Column(Boolean, default=False)
    handles_eu_data  = Column(Boolean, default=False)


class ScoredVendorRow(Base):
    """Cached scoring results table."""
    __tablename__ = "scored_vendors"

    vendor_id    = Column(String, primary_key=True, index=True)
    risk_score   = Column(Float)
    risk_level   = Column(String)
    risk_factors = Column(Text)   # JSON list
    recommendation = Column(Text)
    anomaly_type = Column(String)
    severity     = Column(String)
    scored_at    = Column(Date)


def get_db():
    """FastAPI dependency: yields a SQLAlchemy session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)
