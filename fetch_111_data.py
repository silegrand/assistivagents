"""
fetch_111_data.py — Assistiv Systems NHS 111 Monthly Data Fetcher v2
====================================================================
Scrapes NHS England IUCADC page, downloads the latest Provisional CSV,
extracts Kent/Medway/Sussex contract figures (SECAmb),
applies population weighting to estimate Kent & Medway ICB share,
and commits:
  - kent-111-data.json              (current — always overwritten)
  - history/kent-111-YYYY-MM.json   (monthly snapshot)

v2 fixes:
  - Robust column detection: prints all columns on first load so mismatches
    are immediately visible in the Actions log
  - Zero-guard: if extraction returns all zeros, raises an error rather than
    silently committing a blank snapshot
  - Force re-run: if FORCE_RERUN env var is set, skips the already_committed
    check (use when reprocessing a month that previously returned zeros)
  - Contract name fallback chain: tries CONTRACT_NAME → ORG_NAME → ORG_CODE
    → free text search across all string columns for 'kent' or 'secamb'
  - Item code fallback: tries both lowercase and uppercase column names
  - Output structure: now matches kent_icb_estimated + secamb_contract_raw
    (old structure had kent_icb / england — updated)
"""

import os, re, json, base64, requests
import pandas as pd
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# ── CONSTANTS ─────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistivagents"

# SECAmb contract covers Kent, Medway & Sussex
# Kent ICB 1.9m / contract area ~4.85m ≈ 0.39 — use 0.40
KENT_WEIGHT  = 0.40
KENT_ICB_POP = 1_900_000
ENGLAND_POP  = 56_490_000

# England reference rates per 1,000 population per month (IUCADC 2024/25)
ENG_CALL_RATE_MONTHLY = 65.4
ENG_AMB_RATE_MONTHLY  =  3.9
ENG_ED_RATE_MONTHLY   =  7.7

IUCADC_PAGES = [
    ("https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
     "integrated-urgent-care-aggregate-data-collection-iucadc-inc-nhs111-statistics-apr-2026-mar-2027/"),
    ("https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
     "integrated-urgent-care-aggregate-data-collection-iucadc-including-nhs111-statistics-apr-2025-mar-2026/"),
]

MONTH_MAP = {
    'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
    'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12',
}
YEAR_MAP = {'25':'2025','26':'2026','27':'2027','28':'2028'}

# GitHub Actions provides a meaningful UA; direct fetches may need a browser UA
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

FORCE_RERUN = os.environ.get("FORCE_RERUN", "").lower() in ("1", "true", "yes")


# ── STEP 1: DISCOVER CSV URL ──────────────────────────────────────────
def discover_latest_csv():
    print("Step 1: Scraping NHS England IUCADC pages...")
    url_pattern = re.compile(r'Provisional-IUCADC-Raw-([A-Za-z]{3})(\d{2})', re.IGNORECASE)
    candidates = []

    for page_url in IUCADC_PAGES:
        try:
            r = requests.get(page_url, timeout=20, headers=HEADERS)
            print(f"  Page HTTP {r.status_code}: {page_url[-60:]}")
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'Provisional-IUCADC-Raw' not in href or not href.endswith('.csv'):
                    continue
                m = url_pattern.search(href)
                if m:
                    mon, yr = m.groups()
                    month_num = MONTH_MAP.get(mon.lower())
                    year = YEAR_MAP.get(yr, f"20{yr}")
                    if month_num:
                        period = f"{year}-{month_num}"
                        full_url = href if href.startswith('http') else \
                                   'https://www.england.nhs.uk' + href
                        candidates.append((period, f"{mon.capitalize()} {year}", full_url))
                        print(f"  Found: {period} — ...{href[-50:]}")
        except Exception as e:
            print(f"  Warning on {page_url[-40:]}: {e}")

    if not candidates:
        raise RuntimeError(
            "No Provisional CSV links found. Page structure may have changed.\n"
            "Check: https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
        )

    candidates.sort(key=lambda x: x[0], reverse=True)
    period, period_nice, url = candidates[0]
    print(f"\n  Selected: {period_nice} ({period})")
    return period, period_nice, url


