"""
fetch_shmi_gp.py — Assistiv Systems NHS Pressure Intelligence
SHMI + GP Registration Monthly Fetcher

Runs in GitHub Actions on the 12th of each month at 09:00 UTC.

Fetches two datasets:
  1. SHMI (Summary Hospital-level Mortality Indicator)
     — trust-level SHMI value and banding for Kent trusts
     — source: https://digital.nhs.uk/data-and-information/publications/statistical/shmi/

  2. GP Registration (Patients Registered at a GP Practice)
     — 75+ registered patient counts by district, updated monthly
     — live list sizes per GP practice, aggregated to Kent districts
     — source: https://digital.nhs.uk/data-and-information/publications/statistical/
               patients-registered-at-a-gp-practice/

Writes:
  kent-shmi-data.json
  kent-gp-reg-data.json  (also updates list_size in kent-fep-data.json if GITHUB_TOKEN set)

Licence: Open Government Licence v3.0
"""

import os
import re
import csv
import json
import base64
import zipfile
import requests
from datetime import datetime, timezone
from io import StringIO, BytesIO
from bs4 import BeautifulSoup

# ── CONFIG ────────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistiv_cloud"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/"

HEADERS = {
    "User-Agent": "AssistivSystems/1.0 (NHS open data; simon@assistiv.co)"
}

KENT_TRUSTS = {
    "RVV": "East Kent Hospitals University NHS Foundation Trust",
    "RWF": "Maidstone and Tunbridge Wells NHS Trust",
}

# Kent ICB ONS code and sub-ICB location codes
KENT_ICB_CODE  = "QKS"  # NHS Kent and Medway ICB
KENT_ICB_ONS   = "E54000032"

# LAD codes for Kent & Medway districts — for GP registration aggregation
KENT_LAD_CODES = {
    "Thanet":                "E07000114",
    "Folkestone & Hythe":    "E07000112",
    "Dover":                 "E07000108",
    "Swale":                 "E07000113",
    "Medway":                "E06000035",
    "Gravesham":             "E07000109",
    "Ashford":               "E07000105",
    "Canterbury":            "E07000106",
    "Dartford":              "E07000107",
    "Maidstone":             "E07000110",
    "Tonbridge & Malling":   "E07000115",
    "Sevenoaks":             "E07000111",
    "Tunbridge Wells":       "E07000116",
}

# ════════════════════════════════════════════════════════════════
# PART 1: SHMI
# ════════════════════════════════════════════════════════════════

SHMI_INDEX = "https://digital.nhs.uk/data-and-information/publications/statistical/shmi"

def find_latest_shmi_publication():
    """Find the most recent SHMI publication page URL."""
    print(f"Scanning SHMI index: {SHMI_INDEX}")
    r = requests.get(SHMI_INDEX, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # SHMI pub URLs look like /statistical/shmi/2026-06
        if re.search(r'/shmi/20\d{2}-\d{2}$', href):
            url = href if href.startswith("http") else "https://digital.nhs.uk" + href
            m = re.search(r'(\d{4}-\d{2})$', href)
            date_str = m.group(1) if m else ""
            candidates.append((date_str, url))

    if not candidates:
        raise ValueError("No SHMI publication links found")

    candidates.sort(reverse=True)
    latest_date, latest_url = candidates[0]
    print(f"  Latest SHMI: {latest_date} — {latest_url}")
    return latest_url, latest_date


def find_shmi_csv_url(pub_url):
    """Find CSV download URL from SHMI publication page."""
    r = requests.get(pub_url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".csv") and "shmi" in href.lower():
            return href if href.startswith("http") else "https://digital.nhs.uk" + href
    # Fallback: any CSV link
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".csv"):
            return href if href.startswith("http") else "https://digital.nhs.uk" + href
    return None


