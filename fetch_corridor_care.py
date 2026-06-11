"""
fetch_corridor_care.py — Assistiv Systems NHS Pressure Intelligence
Corridor Care Monthly Fetcher

Fetches the NHS England Corridor Care monthly publication (new from June 2026).
Uses direct CSV download URLs — bypasses the publication index page which
blocks cloud runner IPs with 403.

Publication page:
  https://www.england.nhs.uk/statistics/statistical-work-areas/
  corridor-care-urgent-and-emergency-care-daily-situation-reports/

Published monthly. First publication: 11 June 2026 (covering May 2026).
Data is experimental and immature — NHS England note that figures will
evolve as reporting matures ahead of winter.

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
GITHUB_FILE  = "kent-corridor-data.json"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
RAW_URL      = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{GITHUB_FILE}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AssistivSystems/1.0; +https://assistiv.co)"
}

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

# ── KNOWN DIRECT URLS ─────────────────────────────────────────────────
# Each month add the new CSV URL from the corridor care publication page.
# Page: https://www.england.nhs.uk/statistics/statistical-work-areas/
#       corridor-care-urgent-and-emergency-care-daily-situation-reports/
KNOWN_RELEASES = {
    "2026-05": {
        "period_label": "May 2026",
        "pub_url": "https://www.england.nhs.uk/statistics/statistical-work-areas/corridor-care-urgent-and-emergency-care-daily-situation-reports/",
        "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/06/Corridor-Care-Publication-2026.05-May-prov-v2-csv.csv",
        "xlsx_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/06/Corridor-Care-Publication-2026.05-May-prov-v2.xlsx",
    },
    # Add new months here:
    # "2026-06": {
    #     "period_label": "June 2026",
    #     "pub_url": "https://www.england.nhs.uk/statistics/...",
    #     "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/07/Corridor-Care-Publication-2026.06-June-prov-vX-csv.csv",
    # },
}


def find_col(fieldnames, *patterns):
    for name in fieldnames:
        n = name.lower().replace("_", " ").strip()
        for p in patterns:
            if p.lower() in n:
                return name
    return None


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


def parse_corridor_csv(csv_content, trust_codes):
    """
    Parse the NHS England corridor care CSV publication.
    The CSV contains daily provider-level data for:
      - Corridor care in ED (24h count of patients ≥45 mins in inappropriate ED area)
      - Corridor care in wards (8am snapshot of patients in non-designated bed spaces)

    Returns dict: {trust_code: {corridor_ed, corridor_ward, corridor_total,
                                avg_corridor_ed, avg_corridor_ward, days_submitted}}
    """
    reader = csv.DictReader(StringIO(csv_content))
    rows   = list(reader)
    fields = reader.fieldnames or []
    print(f"  CSV: {len(rows):,} rows, {len(fields)} columns")
    print(f"  Columns: {fields}")

    if not rows:
        return {}

    # Show sample rows
    print(f"\n  First 3 rows (sample):")
    for row in rows[:3]:
        print(f"    {dict(row)}")

    # Identify key columns
    # NHS publication likely has: Org Code/Provider Code, Org Name,
    # Date/Period, Corridor ED count, Corridor Ward count, Region, ICB
    org_col    = find_col(fields, "org code", "provider code", "code",
                          "trust code", "ods", "org_code")
    name_col   = find_col(fields, "org name", "provider name", "trust name",
                          "organisation name", "name")
    date_col   = find_col(fields, "date", "period", "day", "reporting")
    ed_col     = find_col(fields, "ed corridor", "corridor ed", "corridor care ed",
                          "emergency department", "a&e corridor", "type 1",
                          "corridor_ed", "ed_corridor")
    ward_col   = find_col(fields, "ward corridor", "corridor ward", "corridor care ward",
                          "inpatient corridor", "general acute", "ward_corridor",
                          "corridor_ward", "beds")
    region_col = find_col(fields, "region", "nhs region")
    icb_col    = find_col(fields, "icb", "integrated care")

    print(f"\n  Column map:")
    print(f"    org:{org_col} name:{name_col} date:{date_col}")
    print(f"    ed:{ed_col} ward:{ward_col} region:{region_col} icb:{icb_col}")

    # If we can't find org column, try to identify trust rows by name
    results = {}

    # Accumulate daily values per trust for averaging
    trust_accumulator = {}

    for row in rows:
        # Try to identify trust by code
        code_val = str(row.get(org_col or "", "")).strip().upper()
        name_val = str(row.get(name_col or "", "")).strip().upper()

        matched_code = None
        if code_val in trust_codes:
            matched_code = code_val
        else:
            # Try name matching
            for tc in trust_codes:
                trust_name = KENT_TRUSTS[tc]["name"].upper()
                trust_short = KENT_TRUSTS[tc]["short"].upper()
                if (trust_name in name_val or trust_short in name_val or
                        tc in code_val or
                        ("EAST KENT" in name_val and tc == "RVV") or
                        ("MAIDSTONE" in name_val and tc == "RWF")):
                    matched_code = tc
                    break

        if not matched_code:
            continue

        if matched_code not in trust_accumulator:
            trust_accumulator[matched_code] = {
                "ed_values": [], "ward_values": [],
                "rows_found": 0,
            }

        trust_accumulator[matched_code]["rows_found"] += 1

        def safe_float(col):
            if not col: return None
            val = str(row.get(col, "")).strip()
            if not val or val.lower() in ("", "na", "n/a", "-", "null"):
                return None
            try:
                return float(val.replace(",", ""))
            except (ValueError, TypeError):
                return None

        ed_val   = safe_float(ed_col)
        ward_val = safe_float(ward_col)

        if ed_val is not None:
            trust_accumulator[matched_code]["ed_values"].append(ed_val)
        if ward_val is not None:
            trust_accumulator[matched_code]["ward_values"].append(ward_val)

    # Compute averages and totals
    print(f"\n  Accumulator results:")
    for code, acc in trust_accumulator.items():
        print(f"    {code}: {acc['rows_found']} rows, "
              f"{len(acc['ed_values'])} ED values, "
              f"{len(acc['ward_values'])} ward values")

        ed_vals   = acc["ed_values"]
        ward_vals = acc["ward_values"]

        avg_ed   = round(sum(ed_vals) / len(ed_vals), 1) if ed_vals else None
        avg_ward = round(sum(ward_vals) / len(ward_vals), 1) if ward_vals else None
        max_ed   = round(max(ed_vals), 1) if ed_vals else None
        max_ward = round(max(ward_vals), 1) if ward_vals else None

        total = None
        if avg_ed is not None and avg_ward is not None:
            total = round(avg_ed + avg_ward, 1)
        elif avg_ed is not None:
            total = avg_ed
        elif avg_ward is not None:
            total = avg_ward

        results[code] = {
            "corridor_ed":      avg_ed,
            "corridor_ward":    avg_ward,
            "corridor_total":   total,
            "corridor_ed_max":  max_ed,
            "corridor_ward_max": max_ward,
            "days_submitted":   acc["rows_found"],
        }
        print(f"    → ED avg:{avg_ed} ward avg:{avg_ward} total:{total} "
              f"(max ED:{max_ed} max ward:{max_ward})")

    return results


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"\n── Assistiv Corridor Care Fetcher ── {today} ──\n")

    # Get latest release
    latest_key   = sorted(KNOWN_RELEASES.keys())[-1]
    release      = KNOWN_RELEASES[latest_key]
    period_label = release["period_label"]
    csv_url      = release["csv_url"]
    pub_url      = release["pub_url"]

    print(f"Using release: {period_label}")
    print(f"CSV URL: {csv_url}")

    # Download CSV
    print(f"\nDownloading corridor care CSV...")
    r = requests.get(csv_url, headers=HEADERS, timeout=60)
    if r.status_code != 200:
        print(f"ERROR: HTTP {r.status_code} — {r.text[:200]}")
        raise Exception(f"CSV download failed: {r.status_code}")

    print(f"Downloaded {len(r.content):,} bytes")
    csv_content = r.content.decode("utf-8-sig", errors="replace")

    trust_codes   = set(KENT_TRUSTS.keys())
    trust_metrics = parse_corridor_csv(csv_content, trust_codes)

    if not trust_metrics:
        print("\nWARNING: No Kent trust data found in corridor care CSV.")
        print("The publication may use different provider codes or names.")
        print("Check the sample rows above and update the name matching logic.")

    # Load history
    last    = load_last_json()
    history = last.get("history", [])

    # Build current trust objects
    trusts_current = {}
    for code, info in KENT_TRUSTS.items():
        metrics = trust_metrics.get(code, {})

        # Compute trend vs last history snapshot
        recent = [
            h["trusts"].get(code, {}).get("corridor_total")
            for h in history[-5:]
            if h["trusts"].get(code, {}).get("corridor_total") is not None
        ]
        ct    = metrics.get("corridor_total")
        if len(recent) >= 1 and ct is not None:
            delta = round(ct - recent[-1], 1)
            trend = "rising" if delta > 1 else "falling" if delta < -1 else "stable"
        else:
            delta = None
            trend = "unknown"

        trusts_current[code] = {
            "name":              info["name"],
            "short":             info["short"],
            "districts":         info["districts"],
            "corridor_ed":       metrics.get("corridor_ed"),
            "corridor_ward":     metrics.get("corridor_ward"),
            "corridor_total":    ct,
            "corridor_ed_max":   metrics.get("corridor_ed_max"),
            "corridor_ward_max": metrics.get("corridor_ward_max"),
            "days_submitted":    metrics.get("days_submitted"),
            "twelve_hour_waits": None,   # not in this publication
            "beds_occupancy_pct": None,  # not in this publication
            "delayed_discharges": None,  # not in this publication
            "corridor_delta":    delta,
            "corridor_trend":    trend,
            "period_label":      period_label,
        }

    # History snapshot
    snapshot = {
        "period_label": period_label,
        "fetched":      today,
        "csv_url":      csv_url,
        "trusts":       {
            code: {
                "corridor_total": trusts_current[code]["corridor_total"],
                "corridor_ed":    trusts_current[code]["corridor_ed"],
                "corridor_ward":  trusts_current[code]["corridor_ward"],
                "name":           trusts_current[code]["name"],
                "short":          trusts_current[code]["short"],
            }
            for code in KENT_TRUSTS
        },
    }
    history = [h for h in history if h.get("period_label") != period_label]
    history.append(snapshot)
    history = sorted(history, key=lambda x: x.get("period_label", ""))[-24:]

    output = {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "Kent NHS Trust corridor care — Assistiv Systems",
            "version":      "2.0",
            "refresh_type": "monthly — NHS England Corridor Care publication",
            "period_label": period_label,
            "pub_url":      pub_url,
            "csv_url":      csv_url,
            "source":       "NHS England Corridor Care – UEC Daily Situation Reports",
            "licence":      "Open Government Licence v3.0",
            "data_note":    ("Experimental data — NHS England note this collection is new "
                             "and figures will evolve as reporting matures. "
                             "Values are monthly averages of daily submissions. "
                             "Blank submission = no data submitted; zero = confirmed zero corridor care."),
            "corridor_care_definition": (
                "Patient has experienced corridor care if they spent ≥45 minutes "
                "in a clinically inappropriate area of an ED or general & acute ward. "
                "NHS England definition, March 2026."
            ),
            "update_note": ("Each month add the new CSV URL from the corridor care "
                            "publication page to KNOWN_RELEASES in fetch_corridor_care.py"),
            "trust_codes": list(KENT_TRUSTS.keys()),
        },
        "trusts":  trusts_current,
        "history": history,
    }

    # Print summary
    print(f"\n── Corridor Care Summary ── {period_label} ──")
    for code, t in trusts_current.items():
        print(f"  {code} ({t['short']})")
        print(f"    Corridor ED (avg/day):   {t['corridor_ed']} (max: {t['corridor_ed_max']})")
        print(f"    Corridor Ward (avg/day): {t['corridor_ward']} (max: {t['corridor_ward_max']})")
        print(f"    Corridor Total:          {t['corridor_total']} ({t['corridor_trend']})")
        print(f"    Days submitted:          {t['days_submitted']}")

    # Commit
    msg = f"Corridor care refresh — {period_label} — {today}"
    print(f"\nCommitting {GITHUB_FILE}...")
    commit_json(output, GITHUB_FILE, msg)
    print(f"\nDone — {today}")


if __name__ == "__main__":
    main()
