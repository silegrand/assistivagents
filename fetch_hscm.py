"""
fetch_hscm.py — Assistiv Systems KPHO Health & Social Care Maps Pipeline
Runs in GitHub Actions as part of hes_shmi_gp_monthly.yml (12th of each month).

Source: Kent Public Health Observatory Health and Social Care Maps v1.x
URL:    https://www.kpho.org.uk/joint-strategic-needs-assessment/health-and-social-care-maps
Data:   https://www.kpho.org.uk/__data/assets/excel_doc/XXXX/XXXXXX/hscm_combined-VX.X.xlsx
Licence: Open Government Licence v3.0

IMPORTANT — MONTHLY MAINTENANCE:
  KPHO update the HSCM dataset periodically (typically quarterly, sometimes more often).
  When a new version is published, update HSCM_DOWNLOAD_URL below with the new link.
  The version and date are in the filename: hscm_combined-V1.6.xlsx = v1.6, published March 2026.
  Check: https://www.kpho.org.uk/joint-strategic-needs-assessment/health-and-social-care-maps

What this script produces:
  kent-hscm-data.json — committed to assistiv_cloud repo, consumed by:
    - nhs-pressure-map.html  (MSOA frailty layer, disease prevalence panel)
    - winter-readiness.html  (carer burden, thermal risk, fuel poverty enrichment)
    - daily_refresh.py       (KPHO frailty signal for FEP recalibration)

Data extracted (all at District level + MSOA level where available):
  Tier 1 — FEP Recalibration:
    frailty_pct          GP-recorded Clinical Frailty Scale % (Nov 2025, quarterly)
    winter_mortality     Winter Mortality Index (2023/24, annual)
    falls_hip_65         Falls admissions 65+ with hip fracture (2022-25, rolling 3yr)

  Tier 2 — Winter Readiness Enrichment:
    fuel_poverty         Fuel poverty % households (2023, annual)
    winter_fuel_pmt      Winter fuel payment recipients % (2023/24, annual)
    older_alone          Older adults living alone % (2021 Census, 5yr)
    unpaid_carers        Unpaid carers % population (2021 Census)
    unpaid_carers_50plus Unpaid carers aged 50+ % (2021 Census)
    unpaid_heavy         Unpaid care 50+ hrs/week % (2021 Census)
    osteoporosis         Osteoporosis prevalence % (2024/25, annual)
    phys_act_65plus      Physical activity 65+ 150+mins/week % (2023/24, annual)

  Tier 3 — Disease Prevalence (MSOA + District):
    copd                 COPD prevalence % (Dec 2025 KMCR)
    dementia             Dementia prevalence % (Dec 2025 KMCR)
    depression           Depression prevalence % (Dec 2025 KMCR)
    heart_failure        Heart failure prevalence % (Dec 2025 KMCR)
    stroke               Stroke prevalence % (Dec 2025 KMCR)
    hypertension         Hypertension prevalence % (Dec 2025 KMCR)

  Tier 4 — Social Determinants:
    pension_credit       Pension Credit claimants % (2024, quarterly)
    dla_65plus           DLA claimants 65+ % (2024/25 Q3, quarterly)
    pip                  PIP claimants % (Feb 2025, monthly)
    access_healthcare    Access to healthcare index (2024, periodic)
"""

import os, json, base64, io, requests, warnings
from datetime import datetime, timezone
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
GITHUB_REPO    = "silegrand/assistiv_cloud"
GITHUB_FILE    = "kent-hscm-data.json"
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
RAW_BASE       = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"

# ── UPDATE THIS URL WHEN KPHO PUBLISH A NEW VERSION ──────────────────────────
# Check: https://www.kpho.org.uk/joint-strategic-needs-assessment/health-and-social-care-maps
# Current version: V1.6, published March 2026
HSCM_VERSION      = "V1.6"
HSCM_PUBLISH_DATE = "March 2026"
HSCM_DOWNLOAD_URL = (
    "https://www.kpho.org.uk/__data/assets/excel_doc/0018/207234/hscm_combined-V1.6.xlsx"
)
HSCM_PAGE_URL = (
    "https://www.kpho.org.uk/joint-strategic-needs-assessment/health-and-social-care-maps"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AssistivSystems/1.0; +https://assistiv.co)",
    "Referer": HSCM_PAGE_URL,
}

# ── KENT DISTRICTS ────────────────────────────────────────────────────────────
KENT_DISTRICTS = [
    "Ashford", "Canterbury", "Dartford", "Dover", "Folkestone & Hythe",
    "Gravesham", "Maidstone", "Medway", "Sevenoaks", "Swale",
    "Thanet", "Tonbridge & Malling", "Tunbridge Wells",
]

