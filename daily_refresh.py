"""
daily_refresh.py — Assistiv Systems FEP Daily Refresh
Runs in GitHub Actions. Fetches latest NHS Fingertips indicators,
recalculates district FEP scores using last committed EPD data,
and saves both the current JSON and a dated historic snapshot.

EPD prescribing data is NOT re-streamed here — it uses the last
committed values from icb_baseline.prescribing in kent-fep-data.json.
EPD is updated manually when NHSBSA publish a new monthly release.
"""

import os, json, requests, base64
import fingertips_py as ftp
from datetime import datetime, timezone
from collections import defaultdict

# ── CONFIG ────────────────────────────────────────────────────────────
GITHUB_REPO   = "silegrand/assistivagents"
GITHUB_FILE   = "kent-fep-data.json"
GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
KENT_ICB_ONS  = "E54000032"
KENT_COUNTY   = "E10000016"
ENGLAND       = "E92000001"

RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"

# ── LOAD LAST COMMITTED JSON (to reuse EPD data) ──────────────────────
print("Loading last committed kent-fep-data.json...")
r = requests.get(RAW_URL, timeout=15)
last = r.json()
last_epd   = last.get("icb_baseline", {}).get("prescribing", {})
last_meta  = last.get("meta", {})
last_epd_d = {d["name"]: d.get("epd_district", {}) for d in last.get("districts", [])}
print(f"  Last version: {last_meta.get('version','?')} | EPD period: {last_meta.get('epd_period','?')}")

# ── FINGERTIPS FETCH ──────────────────────────────────────────────────
# Each indicator is fetched at ICB/county level (for the England-benchmarked
# ICB baseline) AND at district (LAD) level where published. District values
# replace the former hand-assigned PROFILES multipliers with real measured data.
FINGERTIPS_INDICATORS = {
    "falls_65":           (22401, "Falls admissions 65+",        KENT_ICB_ONS),
    "falls_65_79":        (22402, "Falls admissions 65-79",      KENT_ICB_ONS),
    "falls_80":           (22403, "Falls admissions 80+",        KENT_ICB_ONS),
    "winter_mortality":   (90360, "Winter mortality index",      KENT_COUNTY),
    "loneliness":         (94175, "Loneliness often/always",     KENT_ICB_ONS),
    "social_isolation":   (90280, "Social isolation SC users",   KENT_COUNTY),
    "dementia_diagnosis": (92949, "Dementia diagnosis rate 65+", KENT_ICB_ONS),
    "hip_fractures_65":   (41401, "Hip fractures 65+",           KENT_ICB_ONS),
    "hip_fractures_80":   (41403, "Hip fractures 80+",           KENT_ICB_ONS),
    "fuel_poverty":       (93759, "Fuel poverty",                KENT_ICB_ONS),
}

# LAD codes for all 13 Kent & Medway districts — used to extract district-level
# rows from the same Fingertips response.
LAD_CODES = {
    "Thanet":"E07000114","Folkestone & Hythe":"E07000112","Dover":"E07000108",
    "Swale":"E07000113","Medway":"E06000035","Gravesham":"E07000109",
    "Ashford":"E07000105","Canterbury":"E07000106","Dartford":"E07000107",
    "Maidstone":"E07000110","Tonbridge & Malling":"E07000115",
    "Sevenoaks":"E07000111","Tunbridge Wells":"E07000116",
}
LAD_TO_NAME = {v: k for k, v in LAD_CODES.items()}

fingertips_results = {}          # ICB/county-level baseline (England-benchmarked)
fingertips_district = defaultdict(dict)   # {district_name: {signal_key: value}}
fingertips_resolution = {}       # {signal_key: "district" | "icb_fallback"}

