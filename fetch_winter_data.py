"""
fetch_winter_data.py — Assistiv Systems Winter Readiness Intelligence
Runs in GitHub Actions (hes_shmi_gp_monthly.yml, 12th of each month).

Pulls NHS Fingertips seasonal indicators, reads existing FEP/corridor/GP data,
calculates Winter Vulnerability Index (WVI) per Kent district, generates
deployment window recommendations and plain-English narratives, and commits
kent-winter-data.json to the assistiv_cloud repo.

WVI components (weights):
  1. Baseline Frailty Load     30% — FEP × 75+ registered population
  2. Seasonal Amplifier        20% — national evidence uplift applied to baseline
  3. Prescribing Signal        20% — six high-frailty EPD drug class trends
  4. System Headroom           20% — corridor care rate at serving trust
  5. Social Isolation          10% — over-75s alone + social isolation index

Deployment windows derived from NICE evidence on intervention lead times:
  - Medication review:      September (4 weeks to optimise pre-winter)
  - Falls prevention:       October (Otago: 6–8 weeks before measurable reduction)
  - Respiratory outreach:   October (flu vaccination complete by end of October)
  - Social connection:      November (social prescribing: 6–8 weeks to engagement)
"""

import os, json, requests, base64
import fingertips_py as ftp
from datetime import datetime, timezone

# ── CONFIG ────────────────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistiv_cloud"
GITHUB_FILE  = "kent-winter-data.json"
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"

KENT_ICB_ONS = "E54000032"
KENT_COUNTY  = "E10000016"
ENGLAND      = "E92000001"

LAD_CODES = {
    "Thanet":              "E07000114",
    "Folkestone & Hythe":  "E07000112",
    "Dover":               "E07000108",
    "Swale":               "E07000113",
    "Medway":              "E06000035",
    "Gravesham":           "E07000109",
    "Ashford":             "E07000105",
    "Canterbury":          "E07000106",
    "Dartford":            "E07000107",
    "Maidstone":           "E07000110",
    "Tonbridge & Malling": "E07000115",
    "Sevenoaks":           "E07000111",
    "Tunbridge Wells":     "E07000116",
}

# Trust → district mapping (mirrors kent-corridor-data.json)
DISTRICT_TO_TRUST = {
    "Thanet": "RVV", "Dover": "RVV", "Folkestone & Hythe": "RVV",
    "Canterbury": "RVV", "Swale": "RVV",
    "Maidstone": "RWF", "Tonbridge & Malling": "RWF", "Tunbridge Wells": "RWF",
    "Sevenoaks": "RWF", "Ashford": "RWF", "Gravesham": "RWF", "Dartford": "RWF",
    "Medway": "RWF",  # Medway served primarily by MTW for frailty pathways
}

TRUST_NAMES = {
    "RVV": "East Kent Hospitals University NHS Foundation Trust",
    "RWF": "Maidstone and Tunbridge Wells NHS Trust",
}

# ── SEASONAL EVIDENCE CONSTANTS ───────────────────────────────────────────────
# From published evidence — baked in as per build plan
# These calibrate the seasonal amplifier component
SEASONAL_UPLIFT = {
    "falls_jan_uplift_pct":          27,   # NHS Digital HES / Fingertips midpoint 23–31%
    "hip_fracture_jan_uplift_pct":   21,   # NICE NG147 evidence review midpoint 18–24%
    "copd_winter_uplift_pct":        50,   # Fingertips / NICOR midpoint 40–60%
    "mortality_jan_uplift_pct":      18,   # ONS excess winter deaths midpoint 15–22%
    "ae_jan_uplift_pct":             15,   # NHS England UEC data midpoint 12–18%
    "non_adherence_festive_pct":     40,   # RCGP evidence midpoint 35–45%
    "gp_consult_drop_dec_pct":      -25,   # NHS Digital GP appointments
}

