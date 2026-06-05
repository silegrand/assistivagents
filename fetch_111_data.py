"""
fetch_111_data.py — Assistiv Systems NHS 111 Monthly Data Fetcher
=================================================================
Runs automatically via GitHub Actions on the 1st of each month.
Can also be run manually in Colab.

What it does:
  1. Scrapes the NHS England IUCADC page to find the latest published CSV
  2. Downloads the Raw Data CSV (~4MB)
  3. Extracts Kent & Medway ICB figures
  4. Calculates rates per 1,000 vs England
  5. Commits to GitHub:
       kent-111-data.json              (current — always overwritten)
       history/kent-111-YYYY-MM.json   (monthly snapshot — never overwritten)

No manual updates needed — the script auto-discovers the latest published month.
If it has already committed data for that month it skips to avoid duplicates.

Run schedule: 1st of each month at 07:00 UTC via GitHub Actions.
NHSBSA publishes ~6 weeks after month end, so the script collects
data that is approximately 6-8 weeks old.

Requirements: requests, pandas (both available in GitHub Actions ubuntu-latest)
"""

import os
import re
import json
import base64
import requests
import pandas as pd
from io import StringIO
from datetime import datetime, timezone


# ── CONSTANTS ─────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistivagents"
KENT_ICB_POP =  1_900_000   # Kent & Medway ICB registered population
ENGLAND_POP  = 56_490_000   # England total population

# NHS England IUCADC pages — current year first, previous year as fallback
IUCADC_PAGES = [
    "https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
    "integrated-urgent-care-aggregate-data-collection-iucadc-inc-nhs111-statistics-apr-2026-mar-2027/",
    "https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
    "integrated-urgent-care-aggregate-data-collection-iucadc-including-nhs111-statistics-apr-2025-mar-2026/",
]

MONTH_MAP = {
    'january':'01', 'february':'02', 'march':'03',    'april':'04',
    'may':'05',     'june':'06',     'july':'07',      'august':'08',
    'september':'09','october':'10', 'november':'11',  'december':'12',
}

CSV_PATTERN = re.compile(
    r'(https://www\.england\.nhs\.uk/statistics/wp-content/uploads/sites/2/'
    r'\d{4}/\d{2}/Aggregated-IUC-ADC-Raw-Data-([A-Za-z]+?)(\d{4})\.csv)',
    re.IGNORECASE
)


# ── STEP 1: AUTO-DISCOVER LATEST CSV ─────────────────────────────────
def discover_latest_csv():
    """
    Scrapes NHS England IUCADC pages to find the most recently published
    Raw Data CSV URL. Returns (period, period_nice, csv_url).
    """
    print("Step 1: Discovering latest IUCADC CSV...")
    candidates = []

    for page_url in IUCADC_PAGES:
        try:
            r = requests.get(page_url, timeout=20,
                             headers={"User-Agent": "Mozilla/5.0 AssistivSystems/1.0"})
            if r.status_code != 200:
                print(f"  {r.status_code} — {page_url[:80]}...")
                continue
            for match in CSV_PATTERN.finditer(r.text):
                url, month_name, year = match.groups()
                month_num = MONTH_MAP.get(month_name.lower())
                if month_num:
                    period = f"{year}-{month_num}"
                    period_nice = f"{month_name.capitalize()} {year}"
                    candidates.append((period, period_nice, url))
                    print(f"  Found: {period_nice} — {url[-60:]}")
        except Exception as e:
            print(f"  Warning: could not fetch page — {e}")

    if not candidates:
        raise RuntimeError(
            "Could not find any IUCADC CSV links on NHS England pages.\n"
            "Check: https://www.england.nhs.uk/statistics/statistical-work-areas/"
            "iucadc-new-from-april-2021/"
        )

    # Sort by period descending — most recent first
    candidates.sort(key=lambda x: x[0], reverse=True)
    period, period_nice, url = candidates[0]
    print(f"\n  Selected: {period_nice} ({period})")
    print(f"  URL: {url}")
    return period, period_nice, url


# ── STEP 2: CHECK IF ALREADY COMMITTED ───────────────────────────────
def already_committed(period, token):
    """Returns True if history/kent-111-{period}.json already exists in the repo."""
    api_url = (f"https://api.github.com/repos/{GITHUB_REPO}"
               f"/contents/history/kent-111-{period}.json")
    headers = {"Authorization": f"token {token}",
               "Accept": "application/vnd.github.v3+json"}
    r = requests.get(api_url, headers=headers)
    if r.status_code == 200:
        print(f"\nStep 2: history/kent-111-{period}.json already exists — skipping.")
        print(f"  (Delete that file from the repo to force a re-fetch.)")
        return True
    print(f"\nStep 2: No existing snapshot for {period} — proceeding with fetch.")
    return False