def parse_shmi_csv(csv_url, trust_codes):
    """
    Download and parse SHMI CSV. Extract Kent trust rows.
    SHMI CSV columns (typical): ORG_CODE, ORG_NAME, PREDICTED_DEATHS, OBSERVED_DEATHS,
                                 SHMI, BANDING, SPELL_COUNT, ...
    Bandings: 1 = Higher than expected, 2 = As expected, 3 = Lower than expected
    """
    print(f"\nDownloading SHMI CSV: {csv_url}")
    r = requests.get(csv_url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    content = r.content.decode("utf-8-sig", errors="replace")
    reader  = csv.DictReader(StringIO(content))
    rows    = list(reader)
    fields  = reader.fieldnames or []
    print(f"  {len(rows):,} rows, columns: {fields[:10]}")

    # Normalise column name lookup
    def col(patterns):
        for name in fields:
            n = name.lower().replace("_", " ").strip()
            for p in patterns:
                if p.lower() in n:
                    return name
        return None

    org_col       = col(["org code", "org_code", "prov", "code"])
    shmi_col      = col(["shmi value", "shmi"])
    banding_col   = col(["banding", "band"])
    obs_col       = col(["observed", "actual deaths"])
    pred_col      = col(["predicted", "expected"])
    spells_col    = col(["spell", "discharge", "total"])

    BANDING_LABELS = {
        "1": "Higher than expected",
        "2": "As expected",
        "3": "Lower than expected",
    }

    results = {}
    for row in rows:
        code = str(row.get(org_col or "", "")).strip().upper()
        if code not in trust_codes:
            continue

        def safe_float(col_name):
            if not col_name: return None
            try:
                return round(float(str(row.get(col_name, "")).replace(",", "")), 4)
            except (ValueError, TypeError):
                return None

        def safe_int(col_name):
            if not col_name: return None
            try:
                return int(float(str(row.get(col_name, "")).replace(",", "")))
            except (ValueError, TypeError):
                return None

        banding_raw = str(row.get(banding_col or "", "")).strip()
        results[code] = {
            "shmi_value":       safe_float(shmi_col),
            "banding_code":     banding_raw,
            "banding_label":    BANDING_LABELS.get(banding_raw, banding_raw),
            "observed_deaths":  safe_int(obs_col),
            "predicted_deaths": safe_float(pred_col),
            "spell_count":      safe_int(spells_col),
        }
        print(f"  {code}: SHMI={results[code]['shmi_value']}, "
              f"Banding={results[code]['banding_label']}")

    return results


def fetch_and_write_shmi():
    """Main SHMI fetch flow. Returns output dict."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load last JSON for history
    try:
        r = requests.get(RAW_BASE + "kent-shmi-data.json", timeout=10)
        last = r.json() if r.status_code == 200 else {}
    except Exception:
        last = {}
    history = last.get("history", [])

    pub_url, period = find_latest_shmi_publication()
    csv_url = find_shmi_csv_url(pub_url)
    if not csv_url:
        raise ValueError("Could not find SHMI CSV download URL")

    trust_data = parse_shmi_csv(csv_url, set(KENT_TRUSTS.keys()))

    # Build trust objects
    trusts_current = {}
    for code, name in KENT_TRUSTS.items():
        data = trust_data.get(code, {})
        trusts_current[code] = {
            "name":             name,
            "shmi_value":       data.get("shmi_value"),
            "banding_code":     data.get("banding_code"),
            "banding_label":    data.get("banding_label"),
            "observed_deaths":  data.get("observed_deaths"),
            "predicted_deaths": data.get("predicted_deaths"),
            "spell_count":      data.get("spell_count"),
            "period":           period,
        }

    # Append history
    snapshot = {"period": period, "fetched": today,
                "trusts": {c: {"shmi_value": trusts_current[c]["shmi_value"],
                               "banding_code": trusts_current[c]["banding_code"]}
                           for c in KENT_TRUSTS}}
    history = [h for h in history if h.get("period") != period]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x.get("period", ""))[-24:]

    output = {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "Kent NHS Trust SHMI — Assistiv Systems",
            "version":      "1.0",
            "refresh_type": "monthly — NHS Digital SHMI (publishes monthly)",
            "period":       period,
            "pub_url":      pub_url,
            "csv_url":      csv_url,
            "source":       "NHS Digital Summary Hospital-level Mortality Indicator",
            "licence":      "Open Government Licence v3.0",
            "shmi_note": (
                "The SHMI is the ratio of observed to expected deaths following "
                "hospitalisation (in-hospital or within 30 days of discharge). "
                "It is a 'smoke alarm' indicator — higher than expected does NOT "
                "directly indicate poor care quality; it requires further investigation. "
                "Source: NHS Digital / OHID."
            ),
            "banding_labels": {
                "1": "Higher than expected",
                "2": "As expected",
                "3": "Lower than expected",
            },
            "data_currency_note": (
                "SHMI covers a rolling 12-month period, published monthly. "
                "Current publication covers approximately 5-6 months prior to publication date."
            ),
        },
        "trusts":  trusts_current,
        "history": history,
    }
    return output


# ════════════════════════════════════════════════════════════════
# PART 2: GP REGISTRATION
# ════════════════════════════════════════════════════════════════

GP_REG_INDEX = (
    "https://digital.nhs.uk/data-and-information/publications/statistical/"
    "patients-registered-at-a-gp-practice"
)

# Five-year age bands of interest
TARGET_AGE_BANDS = {
    "75-79", "80-84", "85-89", "90-94", "95+",
    "75 to 79", "80 to 84", "85 to 89", "90 to 94", "95 and over",
}
ALL_75_PLUS = TARGET_AGE_BANDS  # used for 75+ total

OVER_65_BANDS = {
    "65-69", "70-74", "75-79", "80-84", "85-89", "90-94", "95+",
    "65 to 69", "70 to 74", "75 to 79", "80 to 84", "85 to 89",
    "90 to 94", "95 and over",
}


def find_latest_gp_reg_zip():
    """Find the latest GP registration five-year age bands ZIP URL."""
    print(f"\nScanning GP registration index: {GP_REG_INDEX}")
    r = requests.get(GP_REG_INDEX, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        # Looking for the 5-year age groups file covering ICB/SICBL/PCN/practice
        if (href.endswith(".zip") and
                ("quin" in href.lower() or "5-year" in text or "five" in text or
                 "quin" in text or "age" in text)):
            url = href if href.startswith("http") else "https://files.digital.nhs.uk" + href
            print(f"  Found GP reg ZIP: {url}")
            return url

    # Fallback: any gp-reg ZIP with 'age' in the name
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.endswith(".zip") and "gp-reg" in href.lower():
            url = href if href.startswith("http") else "https://files.digital.nhs.uk" + href
            print(f"  Fallback GP reg ZIP: {url}")
            return url

    raise ValueError("Could not find GP registration age-bands ZIP")


def parse_gp_reg_csv(zip_bytes, kent_icb_code):
    """
    Extract Kent district-level 75+ population from the GP registration ZIP.
    The ZIP contains a CSV with columns including:
      ORG_CODE, ORG_NAME, ICB_CODE, ICB_NAME, LAD_CODE, LAD_NAME,
      AGE_GROUP_5, SEX, NUMBER_OF_PATIENTS

    Returns dict: {district_name: {total_list_size, pop_75plus, pop_65plus, by_age_band}}
    """
    print(f"\nParsing GP registration ZIP ({len(zip_bytes):,} bytes)...")

    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        print(f"  CSV files in ZIP: {csv_names}")

        # Prefer the ICB/SICBL/PCN/practice file
        target = None
        for name in csv_names:
            if "icb" in name.lower() or "region" in name.lower() or "quin" in name.lower():
                target = name
                break
        if not target:
            target = csv_names[0] if csv_names else None
        if not target:
            raise ValueError("No CSV found in GP registration ZIP")

        print(f"  Using: {target}")
        content = zf.read(target).decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(StringIO(content))
    rows   = list(reader)
    fields = reader.fieldnames or []
    print(f"  {len(rows):,} rows, fields: {fields[:12]}")

    def col(patterns):
        for name in fields:
            n = name.lower().replace("_", " ").strip()
            for p in patterns:
                if p.lower() in n:
                    return name
        return None

    icb_col     = col(["icb code", "icb_code", "icb"])
    lad_col     = col(["lad code", "lad_code", "lad"])
    lad_name_col= col(["lad name", "lad_name", "district"])
    age_col     = col(["age_group_5", "age group", "age_grp", "age band", "agegrp"])
    count_col   = col(["number_of_patients", "patients", "count", "total"])
    org_col     = col(["org code", "org_code", "practice code", "gp"])

    print(f"  Column map: icb={icb_col}, lad={lad_col}, age={age_col}, count={count_col}")

    # Aggregate by district
    district_data = {}

    for row in rows:
        # Filter to Kent ICB
        icb_val = str(row.get(icb_col or "", "")).strip().upper()
        if kent_icb_code.upper() not in icb_val and "KENT" not in icb_val.upper():
            continue

        # Get district LAD name
        lad_name = str(row.get(lad_name_col or lad_col or "", "")).strip()
        if not lad_name:
            continue

        # Normalise district name
        district = None
        for d_name in KENT_LAD_CODES:
            if d_name.lower() in lad_name.lower() or lad_name.lower() in d_name.lower():
                district = d_name
                break
        if not district:
            continue

        if district not in district_data:
            district_data[district] = {
                "total_list_size": 0,
                "pop_75plus":      0,
                "pop_65plus":      0,
                "by_age_band":     {},
            }

        try:
            count = int(float(str(row.get(count_col or "", "0")).replace(",", "")))
        except (ValueError, TypeError):
            count = 0

        age_val = str(row.get(age_col or "", "")).strip()

        district_data[district]["total_list_size"] += count

        if age_val:
            district_data[district]["by_age_band"][age_val] = (
                district_data[district]["by_age_band"].get(age_val, 0) + count
            )
            if any(band in age_val for band in ALL_75_PLUS):
                district_data[district]["pop_75plus"] += count
            if any(band in age_val for band in OVER_65_BANDS):
                district_data[district]["pop_65plus"] += count

    print(f"\n  Districts found: {list(district_data.keys())}")
    return district_data


def fetch_and_write_gp_reg():
    """Main GP registration fetch flow. Returns output dict."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load last JSON for history
    try:
        r = requests.get(RAW_BASE + "kent-gp-reg-data.json", timeout=10)
        last = r.json() if r.status_code == 200 else {}
    except Exception:
        last = {}
    history = last.get("history", [])

    # Find and download
    zip_url   = find_latest_gp_reg_zip()
    r         = requests.get(zip_url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    zip_bytes = r.content
    print(f"  Downloaded ZIP: {len(zip_bytes):,} bytes")

    # Derive snapshot date from URL (filename often contains YYYYMM)
    snap_date = today
    m = re.search(r'(20\d{2})(\d{2})', zip_url)
    if m:
        snap_date = f"{m.group(1)}-{m.group(2)}-01"

    district_data = parse_gp_reg_csv(zip_bytes, KENT_ICB_CODE)

    # Build district output objects
    districts_output = {}
    for name in KENT_LAD_CODES:
        data = district_data.get(name, {})
        districts_output[name] = {
            "lad_code":        KENT_LAD_CODES[name],
            "total_list_size": data.get("total_list_size", 0),
            "pop_75plus":      data.get("pop_75plus", 0),
            "pop_65plus":      data.get("pop_65plus", 0),
            "by_age_band":     data.get("by_age_band", {}),
            "snapshot_date":   snap_date,
        }

    # History snapshot
    snapshot = {
        "snapshot_date": snap_date,
        "fetched":       today,
        "districts":     {
            name: {"total_list_size": districts_output[name]["total_list_size"],
                   "pop_75plus":      districts_output[name]["pop_75plus"]}
            for name in KENT_LAD_CODES
        },
    }
    history = [h for h in history if h.get("snapshot_date") != snap_date]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x.get("snapshot_date", ""))[-24:]

    output = {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "Kent GP practice registered patients by district — Assistiv Systems",
            "version":      "1.0",
            "refresh_type": "monthly — NHS Digital GP Registration (publishes ~11th each month)",
            "snapshot_date": snap_date,
            "zip_url":      zip_url,
            "source":       "NHS Digital Patients Registered at a GP Practice",
            "licence":      "Open Government Licence v3.0",
            "icb":          "NHS Kent and Medway ICB (QKS)",
            "data_currency_note": (
                "GP registration data is a monthly snapshot from the Primary Care "
                "Registration database (Personal Demographics Service). "
                "Snapshot date is the 1st of the publication month. "
                "Used to update district 75+ population counts and list sizes "
                "in the FEP scoring model."
            ),
            "signals": {
                "total_list_size": "All registered patients at GP practices in the district",
                "pop_75plus":      "Registered patients aged 75+",
                "pop_65plus":      "Registered patients aged 65+",
            },
        },
        "districts": districts_output,
        "history":   history,
    }
    return output


