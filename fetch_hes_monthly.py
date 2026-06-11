"""
fetch_hes_monthly.py — Assistiv Systems NHS Pressure Intelligence
Hospital Episode Statistics Monthly Fetcher

Runs in GitHub Actions on the 12th of each month at 08:00 UTC.
HES provisional monthly data publishes on or around the 11th.

Monitors the NHS Digital provisional monthly HES publications index,
downloads the age-groups CSV and treatment specialty CSV, filters for
Kent trust data, extracts 65+ emergency admissions and geriatric medicine
activity, and writes kent-hes-data.json.

Kent Trusts:
  RVV — East Kent Hospitals University NHS Foundation Trust
  RWF — Maidstone and Tunbridge Wells NHS Trust

Data sources:
  - HES Monthly: Age Groups CSV (emergency admissions by age band and trust)
  - HES Monthly: Treatment Specialty CSV (specialty 430 Geriatric Medicine)

NHS Digital HES index:
  https://digital.nhs.uk/data-and-information/publications/statistical/
  provisional-monthly-hospital-episode-statistics-for-admitted-patient-care-
  outpatient-and-accident-and-emergency-data/

Licence: Open Government Licence v3.0
"""

import os
import re
import csv
import json
import base64
import requests
from datetime import datetime, timezone
from io import StringIO, BytesIO
from bs4 import BeautifulSoup
import zipfile

# ── CONFIG ────────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistiv_cloud"
GITHUB_FILE  = "kent-hes-data.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

RAW_URL      = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"

HES_INDEX    = (
    "https://digital.nhs.uk/data-and-information/publications/statistical/"
    "provisional-monthly-hospital-episode-statistics-for-admitted-patient-care-"
    "outpatient-and-accident-and-emergency-data/"
)

HEADERS = {
    "User-Agent": "AssistivSystems/1.0 (NHS open data; simon@assistiv.co)"
}

# Kent trust ODS codes
KENT_TRUSTS = {
    "RVV": {
        "name":      "East Kent Hospitals University NHS Foundation Trust",
        "short":     "East Kent Hospitals",
        "districts": ["Thanet", "Dover", "Folkestone & Hythe", "Canterbury", "Swale"],
    },
    "RWF": {
        "name":      "Maidstone and Tunbridge Wells NHS Trust",
        "short":     "Maidstone & Tunbridge Wells",
        "districts": ["Maidstone", "Tonbridge & Malling", "Tunbridge Wells",
                      "Sevenoaks", "Ashford", "Gravesham", "Dartford"],
    },
}

# Age bands of interest (65+) — as they appear in HES CSVs
AGE_BANDS_65_PLUS = {
    "65-69", "70-74", "75-79", "80-84", "85-89", "90-94", "95+",
    "65 to 69", "70 to 74", "75 to 79", "80 to 84", "85 to 89",
    "90 to 94", "95 and over",
}

# Geriatric Medicine specialty code
GERIATRIC_MEDICINE_CODE = "430"

# Admission type filters for emergency
EMERGENCY_ADMISSION_TYPES = {"1", "21", "22", "23", "24", "25", "2a", "2b", "2c", "2d",
                              "emergency", "non-elective"}


