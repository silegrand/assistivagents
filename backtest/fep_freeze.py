#!/usr/bin/env python3
"""
fep_freeze.py — Assistiv Cloud · FEP backtest harness (prediction side)

PURPOSE
  Freeze the current FEP scores as a formal, immutable monthly prediction.
  This is the prediction ledger the backtest scores against once lagged
  outcome data publishes 3-6 months later. The whole credibility of the
  backtest rests on these predictions being frozen BEFORE the outcome is
  known and never altered afterwards — so this script appends, never edits.

WHAT IT WRITES
  backtest/predictions/fep-YYYY-MM.json   one frozen prediction per month
  backtest/ledger.json                    append-only index of all predictions

CADENCE
  Run monthly (1st of month). FEP recomputes daily, but a monthly freeze is
  the right granularity to score against monthly/quarterly outcome data. The
  freeze takes the FIRST run of each month so the prediction precedes the
  month it is predicting.

DESIGN NOTES
  - A prediction is the district FEP ranking + scores + risk tiers at freeze
    time, plus a sha256 of the source FEP file for tamper-evidence.
  - We store the rank explicitly: the backtest scores ranking skill, which is
    the honest claim ("we tell you WHERE to look first"), not absolute risk.
  - Idempotent: if this month's prediction already exists, it will not be
    overwritten (immutability), unless FORCE_REFREEZE=true is set AND the
    existing file is from the same UTC day (guards an accidental same-day rerun
    only; never lets a later day rewrite an earlier freeze).

USAGE
  python fep_freeze.py                      # freeze current kent-fep-data.json
  python fep_freeze.py --seed-from-history  # backfill from history/kent-fep-*.json
"""

import json
import hashlib
import os
import sys
from datetime import datetime, timezone

FEP_FILE = "kent-fep-data.json"
PRED_DIR = "backtest/predictions"
LEDGER = "backtest/ledger.json"
HISTORY_DIR = "history"


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def build_prediction(fep, source_name, source_sha, frozen_at, target_month):
    """Construct one frozen prediction record from a loaded FEP dict."""
    districts = fep.get("districts", [])
    # Rank by FEP descending; ties broken by name for determinism.
    ranked = sorted(districts, key=lambda d: (-d.get("fep", 0), d.get("name", "")))
    rows = []
    for rank, d in enumerate(ranked, start=1):
        rows.append({
            "name": d.get("name"),
            "lad_code": d.get("lad_code"),
            "fep": d.get("fep"),
            "risk": d.get("risk"),
            "rank": rank,
            # carry the precursor flag if present — lets us test whether the
            # model's own early-warning flag had predictive value
            "crisis_precursor": d.get("crisis_precursor"),
        })
    return {
        "schema": "assistiv.fep.prediction/1",
        "target_month": target_month,        # the month this prediction is ABOUT
        "frozen_at": frozen_at,              # when we locked it (UTC)
        "source_file": source_name,
        "source_sha256": source_sha,
        "fep_version": fep.get("meta", {}).get("version"),
        "epd_period": fep.get("meta", {}).get("epd_period"),
        "n_districts": len(rows),
        "predictions": rows,
        "note": ("Frozen FEP ranking. Scored later against district-level "
                 "outcome indicators (falls/emergency admissions 65+) as they "
                 "publish. Ranking skill is the claim, not absolute risk."),
    }


def load_ledger():
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            return json.load(f)
    return {"schema": "assistiv.fep.ledger/1",
            "description": "Append-only index of frozen FEP predictions.",
            "predictions": []}