# Monthly seasonal pressure indices (relative to annual average = 100)
# Index 0 = October 2026 (deployment month), through winter peak, to March 2027
SEASONAL_CURVE = {
    "months":       ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"],
    "falls_index":  [88,    92,    108,   127,   115,   98,    82,    75,    72,    70,    72,    78],
    "copd_index":   [92,    105,   128,   158,   145,   110,   88,    78,    72,    68,    70,    80],
    "corridor_idx": [85,    92,    108,   128,   118,   102,   84,    78,    75,    72,    74,    80],
}

# NICE intervention lead times (weeks before measurable impact)
INTERVENTION_LEAD = {
    "falls_prevention":    8,   # Otago exercise programme
    "medication_review":   4,
    "respiratory_outreach": 4,  # flu vaccination + COPD review
    "social_connection":   8,   # social prescribing to meaningful engagement
}

# England prescribing benchmarks (rate per 1,000 registered patients)
# Used to normalise district EPD data
ENGLAND_EPD_RATES = {
    "bladder_antimusc": 4.2,
    "anti_dementia":    2.8,
    "parkinsons":       2.4,
    "hypnotics":       10.2,
    "anxiolytics":      8.5,
    "ons_nutrition":    3.8,
}

# WVI component weights
WVI_WEIGHTS = {
    "baseline_frailty":  0.30,
    "seasonal_amplifier": 0.20,
    "prescribing_signal": 0.20,
    "system_headroom":   0.20,
    "social_isolation":  0.10,
}

assert abs(sum(WVI_WEIGHTS.values()) - 1.0) < 0.001


# ── LOAD EXISTING DATA ────────────────────────────────────────────────────────

def load_json(filename):
    url = f"{RAW_BASE}/{filename}"
    r = requests.get(url, timeout=20)
    if r.status_code == 200:
        print(f"  ✓ Loaded {filename}")
        return r.json()
    print(f"  ✗ Could not load {filename} (HTTP {r.status_code})")
    return {}


print("Loading existing Assistiv data files...")
fep_data      = load_json("kent-fep-data.json")
corridor_data = load_json("kent-corridor-data.json")
gp_data       = load_json("kent-gp-reg-data.json")
hes_data      = load_json("kent-hes-data.json")

fep_by_district   = {d["name"]: d for d in fep_data.get("districts", [])}
corridor_by_trust = corridor_data.get("trusts", {})
gp_by_district    = gp_data.get("districts", {})


# ── FINGERTIPS: SEASONAL INDICATORS ───────────────────────────────────────────
# Two indicators per the build plan (COPD + flu vaccination)
# Also fetches falls indicator for cross-validation
SEASONAL_INDICATORS = {
    "copd_emergency":  (41001, "COPD emergency admissions",          KENT_ICB_ONS),
    "asthma_emergency": (90640, "Asthma emergency admissions",       KENT_ICB_ONS),
    "flu_vacc_65plus": (93096, "Flu vaccination coverage 65+",       KENT_ICB_ONS),
    "falls_65":        (22401, "Falls admissions 65+",               KENT_ICB_ONS),
    "mortality_rate":  (40401, "All-cause mortality rate",           KENT_ICB_ONS),
}

seasonal_ft = {}
print("\nFetching Fingertips seasonal indicators...")
for key, (ind_id, label, area_code) in SEASONAL_INDICATORS.items():
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
        seasonal_ft[key] = {
            "value": kent_val, "england": eng_val,
            "period": period, "label": label,
            "source": f"NHS Fingertips indicator {ind_id}",
        }
        direction = "▲" if eng_val and kent_val > eng_val else "▼"
        print(f"  ✓ {label:<40} {kent_val:>8} vs {str(eng_val):>8} {direction}")
    except Exception as e:
        print(f"  ✗ {label}: {e}")
        seasonal_ft[key] = {
            "value": None, "england": None, "period": None,
            "label": label, "source": f"NHS Fingertips {ind_id}",
        }


# ── WVI CALCULATION ───────────────────────────────────────────────────────────

