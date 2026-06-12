"""
fetch_hes_monthly.py — Assistiv Systems NHS Pressure Intelligence
Hospital Episode Statistics Monthly Fetcher

Runs in GitHub Actions on the 12th of each month at 08:00 UTC.

Uses direct CSV download URLs from files.digital.nhs.uk — bypasses the
NHS Digital index page which blocks cloud runner IPs with a 403.

The KNOWN_RELEASES dict contains the direct file URLs for recent releases.
Update this dict each month when NHS Digital publishes a new release.
The URL pattern is stable: https://files.digital.nhs.uk/[HASH]/HES_M[N]_OPEN_DATA_AGE_GROUPS.csv

Current release: April 2025 - March 2026 (M13), published 11 June 2026.
Direct URLs confirmed from NHS Digital publication page.

Kent Trusts:
  RVV — East Kent Hospitals University NHS Foundation Trust
  RWF — Maidstone and Tunbridge Wells NHS Trust

Licence: Open Government Licence v3.0
"""

import os
import re
import csv
import json
import base64
import requests
from datetime import datetime, timezone
from io import StringIO

# ── CONFIG ────────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistiv_cloud"
GITHUB_FILE  = "kent-hes-data.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
RAW_URL      = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AssistivSystems/1.0; +https://assistiv.co)"
}