# ════════════════════════════════════════════════════════════════
# SHARED: COMMIT HELPER
# ════════════════════════════════════════════════════════════════

def commit_json(content_dict, filepath, message):
    if not GITHUB_TOKEN:
        print(f"  [DRY RUN — no token] Would commit {filepath}")
        return True
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    hdrs = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json",
    }
    b64 = base64.b64encode(json.dumps(content_dict, indent=2).encode()).decode()
    r   = requests.get(api_url, headers=hdrs)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": message, "content": b64, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=hdrs, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ Committed {filepath}")
        return True
    print(f"  ✗ Failed: {r.status_code} — {r.json().get('message','')}")
    return False


def update_fep_list_sizes(gp_data):
    """
    Read kent-fep-data.json, update list_size and pop75 fields from
    the fresh GP registration data, re-commit.
    """
    if not GITHUB_TOKEN:
        print("  [DRY RUN] Would update kent-fep-data.json list sizes")
        return

    try:
        r   = requests.get(RAW_BASE + "kent-fep-data.json", timeout=15)
        fep = r.json()
    except Exception as e:
        print(f"  Could not load kent-fep-data.json: {e}")
        return

    updated = 0
    for district in fep.get("districts", []):
        name = district.get("name")
        reg  = gp_data.get("districts", {}).get(name)
        if reg:
            old_ls = district.get("list_size")
            old_p  = district.get("pop75")
            new_ls = reg.get("total_list_size")
            new_p  = reg.get("pop_75plus")
            if new_ls and new_ls != old_ls:
                district["list_size"] = new_ls
                updated += 1
            if new_p and new_p != old_p:
                district["pop75"] = new_p

    if updated:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fep["meta"]["list_size_updated"] = today
        fep["meta"]["list_size_source"]  = "NHS GP Registration monthly snapshot"
        commit_json(fep, "kent-fep-data.json",
                    f"List size update from GP registration — {today}")
        print(f"  Updated list sizes for {updated} districts in kent-fep-data.json")
    else:
        print("  No list size changes detected")


