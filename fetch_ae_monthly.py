"""
fetch_ae_monthly.py — Assistiv Systems NHS Pressure Intelligence
A&E Monthly Attendance and Emergency Admissions Fetcher

Fetches the NHS England Monthly A&E Attendances and Emergency Admissions
publication (official monthly statistics, published 2nd Thursday each month).

Pulls provider-level CSV data for the four Kent acute trusts:
  RVV — East Kent Hospitals University NHS Foundation Trust
  RWF — Maidstone and Tunbridge Wells NHS Trust
  RPA — Medway NHS Foundation Trust
  RN7 — Dartford and Gravesham NHS Trust

Data captured per trust per month:
  - Type 1 (major A&E) attendances
  - Type 2 (single specialty) attendances
  - Type 3 (UTC/MIU/walk-in) attendances
  - Total attendances (all types)
  - Attendances seen within 4 hours (4hr performance %)
  - Emergency admissions via A&E
  - 4hr+ waits for admission following decision to admit
  - 12hr+ waits (from ECDS, where available)

Also builds a 12-month rolling curve per trust for the NHS Pressure Map
historical chart.

Publication page:
  https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/

Published monthly, ~6-week lag (March data published mid-April).
Licence: Open Government Licence v3.0

Runs in GitHub Actions as part of hes_shmi_gp_monthly.yml (12th of each month).
"""

import os
import csv
import json
import base64
import requests
from datetime import datetime, timezone
from io import StringIO

# ── CONFIG ────────────────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistiv_cloud"
GITHUB_FILE  = "kent-ae-monthly.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
RAW_URL      = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AssistivSystems/1.0; +https://assistiv.co)"
}

# ── KENT TRUST DEFINITIONS ────────────────────────────────────────────────────
KENT_TRUSTS = {
    "RVV": {
        "name":      "East Kent Hospitals University NHS Foundation Trust",
        "short":     "East Kent Hospitals",
        "districts": ["Thanet", "Dover", "Folkestone & Hythe", "Canterbury", "Swale", "Ashford"],
    },
    "RWF": {
        "name":      "Maidstone and Tunbridge Wells NHS Trust",
        "short":     "Maidstone & Tunbridge Wells",
        "districts": ["Maidstone", "Tonbridge & Malling", "Tunbridge Wells",
                      "Sevenoaks", "Gravesham", "Dartford"],
    },
    "RPA": {
        "name":      "Medway NHS Foundation Trust",
        "short":     "Medway Maritime",
        "districts": ["Medway", "Swale"],
    },
    "RN7": {
        "name":      "Dartford and Gravesham NHS Trust",
        "short":     "Darent Valley",
        "districts": ["Dartford", "Gravesham"],
    },
}

# ── KNOWN MONTHLY CSV URLS ────────────────────────────────────────────────────
# Each month add the new CSV URL from the A&E publication page.
# Page: https://www.england.nhs.uk/statistics/statistical-work-areas/
#       ae-waiting-times-and-activity/ae-attendances-and-emergency-admissions-2025-26/
# Published 2nd Thursday of each month. Latest at time of build: March 2026.
#
# URL pattern: .../uploads/sites/2/{YYYY}/{MM}/{Month}-{Year}-CSV-{hash}.csv
# The hash changes each release — update from the publication page.
KNOWN_RELEASES = {
    "2025-04": {
        "period_label": "April 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/11/April-2025-CSV-revised.csv",
    },
    "2025-05": {
        "period_label": "May 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/11/May-2025-CSV-revised.csv",
    },
    "2025-06": {
        "period_label": "June 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/11/June-2025-CSV-revised.csv",
    },
    "2025-07": {
        "period_label": "July 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/11/July-2025-CSV-revised.csv",
    },
    "2025-08": {
        "period_label": "August 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/11/August-2025-CSV-revised.csv",
    },
    "2025-09": {
        "period_label": "September 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/11/September-2025-CSV-revised.csv",
    },
    "2025-10": {
        "period_label": "October 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/11/October-2025-CSV-hg6dl.csv",
    },
    "2025-11": {
        "period_label": "November 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2025/12/November-2025-CSV-G9pr3.csv",
    },
    "2025-12": {
        "period_label": "December 2025",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/01/December-2025-CSV-K7F4Sp.csv",
    },
    "2026-01": {
        "period_label": "January 2026",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/02/January-2026-CSV-S6H81b.csv",
    },
    "2026-02": {
        "period_label": "February 2026",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/03/February-2026-CSV-Dl8t54.csv",
    },
    "2026-03": {
        "period_label": "March 2026",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/04/March-2026-CSV-G49lw.csv",
    },
    # Add new months here:
    # "2026-04": {
    #     "period_label": "April 2026",
    #     "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/05/April-2026-CSV-{hash}.csv",
    # },
}