# Kent trust ODS codes
KENT_TRUSTS = {
    "RVV": {
        "name":      "East Kent Hospitals University NHS Foundation Trust",
        "short":     "East Kent Hospitals",
        "districts": ["Thanet", "Dover", "Folkestone & Hythe", "Canterbury", "Ashford"],
    },
    "RWF": {
        "name":      "Maidstone and Tunbridge Wells NHS Trust",
        "short":     "Maidstone & Tunbridge Wells",
        "districts": ["Maidstone", "Tonbridge & Malling", "Tunbridge Wells", "Sevenoaks"],
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

# ── KNOWN RELEASE URLs ────────────────────────────────────────────────
# Direct download URLs from files.digital.nhs.uk — these bypass bot protection.
# Update each month. Period label → {age_groups, specialty}
# Source: https://digital.nhs.uk/data-and-information/publications/statistical/
#   provisional-monthly-hospital-episode-statistics-for-admitted-patient-care-
#   outpatient-and-accident-and-emergency-data/april-2025---march-2026-m13-new
KNOWN_RELEASES = {
    "April 2025 - March 2026 (M13)": {
        # Kent-filtered CCG by Provider CSV committed to repo
        # Source: HES MAR 2025-26 M13 CCG by Provider ZIP (35MB full file)
        # Filtered to RVV + RWF only (1,925 rows) for repo efficiency
        "kent_csv":  "https://raw.githubusercontent.com/silegrand/assistiv_cloud/main/HES_MAR_M13_Kent_Trusts.csv",
        "pub_url":   "https://digital.nhs.uk/data-and-information/publications/statistical/provisional-monthly-hospital-episode-statistics-for-admitted-patient-care-outpatient-and-accident-and-emergency-data/april-2025---march-2026-m13-new",
    },
    # Add new releases here each month:
    # "May 2025 - April 2026 (M1)": {
    #     "kent_csv": "https://raw.githubusercontent.com/silegrand/assistiv_cloud/main/HES_MAR_M1_Kent_Trusts.csv",
    #     "pub_url":  "https://digital.nhs.uk/...",
    # },
}

# Age bands of interest (65+)
AGE_BANDS_65_PLUS = {
    "65-69", "70-74", "75-79", "80-84", "85-89", "90-94", "95+",
    "65 to 69", "70 to 74", "75 to 79", "80 to 84", "85 to 89",
    "90 to 94", "95 and over",
}

GERIATRIC_MEDICINE_CODE  = "430"
EMERGENCY_ADMISSION_TYPES = {"1", "21", "22", "23", "24", "25", "2a", "2b", "2c", "2d",
                              "emergency", "non-elective"}


def get_latest_release():
    """Return the most recent release label and URLs from KNOWN_RELEASES."""
    # Sort by M-number descending
    def m_num(label):
        m = re.search(r'M(\d+)', label, re.I)
        # M13 is end of year; M1-M12 are months. Treat M13 as highest.
        return int(m.group(1)) if m else 0

    sorted_releases = sorted(KNOWN_RELEASES.keys(), key=m_num, reverse=True)
    latest = sorted_releases[0]
    return latest, KNOWN_RELEASES[latest]


def download_csv(url, label):
    """Download CSV, return (rows, fieldnames)."""
    print(f"\nDownloading {label}: {url}")
    r = requests.get(url, headers=HEADERS, timeout=120)
    if r.status_code == 403:
        print(f"  403 Forbidden — URL may have expired. Update KNOWN_RELEASES with current month URLs.")
        return [], []
    r.raise_for_status()
    print(f"  Downloaded {len(r.content):,} bytes")
    content = r.content.decode("utf-8-sig", errors="replace")
    reader  = csv.DictReader(StringIO(content))
    rows    = list(reader)
    fields  = reader.fieldnames or []
    print(f"  Parsed {len(rows):,} rows, {len(fields)} columns")
    if fields:
        print(f"  Columns sample: {fields[:10]}")
    return rows, fields


def find_col(fieldnames, *patterns):
    """Find first column name matching any pattern."""
    for name in fieldnames:
        n = name.lower().replace("_", " ").strip()
        for p in patterns:
            if p.lower() in n:
                return name
    return None


def extract_nonelective_admissions(rows, fieldnames, trust_codes):
    """
    Extract total non-elective admissions from the Kent-filtered
    CCG by Provider CSV. Sums across all CCG rows per provider
    to get trust-level totals for the full year.

    Columns: Provider code, Provider name, Activity Month,
             All specialties: Non-Elective, etc.

    Returns dict: {trust_code: {total_emerg_65plus (proxy), by_month}}
    Note: this file has no age breakdown — total_emerg_65plus is used
    as the field name for compatibility but contains all-age non-elective.
    """
    prov_col  = find_col(fieldnames, "provider code", "provider_code")
    nonel_col = find_col(fieldnames, "all specialties: non-elective",
                         "non-elective", "non_elective")
    month_col = find_col(fieldnames, "activity month", "month")

    print(f"  CCG by Provider cols → provider:{prov_col} "
          f"non-elective:{nonel_col} month:{month_col}")

    results = {code: {"total_emerg_65plus": 0, "by_month": {}, "by_age_band": {}}
               for code in trust_codes}

    for row in rows:
        code = str(row.get(prov_col or "Provider code", "")).strip().upper()
        if code not in trust_codes:
            continue

        val_str = str(row.get(nonel_col or "", "")).strip()
        # '*' means suppressed small number — treat as 0 for aggregation
        try:
            val = int(float(val_str.replace(",", ""))) if val_str != "*" else 0
        except (ValueError, TypeError):
            val = 0

        results[code]["total_emerg_65plus"] += val

        month = str(row.get(month_col or "", "")).strip()
        if month:
            results[code]["by_month"][month] = (
                results[code]["by_month"].get(month, 0) + val
            )

    for code in trust_codes:
        total = results[code]["total_emerg_65plus"]
        print(f"  {code}: {total:,} total non-elective admissions (all ages, full year)")

    return results


def extract_65plus_emergency(rows, fieldnames, trust_codes):
    """Extract 65+ emergency admissions by trust from age-groups CSV."""
    trust_col = find_col(fieldnames, "provider", "procode", "pro code",
                         "org code", "trust", "provider code")
    age_col   = find_col(fieldnames, "age band", "age_band", "age group",
                         "age_group", "agegrp", "startage", "age_grp")
    adm_col   = find_col(fieldnames, "emergency", "non elective", "non_elective",
                         "fae", "finished admission", "admissions", "episodes", "count")
    type_col  = find_col(fieldnames, "admimeth", "admission method", "adm type", "adm_type")

    print(f"\n  Column map → trust:{trust_col} age:{age_col} admissions:{adm_col} type:{type_col}")

    if not trust_col:
        print("  WARNING: trust column not found — check CSV structure")
        return {}

    results = {code: {"total_emerg_65plus": 0, "by_age_band": {}} for code in trust_codes}

    for row in rows:
        provider = str(row.get(trust_col, "")).strip().upper()
        if provider not in trust_codes:
            continue

        age_val   = str(row.get(age_col or "", "")).strip() if age_col else ""
        age_match = any(band in age_val for band in AGE_BANDS_65_PLUS)
        if not age_match:
            continue

        if type_col:
            adm_type     = str(row.get(type_col, "")).strip().lower()
            is_emergency = any(t in adm_type for t in EMERGENCY_ADMISSION_TYPES)
        else:
            is_emergency = True

        if not is_emergency:
            continue

        try:
            count_val = row.get(adm_col or "", 0)
            count = int(float(str(count_val).replace(",", ""))) if count_val else 0
        except (ValueError, TypeError):
            count = 0

        results[provider]["total_emerg_65plus"] += count
        if age_val:
            results[provider]["by_age_band"][age_val] = (
                results[provider]["by_age_band"].get(age_val, 0) + count
            )

    return results


def extract_geriatric_medicine(rows, fieldnames, trust_codes):
    """Extract specialty 430 (Geriatric Medicine) activity by trust."""
    trust_col = find_col(fieldnames, "provider", "procode", "pro code",
                         "org code", "trust", "provider code")
    spec_col  = find_col(fieldnames, "tretspef", "specialty", "spec code",
                         "treatment specialty", "mainspef", "spec_code")
    eps_col   = find_col(fieldnames, "episodes", "fce", "finished consultant",
                         "count", "total", "admissions")
    type_col  = find_col(fieldnames, "admimeth", "admission method", "adm type")

    print(f"\n  Column map → trust:{trust_col} specialty:{spec_col} episodes:{eps_col} type:{type_col}")

    if not trust_col or not spec_col:
        print("  WARNING: trust or specialty column not found")
        return {}

    results = {code: {"geri_total_episodes": 0, "geri_emergency_episodes": 0}
               for code in trust_codes}

    for row in rows:
        provider = str(row.get(trust_col, "")).strip().upper()
        if provider not in trust_codes:
            continue

        spec = str(row.get(spec_col, "")).strip()
        if spec != GERIATRIC_MEDICINE_CODE:
            continue

        try:
            count_val = row.get(eps_col or "", 0)
            count = int(float(str(count_val).replace(",", ""))) if count_val else 0
        except (ValueError, TypeError):
            count = 0

        results[provider]["geri_total_episodes"] += count

        if type_col:
            adm_type = str(row.get(type_col, "")).strip().lower()
            if any(t in adm_type for t in EMERGENCY_ADMISSION_TYPES):
                results[provider]["geri_emergency_episodes"] += count

    return results


def load_last_json():
    try:
        r = requests.get(RAW_URL, timeout=10)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def commit_json(content_dict, filepath, message):
    if not GITHUB_TOKEN:
        print(f"  [DRY RUN] Would commit {filepath}")
        return True
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    hdrs    = {"Authorization": f"token {GITHUB_TOKEN}",
               "Accept": "application/vnd.github.v3+json"}
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


# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n── Assistiv HES Monthly Fetcher ── {today} ──\n")

    period_label, urls = get_latest_release()
    pub_url = urls.get("pub_url", "")
    print(f"Using release: {period_label}")
    print(f"Pub URL: {pub_url}")

    trust_codes = set(KENT_TRUSTS.keys())

    # Use Kent-filtered CCG by Provider CSV committed to repo
    kent_csv_url = urls.get("kent_csv")
    emerg_data   = {}
    geri_data    = {}

    if kent_csv_url:
        rows, fieldnames = download_csv(kent_csv_url, "Kent Trusts CCG by Provider")
        if rows:
            emerg_data = extract_nonelective_admissions(rows, fieldnames, trust_codes)
            print(f"\n  Non-elective admissions extracted:")
            for code, data in emerg_data.items():
                print(f"    {code}: {data.get('total_emerg_65plus',0):,} total non-elective")
    else:
        print("WARNING: No kent_csv URL configured for this release")

    # Load history
    last    = load_last_json()
    history = last.get("history", [])

    # Build trust objects
    trusts_current = {}
    for code, info in KENT_TRUSTS.items():
        emerg = emerg_data.get(code, {})
        geri  = geri_data.get(code, {})

        # YoY delta
        prior_emerg = None
        for h in reversed(history):
            if h.get("period_label") != period_label:
                prior_emerg = h.get("trusts", {}).get(code, {}).get("total_emerg_65plus")
                break

        current_emerg = emerg.get("total_emerg_65plus")
        yoy_delta = None
        yoy_pct   = None
        if current_emerg and prior_emerg:
            yoy_delta = current_emerg - prior_emerg
            yoy_pct   = round((yoy_delta / prior_emerg) * 100, 1)

        trusts_current[code] = {
            "name":                    info["name"],
            "short":                   info["short"],
            "districts":               info["districts"],
            "total_emerg_65plus":      current_emerg,
            "emerg_by_age_band":       emerg.get("by_age_band", {}),
            "geri_total_episodes":     geri.get("geri_total_episodes"),
            "geri_emergency_episodes": geri.get("geri_emergency_episodes"),
            "emerg_65plus_yoy_delta":  yoy_delta,
            "emerg_65plus_yoy_pct":    yoy_pct,
            "period_label":            period_label,
        }

    # Append history snapshot
    snapshot = {
        "period_label": period_label,
        "fetched":      today,
        "pub_url":      pub_url,
        "trusts": {
            code: {
                "total_emerg_65plus":  trusts_current[code]["total_emerg_65plus"],
                "geri_total_episodes": trusts_current[code]["geri_total_episodes"],
            }
            for code in KENT_TRUSTS
        },
    }
    history = [h for h in history if h.get("period_label") != period_label]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x.get("fetched", ""))[-24:]

    # Assemble output
    output = {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "Kent NHS Trust HES 65+ emergency admissions and geriatric medicine",
            "version":      "1.1",
            "refresh_type": "monthly — NHS Digital provisional HES",
            "period_label": period_label,
            "pub_url":      pub_url,
            "source":       "NHS Digital Provisional Monthly Hospital Episode Statistics",
            "licence":      "Open Government Licence v3.0",
            "data_currency_note": (
                "Provisional monthly HES. Data covers admissions approximately "
                "8-10 weeks prior to publication date. "
                "Update KNOWN_RELEASES dict in fetch_hes_monthly.py each month "
                "with new direct CSV URLs from files.digital.nhs.uk."
            ),
        },
        "trusts":  trusts_current,
        "history": history,
    }

    # Print summary
    print(f"\n── HES Summary ── {period_label} ──")
    for code, t in trusts_current.items():
        emerg_str = f"{t['total_emerg_65plus']:,}" if t['total_emerg_65plus'] else "N/A"
        geri_str  = f"{t['geri_total_episodes']:,}" if t['geri_total_episodes'] else "N/A"
        print(f"  {code}: 65+ emergency={emerg_str}, geriatric={geri_str}")

    # Commit
    msg = f"HES monthly refresh — {period_label} — {today}"
    print(f"\nCommitting {GITHUB_FILE}...")
    commit_json(output, GITHUB_FILE, msg)
    print(f"\nDone — {today}")


if __name__ == "__main__":
    main()
