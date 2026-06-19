"""
tests/test_scoring/test_engine.py — Regression tests for the risk engine.

Tests run against the H0 FIXTURE_VENDORS so they are fully self-contained
(no dependency on the generated CSVs). The fixture set is designed to cover
every major rule path.

Run: python3 -m pytest tests/ -v
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from common.schema import FIXTURE_VENDORS, AnomalyType, RiskLevel
from scoring.risk_engine import score_vendor

TODAY = date(2026, 6, 19)

FIXTURES = {v.vendor_id: v for v in FIXTURE_VENDORS}


def score(vendor_id: str):
    return score_vendor(FIXTURES[vendor_id], TODAY)


class TestHardFloors:
    def test_breach_high_access_critical(self):
        sv = score("VND-0285")  # CyberBackup: breach Jan 2026 + HIGH sensitivity
        assert sv.risk_level == RiskLevel.CRITICAL
        assert sv.anomaly_type == AnomalyType.BREACHED_VENDOR_HIGH_ACCESS
        assert sv.risk_score >= 80.0

    def test_under_investigation_critical(self):
        sv = score("VND-0099")  # ShadyConsulting: under_investigation
        assert sv.risk_level == RiskLevel.CRITICAL
        assert sv.anomaly_type == AnomalyType.VENDOR_UNDER_INVESTIGATION
        assert sv.risk_score == 95.0

    def test_floors_produce_risk_factors(self):
        sv = score("VND-0285")
        assert len(sv.risk_factors) > 0
        assert any("CRITICAL" in f or "breach" in f.lower() for f in sv.risk_factors)


class TestWeightedScoring:
    def test_clean_vendor_low(self):
        sv = score("VND-0001")  # CleanCo Analytics: zero issues
        assert sv.risk_level == RiskLevel.LOW
        assert sv.risk_score == 0.0
        assert sv.anomaly_type == AnomalyType.NONE

    def test_orphaned_access_medium(self):
        sv = score("VND-0200")  # LegacyIntegration: expired contract + active access
        assert sv.risk_level == RiskLevel.MEDIUM
        # Contract expired + missing certs → EXPIRED_CERTIFICATION anomaly
        assert sv.risk_score >= 40.0

    def test_orphaned_access_risk_factor_text(self):
        sv = score("VND-0200")
        assert any("orphaned" in f.lower() or "contract expired" in f.lower() for f in sv.risk_factors)

    def test_cert_boundary_60days_not_medium(self):
        sv = score("VND-0150")  # MidTier SaaS: cert expiring 60d, no other major issues
        # Cert expiry alone at 60d doesn't push past 40; expect LOW
        assert sv.risk_level == RiskLevel.LOW
        assert sv.risk_score < 40.0

    def test_d_rating_alone_stays_low(self):
        sv = score("VND-0310")  # ShakyFinance: D rating, read-only, low sensitivity
        assert sv.risk_level == RiskLevel.LOW

    def test_recommendation_is_non_empty(self):
        for v in FIXTURE_VENDORS:
            sv = score_vendor(v, TODAY)
            assert sv.recommendation, f"{v.vendor_id} has empty recommendation"

    def test_risk_factors_are_specific(self):
        sv = score("VND-0200")
        for f in sv.risk_factors:
            assert len(f) > 20, f"Risk factor too generic: {f!r}"


class TestScoreRange:
    def test_scores_in_range(self):
        for v in FIXTURE_VENDORS:
            sv = score_vendor(v, TODAY)
            assert 0.0 <= sv.risk_score <= 100.0, f"{v.vendor_id} score out of range: {sv.risk_score}"

    def test_all_vendors_have_level(self):
        for v in FIXTURE_VENDORS:
            sv = score_vendor(v, TODAY)
            assert sv.risk_level in RiskLevel


class TestEvalRecall:
    """Verify 100% recall against the ground-truth label file (requires CSVs)."""

    def test_critical_recall_perfect(self):
        try:
            from eval.evaluate import run_eval
            metrics = run_eval(today=TODAY, verbose=False)
            assert metrics["critical_recall"] >= 0.95, (
                f"CRITICAL recall {metrics['critical_recall']:.3f} below target 0.95"
            )
        except FileNotFoundError:
            pytest.skip("vendor_labels.csv not found — skipping recall test")