print("\nFetching NHS Fingertips indicators (ICB + LAD level)...")
for key, (ind_id, label, area_code) in FINGERTIPS_INDICATORS.items():
    try:
        data = ftp.get_data_for_indicator_at_all_available_geographies(ind_id)
        if data is None:
            raise ValueError("Returned None")

        kent = data[data["Area Code"] == area_code].sort_values("Time period")
        eng  = data[data["Area Code"] == ENGLAND].sort_values("Time period")
        if len(kent) == 0:
            raise ValueError(f"No data for {area_code}")
        kent_val = round(float(kent.tail(1)["Value"].values[0]), 2)
        eng_val  = round(float(eng.tail(1)["Value"].values[0]), 2) if len(eng) else None
        period   = str(kent.tail(1)["Time period"].values[0])
        fingertips_results[key] = {
            "value": kent_val, "england": eng_val,
            "period": period, "source": f"NHS Fingertips indicator {ind_id}", "label": label,
        }
        direction = "▲" if eng_val and kent_val > eng_val else "▼"
        print(f"  ✓ {label:<35} {kent_val:>8} vs {str(eng_val):>8} {direction} [{period}]")

        # ── Extract district (LAD) level values from the same response ──
        latest_period = period
        district_hits = 0
        for lad_code in LAD_CODES.values():
            rows = data[(data["Area Code"] == lad_code)].sort_values("Time period")
            if len(rows) == 0:
                continue
            # Prefer the same period as the ICB latest; else take that LAD's latest
            same_period = rows[rows["Time period"].astype(str) == latest_period]
            chosen = same_period if len(same_period) else rows.tail(1)
            try:
                val = round(float(chosen.tail(1)["Value"].values[0]), 2)
            except (ValueError, TypeError):
                continue
            if val is None or (isinstance(val, float) and val != val):  # NaN guard
                continue
            fingertips_district[LAD_TO_NAME[lad_code]][key] = val
            district_hits += 1

        if district_hits >= len(LAD_CODES) - 2:   # allow up to 2 missing
            fingertips_resolution[key] = "district"
            print(f"      → district-level: {district_hits}/{len(LAD_CODES)} LADs resolved")
        else:
            fingertips_resolution[key] = "icb_fallback"
            print(f"      → ICB fallback ({district_hits}/{len(LAD_CODES)} LADs only)")

    except Exception as e:
        print(f"  ✗ {label}: {e}")
        fingertips_results[key] = {"value": None, "england": None, "period": None,
                                    "source": f"NHS Fingertips {ind_id}", "label": label}
        fingertips_resolution[key] = "unavailable"

# ── SIGNAL DEFINITIONS ────────────────────────────────────────────────
SIGNAL_NAMES = [
    "Over-75s Living Alone", "Falls Admissions 65+", "Hip Fracture Rate 65+",
    "Deprivation (IMD)", "Winter Mortality Index", "Care Home Gap",
    "Loneliness Rate", "Dementia Diagnosis Rate", "Hip Fractures 80+",
    "Social Isolation Rate", "Hypnotics Prescribing", "Antidepressant Rate",
    "Bisphosphonate Rate", "Diuretics Rate", "ACE/ARB Prescribing",
    "Anxiolytics Prescribing", "Bladder Antimuscarinic Rate",
    "Oral Nutritional Supplements", "Anti-Dementia Drug Rate",
    "Denosumab Prescribing", "Parkinson's Drug Rate",
]

WEIGHTS = [
    0.11, 0.11, 0.08, 0.07, 0.07, 0.06, 0.05, 0.05, 0.04, 0.04,
    0.04, 0.04, 0.03, 0.01, 0.01, 0.03, 0.02, 0.05, 0.04, 0.02, 0.03,
]
assert abs(sum(WEIGHTS) - 1.0) < 0.001

ENGLAND_PRESCRIBING_RATES = {
    "hypnotics": 10.2, "anxiolytics": 8.5, "antidepressants": 110.0,
    "bisphosphonates": 6.8, "diuretics": 2.5, "ace_arb": 95.0,
    "bladder_antimusc": 4.2, "oral_nutrition": 3.1,
    "anti_dementia": 2.8, "denosumab": 0.9, "parkinsons": 2.4,
}

EPD_SIGNAL_KEYS_ORDERED = [
    "hypnotics", "antidepressants", "bisphosphonates", "diuretics", "ace_arb",
    "anxiolytics", "bladder_antimusc", "oral_nutrition", "anti_dementia", "denosumab", "parkinsons"
]
EPD_SIGNAL_INDICES = list(range(10, 21))

def norm(value, england, invert=False):
    if not value or not england: return 50.0
    score = (value / england) * 50
    return round(min(100, max(0, 100 - score if invert else score)), 1)

def ft(key, invert=False):
    v = fingertips_results.get(key, {})
    return norm(v.get("value"), v.get("england"), invert)