# ── INDICATOR DEFINITIONS ─────────────────────────────────────────────────────
# Each entry: output_key → (indicator_name, sex_filter, deprivation_filter, tier)
DISTRICT_INDICATORS = {
    # T1: FEP Recalibration
    "frailty_pct":          ("Frailty in older people", "Persons", "All", 1),
    "frailty_q1":           ("Frailty in older people", "Persons", "District quintile 1", 1),
    "frailty_q5":           ("Frailty in older people", "Persons", "District quintile 5", 1),
    "winter_mortality":     ("Winter Mortality Index", None, "All", 1),
    "falls_hip_65":         ("Falls admissions in people aged 65+ resulting in leg or hip fracture", None, "All", 1),
    # T2: Winter Readiness
    "fuel_poverty":         ("Fuel Poverty", None, "All", 2),
    "winter_fuel_pmt":      ("Winter fuel payments", None, "All", 2),
    "older_alone":          ("Older adults living alone", None, "All", 2),
    "unpaid_carers":        ("Unpaid carers", None, "All", 2),
    "unpaid_carers_50plus": ("Unpaid carers aged 50+", None, "All", 2),
    "unpaid_heavy":         ("Unpaid care of more than 50 hours", None, "All", 2),
    "osteoporosis":         ("Osteoporosis prevalence", None, "All", 2),
    "phys_act_65plus":      ("Physical activity in older adults (150+ minutes a week)", None, "All", 2),
    # T3: Disease Prevalence
    "copd":                 ("Chronic obstructive pulmonary disease (COPD) prevalence", None, "All", 3),
    "dementia":             ("Dementia prevalence", None, "All", 3),
    "depression":           ("Depression prevalence", None, "All", 3),
    "heart_failure":        ("Heart failure prevalence", None, "All", 3),
    "stroke":               ("Stroke prevalence", None, "All", 3),
    "hypertension":         ("Hypertension prevalence", None, "All", 3),
    # T4: Social Determinants
    "pension_credit":       ("Pension Credit", None, "All", 4),
    "dla_65plus":           ("Disability Living Allowance aged 65+", None, "All", 4),
    "pip":                  ("Personal Independence Payments (PIP)", None, "All", 4),
    "access_healthcare":    ("Access To Healthcare", None, "All", 4),
}

# MSOA indicators (subset — only those with consistent coverage)
MSOA_INDICATORS = {
    "frailty_pct":      ("Frailty in older people", "Persons", "All"),
    "older_alone":      ("Older adults living alone", None, "All"),
    "unpaid_heavy":     ("Unpaid care of more than 50 hours", None, "All"),
    "fuel_poverty":     ("Fuel Poverty", None, "All"),
    "winter_mortality": ("Winter Mortality Index", None, "All"),
    "falls_hip_65":     ("Falls admissions in people aged 65+ resulting in leg or hip fracture", None, "All"),
    "pension_credit":   ("Pension Credit", None, "All"),
    "winter_fuel":      ("Winter fuel payments", None, "All"),
    "phys_act_65":      ("Physical activity in older adults (150+ minutes a week)", None, "All"),
}

PCN_INDICATORS = {
    "frailty_pct": ("Frailty in older people", "Persons", "All"),
}

# ── FEP RECALIBRATION WEIGHTS ─────────────────────────────────────────────────
# KPHO frailty_pct is a direct GP-recorded Clinical Frailty Scale measurement.
# It is more reliable than proxy-signal FEP for absolute frailty prevalence.
# Blended FEP = 40% KPHO clinical signal + 60% existing proxy-signal FEP
# This is baked into the JSON output for daily_refresh.py to consume.
# Kent min/max anchors for normalisation (from V1.6 dataset):
KPHO_FRAILTY_KENT_MIN = 2.74   # Swale
KPHO_FRAILTY_KENT_MAX = 6.47   # Thanet
KPHO_FEP_WEIGHT       = 0.40   # weight of clinical signal in blended FEP


def normalise_kpho(value):
    """Normalise KPHO frailty % to 0-100 on Kent scale."""
    if value is None:
        return None
    denom = KPHO_FRAILTY_KENT_MAX - KPHO_FRAILTY_KENT_MIN
    return round(
        max(0.0, min(100.0, (value - KPHO_FRAILTY_KENT_MIN) / denom * 100)),
        1
    )