# ── STEP 2: ALREADY COMMITTED? ───────────────────────────────────────
def already_committed(period, token):
    if FORCE_RERUN:
        print(f"\nStep 2: FORCE_RERUN=true — bypassing snapshot check for {period}.")
        return False
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/history/kent-111-{period}.json"
    r = requests.get(api_url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    })
    if r.status_code == 200:
        # Extra check: was the snapshot committed with all zeros? If so, re-run.
        try:
            import base64 as b64mod
            content = json.loads(b64mod.b64decode(r.json()['content']).decode())
            calls = (content.get('kent_icb_estimated') or content.get('kent_icb', {})).get('calls_received', 0)
            if calls == 0:
                print(f"\nStep 2: Snapshot for {period} exists but has zero values — re-running.")
                return False
        except Exception:
            pass
        print(f"\nStep 2: Valid snapshot for {period} already committed — skipping.")
        return True
    print(f"\nStep 2: No snapshot for {period} — proceeding.")
    return False


# ── STEP 3: FETCH CSV ─────────────────────────────────────────────────
def fetch_csv(csv_url, period_nice):
    print(f"\nStep 3: Fetching {period_nice} CSV...")
    r = requests.get(csv_url, timeout=60, headers=HEADERS)
    print(f"  HTTP {r.status_code} | Size: {len(r.content):,} bytes")
    if r.status_code != 200:
        raise RuntimeError(f"Download failed: HTTP {r.status_code}")
    df = pd.read_csv(StringIO(r.text), low_memory=False)
    print(f"  Rows: {len(df):,} | Columns: {list(df.columns)}")
    return df