# ── STEP 3: FETCH AND PARSE CSV ───────────────────────────────────────
def fetch_and_parse(csv_url, period_nice):
    """Downloads the IUCADC CSV and returns (kent_df, england_df, all_df, col_map)."""
    print(f"\nStep 3: Fetching {period_nice} CSV...")
    r = requests.get(csv_url, timeout=60,
                     headers={"User-Agent": "Mozilla/5.0 AssistivSystems/1.0"})
    print(f"  HTTP {r.status_code} | Size: {len(r.content):,} bytes")
    if r.status_code != 200:
        raise RuntimeError(
            f"CSV download failed with HTTP {r.status_code}.\n"
            f"URL: {csv_url}\n"
            f"Check the NHS England page for the correct link."
        )

    df = pd.read_csv(StringIO(r.text), low_memory=False)
    print(f"  Rows: {len(df):,} | Columns: {len(df.columns)}")

    # Find Kent rows — try multiple column strategies
    kent_mask = df.apply(
        lambda col: col.astype(str).str.contains('Kent', case=False, na=False)
    ).any(axis=1)
    kent_df = df[kent_mask]

    if len(kent_df) == 0:
        print("  WARNING: No rows containing 'Kent' found.")
        print("  Column names:", list(df.columns[:10]))
        print("  First row sample:", df.iloc[0].to_dict())
        raise RuntimeError(
            "Could not find Kent & Medway ICB rows in the CSV.\n"
            "The NHS England column naming may have changed — check the raw file."
        )

    print(f"  Kent rows: {len(kent_df)}")

    # Column finder
    def find_col(search_df, keywords):
        for kw in keywords:
            matches = [c for c in search_df.columns if kw.lower() in c.lower()]
            if matches:
                return matches[0]
        return None

    col_map = {
        'calls_received':  find_col(df, ['calls received', 'A01', 'calls offer']),
        'calls_answered':  find_col(df, ['calls answered', 'A03', 'answered']),
        'amb_dispatched':  find_col(df, ['ambulance dispatch', 'E01', 'amb']),
        'ed_referral':     find_col(df, ['ED referral', 'emergency dept', 'E03', 'E02']),
        'gp_referral':     find_col(df, ['GP', 'primary care referral', 'G01']),
        'treated_advised': find_col(df, ['treated', 'advised', 'E07']),
    }

    print(f"\n  Column mapping:")
    for k, v in col_map.items():
        print(f"    {k:<20} → {v}")

    return kent_df, df, col_map


