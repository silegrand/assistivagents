"""
fetch_shmi_gp.py — Assistiv Systems NHS Pressure Intelligence
SHMI + GP Registration Monthly Fetcher

Uses direct download URLs from files.digital.nhs.uk — bypasses NHS Digital
index pages which return 403 to cloud runner IPs.

Update KNOWN_SHMI and KNOWN_GP_REG dicts each month with new URLs from
the NHS Digital publication pages.

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

# ── CONFIG ────────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistiv_cloud"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
RAW_BASE     = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AssistivSystems/1.0; +https://assistiv.co)"
}

KENT_TRUSTS = {
    "RVV": "East Kent Hospitals University NHS Foundation Trust",
    "RWF": "Maidstone and Tunbridge Wells NHS Trust",
}

KENT_LAD_CODES = {
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

# ── KNOWN DIRECT URLS ─────────────────────────────────────────────────
# SHMI: find the CSV link on https://digital.nhs.uk/...statistical/shmi/YYYY-MM
# Set csv_url to None if not yet found — script writes a placeholder gracefully.
KNOWN_SHMI = {
    "February 2025 - January 2026": {
        "period":  "February 2025 - January 2026",
        "pub_url": "https://digital.nhs.uk/data-and-information/publications/statistical/shmi/2026-06",
        "csv_url": None,
    },
}

# GP Registration: two files per month from the publication page:
#   zip_url:     "5-year age groups (GP practice)" — practice patient counts by age
#   mapping_url: "Mapping (Commissioning Regions-ICBs-SICBLs-PCNs-GP practice)"
#                — maps each GP practice ODS code to ICB and LAD
# June 2026 URLs confirmed from NHS Digital publication page.
KNOWN_GP_REG = {
    "2026-06-01": {
        "snapshot_date": "2026-06-01",
        "pub_url":     "https://digital.nhs.uk/data-and-information/publications/statistical/patients-registered-at-a-gp-practice/june-2026",
        "zip_url":     "https://files.digital.nhs.uk/7E/DC8059/gp-reg-pat-prac-quin-age.zip",
        "mapping_url": "https://files.digital.nhs.uk/8B/68C830/gp-reg-pat-prac-map.zip",
    },
    # Add new months here:
    # "2026-07-01": {
    #     "snapshot_date": "2026-07-01",
    #     "pub_url":     "https://digital.nhs.uk/.../july-2026",
    #     "zip_url":     "https://files.digital.nhs.uk/XX/XXXXXX/gp-reg-pat-prac-quin-age.zip",
    #     "mapping_url": "https://files.digital.nhs.uk/XX/XXXXXX/gp-reg-pat-prac-map.zip",
    # },
}

ALL_75_PLUS = {
    "75-79", "80-84", "85-89", "90-94", "95+",
    "75 to 79", "80 to 84", "85 to 89", "90 to 94", "95 and over",
}
OVER_65_BANDS = {
    "65-69", "70-74", "75-79", "80-84", "85-89", "90-94", "95+",
    "65 to 69", "70 to 74", "75 to 79", "80 to 84", "85 to 89",
    "90 to 94", "95 and over",
}


def find_col(fieldnames, *patterns):
    for name in fieldnames:
        n = name.lower().replace("_", " ").strip()
        for p in patterns:
            if p.lower() in n:
                return name
    return None


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


def load_json(filename):
    try:
        r = requests.get(RAW_BASE + filename, timeout=10)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def fetch_and_write_shmi():
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last    = load_json("kent-shmi-data.json")
    history = last.get("history", [])

    latest_period = sorted(KNOWN_SHMI.keys())[-1]
    release       = KNOWN_SHMI[latest_period]
    csv_url       = release.get("csv_url")
    pub_url       = release.get("pub_url", "")
    period        = release.get("period", latest_period)

    trust_data = {}

    if csv_url:
        print(f"  Downloading SHMI CSV: {csv_url}")
        r = requests.get(csv_url, headers=HEADERS, timeout=60)
        if r.status_code == 200:
            content = r.content.decode("utf-8-sig", errors="replace")
            reader  = csv.DictReader(StringIO(content))
            rows    = list(reader)
            fields  = reader.fieldnames or []
            print(f"  {len(rows):,} rows")

            org_col     = find_col(fields, "org code", "org_code", "prov", "code")
            shmi_col    = find_col(fields, "shmi value", "shmi")
            banding_col = find_col(fields, "banding", "band")
            obs_col     = find_col(fields, "observed", "actual")
            pred_col    = find_col(fields, "predicted", "expected")
            spells_col  = find_col(fields, "spell", "discharge", "total")

            BANDING_LABELS = {"1": "Higher than expected",
                              "2": "As expected",
                              "3": "Lower than expected"}

            for row in rows:
                code = str(row.get(org_col or "", "")).strip().upper()
                if code not in KENT_TRUSTS:
                    continue
                def sf(c):
                    if not c: return None
                    try: return round(float(str(row.get(c, "")).replace(",", "")), 4)
                    except: return None
                def si(c):
                    if not c: return None
                    try: return int(float(str(row.get(c, "")).replace(",", "")))
                    except: return None
                band_raw = str(row.get(banding_col or "", "")).strip()
                trust_data[code] = {
                    "shmi_value":       sf(shmi_col),
                    "banding_code":     band_raw,
                    "banding_label":    BANDING_LABELS.get(band_raw, band_raw or "Unknown"),
                    "observed_deaths":  si(obs_col),
                    "predicted_deaths": sf(pred_col),
                    "spell_count":      si(spells_col),
                }
                print(f"  {code}: SHMI={trust_data[code]['shmi_value']}, "
                      f"Banding={trust_data[code]['banding_label']}")
        else:
            print(f"  SHMI CSV returned {r.status_code}")
    else:
        print("  No SHMI CSV URL configured — writing placeholder")
        print("  To fix: find CSV link on pub page and add to KNOWN_SHMI in fetch_shmi_gp.py")

    trusts_current = {}
    for code, name in KENT_TRUSTS.items():
        data = trust_data.get(code, {})
        trusts_current[code] = {
            "name":             name,
            "shmi_value":       data.get("shmi_value"),
            "banding_code":     data.get("banding_code"),
            "banding_label":    data.get("banding_label",
                                         "Pending — add CSV URL to KNOWN_SHMI in fetch_shmi_gp.py"),
            "observed_deaths":  data.get("observed_deaths"),
            "predicted_deaths": data.get("predicted_deaths"),
            "spell_count":      data.get("spell_count"),
            "period":           period,
        }

    snapshot = {"period": period, "fetched": today,
                "trusts": {c: {"shmi_value":   trusts_current[c]["shmi_value"],
                               "banding_code": trusts_current[c]["banding_code"]}
                           for c in KENT_TRUSTS}}
    history = [h for h in history if h.get("period") != period]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x.get("period", ""))[-24:]

    return {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "Kent NHS Trust SHMI — Assistiv Systems",
            "version":      "1.1",
            "refresh_type": "monthly — NHS Digital SHMI",
            "period":       period,
            "pub_url":      pub_url,
            "source":       "NHS Digital Summary Hospital-level Mortality Indicator",
            "licence":      "Open Government Licence v3.0",
            "shmi_note":    "SHMI is a smoke-alarm — higher than expected does not indicate poor care.",
            "update_note":  "Add CSV URL from publication page to KNOWN_SHMI in fetch_shmi_gp.py",
            "banding_labels": {"1": "Higher than expected",
                               "2": "As expected",
                               "3": "Lower than expected"},
        },
        "trusts":  trusts_current,
        "history": history,
    }


# Kent district → GP practice postcode prefixes
# Postcodes in the patient counts CSV are practice postcodes.
# Matching on the outward code (e.g. CT9, ME14) maps each practice to its district.
KENT_POSTCODE_PREFIXES = {
    "Thanet":              ["CT9","CT10","CT11","CT12"],
    "Folkestone & Hythe":  ["CT18","CT19","CT20","CT21","TN29"],
    "Dover":               ["CT13","CT14","CT15","CT16","CT17"],
    "Swale":               ["ME9","ME10","ME11","ME12","ME13"],
    "Medway":              ["ME1","ME2","ME3","ME4","ME5","ME7","ME8"],
    "Gravesham":           ["DA11","DA12","DA13"],
    "Ashford":             ["TN23","TN24","TN25","TN26","TN27"],
    "Canterbury":          ["CT1","CT2","CT3","CT4","CT5","CT6"],
    "Dartford":            ["DA1","DA2","DA4"],
    "Maidstone":           ["ME14","ME15","ME16","ME17","ME18"],
    "Tonbridge & Malling": ["ME19","ME20","TN9","TN10","TN11","TN12"],
    "Sevenoaks":           ["TN13","TN14","TN15","TN16"],
    "Tunbridge Wells":     ["TN1","TN2","TN3","TN4"],
}

# Build reverse lookup: outward_code -> district_name (longest match wins)
_POSTCODE_LOOKUP = {}
for _district, _prefixes in KENT_POSTCODE_PREFIXES.items():
    for _prefix in _prefixes:
        _POSTCODE_LOOKUP[_prefix.upper()] = _district


def postcode_to_district(postcode):
    """
    Extract outward code from a full postcode and look up the Kent district.
    e.g. "CT9 1AA" -> outward "CT9" -> "Thanet"
    Uses longest-match to handle ambiguous prefixes (CT1 vs CT10 etc).
    """
    if not postcode:
        return None
    pc = postcode.strip().upper().replace(" ", "")
    # Outward code is everything except the last 3 chars (inward code)
    outward = pc[:-3] if len(pc) > 3 else pc
    # Try longest match first (CT10 before CT1)
    for length in (4, 3, 2):
        candidate = outward[:length]
        if candidate in _POSTCODE_LOOKUP:
            return _POSTCODE_LOOKUP[candidate]
    return None


def fetch_and_write_gp_reg():
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    last    = load_json("kent-gp-reg-data.json")
    history = last.get("history", [])

    latest_snap = sorted(KNOWN_GP_REG.keys())[-1]
    release     = KNOWN_GP_REG[latest_snap]
    zip_url     = release["zip_url"]
    snap_date   = release["snapshot_date"]
    pub_url     = release.get("pub_url", "")

    # Download patient counts ZIP
    print(f"  Downloading patient counts ZIP: {zip_url}")
    r = requests.get(zip_url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    print(f"  Downloaded {len(r.content):,} bytes")

    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        print(f"  Files in ZIP: {csv_names}")
        target = csv_names[0] if csv_names else None
        if not target:
            raise ValueError("No CSV in ZIP")
        print(f"  Parsing: {target}")
        content_str = zf.read(target).decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(StringIO(content_str))
    rows   = list(reader)
    fields = reader.fieldnames or []
    print(f"  {len(rows):,} rows, columns: {fields}")

    postcode_col = find_col(fields, "postcode", "post_code", "pcd")
    age_col      = find_col(fields, "age_group_5", "age group", "age band", "agegrp")
    count_col    = find_col(fields, "number_of_patients", "patients", "count", "number")
    sex_col      = find_col(fields, "sex", "gender")

    print(f"  Cols → postcode:{postcode_col} age:{age_col} "
          f"count:{count_col} sex:{sex_col}")

    district_data = {}
    matched = 0
    skipped = 0

    # Check what sex codes are present
    sex_codes = set(str(r.get(sex_col or "", "")).strip() for r in rows[:200])
    print(f"  Sex codes in data: {sex_codes}")
    # NHS GP reg typically uses 1=Male, 2=Female only (no persons-total row).
    # Summing M+F gives the correct total persons count per practice per age band.
    has_persons_total = any(s in sex_codes for s in ("0", "PERSONS", "ALL", "TOTAL"))
    print(f"  Has persons-total rows: {has_persons_total}")

    for row in rows:
        if sex_col and has_persons_total:
            # Only keep persons-total rows to avoid double counting
            sex_val = str(row.get(sex_col, "")).strip().upper()
            if sex_val not in ("", "PERSONS", "ALL", "0", "TOTAL"):
                continue
        # If no persons-total row, include all sex rows (M+F sums to persons total)

        # Map practice postcode to Kent district
        postcode = str(row.get(postcode_col or "", "")).strip()
        district = postcode_to_district(postcode)
        if not district:
            skipped += 1
            continue

        matched += 1
        if district not in district_data:
            district_data[district] = {
                "total_list_size": 0, "pop_75plus": 0,
                "pop_65plus": 0, "by_age_band": {},
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
            if any(b in age_val for b in ALL_75_PLUS):
                district_data[district]["pop_75plus"] += count
            if any(b in age_val for b in OVER_65_BANDS):
                district_data[district]["pop_65plus"] += count

    print(f"\n  Matched: {matched:,} rows, skipped (non-Kent): {skipped:,}")
    print(f"  Districts found: {sorted(district_data.keys())}")

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
        print(f"  {name:<25} 75+: {districts_output[name]['pop_75plus']:>6,}  "
              f"list: {districts_output[name]['total_list_size']:>7,}")

    snapshot = {
        "snapshot_date": snap_date, "fetched": today,
        "districts": {n: {"total_list_size": districts_output[n]["total_list_size"],
                          "pop_75plus":      districts_output[n]["pop_75plus"]}
                      for n in KENT_LAD_CODES},
    }
    history = [h for h in history if h.get("snapshot_date") != snap_date]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x.get("snapshot_date", ""))[-24:]

    return {
        "meta": {
            "generated":     datetime.now(timezone.utc).isoformat(),
            "description":   "Kent GP registered patients by district — Assistiv Systems",
            "version":       "1.3",
            "refresh_type":  "monthly — NHS Digital GP Registration",
            "snapshot_date": snap_date,
            "zip_url":       zip_url,
            "pub_url":       pub_url,
            "source":        "NHS Digital Patients Registered at a GP Practice",
            "licence":       "Open Government Licence v3.0",
            "icb":           "NHS Kent and Medway ICB (QKS)",
            "method":        "Practice postcodes mapped to Kent districts via outward code lookup",
            "update_note":   "Add new zip_url monthly to KNOWN_GP_REG in fetch_shmi_gp.py",
        },
        "districts": districts_output,
        "history":   history,
    }


def update_fep_list_sizes(gp_data):
    if not GITHUB_TOKEN:
        print("  [DRY RUN] Would update kent-fep-data.json")
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
        if not reg:
            continue
        new_ls = reg.get("total_list_size")
        new_p  = reg.get("pop_75plus")
        if new_ls and new_ls != district.get("list_size"):
            district["list_size"] = new_ls
            updated += 1
        if new_p and new_p != district.get("pop75"):
            district["pop75"] = new_p
    if updated:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        fep["meta"]["list_size_updated"] = today
        fep["meta"]["list_size_source"]  = "NHS GP Registration monthly snapshot"
        commit_json(fep, "kent-fep-data.json",
                    f"Update list sizes from GP registration — {today}")
        print(f"  Updated {updated} districts in kent-fep-data.json")
    else:
        print("  No list size changes to apply")


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n── Assistiv SHMI + GP Registration Fetcher ── {today} ──\n")

    print("=" * 60)
    print("PART 1: SHMI")
    print("=" * 60)
    try:
        shmi_output = fetch_and_write_shmi()
        for code, t in shmi_output["trusts"].items():
            print(f"  {code}: SHMI={t['shmi_value']}, Banding='{t['banding_label']}'")
        commit_json(shmi_output, "kent-shmi-data.json",
                    f"SHMI refresh — {shmi_output['meta']['period']} — {today}")
    except Exception as e:
        print(f"ERROR in SHMI: {e}")
        import traceback; traceback.print_exc()

    print("\n" + "=" * 60)
    print("PART 2: GP REGISTRATION")
    print("=" * 60)
    try:
        gp_output = fetch_and_write_gp_reg()
        total_75  = sum(d["pop_75plus"] for d in gp_output["districts"].values())
        print(f"\n  Kent & Medway 75+ total: {total_75:,}")
        commit_json(gp_output, "kent-gp-reg-data.json",
                    f"GP registration refresh — {gp_output['meta']['snapshot_date']} — {today}")
        print("\n  Updating FEP list sizes...")
        update_fep_list_sizes(gp_output)
    except Exception as e:
        print(f"ERROR in GP registration: {e}")
        import traceback; traceback.print_exc()

    print(f"\nDone — {today}")


if __name__ == "__main__":
    main()