# ── STEP 4: EXTRACT KENT METRICS ─────────────────────────────────────
def extract_metrics(df, period, period_nice, csv_url):
    # Normalise column names to uppercase for robust matching
    df.columns = [c.strip().upper() for c in df.columns]
    print(f"\n  All columns: {list(df.columns)}")

    # ── Find the Kent contract rows ────────────────────────────────────
    kent = pd.DataFrame()

    # Strategy 1: CONTRACT_NAME column
    if 'CONTRACT_NAME' in df.columns:
        mask = df['CONTRACT_NAME'].str.contains('Kent', case=False, na=False)
        kent = df[mask]
        if len(kent) > 0:
            print(f"  Matched on CONTRACT_NAME: {kent['CONTRACT_NAME'].iloc[0]}")

    # Strategy 2: ORG_NAME
    if len(kent) == 0 and 'ORG_NAME' in df.columns:
        for term in ['Kent', 'SECAmb', 'South East Coast']:
            mask = df['ORG_NAME'].str.contains(term, case=False, na=False)
            kent = df[mask]
            if len(kent) > 0:
                print(f"  Matched on ORG_NAME with '{term}': {kent['ORG_NAME'].iloc[0]}")
                break

    # Strategy 3: ORG_CODE — SECAmb 111 contract code
    if len(kent) == 0 and 'ORG_CODE' in df.columns:
        for code in ['111AI9', 'RYC', 'SECAMB']:
            mask = df['ORG_CODE'].str.contains(code, case=False, na=False)
            kent = df[mask]
            if len(kent) > 0:
                print(f"  Matched on ORG_CODE '{code}'")
                break

    # Strategy 4: Search all string columns for 'Kent'
    if len(kent) == 0:
        str_cols = [c for c in df.columns if df[c].dtype == object]
        print(f"  Trying free-text search across string columns: {str_cols}")
        for col in str_cols:
            mask = df[col].str.contains('Kent', case=False, na=False)
            if mask.any():
                kent = df[mask]
                print(f"  Matched on column '{col}'")
                break

    if len(kent) == 0:
        # Print sample data to help diagnose
        print("\n  *** No Kent rows found. Sample data:")
        for col in list(df.columns)[:6]:
            print(f"    {col}: {df[col].unique()[:5]}")
        raise RuntimeError(
            "Cannot find Kent contract rows in CSV. "
            "Column structure may have changed — check Actions log for column list."
        )

    print(f"  Kent rows: {len(kent):,}")

    # ── Find item code and value columns ──────────────────────────────
    # Try common column name variants
    item_col  = next((c for c in df.columns if c in ('ITEM_NUMBER', 'ITEMID', 'ITEM_CODE', 'ITEM')), None)
    value_col = next((c for c in df.columns if c in ('VALUE', 'TOTAL', 'COUNT', 'VOLUME')), None)
    date_col  = next((c for c in df.columns if c in ('DATE', 'PERIOD', 'MONTH', 'ACTIVITY_DATE')), None)

    print(f"  Item col: {item_col} | Value col: {value_col} | Date col: {date_col}")

    if not item_col or not value_col:
        print(f"  All columns for diagnosis: {list(df.columns)}")
        raise RuntimeError(
            f"Cannot find item/value columns. "
            f"Found: item={item_col}, value={value_col}. "
            f"Check Actions log for full column list."
        )

    if date_col:
        print(f"  Period: {kent[date_col].min()} to {kent[date_col].max()}")

    # ── Sum by item code ──────────────────────────────────────────────
    kent[value_col] = pd.to_numeric(kent[value_col], errors='coerce').fillna(0)
    totals = kent.groupby(item_col)[value_col].sum()

    print(f"  Item codes present: {sorted(totals.index.tolist())}")

    def get(code):
        return int(totals.get(code, totals.get(code.lower(), 0)))

    raw_calls = get('A01')
    raw_answd = get('A03')
    raw_amb   = get('E02')
    raw_ed    = get('E03')
    raw_gp    = get('G03')
    raw_treat = get('E18')

    print(f"\n  SECAmb contract raw totals:")
    print(f"    A01 calls received:  {raw_calls:>8,}")
    print(f"    A03 calls answered:  {raw_answd:>8,}")
    print(f"    E02 amb dispatched:  {raw_amb:>8,}")
    print(f"    E03 ED referrals:    {raw_ed:>8,}")
    print(f"    G03 GP referrals:    {raw_gp:>8,}")
    print(f"    E18 treated/advised: {raw_treat:>8,}")

    # ── Zero-guard ────────────────────────────────────────────────────
    if raw_calls == 0 and raw_amb == 0 and raw_ed == 0:
        raise RuntimeError(
            "All key metrics are zero after extraction. "
            "Item code matching likely failed — see item codes present above."
        )

    # ── Apply Kent weighting ──────────────────────────────────────────
    def kent_est(n): return round(n * KENT_WEIGHT)
    def rate(n):     return round((n / KENT_ICB_POP) * 1000, 1) if n else 0
    def ratio(k, e): return round(k / e, 3) if k and e else None

    k_calls = kent_est(raw_calls)
    k_answd = kent_est(raw_answd)
    k_amb   = kent_est(raw_amb)
    k_ed    = kent_est(raw_ed)
    k_gp    = kent_est(raw_gp)
    k_treat = kent_est(raw_treat)

    k_call_rate = rate(k_calls)
    k_amb_rate  = rate(k_amb)
    k_ed_rate   = rate(k_ed)

    print(f"\n  Kent ICB estimates (×{KENT_WEIGHT}):")
    print(f"    Calls:  {k_calls:,}  ({k_call_rate}/1k, England {ENG_CALL_RATE_MONTHLY}/1k)")
    print(f"    Amb:    {k_amb:,}  ({k_amb_rate}/1k, England {ENG_AMB_RATE_MONTHLY}/1k)")
    print(f"    ED:     {k_ed:,}   ({k_ed_rate}/1k, England {ENG_ED_RATE_MONTHLY}/1k)")

    return {
        "meta": {
            "generated":       datetime.now(timezone.utc).isoformat(),
            "description":     "NHS 111 / IUC demand — Kent & Medway ICB (estimated) v2",
            "period":          period,
            "period_nice":     period_nice,
            "icb":             "NHS Kent and Medway ICB (QKS)",
            "icb_pop":         KENT_ICB_POP,
            "secamb_contract": "Kent, Medway & Sussex",
            "kent_weight":     KENT_WEIGHT,
            "source":          "NHS England IUCADC — Provisional Aggregated Raw Data CSV",
            "source_url":      csv_url,
            "note": (
                f"SECAmb contract covers Kent, Medway & Sussex. "
                f"Kent ICB figures estimated at {int(KENT_WEIGHT*100)}% of contract total "
                f"based on population share. Item codes: A01=calls, E02=amb, E03=ED, G03=GP."
            ),
        },
        "kent_icb_estimated": {
            "calls_received":     k_calls,
            "calls_answered":     k_answd,
            "amb_dispatched":     k_amb,
            "ed_referrals":       k_ed,
            "gp_referrals":       k_gp,
            "treated_advised":    k_treat,
            "call_rate_per_1000": k_call_rate,
            "amb_rate_per_1000":  k_amb_rate,
            "ed_rate_per_1000":   k_ed_rate,
        },
        "secamb_contract_raw": {
            "calls_received":  raw_calls,
            "calls_answered":  raw_answd,
            "amb_dispatched":  raw_amb,
            "ed_referrals":    raw_ed,
            "gp_referrals":    raw_gp,
            "treated_advised": raw_treat,
        },
        "england_reference_monthly": {
            "call_rate_per_1000": ENG_CALL_RATE_MONTHLY,
            "amb_rate_per_1000":  ENG_AMB_RATE_MONTHLY,
            "ed_rate_per_1000":   ENG_ED_RATE_MONTHLY,
            "note": "Annualised 2024/25 IUCADC national rates ÷ 12",
        },
        "ratios": {
            "call_rate": ratio(k_call_rate, ENG_CALL_RATE_MONTHLY),
            "amb_rate":  ratio(k_amb_rate,  ENG_AMB_RATE_MONTHLY),
            "ed_rate":   ratio(k_ed_rate,   ENG_ED_RATE_MONTHLY),
        },
    }


