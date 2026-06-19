# Data Generation Methodology & Edge Cases

This document covers the data layer of the Vendor Risk Management platform:
how synthetic vendor records are generated, how ground-truth labels are derived,
what the normalizer handles, and why each edge-case scenario was chosen.

---

## 1. Overview

The data pipeline has five components:

```
generate_vendors.py  ──>  vendor_registry.csv
                     ──>  vendor_labels.csv
        +
edge_cases.py        ──>  appended to both CSVs
        +
normalize.py         ──>  reconciles messy/inconsistent input shapes
        +
seed_db.py           ──>  loads CSVs into SQLite (activates once api/db.py is ready)
        +
extraction/          ──>  LLM-assisted extraction from real contract documents
```

All records conform to the `Vendor` Pydantic model in `common/schema.py`.
Labels conform to `VendorLabel`.

---

## 2. Bulk Synthetic Generator (`data/generate_vendors.py`)

### Philosophy

Random data doesn't test a risk engine — it bypasses it. The generator
deliberately controls the *distribution* of risk factors to guarantee that
every rule in the PRD §5 rubric is exercised by real data rows, not just the
hand-written fixtures.

### Distribution buckets (seed=42, count=420)

| Bucket | N | Description |
|---|---|---|
| `critical_breach` | 63 (15%) | Breach ≤12 months ago + HIGH sensitivity → CRITICAL hard floor |
| `under_investigation` | 5 (1.2%) | `under_investigation=True` → CRITICAL hard floor |
| `high_multi` | 45 (10.7%) | D rating + READ_WRITE + HIGH sensitivity + orphaned access → multi-factor HIGH |
| `expired_cert` | 42 (10%) | HIGH sensitivity + READ_WRITE + expired SOC2 → MEDIUM/HIGH |
| `orphaned_contract` | 21 (5%) | Expired contract, access still populated → MEDIUM |
| `low_rating` | 21 (5%) | D/C- rating only (otherwise clean) → LOW/MEDIUM |
| `missing_gdpr` | 21 (5%) | Handles EU data, no GDPR DPA, otherwise clean → MEDIUM |
| `low_clean` | 202 (48%) | All factors clean → LOW baseline |

The LOW baseline represents the realistic case where most vendors are not
high-risk — over-flagging would make the system useless to operators.

### Reproducibility

`TODAY = date(2026, 6, 19)` is hard-coded (not `date.today()`). All relative
dates (breach recency, cert expiry) are computed from this fixed anchor.
`random.seed(42)` is set before any random call. This means the CSV output is
deterministic across reruns — important for eval reproducibility.

### Vendor ID space

- `VND-0001` to `VND-0512`: reserved for the 8 hand-written fixtures in `common/schema.py`
- `VND-1000` to `VND-9000`: assigned to bulk-generated vendors
- `VND-9001` to `VND-9020`: reserved for hand-scripted edge cases

---

## 3. Ground-Truth Labels (`vendor_labels.csv`)

### How labels are generated

Labels are produced by `compute_label(v: Vendor) -> VendorLabel` in
`generate_vendors.py`, which implements the **exact PRD §5 rubric** as a
deterministic reference implementation. This is intentional: the labels
measure whether the scoring engine *matches the rubric*, not whether it matches
the data generator's private judgment.

### Label fields

| Field | Source |
|---|---|
| `vendor_id` | from Vendor |
| `is_anomaly` | True for MEDIUM / HIGH / CRITICAL risk levels |
| `anomaly_type` | Derived from which rule fires first (priority order below) |
| `severity` | Maps from risk_level |
| `expired_certifications` | List of `"SOC2"` / `"ISO27001"` if expired |
| `explanation` | Human-readable string — auditor-style rationale |

### Anomaly type priority order

```
1. under_investigation             → VENDOR_UNDER_INVESTIGATION (CRITICAL)
2. breach ≤12mo + HIGH sensitivity → BREACHED_VENDOR_HIGH_ACCESS (CRITICAL)
3. breach ≤12mo (any sensitivity)  → RECENTLY_BREACHED_VENDOR (MEDIUM)
4. score > 80 (no hard floor)      → HIGH_RISK_SCORE (HIGH)
5. orphaned access                 → CONTRACT_EXPIRED_ACTIVE_ACCESS (MEDIUM)
6. cert expired                    → EXPIRED_CERTIFICATION (HIGH/MEDIUM by access)
7. score 65-79                     → ELEVATED_RISK_VENDOR (LOW anomaly marker)
8. otherwise                       → NONE (clean)
```