def find_latest_hes_publication():
    """
    Scrape the HES publications index to find the most recent monthly release page URL.
    Returns (page_url, period_label).
    """
    print(f"Scanning HES index: {HES_INDEX}")
    r = requests.get(HES_INDEX, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Look for links to individual monthly publication pages
    # Pattern: "/april-2025---march-2026-m13-new" or similar
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if ("provisional-monthly-hospital-episode" in href
                and re.search(r'm\d+', href, re.I)):
            candidates.append((href, text))

    if not candidates:
        raise ValueError("No HES monthly publication links found on index page")

    # Sort by M-number to get the latest
    def m_number(item):
        m = re.search(r'm(\d+)', item[0], re.I)
        return int(m.group(1)) if m else 0

    candidates.sort(key=m_number, reverse=True)
    latest_href, latest_text = candidates[0]
    url = latest_href if latest_href.startswith("http") else "https://digital.nhs.uk" + latest_href
    print(f"  Latest HES publication: {latest_text}")
    print(f"  URL: {url}")
    return url, latest_text


def find_csv_urls(publication_page_url):
    """
    Scrape individual publication page for direct CSV download URLs.
    Returns dict: {"age_groups": url, "specialty": url}
    """
    print(f"\nScanning publication page for CSV links...")
    r = requests.get(publication_page_url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    urls = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        if not href.endswith(".csv") and "open_data" not in href.upper():
            continue
        if "age" in text or "AGE_GROUPS" in href.upper():
            urls["age_groups"] = href
            print(f"  Age groups CSV: {href}")
        elif "specialty" in text.lower() or "TREATMENT_SPECIALTY" in href.upper():
            urls["specialty"] = href
            print(f"  Specialty CSV: {href}")
        elif "totals" in text or "OPEN_DATA.csv" in href.upper():
            urls.setdefault("totals", href)

    return urls


def download_csv(url):
    """Download CSV file, return as list of dicts."""
    print(f"\nDownloading: {url}")
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    print(f"  Downloaded {len(r.content):,} bytes")
    content = r.content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(StringIO(content))
    rows = list(reader)
    print(f"  Parsed {len(rows):,} rows, {len(reader.fieldnames)} columns")
    if reader.fieldnames:
        print(f"  Columns: {reader.fieldnames[:8]}{'...' if len(reader.fieldnames) > 8 else ''}")
    return rows, reader.fieldnames or []


def find_trust_col(fieldnames):
    """Find the column name that contains trust/provider codes."""
    for name in fieldnames:
        if name.lower() in ("provider", "procode", "pro_code", "trust", "org_code",
                            "provider_code", "der_provider_code"):
            return name
    # Fallback: find any col with 'prov' or 'trust' in the name
    for name in fieldnames:
        if "prov" in name.lower() or "trust" in name.lower():
            return name
    return None


def find_col(fieldnames, *patterns):
    """Find first column matching any pattern (case-insensitive)."""
    for name in fieldnames:
        n = name.lower()
        for p in patterns:
            if p.lower() in n:
                return name
    return None


def extract_65plus_emergency(rows, fieldnames, trust_codes):
    """
    From the age-groups CSV, extract:
      - total emergency admissions for 65+ patients by trust
      - breakdown by age band (65-69, 70-74, 75-79, 80+)

    Returns dict: {trust_code: {total_emerg_65plus, by_age_band: {...}}}
    """
    trust_col = find_trust_col(fieldnames)
    age_col   = find_col(fieldnames, "age_band", "age band", "age_group",
                         "age group", "age_grp", "startage")
    adm_col   = find_col(fieldnames, "emergency", "non_elective", "fae",
                         "finished_admission", "admissions", "episodes")
    type_col  = find_col(fieldnames, "admimeth", "admission_method", "adm_type")

    print(f"\n  Age-groups CSV columns mapped:")
    print(f"    trust={trust_col}, age={age_col}, admissions={adm_col}, type={type_col}")

    if not trust_col:
        print("  WARNING: Could not find trust column")
        return {}

    results = {code: {"total_emerg_65plus": 0, "by_age_band": {}} for code in trust_codes}

    for row in rows:
        provider = str(row.get(trust_col, "")).strip().upper()
        if provider not in trust_codes:
            continue

        age_val = str(row.get(age_col or "", "")).strip() if age_col else ""
        age_match = any(band in age_val for band in AGE_BANDS_65_PLUS)
        if not age_match:
            continue

        # Determine if emergency admission
        if type_col:
            adm_type = str(row.get(type_col, "")).strip().lower()
            is_emergency = any(t in adm_type for t in EMERGENCY_ADMISSION_TYPES)
        else:
            is_emergency = True  # no type filter available; include all

        if not is_emergency:
            continue

        # Count admissions
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
    """
    From the specialty CSV, extract geriatric medicine (specialty 430) activity.

    Returns dict: {trust_code: {geri_total_episodes, geri_emergency_episodes}}
    """
    trust_col = find_trust_col(fieldnames)
    spec_col  = find_col(fieldnames, "tretspef", "specialty", "spec_code",
                         "treatment_specialty", "mainspef")
    eps_col   = find_col(fieldnames, "episodes", "fce", "finished_consultant",
                         "count", "total")
    type_col  = find_col(fieldnames, "admimeth", "admission_method", "adm_type")

    print(f"\n  Specialty CSV columns mapped:")
    print(f"    trust={trust_col}, specialty={spec_col}, episodes={eps_col}, type={type_col}")

    if not trust_col or not spec_col:
        print("  WARNING: Could not find trust or specialty column")
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
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def commit_json(content_dict, filepath, message):
    if not GITHUB_TOKEN:
        print(f"  [DRY RUN — no token] Would commit {filepath}")
        return True
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    b64 = base64.b64encode(json.dumps(content_dict, indent=2).encode()).decode()
    r = requests.get(api_url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": message, "content": b64, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ Committed {filepath}")
        return True
    print(f"  ✗ Failed: {r.status_code} — {r.json().get('message','')}")
    return False


# ── MAIN ──────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n── Assistiv HES Monthly Fetcher ── {today} ──\n")

    # 1. Find latest publication
    pub_url, period_label = find_latest_hes_publication()

    # 2. Find CSV download URLs
    csv_urls = find_csv_urls(pub_url)
    if not csv_urls:
        raise ValueError("No CSV download URLs found on publication page")

    trust_codes = set(KENT_TRUSTS.keys())

    # 3. Process age-groups CSV
    emerg_data = {}
    if "age_groups" in csv_urls:
        rows, fieldnames = download_csv(csv_urls["age_groups"])
        emerg_data = extract_65plus_emergency(rows, fieldnames, trust_codes)
        print(f"\n  65+ emergency admissions extracted:")
        for code, data in emerg_data.items():
            print(f"    {code}: {data['total_emerg_65plus']:,} total")
    else:
        print("WARNING: Age groups CSV not found")

    # 4. Process specialty CSV
    geri_data = {}
    if "specialty" in csv_urls:
        rows, fieldnames = download_csv(csv_urls["specialty"])
        geri_data = extract_geriatric_medicine(rows, fieldnames, trust_codes)
        print(f"\n  Geriatric medicine (spec 430) extracted:")
        for code, data in geri_data.items():
            print(f"    {code}: {data['geri_total_episodes']:,} episodes "
                  f"({data['geri_emergency_episodes']:,} emergency)")
    else:
        print("WARNING: Specialty CSV not found")

    # 5. Load history
    last = load_last_json()
    history = last.get("history", [])

    # 6. Build trust objects
    trusts_current = {}
    for code, info in KENT_TRUSTS.items():
        emerg = emerg_data.get(code, {})
        geri  = geri_data.get(code, {})

        # Compute year-on-year delta if history available
        prior_year_emerg = None
        if history:
            # Look for same period last year
            prior = [h for h in history if h.get("period_label") != period_label]
            if prior:
                prior_latest = prior[-1]
                prior_t = prior_latest.get("trusts", {}).get(code, {})
                prior_year_emerg = prior_t.get("total_emerg_65plus")

        yoy_delta = None
        yoy_pct   = None
        current_emerg = emerg.get("total_emerg_65plus")
        if current_emerg is not None and prior_year_emerg is not None:
            yoy_delta = current_emerg - prior_year_emerg
            yoy_pct   = round((yoy_delta / prior_year_emerg) * 100, 1) if prior_year_emerg else None

        trusts_current[code] = {
            "name":                   info["name"],
            "short":                  info["short"],
            "districts":              info["districts"],
            "total_emerg_65plus":     current_emerg,
            "emerg_by_age_band":      emerg.get("by_age_band", {}),
            "geri_total_episodes":    geri.get("geri_total_episodes"),
            "geri_emergency_episodes": geri.get("geri_emergency_episodes"),
            "emerg_65plus_yoy_delta": yoy_delta,
            "emerg_65plus_yoy_pct":   yoy_pct,
            "period_label":           period_label,
        }

    # 7. Append to history
    snapshot = {
        "period_label": period_label,
        "fetched":      today,
        "pub_url":      pub_url,
        "trusts":       {
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

    # 8. Assemble output
    output = {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "Kent NHS Trust HES 65+ emergency admissions and geriatric medicine activity",
            "version":      "1.0",
            "refresh_type": "monthly — NHS Digital provisional HES (publishes ~11th each month)",
            "period_label": period_label,
            "pub_url":      pub_url,
            "source":       "NHS Digital Provisional Monthly Hospital Episode Statistics",
            "licence":      "Open Government Licence v3.0",
            "data_currency_note": (
                "HES provisional monthly data published by NHS Digital, typically on the 11th. "
                "Data covers admissions approximately 8-10 weeks prior to publication. "
                "Provisional — may be revised in the final annual publication."
            ),
            "signals": {
                "total_emerg_65plus":      "Emergency admissions (finished admission episodes) for patients aged 65+",
                "geri_total_episodes":     "Finished consultant episodes under specialty 430 (Geriatric Medicine)",
                "geri_emergency_episodes": "Emergency FCEs under specialty 430",
            },
            "trust_codes": list(KENT_TRUSTS.keys()),
        },
        "trusts":  trusts_current,
        "history": history,
    }

    # 9. Print summary
    print(f"\n── HES Summary ── {period_label} ──")
    for code, t in trusts_current.items():
        print(f"  {code} ({t['short']})")
        print(f"    65+ Emergency Admissions: {t['total_emerg_65plus']:,}" if t['total_emerg_65plus'] else "    65+ Emergency Admissions: N/A")
        print(f"    Geriatric Medicine Total: {t['geri_total_episodes']:,}" if t['geri_total_episodes'] else "    Geriatric Medicine Total: N/A")
        if t["emerg_65plus_yoy_pct"] is not None:
            direction = "▲" if t["emerg_65plus_yoy_pct"] > 0 else "▼"
            print(f"    YoY Change: {direction} {abs(t['emerg_65plus_yoy_pct'])}%")

    # 10. Commit
    msg = f"HES monthly refresh — {period_label} — {today}"
    print(f"\nCommitting {GITHUB_FILE}...")
    commit_json(output, GITHUB_FILE, msg)
    print(f"\nDone — {today}")


if __name__ == "__main__":
    main()
