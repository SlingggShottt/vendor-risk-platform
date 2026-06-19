#!/usr/bin/env python3
"""
extraction/merge_extracted.py — Merge LLM-extracted contract fields into the vendor registry.

Reads vendor_registry.csv and one or more extracted contract JSON files (output of
extract_contract.py), then writes an updated CSV where extracted fields override the
corresponding registry row for matching vendor_ids.

This is a non-destructive merge: if a field is null/missing in the extracted output,
the existing registry value is kept. vendor_ids not found in the registry are appended
as new rows (with a warning).

Usage:
    # Merge a single extracted JSON dict (piped from extract_contract.py):
    python extraction/extract_contract.py extraction/sample_contracts/contract_VND0285_cyberbackup.txt \\
      | python extraction/merge_extracted.py --registry data/vendor_registry.csv

    # Merge a batch JSON array:
    python extraction/extract_contract.py --batch extraction/sample_contracts/ \\
      | python extraction/merge_extracted.py --registry data/vendor_registry.csv

    # Merge from a saved JSON file:
    python extraction/merge_extracted.py --registry data/vendor_registry.csv --input extracted.json

    # Dry-run: print merged CSV to stdout instead of overwriting:
    python extraction/merge_extracted.py --registry data/vendor_registry.csv --dry-run
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any


# Fields from extracted output that map directly to registry CSV column names.
# "vendor_name" → "name" via the normalize.py alias, but in the CSV the column
# header is "name" (as written by generate_vendors.py using model_dump(mode="json")).
_EXTRACT_TO_CSV: dict[str, str] = {
    "vendor_name": "name",
    "category": "category",
    "contract_start": "contract_start",
    "contract_end": "contract_end",
    "systems": "systems",          # pipe-separated string in both formats
    "data_sensitivity": "data_sensitivity",
    "access_type": "access_type",
    "soc2_type2": "soc2_type2",
    "soc2_expiry": "soc2_expiry",
    "iso27001": "iso27001",
    "gdpr_dpa": "gdpr_dpa",
    "handles_eu_data": "handles_eu_data",
    "financial_rating": "financial_rating",
    "annual_spend": "annual_spend",
    "under_investigation": "under_investigation",
}


def _load_registry(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Return (fieldnames, rows) from the registry CSV."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _coerce_for_csv(value: Any) -> str:
    """Convert extracted Python value to the string form stored in the CSV."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "|".join(str(s) for s in value)
    return str(value)


def merge(
    registry_path: Path,
    extracted_records: list[dict[str, Any]],
    *,
    dry_run: bool = False,
    out_path: Path | None = None,
) -> int:
    """
    Merge extracted_records into the registry CSV.

    Returns the number of rows updated (or inserted if vendor_id not found).
    """
    fieldnames, rows = _load_registry(registry_path)

    # Index rows by vendor_id for O(1) lookup
    index: dict[str, int] = {row["vendor_id"]: i for i, row in enumerate(rows)}

    updated = 0
    for extracted in extracted_records:
        vid = extracted.get("vendor_id")
        if not vid:
            print(f"  [WARN] Extracted record has no vendor_id — skipping: {extracted}", file=sys.stderr)
            continue

        if vid in index:
            row = rows[index[vid]]
            changed_fields = []
            for ext_key, csv_key in _EXTRACT_TO_CSV.items():
                value = extracted.get(ext_key)
                if value is None or value == "" or value == []:
                    continue  # keep existing registry value
                if csv_key in row:
                    new_val = _coerce_for_csv(value)
                    if row[csv_key] != new_val:
                        row[csv_key] = new_val
                        changed_fields.append(csv_key)
            if changed_fields:
                print(f"  [UPDATE] {vid}: {', '.join(changed_fields)}", file=sys.stderr)
                updated += 1
            else:
                print(f"  [SKIP]   {vid}: no changes", file=sys.stderr)
        else:
            # Vendor not in registry — append as new row
            print(f"  [INSERT] {vid}: not in registry, appending", file=sys.stderr)
            new_row: dict[str, str] = {k: "" for k in fieldnames}
            new_row["vendor_id"] = vid
            for ext_key, csv_key in _EXTRACT_TO_CSV.items():
                value = extracted.get(ext_key)
                if csv_key in new_row:
                    new_row[csv_key] = _coerce_for_csv(value)
            rows.append(new_row)
            index[vid] = len(rows) - 1
            updated += 1

    dest = out_path or registry_path
    if dry_run:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        with dest.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Written: {dest} ({len(rows)} rows)", file=sys.stderr)

    return updated


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", required=True, help="Path to vendor_registry.csv")
    parser.add_argument("--input", default=None, help="JSON file to read (default: stdin)")
    parser.add_argument("--output", default=None, help="Output CSV path (default: overwrite registry)")
    parser.add_argument("--dry-run", action="store_true", help="Print merged CSV to stdout instead of writing")
    args = parser.parse_args()

    registry_path = Path(args.registry)
    if not registry_path.exists():
        print(f"Error: registry not found: {registry_path}", file=sys.stderr)
        sys.exit(1)

    # Read extracted JSON from file or stdin
    if args.input:
        raw = Path(args.input).read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON input: {e}", file=sys.stderr)
        sys.exit(1)

    # Accept either a single dict or a list of dicts
    records: list[dict] = data if isinstance(data, list) else [data]
    # Strip internal _source_file key added by --batch mode
    for r in records:
        r.pop("_source_file", None)

    out_path = Path(args.output) if args.output else None
    n = merge(registry_path, records, dry_run=args.dry_run, out_path=out_path)
    print(f"Done: {n} row(s) updated/inserted.", file=sys.stderr)


if __name__ == "__main__":
    main()