---

## 4. Schema Normalization (`data/normalize.py`)

### Problem it solves

The original brief showed the same vendor (`VND-0285 CyberBackup`) represented
in two incompatible JSON shapes — nested `data_access` sub-object vs flat keys,
different field names, contradicting values. Real-world vendor data arrives from
spreadsheets, APIs, and contract extraction with exactly this kind of messiness.

`normalize.py` provides a single public function:

```python
vendor = normalize_raw_vendor(raw_dict)   # any messy shape → Vendor
vendor = normalize_csv_row(csv_row)       # thin wrapper for DictReader rows
```

### What it handles

| Category | Examples |
|---|---|
| Alternate field names | `sensitivity` → `data_sensitivity`, `cert_soc2` → `soc2_type2`, `eu_data` → `handles_eu_data` (40+ aliases) |
| Date formats | ISO 8601, UK (`DD/MM/YYYY`), US (`MM/DD/YYYY`), `DD Mon YYYY`, `DD Month YYYY` |
| Stringified booleans | `"true"`, `"1"`, `"yes"`, `"on"` → `True`; `"false"`, `"0"`, `"no"` → `False` |
| Systems lists | Pipe-separated (`"HR_System\|ERP"`), comma-separated, or Python list |
| Flat vs nested | Top-level keys OR nested `data_access: {...}` / `compliance: {...}` sub-objects |
| Breach history | Nested list OR flat single-breach fields (`breach_count`, `latest_breach_date`, etc.) |

### Design principle

`normalize_raw_vendor` raises `ValueError` only for genuinely unrecoverable
issues (missing `vendor_id`, unparseable required dates). Everything else
defaults safely. This is deliberate: a risk platform that silently drops vendors
due to minor formatting issues is worse than one that scores them conservatively.

---

## 5. Edge Cases (`data/edge_cases.py`)

Edge cases are hand-scripted to stress-test the scoring engine's rule boundaries.
They use IDs `VND-9001` to `VND-9020` and are appended to both CSVs.

### Why hand-scripted, not generated?

The bulk generator controls distributions but cannot guarantee specific
boundary conditions — e.g. "cert expires in exactly 59 days" or "score lands at
exactly 65 points." Boundary cases must be precise, so they're written explicitly.

### Complete edge case catalogue

| ID | Name | What it tests |
|---|---|---|
| VND-9001 | `CriticalFloor Direct` | Breach 3mo ago + HIGH sensitivity → CRITICAL hard floor (must fire regardless of other clean factors) |
| VND-9002 | `InvestigationFloor Direct` | `under_investigation=True`, everything else clean → CRITICAL |
| VND-9003 | `CertBoundary 59d` | SOC2 expires in 59 days → inside the 60-day warning window |
| VND-9004 | `CertBoundary 60d` | SOC2 expires in exactly 60 days → at the boundary |
| VND-9005 | `CertBoundary 61d` | SOC2 expires in 61 days → just outside the window |
| VND-9006 | `OrphanedAccess Clean` | Contract expired, READ_ONLY access still populated → CONTRACT_EXPIRED_ACTIVE_ACCESS |
| VND-9007 | `PerfectVendor` | All factors maximally clean → should score LOW, anomaly_type NONE |
| VND-9008 | `MaxRisk AllFlags` | Every single risk flag set simultaneously (breach + investigation + expired cert + orphaned + D rating + HIGH + READ_WRITE) → CRITICAL |
| VND-9009 | `GDPRMissing EUData` | `handles_eu_data=True`, `gdpr_dpa=False`, otherwise clean → GDPR DPA penalty, MEDIUM |
| VND-9010 | `AmbiguousMiddle` | Old breach (18mo), medium sensitivity, cert expiring in 45 days, B- rating → should land LOW/MEDIUM, not HIGH |
| VND-9011 | `RepeatOffender` | Two old breaches + one recent LOW-sensitivity breach → recent breach should NOT trigger CRITICAL floor |
| VND-9012 | `ISOOnly NoCSOC2` | ISO27001 certified but no SOC2 → partial cert penalty only |
| VND-9013 | `SOC2Only NoISO` | SOC2 certified, no ISO27001, HIGH access → partial cert penalty |
| VND-9014 | `ExpiredBothCerts` | Both SOC2 and ISO27001 expired (not missing — previously held, now lapsed) |
| VND-9015 | `HighSpend LowRisk` | $5M annual spend but otherwise clean LOW vendor → spend alone should not elevate risk |
| VND-9016 | `DRating Clean` | D financial rating, everything else clean → only financial factor fires |
| VND-9017 | `MultiSystem LowSens` | Access to 5 systems but all LOW sensitivity READ_ONLY → breadth alone shouldn't spike score |
| VND-9018 | `ContractExpired NoAccess` | Contract expired, `data_access.systems = []` (no orphaned access) → NOT CONTRACT_EXPIRED_ACTIVE_ACCESS |
| VND-9019 | `EUHandlerWithDPA` | `handles_eu_data=True` + `gdpr_dpa=True` → no GDPR penalty (positive path) |
| VND-9020 | `MultiFactorHigh` | D rating + HIGH + READ_WRITE + expired cert, no breach → scores exactly 65 → HIGH (verifies CRITICAL requires breach or investigation) |