# ── STEP 4: EXTRACT METRICS ───────────────────────────────────────────
def extract_metrics(kent_df, all_df, col_map, period, period_nice, csv_url):
    """Extracts ICB and England totals, calculates rates, returns output dict."""

    def get_total(df, col):
        if col and col in df.columns:
            val = pd.to_numeric(df[col], errors='coerce').sum()
            return int(val) if not pd.isna(val) else 0
        return 0

    k_calls = get_total(kent_df, col_map['calls_received'])
    k_answd = get_total(kent_df, col_map['calls_answered'])
    k_amb   = get_total(kent_df, col_map['amb_dispatched'])
    k_ed    = get_total(kent_df, col_map['ed_referral'])
    k_gp    = get_total(kent_df, col_map['gp_referral'])

    e_calls = get_total(all_df, col_map['calls_received'])
    e_amb   = get_total(all_df, col_map['amb_dispatched'])
    e_ed    = get_total(all_df, col_map['ed_referral'])

    # Rates per 1,000
    def rate(n, pop):
        return round((n / pop) * 1000, 1) if n and pop else 0

    k_call_rate = rate(k_calls, KENT_ICB_POP)
    k_amb_rate  = rate(k_amb,   KENT_ICB_POP)
    k_ed_rate   = rate(k_ed,    KENT_ICB_POP)
    e_call_rate = rate(e_calls,  ENGLAND_POP)
    e_amb_rate  = rate(e_amb,    ENGLAND_POP)
    e_ed_rate   = rate(e_ed,     ENGLAND_POP)

    def ratio(k, e):
        return round(k / e, 3) if k and e else None

    print(f"\nStep 4: Kent & Medway ICB — {period_nice}")
    print(f"  {'Metric':<25} {'Kent':>12}  {'Rate/1k':>8}  {'Eng Rate':>8}  {'Ratio':>7}")
    print(f"  {'-'*65}")
    print(f"  {'Calls received':<25} {k_calls:>12,}  {k_call_rate:>8}  {e_call_rate:>8}  {ratio(k_call_rate, e_call_rate):>7}")
    print(f"  {'Calls answered':<25} {k_answd:>12,}")
    print(f"  {'Ambulance dispatched':<25} {k_amb:>12,}  {k_amb_rate:>8}  {e_amb_rate:>8}  {ratio(k_amb_rate, e_amb_rate):>7}")
    print(f"  {'ED referrals':<25} {k_ed:>12,}  {k_ed_rate:>8}  {e_ed_rate:>8}  {ratio(k_ed_rate, e_ed_rate):>7}")
    print(f"  {'GP referrals':<25} {k_gp:>12,}")

    # QA — flag if any ratio looks implausible
    print(f"\n  QA checks:")
    issues = []
    for name, k, e in [('call rate', k_call_rate, e_call_rate),
                        ('amb rate',  k_amb_rate,  e_amb_rate),
                        ('ED rate',   k_ed_rate,   e_ed_rate)]:
        if e and k:
            r = k / e
            if r > 3.0 or r < 0.3:
                issues.append(f"    *** {name}: ratio {r:.2f} looks implausible — check raw data")
            else:
                print(f"    {name}: {r:.3f}x England — plausible range ✓")
    if issues:
        for i in issues:
            print(i)

    return {
        "meta": {
            "generated":    datetime.now(timezone.utc).isoformat(),
            "description":  "NHS 111 / IUC demand — Kent & Medway ICB QKS",
            "period":       period,
            "period_nice":  period_nice,
            "icb":          "NHS Kent and Medway ICB (QKS)",
            "icb_pop":      KENT_ICB_POP,
            "england_pop":  ENGLAND_POP,
            "source":       "NHS England IUCADC — Aggregated Raw Data CSV",
            "source_url":   csv_url,
            "note":         ("Monthly data published ~6 weeks after month end. "
                             "ICB-level totals only. District figures are "
                             "population-weighted estimates."),
        },
        "kent_icb": {
            "calls_received":     k_calls,
            "calls_answered":     k_answd,
            "amb_dispatched":     k_amb,
            "ed_referrals":       k_ed,
            "gp_referrals":       k_gp,
            "call_rate_per_1000": k_call_rate,
            "amb_rate_per_1000":  k_amb_rate,
            "ed_rate_per_1000":   k_ed_rate,
        },
        "england": {
            "calls_received":     e_calls,
            "amb_dispatched":     e_amb,
            "ed_referrals":       e_ed,
            "call_rate_per_1000": e_call_rate,
            "amb_rate_per_1000":  e_amb_rate,
            "ed_rate_per_1000":   e_ed_rate,
        },
        "ratios": {
            "call_rate": ratio(k_call_rate, e_call_rate),
            "amb_rate":  ratio(k_amb_rate,  e_amb_rate),
            "ed_rate":   ratio(k_ed_rate,   e_ed_rate),
        },
    }


# ── STEP 5: COMMIT TO GITHUB ──────────────────────────────────────────
def commit_file(content, filepath, message, token):
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {"Authorization": f"token {token}",
               "Accept": "application/vnd.github.v3+json"}
    b64 = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
    r = requests.get(api_url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": message, "content": b64, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ {filepath}")
        return True
    print(f"  ✗ {filepath}: {r.status_code} — {r.json().get('message', '')}")
    return False


# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    # Get GitHub token — works in both GitHub Actions and Colab
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("ASSISTIV_GITHUB_TOKEN")
    if not token:
        try:
            from google.colab import userdata
            token = userdata.get("GITHUB_TOKEN").split("\n")[0].strip()
        except Exception:
            pass
    if not token:
        raise RuntimeError(
            "No GitHub token found.\n"
            "In GitHub Actions: add ASSISTIV_GITHUB_TOKEN to repository secrets.\n"
            "In Colab: add GITHUB_TOKEN to Colab Secrets."
        )

    # Step 1 — discover
    period, period_nice, csv_url = discover_latest_csv()

    # Step 2 — skip if already done
    if already_committed(period, token):
        return

    # Step 3 — fetch
    kent_df, all_df, col_map = fetch_and_parse(csv_url, period_nice)

    # Step 4 — extract
    output = extract_metrics(kent_df, all_df, col_map, period, period_nice, csv_url)

    # Step 5 — commit
    msg = (f"NHS 111 data — {period_nice} — "
           f"Kent {output['kent_icb']['calls_received']:,} calls received")
    print(f"\nStep 5: Committing to GitHub...")
    commit_file(output, "kent-111-data.json",
                msg, token)
    commit_file(output, f"history/kent-111-{period}.json",
                msg, token)

    print(f"\nDone — {period_nice}")
    print(f"  Current: kent-111-data.json")
    print(f"  Snapshot: history/kent-111-{period}.json")
    print(f"  Next run: 1st of next month (GitHub Actions) or run manually in Colab")


if __name__ == "__main__":
    main()