def write_prediction(fep, source_name, source_sha, target_month, force=False):
    os.makedirs(PRED_DIR, exist_ok=True)
    out_path = f"{PRED_DIR}/fep-{target_month}.json"
    now = datetime.now(timezone.utc)
    frozen_at = now.isoformat()

    if os.path.exists(out_path) and not force:
        print(f"  · {target_month} already frozen — leaving immutable. "
              f"(Set FORCE_REFREEZE=true to overwrite a same-day rerun.)")
        return None
    if os.path.exists(out_path) and force:
        existing = json.load(open(out_path))
        if existing.get("frozen_at", "")[:10] != frozen_at[:10]:
            print(f"  ✗ refusing to overwrite {target_month}: existing freeze "
                  f"is from a different day. Predictions are immutable.")
            return None

    pred = build_prediction(fep, source_name, source_sha, frozen_at, target_month)
    with open(out_path, "w") as f:
        json.dump(pred, f, indent=2)

    ledger = load_ledger()
    ledger["predictions"] = [p for p in ledger["predictions"]
                             if p.get("target_month") != target_month]
    ledger["predictions"].append({
        "target_month": target_month,
        "frozen_at": frozen_at,
        "file": out_path,
        "source_sha256": source_sha,
        "n_districts": pred["n_districts"],
        "scored": False,           # set true by fep_score.py once outcomes land
    })
    ledger["predictions"].sort(key=lambda p: p["target_month"])
    with open(LEDGER, "w") as f:
        json.dump(ledger, f, indent=2)

    top3 = ", ".join(f"{r['name']}({r['fep']})" for r in pred["predictions"][:3])
    print(f"  ✓ froze {target_month}: {pred['n_districts']} districts. Top 3: {top3}")
    return out_path


def freeze_current():
    if not os.path.exists(FEP_FILE):
        print(f"✗ {FEP_FILE} not found"); sys.exit(1)
    fep = json.load(open(FEP_FILE))
    sha = sha256_of(FEP_FILE)
    target_month = datetime.now(timezone.utc).strftime("%Y-%m")
    force = os.environ.get("FORCE_REFREEZE", "").lower() == "true"
    print(f"Freezing current FEP as prediction for {target_month}")
    write_prediction(fep, FEP_FILE, sha, target_month, force=force)


def seed_from_history():
    """Backfill predictions from existing history/kent-fep-*.json snapshots.
    Takes the EARLIEST snapshot in each month, so the frozen prediction
    genuinely precedes that month's outcomes as far as the archive allows."""
    import glob
    snaps = sorted(glob.glob(f"{HISTORY_DIR}/kent-fep-*.json"))
    if not snaps:
        print("No history/kent-fep-*.json snapshots to seed from."); return
    by_month = {}
    for p in snaps:
        # filename: kent-fep-YYYY-MM-DD.json
        stamp = os.path.basename(p).replace("kent-fep-", "").replace(".json", "")
        month = stamp[:7]
        # keep earliest date per month
        if month not in by_month or stamp < by_month[month][0]:
            by_month[month] = (stamp, p)
    print(f"Seeding {len(by_month)} month(s) from history (earliest snapshot each):")
    for month, (stamp, path) in sorted(by_month.items()):
        fep = json.load(open(path))
        sha = sha256_of(path)
        # frozen_at recorded as the snapshot's own date, honestly
        os.makedirs(PRED_DIR, exist_ok=True)
        out_path = f"{PRED_DIR}/fep-{month}.json"
        if os.path.exists(out_path):
            print(f"  · {month} already exists — skipping (immutable)."); continue
        pred = build_prediction(fep, path, sha,
                                f"{stamp}T00:00:00+00:00 (seeded from history)", month)
        with open(out_path, "w") as f:
            json.dump(pred, f, indent=2)
        ledger = load_ledger()
        ledger["predictions"] = [x for x in ledger["predictions"]
                                 if x.get("target_month") != month]
        ledger["predictions"].append({
            "target_month": month, "frozen_at": pred["frozen_at"],
            "file": out_path, "source_sha256": sha,
            "n_districts": pred["n_districts"], "scored": False,
            "seeded_from_history": True})
        ledger["predictions"].sort(key=lambda p: p["target_month"])
        with open(LEDGER, "w") as f:
            json.dump(ledger, f, indent=2)
        top3 = ", ".join(f"{r['name']}({r['fep']})" for r in pred["predictions"][:3])
        print(f"  ✓ seeded {month} from {stamp}: top 3 {top3}")


if __name__ == "__main__":
    if "--seed-from-history" in sys.argv:
        seed_from_history()
    else:
        freeze_current()