---

## 6. LLM-Assisted Contract Extraction (`extraction/`)

### Overview

`extraction/extract_contract.py` uses the Anthropic API (`claude-opus-4-8`)
to extract structured vendor fields from plaintext contract documents. It
bridges the gap between unstructured legal text and the `Vendor` schema.

### Architecture

```
contract.txt  →  extract_contract.py  →  ContractExtraction (Pydantic)
                 (claude-opus-4-8,            │
                  structured output)           ▼
                                        normalize_raw_vendor()
                                               │
                                               ▼
                                          Vendor object
```

`ContractExtraction` is a Pydantic model with 16 fields. The SDK's
`messages.parse(output_format=ContractExtraction)` enforces the schema
at the API level — Claude cannot return a malformed response.

### Key extraction rules (embedded in system prompt)

- `gdpr_dpa`: **true only if explicitly signed/executed** — "pending", "not required", "open action item" → false
- `under_investigation`: true for any regulatory, legal, or security-review flag on the vendor
- `soc2_type2` / `iso27001`: true only when currently VALID — "NOT HELD" or expired → false
- `vendor_id`: derived from the contract reference number (e.g. `MSA-2023-0285` → `VND-0285`)
- `annual_spend`: always USD; EUR amounts use the stated USD equivalent if provided

### Sample contracts

Five synthetic contracts in `extraction/sample_contracts/` cover representative cases:

| File | Vendor | Key scenario |
|---|---|---|
| `contract_VND0001_cleanco.txt` | CleanCo Analytics | Fully clean — all certs valid, LOW sensitivity, READ_ONLY |
| `contract_VND0285_cyberbackup.txt` | CyberBackup Solutions | HIGH sensitivity, missing GDPR DPA (pending addendum) |
| `contract_VND0099_shadyconsulting.txt` | ShadyConsulting LLC | Under SEC investigation, no certs, `under_investigation=True` |
| `contract_VND0200_legacyintegration.txt` | LegacyIntegration Corp | Expired contract, access NOT revoked (orphaned access) |
| `contract_VND0420_europay.txt` | EuroPay Processing GmbH | HIGH sensitivity, EUR contract value, missing GDPR DPA |

### Usage

```bash
# Single file
python extraction/extract_contract.py extraction/sample_contracts/contract_VND0285_cyberbackup.txt

# Extract + normalize round-trip validation
python extraction/extract_contract.py --validate extraction/sample_contracts/contract_VND0099_shadyconsulting.txt

# Batch — all contracts in a directory
python extraction/extract_contract.py --batch extraction/sample_contracts/
```

Requires `ANTHROPIC_API_KEY` in the environment.

---

## 7. Data Quality Guarantees

Every record in `vendor_registry.csv` and `vendor_labels.csv` satisfies:

1. **Schema conformance** — loadable into `Vendor`/`VendorLabel` Pydantic models with no validation errors
2. **Referential consistency** — every `vendor_id` in `vendor_labels.csv` has a matching row in `vendor_registry.csv`
3. **Label fidelity** — labels are derived by the same rubric as PRD §5, not manual judgment
4. **Reproducibility** — fixed seed and fixed TODAY date → identical CSV output on every run
5. **Rule coverage** — every hard floor and every weighted factor in PRD §5 is triggered by at least one row in the dataset

To regenerate from scratch:

```bash
python data/generate_vendors.py        # produces vendor_registry.csv + vendor_labels.csv
python data/edge_cases.py              # appends VND-9001–9020 to both CSVs
python data/normalize.py              # self-test: validates the 3 messy RAW_MESSY_EXAMPLES
```
