# PRD — Vendor & Third-Party Risk Management Platform

## 1. The problem (why this exists)

Enterprises work with 1,000+ vendors (cloud providers, contractors, SaaS, MSPs, payment processors). 60% of breaches involve a third party. Today, vendor risk is tracked in spreadsheets, nobody can answer "is Vendor X compliant?" in under a meeting, and security becomes the team that blocks everything because it can't answer simple questions fast (see `reference/pain-points.md` if present, or the original brief images).

We are explicitly **not** building the simple version (a CRUD form where a human manually picks a risk level from a dropdown). That version can't produce explainable, auditor-aligned risk scores, and can't be evaluated against ground truth. We're building a real scoring engine.

## 2. What "done" looks like (hackathon deliverables)

Per the hackathon rules, the final submission needs:
1. **Detailed documentation** — architecture, scoring algorithm rationale, UI design (this repo's docs + a final write-up)
2. **Presentation** — summarizing problem + solution
3. **Solution video** — short demo walkthrough
4. **Git repo link**

So the working software is necessary but not sufficient — budget time in the last hours for documentation/video, not just code. See `plan.md`.

## 3. System overview

```
[Data Layer]                [Core Engine]                  [Surface Layer]
 vendor_registry (SQLite)      normalize            ┌──>  dashboard (FastAPI + HTML/JS)
 contract docs (stretch)  ──>  risk scorer    ───┐   │
                               alert engine       ├───┴──> portfolio reports (CSV + view)
                                                   │
                                                   └──────> email notifications
```

The **contract** between the two tracks is `common/schema.py` — a set of Pydantic models. Divyansh's track produces data conforming to `Vendor`. Jatin's track consumes `Vendor` objects and produces `ScoredVendor` objects, alerts, and emails. Neither track needs the other's code to develop or test — Jatin can build entirely against the fixture vendors defined in `common/schema.py`'s examples until Divyansh's real data lands.

## 4. Core data model (summary — full detail in `common/schema.py`)

**Vendor** (input): vendor_id, name, category, contract_start, contract_end, data_access (systems[], sensitivity, access_type), compliance (soc2_type2, soc2_expiry, iso27001, gdpr_dpa), breach_history[] (date, severity, description), financial_rating, annual_spend.

**ScoredVendor** (output): vendor_id, risk_score (0-100), risk_level (LOW/MEDIUM/HIGH/CRITICAL), risk_factors[] (human-readable strings explaining the score), recommendation (string).

This mirrors the target output shape from the original brief's example (a vendor with a recent breach + expiring SOC2 + no GDPR DPA + high-sensitivity access scoring 7.8/10 HIGH with four explicit risk_factors).

## 5. Risk scoring rubric (agreed by both — DO NOT change unilaterally, log changes in `memory.md`)

Deterministic, rule-based, explainable. Not a black-box ML classifier — labels file already gives us anomaly_type + severity + explanation, which signals a rules/weights system is the intended design.

**Hard floors (override everything else — these guarantee CRITICAL recall):**
- Breach in last 12 months AND data_sensitivity is HIGH (PII/financial access) → **CRITICAL**, regardless of other factors
- Vendor explicitly flagged `under_investigation` → **CRITICAL**

**Weighted scoring (0-100) when no hard floor applies:**
| Factor | Weight | Logic |
|---|---|---|
| Breach recency + access sensitivity | 35% | Recent breach scores high; decays with time since breach; scaled by data sensitivity |
| Certification status | 25% | Missing/expired SOC2 or ISO27001 on a vendor with sensitive access scores high; expiring within 60 days = partial penalty |
| Contract status | 15% | Expired contract with still-active access = orphaned access risk |
| Financial rating | 10% | C/D ratings increase score (viability risk) |
| Data access scope | 10% | read_write + HIGH sensitivity scores higher than read-only + LOW |
| GDPR DPA missing (if EU data implied) | 5% | Flat penalty if missing |

**Risk levels from score:** 0-39 LOW · 40-64 MEDIUM · 65-79 HIGH · 80-100 CRITICAL (also CRITICAL if any hard floor triggers, even if numeric score is lower — floors win).

**Anomaly types** (for labels + risk_factors generation), matching the original brief:
`BREACHED_VENDOR_HIGH_ACCESS` (CRITICAL), `VENDOR_UNDER_INVESTIGATION` (CRITICAL), `HIGH_RISK_SCORE` (HIGH, score>80), `EXPIRED_CERTIFICATION` (HIGH/MEDIUM), `RECENTLY_BREACHED_VENDOR` (MEDIUM), `CONTRACT_EXPIRED_ACTIVE_ACCESS` (MEDIUM), `ELEVATED_RISK_VENDOR` (LOW, score 65-80).

## 6. Evaluation

`eval/evaluate.py` computes precision/recall overall AND recall specifically on CRITICAL+HIGH severity rows (this is the metric that matters most per the brief — missing a breached vendor with PII access is far worse than over-flagging a borderline one). Target: CRITICAL recall as close to 100% as achievable; overall precision is secondary.

## 7. Out of scope for the 48-hour build

- Real-time/continuous monitoring infra (cron-style scheduler stub only)
- Multi-tenant auth/login
- PDF contract extraction is **stretch only**, attempted after core pipeline + dashboard + eval are working
- Postgres (using SQLite for the hackathon; schema is portable if migration is ever wanted)

## 8. Success criteria (from the original brief, what we're actually graded against in spirit)

- 95%+ vendor coverage tracked
- Risk scoring aligns with auditor judgment (proxied by CRITICAL/HIGH recall on labels)
- "Is vendor X compliant?" answerable in under 5 minutes (dashboard search/filter)
- Full portfolio report generatable in under 15 minutes (one-click/one-command report)
- Alerts fire 30+ days before contract/cert expiry
