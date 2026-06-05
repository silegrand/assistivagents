"""
fetch_111_data.py — Assistiv Systems NHS 111 Monthly Data Fetcher
=================================================================
Scrapes NHS England IUCADC page, downloads the latest Provisional CSV,
extracts Kent/Medway/Sussex contract figures (SECAmb 111AI9),
applies population weighting to estimate Kent & Medway ICB share,
and commits:
  - kent-111-data.json              (current — always overwritten)
  - history/kent-111-YYYY-MM.json   (monthly snapshot — never overwritten)

Data format: long/narrow — one row per day per item code.
Key item codes: A01=calls received, A03=answered, E02=amb dispatch,
                E03=ED referral, G03=GP referral, E18=treated/advised.

Geography: SECAmb contract "Kent, Medway & Sussex" — Kent ICB is
approximately 55% of this population. A weighting factor is applied.

No manual updates needed — scrapes page to find randomised CSV URLs.
"""

import os, re, json, base64, requests
import pandas as pd
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# ── CONSTANTS ─────────────────────────────────────────────────────────
GITHUB_REPO  = "silegrand/assistivagents"

# SECAmb contract area: Kent, Medway & Sussex
# Kent & Medway ICB population as % of total contract area population
# Kent ICB: 1.9m / (Kent 1.9m + Surrey 1.2m + Sussex 1.7m) ≈ 0.40
# Kent, Medway & Sussex contract = Kent + East Sussex + West Sussex + Brighton
# Kent ICB 1.9m / contract area ~4.85m = 0.39 — use 0.40 as conservative estimate
KENT_WEIGHT  = 0.40            # Kent ICB share of SECAmb contract
KENT_ICB_POP = 1_900_000
ENGLAND_POP  = 56_490_000

# England reference rates (published IUCADC national 2024/25 annualised)
# Per 1,000 population per month
ENG_CALL_RATE_MONTHLY = 65.4   # ~785/year
ENG_AMB_RATE_MONTHLY  =  3.9   # ~47/year
ENG_ED_RATE_MONTHLY   =  7.7   # ~92/year

IUCADC_PAGES = [
    "https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
    "integrated-urgent-care-aggregate-data-collection-iucadc-inc-nhs111-statistics-apr-2026-mar-2027/",
    "https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
    "integrated-urgent-care-aggregate-data-collection-iucadc-including-nhs111-statistics-apr-2025-mar-2026/",
]

MONTH_MAP = {
    'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
    'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12',
}
YEAR_MAP = {'25':'2025','26':'2026','27':'2027','28':'2028'}
HEADERS  = {"User-Agent": "Mozilla/5.0 AssistivSystems/1.0"}


# ── STEP 1: SCRAPE PAGE ───────────────────────────────────────────────
def discover_latest_csv():
    print("Step 1: Scraping NHS England IUCADC pages...")
    url_pattern = re.compile(
        r'Provisional-IUCADC-Raw-([A-Za-z]{3})(\d{2})',
        re.IGNORECASE
    )
    candidates = []

    for page_url in IUCADC_PAGES:
        try:
            r = requests.get(page_url, timeout=20, headers=HEADERS)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'Provisional-IUCADC-Raw' not in href:
                    continue
                if not href.endswith('.csv'):
                    continue
                m = url_pattern.search(href)
                if m:
                    mon, yr = m.groups()
                    month_num = MONTH_MAP.get(mon.lower())
                    year = YEAR_MAP.get(yr, f"20{yr}")
                    if month_num:
                        period = f"{year}-{month_num}"
                        period_nice = f"{mon.capitalize()} {year}"
                        full_url = href if href.startswith('http') else \
                                   'https://www.england.nhs.uk' + href
                        candidates.append((period, period_nice, full_url))
                        print(f"  Found: {period_nice} — ...{href[-45:]}")
        except Exception as e:
            print(f"  Warning: {e}")

    if not candidates:
        raise RuntimeError(
            "No Provisional CSV links found. Page structure may have changed.\n"
            "Check: https://www.england.nhs.uk/statistics/statistical-work-areas/iucadc-new-from-april-2021/"
        )

    candidates.sort(key=lambda x: x[0], reverse=True)
    period, period_nice, url = candidates[0]
    print(f"\n  Selected: {period_nice} ({period})")
    print(f"  URL: {url}")
    return period, period_nice, url


# ── STEP 2: ALREADY COMMITTED? ───────────────────────────────────────
def already_committed(period, token):
    api_url = (f"https://api.github.com/repos/{GITHUB_REPO}"
               f"/contents/history/kent-111-{period}.json")
    r = requests.get(api_url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    })
    if r.status_code == 200:
        print(f"\nStep 2: history/kent-111-{period}.json exists — skipping.")
        return True
    print(f"\nStep 2: No snapshot for {period} — proceeding.")
    return False


# ── STEP 3: FETCH CSV ─────────────────────────────────────────────────
def fetch_csv(csv_url, period_nice):
    print(f"\nStep 3: Fetching {period_nice} CSV...")
    r = requests.get(csv_url, timeout=60, headers=HEADERS)
    print(f"  HTTP {r.status_code} | Size: {len(r.content):,} bytes")
    if r.status_code != 200:
        raise RuntimeError(f"Download failed: HTTP {r.status_code}\nURL: {csv_url}")
    df = pd.read_csv(StringIO(r.text), low_memory=False)
    print(f"  Rows: {len(df):,} | Columns: {list(df.columns)}")
    return df