# ── DOWNLOAD ──────────────────────────────────────────────────────────────────
def download_hscm():
    print(f"Downloading HSCM {HSCM_VERSION} from KPHO…")
    r = requests.get(HSCM_DOWNLOAD_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    print(f"  ✓ Downloaded {len(r.content):,} bytes")
    return r.content


# ── EXTRACT ───────────────────────────────────────────────────────────────────
def extract_district(df, ind_name, sex_filter, dep_filter):
    """Extract latest district-level value per district."""
    sub = df[(df["indicator"] == ind_name) & (df["area_type"] == "District")].copy()
    if sex_filter:
        sub = sub[sub["sex"] == sex_filter]
    dep_values = ["All"] if dep_filter == "All" else [dep_filter]
    sub = sub[sub["deprivation"].isin(dep_values + [float("nan")])]
    # Prefer 'Y' latest; fall back to most recent by sortable period
    latest = sub[sub["latest"] == "Y"]
    if len(latest) == 0:
        latest = sub.sort_values("timeperiod_sortable", ascending=False)
    # Per district: take highest denominator = most complete population base
    latest = latest.sort_values("denominator", ascending=False).groupby("area").first().reset_index()
    return latest


def extract_msoa(df, ind_name, sex_filter, dep_filter):
    """Extract latest MSOA-level values."""
    sub = df[(df["indicator"] == ind_name) & (df["area_type"] == "Middle Super Output Area")].copy()
    if sex_filter:
        sub = sub[sub["sex"] == sex_filter]
    sub = sub[sub["deprivation"].isin(["All", float("nan")])]
    latest = sub[sub["latest"] == "Y"]
    if len(latest) == 0:
        latest = sub.sort_values("timeperiod_sortable", ascending=False)
    latest = latest.sort_values("denominator", ascending=False).groupby("area").first().reset_index()
    return latest


def safe_float(v):
    try:
        f = float(v)
        return round(f, 3) if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def safe_int(v):
    try:
        f = float(v)
        return int(f) if f == f else None
    except (TypeError, ValueError):
        return None


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    import pandas as pd

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"fetch_hscm.py — {today}")

    # ── Download ──
    try:
        content = download_hscm()
        df = pd.read_excel(io.BytesIO(content))
        print(f"  Rows: {len(df):,}  Indicators: {df['indicator'].nunique()}")
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        print("  Falling back to last committed version")
        fallback_url = f"{RAW_BASE}/{GITHUB_FILE}"
        r = requests.get(fallback_url, timeout=10)
        if r.status_code == 200:
            existing = r.json()
            existing["meta"]["fallback"] = True
            existing["meta"]["fallback_reason"] = str(e)
            commit_json(existing, GITHUB_FILE, f"HSCM fallback — {today}")
        return

    # ── Extract district data ──
    print("\nExtracting district-level indicators…")
    district_records = {d: {} for d in KENT_DISTRICTS}

    for key, (ind, sex, dep, tier) in DISTRICT_INDICATORS.items():
        rows = extract_district(df, ind, sex, dep)
        found = 0
        for _, row in rows.iterrows():
            area = row["area"]
            if area in district_records:
                district_records[area][key] = {
                    "value":     safe_float(row["value"]),
                    "numerator": safe_int(row.get("numerator")),
                    "period":    str(row["timeperiod"]),
                    "stat_type": str(row.get("stat_type", "")),
                    "tier":      tier,
                }
                found += 1
        print(f"  {key:<25} {found:>3} districts  [{rows['timeperiod'].iloc[0] if len(rows) > 0 else 'no data'}]")

    # ── FEP recalibration signal ──
    print("\nComputing KPHO-calibrated FEP signal…")
    for district in KENT_DISTRICTS:
        rec = district_records[district]
        kpho_val  = rec.get("frailty_pct", {}).get("value")
        kpho_norm = normalise_kpho(kpho_val)
        rec["kpho_frailty_normalised"] = kpho_norm
        rec["kpho_fep_weight"]         = KPHO_FEP_WEIGHT
        if kpho_norm is not None:
            print(f"  {district:<25} KPHO={kpho_val:.2f}%  norm={kpho_norm:.1f}/100")

    # ── Extract MSOA data ──
    print("\nExtracting MSOA-level indicators…")
    msoa_base = extract_msoa(df, "Frailty in older people", "Persons", "All")
    msoa_records = {}

    for _, row in msoa_base.iterrows():
        area      = row["area"]
        area_code = str(row.get("area_code", ""))
        msoa_records[area] = {
            "area_code":   area_code,
            "frailty_pct": safe_float(row["value"]),
            "frailty_n":   safe_int(row.get("numerator")),
            "frailty_denom": safe_int(row.get("denominator")),
        }

    for key, (ind, sex, dep) in list(MSOA_INDICATORS.items())[1:]:
        companion = extract_msoa(df, ind, sex, dep)
        for _, row in companion.iterrows():
            area = row["area"]
            if area in msoa_records:
                msoa_records[area][key] = safe_float(row["value"])

    print(f"  MSOA records built: {len(msoa_records)}")
    top5 = sorted(msoa_records.items(), key=lambda x: x[1].get("frailty_pct") or 0, reverse=True)[:5]
    for name, rec in top5:
        print(f"  {name:<40} frailty={rec.get('frailty_pct')}%")

    # ── Extract PCN frailty ──
    print("\nExtracting PCN frailty…")
    pcn_rows = df[(df["indicator"] == "Frailty in older people") &
                  (df["area_type"] == "PCN") &
                  (df["sex"] == "Persons") &
                  (df["deprivation"] == "All") &
                  (df["latest"] == "Y")].copy()
    pcn_rows = pcn_rows.sort_values("denominator", ascending=False).groupby("area").first().reset_index()
    pcn_records = {}
    for _, row in pcn_rows.iterrows():
        pcn_records[row["area"]] = {
            "frailty_pct": safe_float(row["value"]),
            "frailty_n":   safe_int(row.get("numerator")),
            "period":      str(row["timeperiod"]),
        }
    print(f"  PCN records: {len(pcn_records)}")

    # ── England benchmarks ──
    print("\nExtracting England benchmarks…")
    eng_benchmarks = {}
    for key, (ind, sex, dep, tier) in DISTRICT_INDICATORS.items():
        sub = df[(df["indicator"] == ind) & (df["area_type"] == "England")].copy()
        sub = sub.sort_values("timeperiod_sortable", ascending=False)
        if len(sub) > 0:
            eng_benchmarks[key] = safe_float(sub["value"].iloc[0])

    # ── Assemble output ──
    output = {
        "meta": {
            "generated":       datetime.now(timezone.utc).isoformat(),
            "source":          "Kent Public Health Observatory — Health and Social Care Maps",
            "source_url":      HSCM_PAGE_URL,
            "version":         HSCM_VERSION,
            "version_date":    HSCM_PUBLISH_DATE,
            "download_url":    HSCM_DOWNLOAD_URL,
            "licence":         "Open Government Licence v3.0",
            "refresh_note":    (
                "KPHO publish new HSCM versions quarterly or as data becomes available. "
                "When a new version is released, update HSCM_DOWNLOAD_URL in fetch_hscm.py "
                "and re-run the workflow. Check: " + HSCM_PAGE_URL
            ),
            "kpho_frailty_kent_min": KPHO_FRAILTY_KENT_MIN,
            "kpho_frailty_kent_max": KPHO_FRAILTY_KENT_MAX,
            "kpho_fep_weight":       KPHO_FEP_WEIGHT,
            "fep_recalibration_note": (
                "KPHO frailty_pct is GP-recorded Clinical Frailty Scale data — a direct clinical "
                "measurement. It is normalised to 0-100 on the Kent scale and blended into the "
                "FEP score at 40% weight in daily_refresh.py. Key corrections: Dartford rises "
                "significantly (FEP was underestimating clinical frailty burden); Maidstone falls "
                "(prescribing signals overstated vs actual GP-recorded prevalence)."
            ),
            "districts":       len(district_records),
            "msoa_areas":      len(msoa_records),
            "pcn_areas":       len(pcn_records),
            "indicators":      list(DISTRICT_INDICATORS.keys()),
            "england_benchmarks": eng_benchmarks,
        },
        "districts": district_records,
        "msoa":      msoa_records,
        "pcn":       pcn_records,
    }

    # ── Summary ──
    print(f"\n── HSCM Summary ({today}) ──")
    frailty_sorted = sorted(
        [(d, r.get("frailty_pct", {}).get("value"), r.get("kpho_frailty_normalised"))
         for d, r in district_records.items() if r.get("frailty_pct")],
        key=lambda x: x[1] or 0, reverse=True
    )
    print(f"  {'District':<25} {'Clinical %':>10} {'Norm/100':>9}")
    for name, val, norm in frailty_sorted:
        print(f"  {name:<25} {val or 0:>10.2f} {norm or 0:>9.1f}")

    print(f"\nCommitting {GITHUB_FILE}…")
    commit_json(output, GITHUB_FILE, f"HSCM {HSCM_VERSION} data refresh — {today}")
    print(f"Done — {today}")


# ── COMMIT ────────────────────────────────────────────────────────────────────
def commit_json(content_dict, filepath, message):
    if not GITHUB_TOKEN:
        print(f"  [DRY RUN] Would commit {filepath}")
        return True
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    hdrs    = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept":        "application/vnd.github.v3+json"}
    b64     = base64.b64encode(json.dumps(content_dict, indent=2).encode()).decode()
    r       = requests.get(api_url, headers=hdrs)
    sha     = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": message, "content": b64, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=hdrs, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ Committed {filepath}")
        return True
    print(f"  ✗ Failed: {r.status_code} — {r.json().get('message','')}")
    return False


if __name__ == "__main__":
    main()