def epd_norm(district, signal_key):
    d_data = last_epd_d.get(district, {}).get(signal_key, {})
    return norm(d_data.get("rate_per_1000"), ENGLAND_PRESCRIBING_RATES.get(signal_key))

# Map FEP signal index → Fingertips key (+ invert flag) for the 7 outcome
# signals that come from Fingertips. Indices 0,3,5 are synthetic; 10-20 are EPD.
FT_SIGNAL_MAP = {
    1: ("falls_65",           False),
    2: ("hip_fractures_65",   False),
    4: ("winter_mortality",   False),
    6: ("loneliness",         False),
    7: ("dementia_diagnosis", True),
    8: ("hip_fractures_80",   False),
    9: ("social_isolation",   False),
}

def ft_district_norm(district, signal_key, invert=False):
    """Normalise a district's real LAD-level Fingertips value against England.
    Falls back to the ICB-level normalised value if the district value is missing."""
    eng = fingertips_results.get(signal_key, {}).get("england")
    dval = fingertips_district.get(district, {}).get(signal_key)
    if dval is not None and eng:
        return norm(dval, eng, invert)
    # Fallback: ICB-level normalised value (same for all districts)
    return ft(signal_key, invert)

ICB_BASE = [
    50.0, ft("falls_65"), ft("hip_fractures_65"), 50.0, ft("winter_mortality"), 50.0,
    ft("loneliness"), ft("dementia_diagnosis", invert=True), ft("hip_fractures_80"),
    ft("social_isolation"), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
]  # retained for reference / ICB-level diagnostics; district scoring uses real LAD data

# ── SYNTHETIC SIGNAL DISTRICT PROFILES ───────────────────────────────
# The 7 Fingertips outcome signals now use REAL district-level data (see
# FT_SIGNAL_MAP + ft_district_norm). Only the 3 synthetic signals that have
# no district-level Fingertips source retain modelled district differentiation:
#   idx 0 — Over-75s Living Alone   (Census 2021 TS011 — to be wired to real data)
#   idx 3 — Deprivation (IMD)       (IMD 2025 LAD-level — to be wired to real data)
#   idx 5 — Care Home Gap           (modelled — no open district source)
# These multipliers scale a 50.0 neutral base and are explicitly flagged as
# 'modelled' in the output. They are the next candidates for real-data upgrade.
SYNTH_PROFILES = {
    "Thanet":              {0: 1.30, 3: 1.35, 5: 1.30},
    "Folkestone & Hythe":  {0: 1.22, 3: 1.22, 5: 1.20},
    "Dover":               {0: 1.18, 3: 1.18, 5: 1.10},
    "Swale":               {0: 1.12, 3: 1.12, 5: 1.12},
    "Medway":              {0: 1.06, 3: 1.08, 5: 1.08},
    "Gravesham":           {0: 1.00, 3: 1.02, 5: 1.05},
    "Ashford":             {0: 0.96, 3: 0.98, 5: 1.00},
    "Canterbury":          {0: 0.90, 3: 0.85, 5: 0.92},
    "Dartford":            {0: 0.88, 3: 0.95, 5: 0.90},
    "Maidstone":           {0: 0.85, 3: 0.95, 5: 0.92},
    "Tonbridge & Malling": {0: 0.78, 3: 0.78, 5: 0.85},
    "Sevenoaks":           {0: 0.65, 3: 0.52, 5: 0.75},
    "Tunbridge Wells":     {0: 0.58, 3: 0.58, 5: 0.65},
}
SYNTH_INDICES = [0, 3, 5]   # Over-75s living alone, IMD deprivation, care home gap

POP75 = {
    "Thanet":18200,"Folkestone & Hythe":14100,"Dover":13800,"Swale":15200,
    "Medway":19400,"Gravesham":11800,"Ashford":13600,"Canterbury":16300,
    "Dartford":10800,"Maidstone":16700,"Tonbridge & Malling":13100,
    "Sevenoaks":12100,"Tunbridge Wells":11200,
}

