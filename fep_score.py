#!/usr/bin/env python3
"""
fep_score.py — Assistiv Cloud · FEP backtest harness (scoring side)

PURPOSE
  Score frozen FEP predictions against outcomes that publish later. This is
  the half that turns "14:1 modelled" into "validated against observed
  outcomes". It reads the immutable prediction ledger, finds predictions whose
  outcome window has now closed, joins them to the outcome data, and writes a
  public scorecard — hits, misses and all.

THE HONEST JOIN
  FEP is district-level (13 districts). The cleanest district-level outcome is
  a Fingertips outcome indicator that updates AFTER the prediction was frozen —
  e.g. falls admissions 65+ or emergency admissions. This script scores
  RANKING SKILL: did the districts FEP ranked high subsequently show worse
  outcomes than those it ranked low? That is the model's actual claim.

  Two scoring modes:
    1. district   — join to a district-level outcome series (primary, honest)
    2. trust      — map 4 trusts -> catchment districts, score catchment means
                    (fallback when only trust-level outcomes are available)

METRICS (all standard, all reported, none hidden)
  - Spearman rank correlation between predicted FEP rank and outcome rank
  - Top-k precision: of the k districts FEP flagged highest, how many were in
    the worst-k on the realised outcome
  - Brier-style calibration on the high/low binary (high-risk tier vs outcome
    above cohort median)
  - The full per-district table, so anyone can audit the call

OUTPUT
  backtest/scorecards/score-<predmonth>-vs-<outcomeperiod>.json
  backtest/scorecard-latest.json   (most recent, for the public page to fetch)

USAGE
  python fep_score.py --prediction 2026-06 --outcome-file kent-fep-data.json \
      --outcome-signal "Falls Admissions 65+" --mode district
  (In production the outcome-file is a LATER FEP/Fingertips pull whose outcome
   indicator has refreshed since the prediction was frozen.)
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone

PRED_DIR = "backtest/predictions"
LEDGER = "backtest/ledger.json"
SCORE_DIR = "backtest/scorecards"

# Trust -> catchment districts (aligned to acute flows; matches the pressure map)
TRUST_DISTRICTS = {
    "RVV": ["Thanet", "Dover", "Folkestone & Hythe", "Canterbury", "Ashford"],
    "RWF": ["Maidstone", "Tonbridge & Malling", "Tunbridge Wells", "Sevenoaks"],
    "RPA": ["Medway", "Swale"],
    "RN7": ["Dartford", "Gravesham"],
}


def spearman(rank_a, rank_b):
    """Spearman rho from two equal-length rank lists (1=worst)."""
    n = len(rank_a)
    if n < 3:
        return None
    d2 = sum((rank_a[i] - rank_b[i]) ** 2 for i in range(n))
    return round(1 - (6 * d2) / (n * (n * n - 1)), 3)


def load_prediction(month):
    path = f"{PRED_DIR}/fep-{month}.json"
    if not os.path.exists(path):
        print(f"✗ no frozen prediction for {month} at {path}"); sys.exit(1)
    return json.load(open(path))


def district_outcomes_from_fep(outcome_fep, signal_name):
    """Extract a district-level outcome value from a later FEP/Fingertips pull,
    by pulling one named signal out of each district's signal vector."""
    out = {}
    for d in outcome_fep.get("districts", []):
        names = d.get("signal_names", [])
        sigs = d.get("signals", [])
        if signal_name in names:
            out[d["name"]] = sigs[names.index(signal_name)]
    return out


def trust_outcomes_to_districts(outcome_hes, field="total_emerg_65plus"):
    """Spread a trust-level outcome to its catchment districts (each district
    inherits its trust's value). Honest fallback only — blurs within trust."""
    out = {}
    for code, t in outcome_hes.get("trusts", {}).items():
        val = t.get(field)
        if val is None:
            continue
        for dname in TRUST_DISTRICTS.get(code, []):
            out[dname] = val
    return out