def norm_score(value, benchmark, invert=False, clamp=(0, 100)):
    """Normalise a value against a benchmark → 0–100 score."""
    if value is None or benchmark is None or benchmark == 0:
        return 50.0
    ratio = value / benchmark
    score = ratio * 50 if not invert else (2 - ratio) * 50
    return round(max(clamp[0], min(clamp[1], score)), 1)


def component_baseline_frailty(district_name, fep_rec, gp_rec):
    """
    Baseline Frailty Load (weight 30%).
    Combines FEP score (intensity) with 75+ registered population (scale).
    Normalised so England-average FEP (50) with median Kent pop75 → 50.
    """
    fep_score = fep_rec.get("fep", 50)
    pop75 = gp_rec.get("pop_75plus", fep_rec.get("pop75", 0))

    # Kent median pop75 ≈ 13,800 (derived from GP reg data)
    KENT_MEDIAN_POP75 = 13800
    MAX_POP75         = 22000   # Medway upper bound

    # Scale: FEP as intensity (0–100), pop75 as concentration (0–100)
    fep_component = fep_score  # already 0–100
    pop_component = norm_score(pop75, KENT_MEDIAN_POP75)

    # Combined: 60% intensity, 40% concentration
    combined = round(fep_component * 0.6 + pop_component * 0.4, 1)
    return min(100, combined)


def component_seasonal_amplifier(district_name, fep_rec):
    """
    Seasonal Amplifier (weight 20%).
    Applies national evidence uplift factors to the district's existing
    frailty and winter mortality signals.
    """
    signals = fep_rec.get("signals", [])
    # Signal index 4 = winter mortality index (from Fingertips)
    winter_mortality_signal = signals[4] if len(signals) > 4 else 50.0

    # COPD admission rate at ICB level (from freshly fetched Fingertips)
    copd_val = seasonal_ft.get("copd_emergency", {}).get("value") or 0
    copd_eng = seasonal_ft.get("copd_emergency", {}).get("england") or 1
    copd_score = norm_score(copd_val, copd_eng)

    # Falls signal from FEP model (already normalised 0–100)
    falls_signal = signals[1] if len(signals) > 1 else 50.0

    # Flu vaccination: lower coverage → higher risk (inverted)
    flu_val = seasonal_ft.get("flu_vacc_65plus", {}).get("value") or 0
    flu_eng = seasonal_ft.get("flu_vacc_65plus", {}).get("england") or 1
    flu_risk = norm_score(flu_val, flu_eng, invert=True)

    # Weighted blend
    amplifier = (
        falls_signal          * 0.30 +
        winter_mortality_signal * 0.25 +
        copd_score            * 0.25 +
        flu_risk              * 0.20
    )
    return round(min(100, amplifier), 1)


def component_prescribing_signal(district_name, fep_rec):
    """
    Pre-Winter Prescribing Signal (weight 20%).
    Six high-frailty EPD drug classes.
    Rising rate vs England benchmark → higher score (more at risk).
    """
    epd = fep_rec.get("epd_district", {})
    if not epd:
        return 50.0  # neutral if no EPD data

    scores = []
    for drug_key, eng_rate in ENGLAND_EPD_RATES.items():
        rec = epd.get(drug_key, {})
        rate = rec.get("rate_per_1000")
        if rate is not None and eng_rate:
            scores.append(norm_score(rate, eng_rate))

    return round(sum(scores) / len(scores), 1) if scores else 50.0