# ── STEP 5: COMMIT ────────────────────────────────────────────────────
def commit_file(content, filepath, message, token):
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {"Authorization": f"token {token}",
               "Accept": "application/vnd.github.v3+json"}
    b64 = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
    r = requests.get(api_url, headers=headers)
    sha = r.json().get("sha") if r.status_code == 200 else None
    payload = {"message": message, "content": b64, "branch": "main"}
    if sha: payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ {filepath}")
        return True
    print(f"  ✗ {filepath}: {r.status_code} — {r.json().get('message','')}")
    return False


# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("ASSISTIV_GITHUB_TOKEN")
    if not token:
        try:
            from google.colab import userdata
            token = userdata.get("GITHUB_TOKEN").split("\n")[0].strip()
        except Exception:
            pass
    if not token:
        raise RuntimeError("No GitHub token found in environment or Colab Secrets.")

    if FORCE_RERUN:
        print("FORCE_RERUN mode: will re-process even if snapshot exists with zeros.")

    period, period_nice, csv_url = discover_latest_csv()
    if already_committed(period, token):
        return
    df = fetch_csv(csv_url, period_nice)
    output = extract_metrics(df, period, period_nice, csv_url)

    msg = (f"NHS 111 data v2 — {period_nice} — "
           f"Kent est. {output['kent_icb_estimated']['calls_received']:,} calls")
    print(f"\nStep 5: Committing...")
    commit_file(output, "kent-111-data.json", msg, token)
    commit_file(output, f"history/kent-111-{period}.json", msg, token)
    print(f"\nDone — {period_nice}")
    print(f"  Kent est. calls:    {output['kent_icb_estimated']['calls_received']:,}")
    print(f"  Call rate/1k/month: {output['kent_icb_estimated']['call_rate_per_1000']}")
    print(f"  Amb rate/1k/month:  {output['kent_icb_estimated']['amb_rate_per_1000']}")


if __name__ == "__main__":
    main()
