"""
eval/evaluate.py — Precision/recall evaluation of the risk engine against ground truth.

Outputs:
  - Overall precision/recall/F1 (binary: anomaly vs clean)
  - Severity-level classification report (LOW/MEDIUM/HIGH/CRITICAL)
  - CRITICAL recall and HIGH recall separately (the metrics that matter per PRD §6)
  - Per-vendor diff for any misclassified CRITICAL/HIGH rows

Usage:
  python eval/evaluate.py [--registry PATH] [--labels PATH] [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    precision_score,
    recall_score,
    f1_score,
)

from common.schema import AnomalyType, Severity, FIXTURE_VENDORS
from data.normalize import normalize_csv_row
from scoring.risk_engine import score_vendor

_DEFAULT_REGISTRY = Path(__file__).parent.parent / "data" / "vendor_registry.csv"
_DEFAULT_LABELS   = Path(__file__).parent.parent / "data" / "vendor_labels.csv"
_SEVERITY_ORDER   = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def load_vendors(registry_path: Path) -> dict[str, object]:
    """Load vendor_registry.csv → {vendor_id: Vendor}."""
    vendors = {}
    with open(registry_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                v = normalize_csv_row(row)
                vendors[v.vendor_id] = v
            except Exception as e:
                print(f"  [WARN] Skipping {row.get('vendor_id', '?')}: {e}", file=sys.stderr)
    return vendors


def load_labels(labels_path: Path) -> dict[str, dict]:
    """Load vendor_labels.csv → {vendor_id: label_row}."""
    labels = {}
    with open(labels_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            labels[row["vendor_id"]] = row
    return labels


def run_eval(
    registry_path: Path = _DEFAULT_REGISTRY,
    labels_path: Path   = _DEFAULT_LABELS,
    today: date | None  = None,
    verbose: bool       = True,
) -> dict:
    """
    Score all vendors in registry, compare to labels, return metrics dict.
    Also includes FIXTURE_VENDORS for a quick sanity check (not counted in metrics).
    """
    if today is None:
        today = date.today()

    vendors = load_vendors(registry_path)
    labels  = load_labels(labels_path)

    matched_ids = sorted(set(vendors) & set(labels))
    if not matched_ids:
        raise ValueError("No vendor IDs overlap between registry and labels.")

    y_true_sev: list[str] = []
    y_pred_sev: list[str] = []
    misclassified_critical_high: list[dict] = []

    for vid in matched_ids:
        vendor = vendors[vid]
        label  = labels[vid]
        scored = score_vendor(vendor, today)

        true_sev = label["severity"]
        pred_sev = scored.severity.value

        y_true_sev.append(true_sev)
        y_pred_sev.append(pred_sev)

        if true_sev in ("CRITICAL", "HIGH") and pred_sev != true_sev:
            misclassified_critical_high.append({
                "vendor_id": vid,
                "name": vendor.name,
                "true_severity": true_sev,
                "pred_severity": pred_sev,
                "true_anomaly": label["anomaly_type"],
                "pred_anomaly": scored.anomaly_type.value,
                "risk_score": scored.risk_score,
                "explanation": label.get("explanation", ""),
                "risk_factors": scored.risk_factors,
            })

    # ── Binary anomaly metrics ─────────────────────────────────────────────────
    y_true_bin = [1 if s != "LOW" else 0 for s in y_true_sev]
    y_pred_bin = [1 if s != "LOW" else 0 for s in y_pred_sev]

    bin_precision = precision_score(y_true_bin, y_pred_bin, zero_division=0)
    bin_recall    = recall_score(y_true_bin, y_pred_bin, zero_division=0)
    bin_f1        = f1_score(y_true_bin, y_pred_bin, zero_division=0)

    # ── Per-severity recall (the number we care about most) ───────────────────
    sev_recall: dict[str, float] = {}
    for sev in _SEVERITY_ORDER:
        true_pos = sum(1 for t, p in zip(y_true_sev, y_pred_sev) if t == sev and p == sev)
        true_total = y_true_sev.count(sev)
        sev_recall[sev] = true_pos / true_total if true_total else 1.0

    critical_recall = sev_recall["CRITICAL"]
    high_recall     = sev_recall["HIGH"]

    # ── Print report ──────────────────────────────────────────────────────────
    if verbose:
        n = len(matched_ids)
        print(f"\n{'='*60}")
        print(f"  Risk Engine Evaluation  ({n} vendors, today={today})")
        print(f"{'='*60}")

        print(f"\n  Binary anomaly detection (any severity > LOW):")
        print(f"    Precision : {bin_precision:.3f}")
        print(f"    Recall    : {bin_recall:.3f}")
        print(f"    F1        : {bin_f1:.3f}")

        print(f"\n  Per-severity recall (KEY METRIC):")
        for sev in _SEVERITY_ORDER:
            total = y_true_sev.count(sev)
            tp    = sum(1 for t, p in zip(y_true_sev, y_pred_sev) if t == sev and p == sev)
            flag  = " ← TARGET" if sev in ("CRITICAL", "HIGH") else ""
            print(f"    {sev:8s}: {sev_recall[sev]:.3f}  ({tp}/{total}){flag}")

        print(f"\n  CRITICAL recall: {critical_recall:.3f}  (target ≥ 0.95)")
        print(f"  HIGH recall    : {high_recall:.3f}  (target ≥ 0.90)")

        if misclassified_critical_high:
            print(f"\n  Misclassified CRITICAL/HIGH vendors ({len(misclassified_critical_high)}):")
            for m in misclassified_critical_high[:10]:
                print(f"    {m['vendor_id']} {m['name'][:30]:<30} "
                      f"true={m['true_severity']} pred={m['pred_severity']} "
                      f"score={m['risk_score']:.1f}")
                print(f"      label: {m['explanation'][:80]}")
                if m['risk_factors']:
                    print(f"      engine: {m['risk_factors'][0][:80]}")
        else:
            print("\n  No CRITICAL/HIGH misclassifications.")

        # Fixture sanity check
        print(f"\n  Fixture vendor sanity check ({len(FIXTURE_VENDORS)} vendors):")
        for v in FIXTURE_VENDORS:
            sv = score_vendor(v, today)
            print(f"    {v.vendor_id} {v.name[:28]:<28} "
                  f"→ {sv.risk_level.value:8s} score={sv.risk_score:.1f} "
                  f"[{sv.anomaly_type.value}]")

        print(f"\n{'='*60}\n")

    return {
        "n_vendors": len(matched_ids),
        "binary_precision": bin_precision,
        "binary_recall": bin_recall,
        "binary_f1": bin_f1,
        "severity_recall": sev_recall,
        "critical_recall": critical_recall,
        "high_recall": high_recall,
        "n_misclassified_critical_high": len(misclassified_critical_high),
        "misclassified": misclassified_critical_high,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate risk engine against ground truth labels.")
    parser.add_argument("--registry", default=str(_DEFAULT_REGISTRY), help="Path to vendor_registry.csv")
    parser.add_argument("--labels",   default=str(_DEFAULT_LABELS),   help="Path to vendor_labels.csv")
    parser.add_argument("--today",    default=None, help="Override today's date (YYYY-MM-DD)")
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else None
    metrics = run_eval(
        registry_path=Path(args.registry),
        labels_path=Path(args.labels),
        today=today,
    )

    if metrics["critical_recall"] < 0.95:
        print("  WARNING: CRITICAL recall below 0.95 — tune rubric weights and re-run.")
        sys.exit(1)
    print("  PASS: CRITICAL recall ≥ 0.95")


if __name__ == "__main__":
    main()