def score(prediction, outcomes, outcome_label, mode):
    """Core scoring: join frozen prediction to realised outcomes."""
    preds = prediction["predictions"]
    common = [p for p in preds if p["name"] in outcomes]
    if len(common) < 3:
        print(f"✗ too few districts overlap ({len(common)}) to score"); return None

    # Predicted rank: 1 = highest FEP (worst predicted). Already in p['rank']
    # but recompute over the COMMON set so ranks are dense.
    common_sorted_pred = sorted(common, key=lambda p: -p["fep"])
    pred_rank = {p["name"]: i + 1 for i, p in enumerate(common_sorted_pred)}

    # Outcome rank: 1 = worst realised outcome (highest value = worst, for
    # admissions/falls where more is worse).
    common_sorted_out = sorted(common, key=lambda p: -outcomes[p["name"]])
    out_rank = {p["name"]: i + 1 for i, p in enumerate(common_sorted_out)}

    names = [p["name"] for p in common]
    rho = spearman([pred_rank[n] for n in names], [out_rank[n] for n in names])

    # Top-k precision (k = third of cohort, min 3)
    k = max(3, len(names) // 3)
    pred_topk = set(sorted(names, key=lambda n: pred_rank[n])[:k])
    out_topk = set(sorted(names, key=lambda n: out_rank[n])[:k])
    hits = pred_topk & out_topk
    topk_precision = round(len(hits) / k, 3)

    # Calibration: predicted high-risk tier vs outcome above cohort median
    vals = sorted(outcomes[n] for n in names)
    median = vals[len(vals) // 2]
    brier_terms = []
    for p in common:
        predicted_high = 1.0 if p.get("risk") in ("high", "critical") else 0.0
        actual_high = 1.0 if outcomes[p["name"]] >= median else 0.0
        brier_terms.append((predicted_high - actual_high) ** 2)
    brier = round(sum(brier_terms) / len(brier_terms), 3)

    table = []
    for p in common:
        table.append({
            "name": p["name"],
            "predicted_fep": p["fep"],
            "predicted_rank": pred_rank[p["name"]],
            "predicted_risk": p.get("risk"),
            "outcome_value": outcomes[p["name"]],
            "outcome_rank": out_rank[p["name"]],
            "rank_error": pred_rank[p["name"]] - out_rank[p["name"]],
            "in_predicted_topk": p["name"] in pred_topk,
            "in_outcome_topk": p["name"] in out_topk,
            "topk_hit": p["name"] in hits,
        })
    table.sort(key=lambda r: r["predicted_rank"])

    return {
        "schema": "assistiv.fep.scorecard/1",
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "prediction_month": prediction["target_month"],
        "prediction_frozen_at": prediction["frozen_at"],
        "outcome_label": outcome_label,
        "mode": mode,
        "n_districts_scored": len(common),
        "metrics": {
            "spearman_rank_correlation": rho,
            "topk_precision": topk_precision,
            "topk_k": k,
            "topk_hits": sorted(hits),
            "calibration_brier": brier,
            "outcome_median": median,
        },
        "interpretation": _interpret(rho, topk_precision, brier),
        "table": table,
    }


def _interpret(rho, topk, brier):
    parts = []
    if rho is None:
        parts.append("Too few districts to compute rank correlation.")
    elif rho >= 0.6:
        parts.append(f"Strong ranking skill (Spearman {rho}): districts FEP "
                     f"ranked high did show worse outcomes.")
    elif rho >= 0.3:
        parts.append(f"Moderate ranking skill (Spearman {rho}).")
    elif rho >= 0:
        parts.append(f"Weak positive ranking skill (Spearman {rho}).")
    else:
        parts.append(f"No ranking skill this period (Spearman {rho}): the model "
                     f"did not order districts in line with outcomes.")
    parts.append(f"Top-{'k'} precision {topk}: that share of the highest-flagged "
                 f"districts were among the worst on the realised outcome.")
    parts.append(f"Calibration Brier {brier} (lower is better; 0.25 is the "
                 f"coin-flip benchmark for a binary high/low call).")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prediction", required=True, help="prediction month YYYY-MM")
    ap.add_argument("--outcome-file", required=True,
                    help="later data file containing the realised outcome")
    ap.add_argument("--outcome-signal", default="Falls Admissions 65+",
                    help="district mode: which FEP signal name is the outcome")
    ap.add_argument("--outcome-field", default="total_emerg_65plus",
                    help="trust mode: which trust field is the outcome")
    ap.add_argument("--mode", choices=["district", "trust"], default="district")
    ap.add_argument("--label", default=None)
    args = ap.parse_args()

    pred = load_prediction(args.prediction)
    odata = json.load(open(args.outcome_file))

    if args.mode == "district":
        outcomes = district_outcomes_from_fep(odata, args.outcome_signal)
        label = args.label or f"{args.outcome_signal} (district, Fingertips)"
    else:
        outcomes = trust_outcomes_to_districts(odata, args.outcome_field)
        label = args.label or f"{args.outcome_field} (trust catchment)"

    if not outcomes:
        print("✗ no outcome values extracted — check signal/field name"); sys.exit(1)

    card = score(pred, outcomes, label, args.mode)
    if not card:
        return

    os.makedirs(SCORE_DIR, exist_ok=True)
    oslug = args.outcome_signal if args.mode == "district" else args.outcome_field
    oslug = oslug.lower().replace(" ", "-").replace("/", "-")
    out_path = f"{SCORE_DIR}/score-{args.prediction}-vs-{oslug}.json"
    with open(out_path, "w") as f:
        json.dump(card, f, indent=2)
    with open("backtest/scorecard-latest.json", "w") as f:
        json.dump(card, f, indent=2)

    # mark scored in ledger
    if os.path.exists(LEDGER):
        ledger = json.load(open(LEDGER))
        for p in ledger["predictions"]:
            if p["target_month"] == args.prediction:
                p["scored"] = True
        json.dump(ledger, open(LEDGER, "w"), indent=2)

    m = card["metrics"]
    print(f"✓ scored {args.prediction} vs {label}")
    print(f"  Spearman {m['spearman_rank_correlation']} · "
          f"top-{m['topk_k']} precision {m['topk_precision']} · "
          f"Brier {m['calibration_brier']}")
    print(f"  {card['interpretation']}")
    print(f"  written: {out_path}")


if __name__ == "__main__":
    main()
