"""
data/bulk_ingest.py — Bulk CSV ingestion for the vendor registry.

Parses an uploaded CSV file (as raw bytes) and normalizes each row into a
canonical Vendor object. Jatin wires this into POST /api/vendors/bulk-upload.

Public API:
    ingest_csv_bytes(raw_bytes) -> (vendors, errors)
        vendors: list of successfully normalized Vendor objects
        errors:  list of per-row error dicts with row number, raw row, and message
"""

from __future__ import annotations

import csv
import io
from typing import Any

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.schema import Vendor
from data.normalize import normalize_csv_row


def ingest_csv_bytes(raw_bytes: bytes) -> tuple[list[Vendor], list[dict[str, Any]]]:
    """
    Parse CSV bytes and normalize each row into a Vendor.

    Args:
        raw_bytes: Raw bytes of the uploaded CSV file.

    Returns:
        A tuple of (vendors, errors) where:
          - vendors is a list of successfully normalized Vendor objects
          - errors is a list of dicts with keys: row, data, error
    """
    text = raw_bytes.decode("utf-8-sig", errors="replace")  # strip BOM if present
    reader = csv.DictReader(io.StringIO(text))

    vendors: list[Vendor] = []
    errors: list[dict[str, Any]] = []

    for row_num, row in enumerate(reader, start=2):  # row 1 is the header
        raw = {k.strip(): (v.strip() if v else "") for k, v in row.items() if k}
        try:
            vendor = normalize_csv_row(raw)
            vendors.append(vendor)
        except Exception as exc:
            errors.append({
                "row": row_num,
                "data": raw,
                "error": str(exc),
            })

    return vendors, errors
