# FEP Backtest Harness

> Turns "14:1 modelled" into "validated against observed outcomes" — in public,
> monthly, misses included. This is roadmap move #1.

## The idea in one paragraph

The FEP engine makes an implicit prediction every time it runs: *these are the
districts where frailty is emerging fastest*. A prediction nobody writes down
can never be wrong — and never be trusted. This harness writes the prediction
down, immutably, **before** the outcome is known, then scores it against the
outcome data that publishes months later. The score is published whether it
flatters us or not. That posture — testable in the open — is the credibility
the methodology pages alone cannot buy.

## Two scripts, two halves

| Script | Role | Cadence |
|---|---|---|
| `fep_freeze.py` | Freezes current FEP as an immutable monthly prediction | Monthly (1st) |
| `fep_score.py`  | Scores a frozen prediction against later outcomes | When outcomes publish (3–6 mo later) |

## Files it maintains

```
backtest/
  predictions/fep-YYYY-MM.json     one frozen prediction per month (immutable)
  ledger.json                      append-only index of all predictions
  scorecards/score-<m>-vs-<o>.json one scorecard per (prediction × outcome)
  scorecard-latest.json            most recent, for the public page to fetch
```

## The immutability guarantee

A prediction file, once written, is never edited. `fep_freeze.py` refuses to
overwrite an existing month unless `FORCE_REFREEZE=true` **and** the existing
freeze is from the same UTC day (an accidental same-day rerun). A freeze from a
later day can never rewrite an earlier one. Each prediction also stores a
sha256 of its source FEP file, so tampering is detectable. This is what lets a
sceptic trust that the prediction genuinely preceded the outcome.

## The honest join — read this before quoting any number

FEP is **district-level** (13 districts). The scorer offers two modes:

1. **district** (primary, honest) — joins to a district-level outcome indicator
   that updated *after* the freeze. Falls admissions 65+ and emergency
   admissions are the natural choices: they publish via Fingertips at LAD level
   on a lag, so a June prediction can be scored against, say, the Q3 falls
   indicator when it lands.

2. **trust** (fallback) — maps the 4 acute trusts to their catchment districts
   and scores catchment means. Weaker, because catchments blur districts; use
   only when no district-level outcome is available, and label it as such.

### The cardinal rule

**Never score a prediction against a signal that was an input to that
prediction from the same period.** That is circular and proves nothing. A valid
backtest scores a frozen prediction against a *later* outcome the model had not
seen at freeze time. The scorer cannot enforce this for you — it is a
methodological discipline. When in doubt, widen the gap between freeze date and
outcome period.

## Metrics (all reported, none hidden)

- **Spearman rank correlation** — did districts ranked high by FEP show worse
  outcomes? This is the model's actual claim ("where to look first"), so rank
  skill is the headline, not absolute-risk accuracy.
- **Top-k precision** — of the k districts FEP flagged highest, how many were
  genuinely among the worst-k on the outcome.
- **Calibration (Brier)** — for the high-risk-tier vs outcome-above-median
  binary. 0.25 is the coin-flip benchmark; lower is better.
- **Full per-district table** — every call, so anyone can audit.

## Running it

```bash
# Monthly — freeze the current prediction (wire into a workflow on the 1st)
python fep_freeze.py

# One-off — backfill from existing history/ snapshots (earliest per month)
python fep_freeze.py --seed-from-history

# Later — score a matured prediction against a real, lagged outcome
python fep_score.py \
  --prediction 2026-06 \
  --outcome-file <a-LATER-fep-or-fingertips-pull>.json \
  --outcome-signal "Falls Admissions 65+" \
  --mode district
```

## Suggested workflow wiring

Add a monthly freeze step to an existing Actions workflow (or a dedicated one):

```yaml
  - name: Freeze monthly FEP prediction
    env:
      GITHUB_TOKEN: ${{ secrets.ASSISTIV_GITHUB_TOKEN }}
    run: python fep_freeze.py
```

Scoring is run when a lagged outcome publishes — best done manually at first so
a human chooses a methodologically valid outcome/period pairing, then automated
once the cadence is understood.

## What "good" looks like over time

Twelve monthly predictions, each scored against the outcome window that has
since closed, plotted as a track record: Spearman and top-k trending positive,
calibration beating the coin flip, and the misses shown openly with a note on
why. That track record is the artifact that moves a commissioner from
"interesting" to "let's pilot" and an investor from "come back with traction"
to "tell me more."

## Status

- [x] Prediction freeze + immutable ledger (`fep_freeze.py`)
- [x] Scoring harness with rank/precision/calibration (`fep_score.py`)
- [x] June 2026 seeded from history (earliest snapshot, 4 June)
- [ ] Wire monthly freeze into a workflow
- [ ] First real score once a post-June district outcome publishes
- [ ] Public scorecard page on assistiv.cloud fetching `scorecard-latest.json`