# ── MAIN ──────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n── Assistiv SHMI + GP Registration Fetcher ── {today} ──\n")

    # ── SHMI ──
    print("=" * 60)
    print("PART 1: SHMI")
    print("=" * 60)
    try:
        shmi_output = fetch_and_write_shmi()
        print(f"\nSHMI Summary:")
        for code, t in shmi_output["trusts"].items():
            print(f"  {code}: SHMI={t['shmi_value']}, Banding='{t['banding_label']}'")
        commit_json(shmi_output, "kent-shmi-data.json",
                    f"SHMI refresh — {shmi_output['meta']['period']} — {today}")
    except Exception as e:
        print(f"ERROR in SHMI fetch: {e}")
        import traceback; traceback.print_exc()

    # ── GP REGISTRATION ──
    print("\n" + "=" * 60)
    print("PART 2: GP REGISTRATION")
    print("=" * 60)
    try:
        gp_output = fetch_and_write_gp_reg()
        print(f"\nGP Registration Summary:")
        total_75plus = sum(d["pop_75plus"] for d in gp_output["districts"].values())
        total_list   = sum(d["total_list_size"] for d in gp_output["districts"].values())
        print(f"  Kent & Medway total list size: {total_list:,}")
        print(f"  Kent & Medway 75+ population:  {total_75plus:,}")
        for name, d in gp_output["districts"].items():
            print(f"    {name:<25} 75+: {d['pop_75plus']:>6,}  list: {d['total_list_size']:>7,}")
        commit_json(gp_output, "kent-gp-reg-data.json",
                    f"GP registration refresh — {gp_output['meta']['snapshot_date']} — {today}")
        # Update FEP list sizes
        print("\nUpdating FEP list sizes...")
        update_fep_list_sizes(gp_output)
    except Exception as e:
        print(f"ERROR in GP registration fetch: {e}")
        import traceback; traceback.print_exc()

    print(f"\nDone — {today}")


if __name__ == "__main__":
    main()