def component_system_headroom(district_name):
    """
    System Headroom (weight 20%).
    Corridor care rate at the serving trust.
    Higher corridor care NOW → less capacity to absorb winter surge → higher WVI score.
    RWF May 2026: 21 avg/day (very limited headroom).
    RVV May 2026: 1 avg/day (more capacity).
    Benchmark: 5 avg/day nationally (pre-winter threshold, NHS England).
    """
    trust_code = DISTRICT_TO_TRUST.get(district_name, "RWF")
    trust = corridor_by_trust.get(trust_code, {})
    corridor_total = trust.get("corridor_total", 0) or 0

    # Normalise: 0 avg = score 0 (full headroom), 30+ avg = score 100 (no headroom)
    BENCHMARK_THRESHOLD = 5.0   # avg corridor/day above which winter risk elevates
    MAX_CORRIDOR        = 30.0

    if corridor_total <= BENCHMARK_THRESHOLD:
        score = (corridor_total / BENCHMARK_THRESHOLD) * 35  # 0–35: adequate
    else:
        score = 35 + ((corridor_total - BENCHMARK_THRESHOLD) / (MAX_CORRIDOR - BENCHMARK_THRESHOLD)) * 65
    return round(min(100, score), 1)


def component_social_isolation(district_name, fep_rec):
    """
    Social Isolation Index (weight 10%).
    Over-75s living alone (FEP signal 0) + social isolation rate (signal 9).
    Christmas isolation peak makes this a genuine winter amplifier.
    """
    signals = fep_rec.get("signals", [])
    alone_signal     = signals[0] if len(signals) > 0 else 50.0   # over-75s living alone
    isolation_signal = signals[9] if len(signals) > 9 else 50.0   # social isolation SC users

    # Straight average of the two isolation signals
    return round((alone_signal + isolation_signal) / 2, 1)


def deployment_windows(wvi_score, wvi_tier):
    """
    Deployment window recommendations based on NICE evidence lead times.
    All windows are months in 2026–27; everything must start Sept/Oct
    to have impact by January peak.
    """
    # Base windows from NICE lead times (relative to January peak)
    # Critical/High districts get accelerated deployment (one month earlier)
    accelerate = wvi_tier in ("critical", "high")

    windows = {
        "medication_review":    "September 2026",
        "falls_prevention":     "October 2026",
        "respiratory_outreach": "October 2026",
        "social_connection":    "November 2026",
    }

    if accelerate and wvi_score >= 65:
        # For highest-risk districts, compress medication review and falls into Sept
        windows["medication_review"]    = "September 2026 (urgent)"
        windows["falls_prevention"]     = "September 2026"

    # Evidence rationale per intervention
    evidence = {
        "medication_review":    "NICE NG191 — 4 weeks lead time for structured review to optimise medication pre-winter; reduces emergency admissions and medication non-adherence over festive period.",
        "falls_prevention":     "NICE NG147 — Otago exercise programme requires 6–8 weeks before measurable falls reduction; home hazard assessment 4–6 weeks; deploy by October for January impact.",
        "respiratory_outreach": "UKHSA guidance — flu vaccination ideally complete by end of October; COPD review identifies patients at highest respiratory risk before winter.",
        "social_connection":    "BGS Frailty Toolkit 2024 — social prescribing requires 6–8 weeks to meaningful engagement; November deployment targets Christmas isolation peak.",
    }

    return {"windows": windows, "evidence": evidence}


def winter_narrative(district_name, fep_rec, wvi_score, wvi_tier, component_scores, gp_rec):
    """
    Plain-English three-sentence commissioner narrative per district.
    Mirrors the Ada approach: specific, data-grounded, action-oriented.
    """
    pop75     = gp_rec.get("pop_75plus", fep_rec.get("pop75", 0))
    fep_score = fep_rec.get("fep", 50)
    trust_code = DISTRICT_TO_TRUST.get(district_name, "RWF")
    trust_short = "East Kent Hospitals" if trust_code == "RVV" else "Maidstone & Tunbridge Wells"
    corridor = corridor_by_trust.get(trust_code, {}).get("corridor_total", 0) or 0

    tier_phrase = {
        "critical": "the highest-risk district in Kent for winter frailty decompensation",
        "high":     "one of Kent's higher-risk districts for winter frailty decompensation",
        "elevated": "an elevated-risk district requiring targeted winter planning",
        "managed":  "a district where proactive planning can hold risk at manageable levels",
    }.get(wvi_tier, "a district requiring winter planning attention")

    falls_uplift = SEASONAL_UPLIFT["falls_jan_uplift_pct"]

    narrative = (
        f"{district_name} is {tier_phrase}, with {pop75:,} adults aged 75 and over "
        f"on GP registers and a Frailty Emergence Probability of {fep_score} — "
        f"{"above" if fep_score > 50 else "at"} the England average. "
        f"The serving trust ({trust_short}) is already managing an average of {corridor:.0f} "
        f"corridor care patients per day in May 2026, leaving limited buffer before the winter surge "
        f"that historically drives falls admissions {falls_uplift}% above the annual average in January. "
        f"A September–October deployment of medication review and falls prevention outreach in {district_name} "
        f"is the evidence-supported window to have measurable impact on January admission pressure."
    )
    return narrative


