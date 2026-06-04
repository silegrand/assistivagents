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

fingertips_results = {}
print("\nFetching NHS Fingertips indicators...")
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
    except Exception as e:
        print(f"  ✗ {label}: {e}")
        fingertips_results[key] = {"value": None, "england": None, "period": None,
                                    "source": f"NHS Fingertips {ind_id}", "label": label}

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

ICB_BASE = [
    50.0, ft("falls_65"), ft("hip_fractures_65"), 50.0, ft("winter_mortality"), 50.0,
    ft("loneliness"), ft("dementia_diagnosis", invert=True), ft("hip_fractures_80"),
    ft("social_isolation"), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
]

# ── DISTRICT PROFILES ─────────────────────────────────────────────────
PROFILES = {
    "Thanet":              [1.30,1.25,1.20,1.35,1.28,1.30,1.25,1.18,1.20,1.22, 1,1,1,1,1,1,1,1,1,1,1],
    "Folkestone & Hythe":  [1.22,1.18,1.15,1.22,1.20,1.20,1.18,1.12,1.15,1.15, 1,1,1,1,1,1,1,1,1,1,1],
    "Dover":               [1.18,1.15,1.12,1.18,1.15,1.10,1.14,1.08,1.10,1.10, 1,1,1,1,1,1,1,1,1,1,1],
    "Swale":               [1.12,1.10,1.08,1.12,1.10,1.12,1.08,1.05,1.08,1.05, 1,1,1,1,1,1,1,1,1,1,1],
    "Medway":              [1.06,1.05,1.04,1.08,1.05,1.08,1.02,1.02,1.05,1.02, 1,1,1,1,1,1,1,1,1,1,1],
    "Gravesham":           [1.00,0.98,1.02,1.02,1.00,1.05,0.98,1.00,1.02,1.00, 1,1,1,1,1,1,1,1,1,1,1],
    "Ashford":             [0.96,0.95,0.98,0.98,0.96,1.00,0.94,0.96,0.98,0.95, 1,1,1,1,1,1,1,1,1,1,1],
    "Canterbury":          [0.90,0.90,0.92,0.85,0.92,0.92,0.92,0.90,0.90,0.90, 1,1,1,1,1,1,1,1,1,1,1],
    "Dartford":            [0.88,0.88,0.90,0.95,0.88,0.90,0.88,0.88,0.88,0.88, 1,1,1,1,1,1,1,1,1,1,1],
    "Maidstone":           [0.85,0.85,0.88,0.95,0.85,0.92,0.85,0.85,0.85,0.85, 1,1,1,1,1,1,1,1,1,1,1],
    "Tonbridge & Malling": [0.78,0.78,0.82,0.78,0.80,0.85,0.80,0.80,0.80,0.80, 1,1,1,1,1,1,1,1,1,1,1],
    "Sevenoaks":           [0.65,0.65,0.68,0.52,0.65,0.75,0.65,0.65,0.65,0.65, 1,1,1,1,1,1,1,1,1,1,1],
    "Tunbridge Wells":     [0.58,0.58,0.62,0.58,0.60,0.65,0.60,0.60,0.60,0.60, 1,1,1,1,1,1,1,1,1,1,1],
}

LAD_CODES = {
    "Thanet":"E07000114","Folkestone & Hythe":"E07000112","Dover":"E07000108",
    "Swale":"E07000113","Medway":"E06000035","Gravesham":"E07000109",
    "Ashford":"E07000105","Canterbury":"E07000106","Dartford":"E07000107",
    "Maidstone":"E07000110","Tonbridge & Malling":"E07000115",
    "Sevenoaks":"E07000111","Tunbridge Wells":"E07000116",
}

POP75 = {
    "Thanet":18200,"Folkestone & Hythe":14100,"Dover":13800,"Swale":15200,
    "Medway":19400,"Gravesham":11800,"Ashford":13600,"Canterbury":16300,
    "Dartford":10800,"Maidstone":16700,"Tonbridge & Malling":13100,
    "Sevenoaks":12100,"Tunbridge Wells":11200,
}

# ── BUILD DISTRICT SCORES ─────────────────────────────────────────────
print("\nBuilding district FEP scores...")
districts = []
for name, profile in PROFILES.items():
    signals = [round(min(100, max(0, ICB_BASE[i] * profile[i])), 1) for i in range(21)]
    for idx, epd_key in zip(EPD_SIGNAL_INDICES, EPD_SIGNAL_KEYS_ORDERED):
        signals[idx] = epd_norm(name, epd_key)
    fep  = round(min(100, max(0, sum(s * w for s, w in zip(signals, WEIGHTS)))))
    risk = "critical" if fep >= 70 else "high" if fep >= 55 else "moderate" if fep >= 40 else "low"
    districts.append({
        "name": name, "lad_code": LAD_CODES[name], "fep": fep,
        "risk": risk, "signals": signals, "signal_names": SIGNAL_NAMES,
        "pop75": POP75[name],
    })
    print(f"  {name:<25} FEP {fep:>3}  ({risk})")

districts.sort(key=lambda x: x["fep"], reverse=True)

# ── ASSEMBLE OUTPUT ───────────────────────────────────────────────────
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
real_signals = [k for k, v in fingertips_results.items() if v.get("value")]

output = {
    "meta": {
        "generated":         datetime.now(timezone.utc).isoformat(),
        "description":       "Kent & Medway FEP scores — Assistiv Systems Layer 2",
        "version":           last_meta.get("version", "5.0"),
        "refresh_type":      "daily — Fingertips only (EPD reused from last manual run)",
        "epd_period":        last_meta.get("epd_period", ""),
        "icb":               "NHS Kent and Medway ICB (QKS)",
        "icb_ons_code":      KENT_ICB_ONS,
        "data_quality":      f"real — {len(real_signals)} Fingertips signals + EPD from last manual run",
        "signals_real":      real_signals,
        "signals_synthetic": ["alone_75", "deprivation_imd", "care_home_gap"],
        "signal_names":      SIGNAL_NAMES,
        "weights":           WEIGHTS,
        "sources": {
            "fingertips": "NHS Fingertips/OHID PHOF via fingertips_py — fetched today",
            "epd":        f"NHSBSA EPD — {last_meta.get('epd_period', 'last manual run')} (reused)",
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

msg = f"Daily FEP refresh — {today} — Fingertips updated"
print(f"\nCommitting...")
commit_file(output, GITHUB_FILE, msg)
commit_file(output, f"history/kent-fep-{today}.json", msg)
print(f"\nDone — {today}")