# ── CSV COLUMN HELPERS ────────────────────────────────────────────────────────
# The monthly A&E CSV column names have varied slightly over time.
# These helpers find the right column regardless of minor naming changes.

def find_col(fieldnames, *patterns):
    """Return first fieldname matching any pattern (case-insensitive)."""
    for name in fieldnames:
        n = name.lower().strip()
        for p in patterns:
            if p.lower() in n:
                return name
    return None


def safe_int(val):
    """Parse integer, return None on blank/dash."""
    if val is None:
        return None
    v = str(val).strip().replace(",", "")
    if v in ("", "-", "N/A", "n/a", "*"):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def safe_float(val, digits=1):
    """Parse float, return None on blank/dash."""
    if val is None:
        return None
    v = str(val).strip().replace(",", "").replace("%", "")
    if v in ("", "-", "N/A", "n/a", "*"):
        return None
    try:
        return round(float(v), digits)
    except (ValueError, TypeError):
        return None


# ── LOAD LAST COMMITTED JSON ──────────────────────────────────────────────────
def load_last_json():
    try:
        r = requests.get(RAW_URL, timeout=10, headers=HEADERS)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


# ── CSV FETCH AND PARSE ───────────────────────────────────────────────────────
def fetch_and_parse(period_key, release):
    """
    Fetch one month's A&E CSV and extract Kent trust rows.

    The CSV has one row per provider organisation per period.
    Key columns (names vary slightly by release):
      - Code / Org Code / Provider Code
      - Name / Org Name / Provider Name
      - A&E attendances Type 1 (major A&E)
      - A&E attendances Type 2 (single specialty)
      - A&E attendances Type 3 (UTC/MIU/walk-in)
      - Total A&E Attendances
      - Total attended within 4 hours
      - Emergency Admissions via A&E
      - Number of patients spending >4 hours in A&E from decision to admit
      - Number of patients spending >12 hours in A&E from decision to admit (Type 1 only)
    """
    url = release["csv_url"]
    print(f"  Fetching {release['period_label']} — {url[-50:]}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"    ✗ Fetch failed: {e}")
        return None

    reader = csv.DictReader(StringIO(r.text))
    fields = reader.fieldnames or []

    # Locate columns — names vary by release year
    col_code     = find_col(fields, "code", "org code", "provider code")
    col_type1    = find_col(fields, "type 1 departments", "type1", "major a&e", "a&e attendances type 1")
    col_type2    = find_col(fields, "type 2 departments", "type2", "single specialty", "a&e attendances type 2")
    col_type3    = find_col(fields, "type 3 departments", "type3", "utc", "miu", "walk-in", "a&e attendances type 3")
    col_total    = find_col(fields, "total attendances", "total a&e attendances", "all a&e attendances")
    col_4hr_att  = find_col(fields, "total attended within 4 hours", "within 4 hours", "4 hour attendances")
    col_emerg    = find_col(fields, "emergency admissions via a&e", "emergency admissions")
    col_4hr_adm  = find_col(fields, ">4 hours from decision to admit", "4 hours from decision", "over 4 hours")
    col_12hr_adm = find_col(fields, ">12 hours from decision to admit", "12 hours from decision", "over 12 hours",
                            "number of patients spending >12")

    if not col_code:
        print(f"    ✗ Cannot find provider code column in {fields[:5]}")
        return None

    results = {}
    for row in reader:
        code = str(row.get(col_code, "")).strip().upper()
        if code not in KENT_TRUSTS:
            continue

        type1    = safe_int(row.get(col_type1))
        type2    = safe_int(row.get(col_type2))
        type3    = safe_int(row.get(col_type3))
        total    = safe_int(row.get(col_total))
        att_4hr  = safe_int(row.get(col_4hr_att))
        emerg    = safe_int(row.get(col_emerg))
        adm_4hr  = safe_int(row.get(col_4hr_adm))
        adm_12hr = safe_int(row.get(col_12hr_adm))

        # 4-hour performance %
        perf_4hr = None
        if total and att_4hr and total > 0:
            perf_4hr = round((att_4hr / total) * 100, 1)

        results[code] = {
            "period_key":         period_key,
            "period_label":       release["period_label"],
            "type1_attendances":  type1,
            "type2_attendances":  type2,
            "type3_attendances":  type3,
            "total_attendances":  total,
            "attended_4hr":       att_4hr,
            "perf_4hr_pct":       perf_4hr,
            "emergency_admissions": emerg,
            "over_4hr_decision_to_admit": adm_4hr,
            "over_12hr_decision_to_admit": adm_12hr,
        }

    if results:
        found = list(results.keys())
        print(f"    ✓ Found: {found} | total_att sample: "
              f"{results[found[0]].get('total_attendances')}")
    else:
        print(f"    ✗ No Kent trust rows found — check trust codes in CSV")

    return results


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
    print(f"  ✗ Failed {filepath}: {r.status_code} — {r.json().get('message', '')}")
    return False


# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"fetch_ae_monthly.py — {today}")
    print(f"Releases in KNOWN_RELEASES: {len(KNOWN_RELEASES)}")

    # Load existing JSON to preserve any months already committed
    print("\nLoading existing kent-ae-monthly.json...")
    existing = load_last_json()
    existing_by_trust = {}
    for trust_code in KENT_TRUSTS:
        existing_by_trust[trust_code] = {
            m: d for m, d in
            existing.get("trusts", {}).get(trust_code, {}).get("monthly", {}).items()
        }

    # Fetch all months — skip if already in the JSON for that trust
    all_months = {}
    for period_key in sorted(KNOWN_RELEASES.keys()):
        release = KNOWN_RELEASES[period_key]
        # Skip if all Kent trusts already have this month
        already_have = all(
            period_key in existing_by_trust.get(tc, {})
            for tc in KENT_TRUSTS
        )
        if already_have:
            print(f"  {release['period_label']}: already committed, skipping")
            # Preserve existing data
            for tc in KENT_TRUSTS:
                all_months.setdefault(tc, {})[period_key] = existing_by_trust[tc][period_key]
            continue

        result = fetch_and_parse(period_key, release)
        if result:
            for tc, data in result.items():
                all_months.setdefault(tc, {})[period_key] = data
        # Preserve existing months not in the fetch result
        for tc in KENT_TRUSTS:
            if tc not in (result or {}):
                existing_month = existing_by_trust.get(tc, {}).get(period_key)
                if existing_month:
                    all_months.setdefault(tc, {})[period_key] = existing_month

    # ── Compute YoY and trend for latest month ──
    latest_key = sorted(KNOWN_RELEASES.keys())[-1]
    prev_year_key = f"{int(latest_key[:4])-1}{latest_key[4:]}"

    def compute_yoy(tc, metric):
        this_val = all_months.get(tc, {}).get(latest_key, {}).get(metric)
        last_val = all_months.get(tc, {}).get(prev_year_key, {}).get(metric)
        if this_val is None or last_val is None or last_val == 0:
            return None, None
        delta = this_val - last_val
        pct   = round((delta / last_val) * 100, 1)
        return delta, pct

    def trend_direction(tc, metric, n=3):
        """Rising/falling/stable trend over last n months."""
        months = sorted(all_months.get(tc, {}).keys())[-n:]
        vals = [all_months[tc][m].get(metric) for m in months if all_months.get(tc, {}).get(m, {}).get(metric)]
        if len(vals) < 2:
            return "unknown"
        deltas = [vals[i+1] - vals[i] for i in range(len(vals)-1)]
        avg = sum(deltas) / len(deltas)
        if avg > vals[-1] * 0.01:   return "rising"
        if avg < -vals[-1] * 0.01:  return "falling"
        return "stable"

    # ── Assemble output ──
    trust_records = {}
    for trust_code, trust_info in KENT_TRUSTS.items():
        monthly = all_months.get(trust_code, {})
        latest  = monthly.get(latest_key, {})

        yoy_delta_att, yoy_pct_att   = compute_yoy(trust_code, "total_attendances")
        yoy_delta_emg, yoy_pct_emg   = compute_yoy(trust_code, "emergency_admissions")
        att_trend   = trend_direction(trust_code, "total_attendances")
        perf_trend  = trend_direction(trust_code, "perf_4hr_pct")
        emg_trend   = trend_direction(trust_code, "emergency_admissions")

        trust_records[trust_code] = {
            "name":      trust_info["name"],
            "short":     trust_info["short"],
            "districts": trust_info["districts"],
            # Latest month headline figures
            "latest_period":              latest_key,
            "total_attendances":          latest.get("total_attendances"),
            "type1_attendances":          latest.get("type1_attendances"),
            "type3_attendances":          latest.get("type3_attendances"),
            "perf_4hr_pct":               latest.get("perf_4hr_pct"),
            "emergency_admissions":       latest.get("emergency_admissions"),
            "over_4hr_decision_to_admit": latest.get("over_4hr_decision_to_admit"),
            "over_12hr_decision_to_admit":latest.get("over_12hr_decision_to_admit"),
            # YoY
            "att_yoy_delta": yoy_delta_att,
            "att_yoy_pct":   yoy_pct_att,
            "emg_yoy_delta": yoy_delta_emg,
            "emg_yoy_pct":   yoy_pct_emg,
            # Trends (last 3 months)
            "att_trend":  att_trend,
            "perf_trend": perf_trend,
            "emg_trend":  emg_trend,
            # Full monthly history for chart
            "monthly": monthly,
        }

    output = {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "Kent NHS Trust A&E monthly attendances and performance — Assistiv Systems",
            "version":      "1.0",
            "refresh_type": "monthly — runs 12th of each month via hes_shmi_gp_monthly.yml",
            "latest_period":    KNOWN_RELEASES[latest_key]["period_label"],
            "months_available": len(KNOWN_RELEASES),
            "trust_codes":      list(KENT_TRUSTS.keys()),
            "pub_url":      "https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/ae-attendances-and-emergency-admissions-2025-26/",
            "source":       "NHS England Monthly A&E Attendances and Emergency Admissions",
            "licence":      "Open Government Licence v3.0",
            "4hr_target":   "95% of patients should be seen within 4 hours (NHS standard)",
            "update_note":  "Each month add the new CSV URL from the A&E publication page to KNOWN_RELEASES in fetch_ae_monthly.py",
            "type_notes": {
                "type1": "Major A&E departments — 24-hour consultant-led services",
                "type2": "Single specialty A&E departments",
                "type3": "Urgent Treatment Centres, Minor Injury Units, Walk-in Centres",
            },
        },
        "trusts": trust_records,
    }

    # ── Summary ──
    print(f"\n── A&E Monthly Summary ({latest_key}) ──")
    print(f"  {'Trust':<10} {'Total att':>12} {'4hr%':>7} {'Emerg':>8} {'Att trend':>12}")
    print(f"  {'-'*55}")
    for tc, t in trust_records.items():
        att   = f"{t['total_attendances']:,}" if t['total_attendances'] else "–"
        perf  = f"{t['perf_4hr_pct']}%" if t['perf_4hr_pct'] else "–"
        emg   = f"{t['emergency_admissions']:,}" if t['emergency_admissions'] else "–"
        trend = t['att_trend']
        print(f"  {tc:<10} {att:>12} {perf:>7} {emg:>8} {trend:>12}")

    msg = f"A&E monthly data refresh — {today}"
    print(f"\nCommitting {GITHUB_FILE}...")
    commit_json(output, GITHUB_FILE, msg)
    print(f"\nDone — {today}")


if __name__ == "__main__":
    main()