def wvi_tier(score):
    if score >= 70: return "critical"
    if score >= 55: return "high"
    if score >= 40: return "elevated"
    return "managed"


# ── BUILD DISTRICT WVI RECORDS ────────────────────────────────────────────────

print("\nCalculating Winter Vulnerability Index for all 13 Kent districts...")
print(f"  {'District':<25} {'WVI':>5}  {'Tier':<10}  Components")
print(f"  {'-'*75}")

districts_out = {}

for district_name in LAD_CODES:
    fep_rec = fep_by_district.get(district_name, {})
    gp_rec  = gp_by_district.get(district_name, {}) if isinstance(gp_by_district, dict) else {}

    # Calculate the five components
    c_baseline  = component_baseline_frailty(district_name, fep_rec, gp_rec)
    c_seasonal  = component_seasonal_amplifier(district_name, fep_rec)
    c_prescribe = component_prescribing_signal(district_name, fep_rec)
    c_headroom  = component_system_headroom(district_name)
    c_isolation = component_social_isolation(district_name, fep_rec)

    component_scores = {
        "baseline_frailty":  c_baseline,
        "seasonal_amplifier": c_seasonal,
        "prescribing_signal": c_prescribe,
        "system_headroom":   c_headroom,
        "social_isolation":  c_isolation,
    }

    # Weighted composite
    wvi_score = round(
        c_baseline  * WVI_WEIGHTS["baseline_frailty"]  +
        c_seasonal  * WVI_WEIGHTS["seasonal_amplifier"] +
        c_prescribe * WVI_WEIGHTS["prescribing_signal"] +
        c_headroom  * WVI_WEIGHTS["system_headroom"]   +
        c_isolation * WVI_WEIGHTS["social_isolation"],
        1
    )

    tier = wvi_tier(wvi_score)
    deployment = deployment_windows(wvi_score, tier)
    narrative  = winter_narrative(district_name, fep_rec, wvi_score, tier, component_scores, gp_rec)

    trust_code = DISTRICT_TO_TRUST.get(district_name, "RWF")
    trust = corridor_by_trust.get(trust_code, {})

    districts_out[district_name] = {
        "wvi_score":      wvi_score,
        "wvi_tier":       tier,
        "wvi_components": component_scores,
        "deployment_windows": deployment["windows"],
        "deployment_evidence": deployment["evidence"],
        "winter_narrative": narrative,
        "historical_peak_month":      "January",
        "historical_peak_uplift_pct": SEASONAL_UPLIFT["falls_jan_uplift_pct"],
        "fep_score":  fep_rec.get("fep"),
        "fep_risk":   fep_rec.get("risk"),
        "pop_75plus": gp_rec.get("pop_75plus", fep_rec.get("pop75")),
        "list_size":  gp_rec.get("total_list_size"),
        "lad_code":   LAD_CODES[district_name],
        "trust_code": trust_code,
        "trust_name": TRUST_NAMES.get(trust_code, ""),
        "corridor_avg_may2026": trust.get("corridor_total"),
        "corridor_max_may2026": trust.get("corridor_ed_max"),
    }

    print(
        f"  {district_name:<25} {wvi_score:>5}  {tier:<10}  "
        f"base={c_baseline:.0f} sea={c_seasonal:.0f} rx={c_prescribe:.0f} "
        f"hdr={c_headroom:.0f} iso={c_isolation:.0f}"
    )