# ── STEP 4: EXTRACT KENT METRICS ─────────────────────────────────────
def extract_metrics(df, period, period_nice, csv_url):
    # Filter Kent, Medway & Sussex contract
    kent_mask = df['CONTRACT_NAME'].str.contains('Kent', case=False, na=False)
    kent = df[kent_mask]

    if len(kent) == 0:
        # Try ORG_NAME as fallback
        kent_mask = df['ORG_NAME'].str.contains('South East Coast', case=False, na=False)
        kent = df[kent_mask]

    if len(kent) == 0:
        print("  All contract names:", df['CONTRACT_NAME'].unique()[:10])
        raise RuntimeError("Cannot find Kent contract rows.")

    print(f"\n  Contract: {kent['CONTRACT_NAME'].iloc[0]} ({len(kent)} rows)")
    print(f"  Period: {kent['DATE'].min()} to {kent['DATE'].max()}")

    # Sum all values per item code across the full month
    totals = kent.groupby('ITEM_NUMBER')['VALUE'].sum()

    def get(code):
        return int(totals.get(code, 0))

    # Raw SECAmb contract totals
    raw_calls = get('A01')   # calls received
    raw_answd = get('A03')   # calls answered
    raw_amb   = get('E02')   # ambulance dispatched
    raw_ed    = get('E03')   # ED referrals
    raw_gp    = get('G03')   # GP/primary care referrals
    raw_treat = get('E18')   # treated/advised (no escalation)

    print(f"\n  SECAmb contract raw totals (Kent, Medway & Sussex):")
    print(f"    A01 calls received:  {raw_calls:>8,}")
    print(f"    A03 calls answered:  {raw_answd:>8,}")
    print(f"    E02 amb dispatched:  {raw_amb:>8,}")
    print(f"    E03 ED referrals:    {raw_ed:>8,}")
    print(f"    G03 GP referrals:    {raw_gp:>8,}")
    print(f"    E18 treated/advised: {raw_treat:>8,}")

    # Apply Kent ICB population weighting (~40% of contract area)
    def kent_est(n):
        return round(n * KENT_WEIGHT)

    k_calls = kent_est(raw_calls)
    k_answd = kent_est(raw_answd)
    k_amb   = kent_est(raw_amb)
    k_ed    = kent_est(raw_ed)
    k_gp    = kent_est(raw_gp)
    k_treat = kent_est(raw_treat)

    # Rates per 1,000 Kent ICB population per month
    def rate(n):
        return round((n / KENT_ICB_POP) * 1000, 1) if n else 0

    k_call_rate = rate(k_calls)
    k_amb_rate  = rate(k_amb)
    k_ed_rate   = rate(k_ed)

    print(f"\n  Kent ICB estimates (×{KENT_WEIGHT} weighting):")
    print(f"    {'Metric':<22} {'Estimate':>10}  {'Rate/1k':>8}  {'Eng/1k':>8}  {'Ratio':>7}")
    print(f"    {'-'*60}")

    def ratio(k, e):
        return round(k / e, 3) if k and e else None

    rows = [
        ('Calls received', k_calls, k_call_rate, ENG_CALL_RATE_MONTHLY),
        ('Amb dispatched', k_amb,   k_amb_rate,  ENG_AMB_RATE_MONTHLY),
        ('ED referrals',   k_ed,    k_ed_rate,   ENG_ED_RATE_MONTHLY),
    ]
    for name, k, kr, er in rows:
        rv = ratio(kr, er)
        print(f"    {name:<22} {k:>10,}  {kr:>8}  {er:>8}  {str(rv):>7}")

    # QA
    print(f"\n  QA checks:")
    for name, kr, er in [('call', k_call_rate, ENG_CALL_RATE_MONTHLY),
                          ('amb',  k_amb_rate,  ENG_AMB_RATE_MONTHLY),
                          ('ED',   k_ed_rate,   ENG_ED_RATE_MONTHLY)]:
        if er and kr:
            rv = kr / er
            flag = "*** implausible" if rv > 4 or rv < 0.2 else "plausible OK"
            print(f"    {name} rate: {rv:.3f}x England — {flag}")

    return {
        "meta": {
            "generated":        datetime.now(timezone.utc).isoformat(),
            "description":      "NHS 111 demand — Kent & Medway ICB (estimated)",
            "period":           period,
            "period_nice":      period_nice,
            "icb":              "NHS Kent and Medway ICB (QKS)",
            "icb_pop":          KENT_ICB_POP,
            "secamb_contract":  "Kent, Medway & Sussex (111AI9)",
            "kent_weight":      KENT_WEIGHT,
            "source":           "NHS England IUCADC — Provisional Aggregated Raw Data",
            "source_url":       csv_url,
            "note":             (
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
            "note": "Annualised 2024/25 IUCADC national rates divided by 12",
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
        raise RuntimeError("No GitHub token found.")

    period, period_nice, csv_url = discover_latest_csv()
    if already_committed(period, token): return
    df = fetch_csv(csv_url, period_nice)
    output = extract_metrics(df, period, period_nice, csv_url)

    msg = (f"NHS 111 data — {period_nice} — "
           f"Kent est. {output['kent_icb_estimated']['calls_received']:,} calls")
    print(f"\nStep 5: Committing...")
    commit_file(output, "kent-111-data.json", msg, token)
    commit_file(output, f"history/kent-111-{period}.json", msg, token)
    print(f"\nDone — {period_nice}")
    print(f"  Kent est. calls: {output['kent_icb_estimated']['calls_received']:,}")
    print(f"  Call rate/1k:    {output['kent_icb_estimated']['call_rate_per_1000']}")


if __name__ == "__main__":
    main()