# ── BUILD DISTRICT SCORES ─────────────────────────────────────────────
# Signal construction per district:
#   • Fingertips outcome signals (idx 1,2,4,6,7,8,9) → REAL LAD-level data,
#     normalised vs England, with ICB fallback if a district is unpublished.
#   • Synthetic signals (idx 0,3,5) → 50.0 neutral base × modelled multiplier.
#   • EPD prescribing signals (idx 10-20) → reused from last manual NHSBSA run.
print("\nBuilding district FEP scores (real LAD-level Fingertips)...")
districts = []
for name in LAD_CODES:
    synth = SYNTH_PROFILES[name]
    signals = [0.0] * 21

    # Synthetic signals — neutral 50 base scaled by modelled district multiplier
    for i in SYNTH_INDICES:
        signals[i] = round(min(100, max(0, 50.0 * synth.get(i, 1.0))), 1)

    # Fingertips outcome signals — real district data with ICB fallback
    for i, (ft_key, invert) in FT_SIGNAL_MAP.items():
        signals[i] = ft_district_norm(name, ft_key, invert)

    # EPD prescribing signals — reused district-level prescribing
    for idx, epd_key in zip(EPD_SIGNAL_INDICES, EPD_SIGNAL_KEYS_ORDERED):
        signals[idx] = epd_norm(name, epd_key)

    fep  = round(min(100, max(0, sum(s * w for s, w in zip(signals, WEIGHTS)))))
    risk = "critical" if fep >= 70 else "high" if fep >= 55 else "moderate" if fep >= 40 else "low"

    # Count how many Fingertips signals resolved to real district data
    real_ft = sum(1 for i,(k,_) in FT_SIGNAL_MAP.items()
                  if fingertips_district.get(name, {}).get(k) is not None)

    districts.append({
        "name": name, "lad_code": LAD_CODES[name], "fep": fep,
        "risk": risk, "signals": signals, "signal_names": SIGNAL_NAMES,
        "pop75": POP75[name],
        "fingertips_district_signals": real_ft,
    })
    print(f"  {name:<25} FEP {fep:>3}  ({risk})  [{real_ft}/{len(FT_SIGNAL_MAP)} real district signals]")

districts.sort(key=lambda x: x["fep"], reverse=True)

# ── v5.1: FEP delta — rate of change vs previous commit ──────────────────────
# Loads the last committed JSON and computes per-district FEP change.
# fep_delta > 0 = rising risk, fep_delta < 0 = falling risk.
# Used for predictive alerting: a zone with rising FEP + rising 111 demand
# is a crisis precursor candidate even if absolute FEP score is not yet critical.
print("\nComputing FEP deltas vs previous commit...")
prev_scores = {}
try:
    prev_resp = requests.get(RAW_URL, timeout=10)
    if prev_resp.status_code == 200:
        prev_data = prev_resp.json()
        prev_scores = {d["name"]: d["fep"] for d in prev_data.get("districts", [])}
        print(f"  Previous commit loaded: {prev_data.get('meta',{}).get('generated','?')[:10]}")
except Exception as e:
    print(f"  Could not load previous commit: {e} — deltas will be null")

for d in districts:
    prev = prev_scores.get(d["name"])
    d["fep_delta"]          = (d["fep"] - prev) if prev is not None else None
    d["fep_delta_direction"] = ("rising" if d["fep_delta"] and d["fep_delta"] > 0
                                 else "falling" if d["fep_delta"] and d["fep_delta"] < 0
                                 else "stable" if d["fep_delta"] == 0 else "unknown")

# ── v5.1: Crisis precursor flags ─────────────────────────────────────────────
# A zone is flagged as a crisis precursor if BOTH:
#   1. FEP score is rising (fep_delta > 0) AND fep_delta >= 2 points
#   2. FEP risk tier is 'high' or 'critical'
# This is a conservative threshold — designed to surface genuine acceleration
# rather than noise from minor Fingertips indicator updates.
# The 111 velocity component will be added once 111 data is non-zero.
print("\nCrisis precursor assessment:")
for d in districts:
    delta = d.get("fep_delta") or 0
    rising_significant = delta >= 2
    high_risk = d["risk"] in ("high", "critical")
    d["crisis_precursor"] = rising_significant and high_risk
    if d["crisis_precursor"]:
        print(f"  ⚠ CRISIS PRECURSOR: {d['name']} FEP {d['fep']} (Δ+{delta})")

precursor_count = sum(1 for d in districts if d.get("crisis_precursor"))
if precursor_count == 0:
    print("  No crisis precursors flagged (all deltas < 2 points or risk < high)")


# ── ASSEMBLE OUTPUT ───────────────────────────────────────────────────
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
real_signals = [k for k, v in fingertips_results.items() if v.get("value")]