# Sort by WVI descending
districts_sorted = dict(
    sorted(districts_out.items(), key=lambda x: x[1]["wvi_score"], reverse=True)
)


# ── ASSEMBLE OUTPUT ───────────────────────────────────────────────────────────

today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

output = {
    "meta": {
        "generated":      datetime.now(timezone.utc).isoformat(),
        "planning_year":  "2026-27",
        "description":    "Kent & Medway Winter Vulnerability Index — Assistiv Systems",
        "version":        "1.0",
        "refresh_type":   "monthly — runs 12th of each month via hes_shmi_gp_monthly.yml",
        "wvi_components": WVI_WEIGHTS,
        "seasonal_evidence": SEASONAL_UPLIFT,
        "intervention_lead_weeks": INTERVENTION_LEAD,
        "seasonal_indicators_fetched": {
            k: {
                "value":   v.get("value"),
                "england": v.get("england"),
                "period":  v.get("period"),
                "label":   v.get("label"),
            }
            for k, v in seasonal_ft.items()
        },
        "sources": {
            "fep":       "kent-fep-data.json (daily refresh — Assistiv Systems FEP pipeline)",
            "corridor":  "kent-corridor-data.json (monthly — NHS England corridor care)",
            "gp_reg":    "kent-gp-reg-data.json (monthly — NHS Digital GP Registration)",
            "fingertips": "NHS Fingertips/OHID — COPD admissions, flu vaccination, falls",
            "evidence":  "NICE NG147 (falls), NICE NG191 (frailty), BGS Frailty Toolkit 2024, ONS excess winter deaths, NHS Digital HES, NHS England UEC data",
        },
        "licence": "NHS data published under Open Government Licence v3.0",
        "tiers": {
            "critical": "WVI ≥ 70 — highest winter decompensation risk, accelerated deployment recommended",
            "high":     "WVI 55–69 — elevated risk, September–October deployment essential",
            "elevated": "WVI 40–54 — above-average risk, proactive planning will yield measurable impact",
            "managed":  "WVI < 40 — manageable risk with standard winter planning",
        },
        "commissioner_note": (
            "WVI is a forward-looking planning tool, not a clinical assessment. "
            "It connects existing NHS open data — FEP scores, corridor care, GP registers, "
            "Fingertips outcomes — into a single composite that indicates where preventative "
            "deployment will have the greatest impact on January admission pressure. "
            "Decisions made in August determine what can be deployed by October."
        ),
    },
    "districts": districts_sorted,
    "seasonal_curve": SEASONAL_CURVE,
    "deployment_planning_calendar": {
        "commissioner_decision_by": "August 2026",
        "deployment_start":         "September 2026",
        "impact_target":            "January 2027",
        "rationale": (
            "NICE evidence on intervention lead times requires September–October deployment "
            "to achieve measurable impact by the January–February admission peak. "
            "Commissioner decisions must therefore be made by August 2026."
        ),
    },
}


# ── COMMIT TO GITHUB ──────────────────────────────────────────────────────────

def commit_file(content_dict, filepath, message):
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json",
    }
    b64 = base64.b64encode(json.dumps(content_dict, indent=2).encode()).decode()
    r   = requests.get(api_url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": message, "content": b64, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ Committed {filepath}")
        return True
    print(f"  ✗ Failed {filepath}: {r.status_code} {r.json().get('message', '')}")
    return False


msg = f"Winter readiness data refresh — {today}"
print(f"\nCommitting...")
commit_file(output, GITHUB_FILE, msg)

# Tier summary
print(f"\n── Winter Readiness Summary ({today}) ──")
for tier in ("critical", "high", "elevated", "managed"):
    tier_dists = [n for n, d in districts_sorted.items() if d["wvi_tier"] == tier]
    if tier_dists:
        print(f"  {tier.upper():<10}  {', '.join(tier_dists)}")

print(f"\nDone — {today}")