# Derive EPD period from the actual prescribing data rather than inheriting a
# possibly-blank meta field. Each prescribing signal carries its own "period"
# (e.g. "Mar 2026") stamped at the last manual EPD run. Read it from the data
# so the published period can never silently go blank.
def derive_epd_period():
    # 1. Prefer a non-blank inherited meta value
    inherited = (last_meta.get("epd_period") or "").strip()
    if inherited:
        return inherited
    # 2. Fall back to the period stamped on any prescribing signal
    for sig in last_epd.values():
        if isinstance(sig, dict):
            p = (sig.get("period") or "").strip()
            if p:
                return p
    # 3. Last resort: parse from a signal source string like "...MAR2026"
    import re as _re
    for sig in last_epd.values():
        if isinstance(sig, dict):
            src = sig.get("source", "")
            m = _re.search(r'([A-Z]{3})(\d{4})', src.upper())
            if m:
                return f"{m.group(1).title()} {m.group(2)}"
    return "unknown"

epd_period = derive_epd_period()
print(f"\nEPD period resolved: {epd_period}")

output = {
    "meta": {
        "generated":         datetime.now(timezone.utc).isoformat(),
        "description":       "Kent & Medway FEP scores — Assistiv Systems Layer 2",
        "version":           "5.1 — real LAD-level Fingertips (district scoring)",
        "refresh_type":      "daily — Fingertips at LAD level (EPD reused from last manual run)",
        "epd_period":        epd_period,
        "icb":               "NHS Kent and Medway ICB (QKS)",
        "icb_ons_code":      KENT_ICB_ONS,
        "data_quality":      f"real — {len(real_signals)} Fingertips signals (district-level where published) + EPD from last manual run",
        "signals_real":      real_signals,
        "signals_synthetic": ["alone_75", "deprivation_imd", "care_home_gap"],
        "fingertips_resolution": fingertips_resolution,
        "scoring_note": ("Fingertips outcome signals use real LAD-level district data normalised vs England, "
                         "with ICB-level fallback for any district not published at LAD level. "
                         "Synthetic signals (over-75s living alone, IMD deprivation, care home gap) remain "
                         "modelled pending real district sources. EPD prescribing reused from last manual NHSBSA run."),
        "signal_names":      SIGNAL_NAMES,
        "weights":           WEIGHTS,
        "fep_delta_note": ("fep_delta = change vs previous daily commit. ""Positive = rising risk. crisis_precursor = True when delta >= 2 AND risk is high/critical. ""Phase 2: add 111 call velocity to precursor logic."),
        "sources": {
            "fingertips": "NHS Fingertips/OHID PHOF via fingertips_py — fetched today",
            "epd":        f"NHSBSA EPD — {epd_period} (reused)",
        },
    },
    "icb_baseline": {
        "fingertips":  fingertips_results,
        "prescribing": last_epd,
    },
    "districts": districts,
}

# ── COMMIT CURRENT + HISTORIC ─────────────────────────────────────────
def commit_file(content_dict, filepath, message):
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
    b64 = base64.b64encode(json.dumps(content_dict, indent=2).encode()).decode()
    r = requests.get(api_url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": message, "content": b64, "branch": "main"}
    if sha: payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ {filepath}")
        return True
    print(f"  ✗ {filepath}: {r.status_code} {r.json().get('message','')}")
    return False

# ── Delta scorecard ──────────────────────────────────────────────────────────
print(f"\n── FEP Delta Scorecard ({today}) ──")
print(f"  {'District':<25} {'FEP':>5}  {'Prev':>5}  {'Δ':>5}  Direction     Precursor")
print(f"  {'-'*70}")
for d in districts:
    prev_fep = prev_scores.get(d["name"], "?")
    delta_str = f"+{d['fep_delta']}" if d.get('fep_delta') and d['fep_delta'] > 0 else str(d.get('fep_delta','?'))
    precursor = "⚠ YES" if d.get("crisis_precursor") else ""
    print(f"  {d['name']:<25} {d['fep']:>5}  {str(prev_fep):>5}  {delta_str:>5}  {d['fep_delta_direction']:<12}  {precursor}")

msg = f"Daily FEP refresh — {today} — Fingertips updated"
print(f"\nCommitting...")
commit_file(output, GITHUB_FILE, msg)
commit_file(output, f"history/kent-fep-{today}.json", msg)
print(f"\nDone — {today}")
