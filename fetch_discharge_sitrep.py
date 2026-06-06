"""
fetch_discharge_sitrep.py — Assistiv Systems Discharge SitRep Fetcher v1
=========================================================================
Scrapes NHS England Acute Discharge SitRep monthly XLSX,
extracts Kent & Medway ICB (QKS) figures, and commits:
  - kent-discharge-data.json              (current — always overwritten)
  - history/kent-discharge-YYYY-MM.json   (monthly snapshot)

Key metrics extracted:
  Table 2 — Daily patients not discharged despite meeting criteria to reside
  Table 3 — Delayed bed days (7+, 14+, 21+ days LOS)
  Table 4 — Discharge destinations (Pathway 0–3)
  Table 5 — Delay reasons (hospital process, social care, capacity etc.)
  Table 7 — Cost of delays (bed days × £562/day unit cost)

Run monthly, ideally ~5 days after NHS England publishes the new file.
Published at:
  https://www.england.nhs.uk/statistics/statistical-work-areas/discharge-delays/
  acute-discharge-situation-report/
"""

import os, re, json, base64, io, requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# ── CONSTANTS ─────────────────────────────────────────────────────────
GITHUB_REPO  = 'silegrand/assistivagents'
KENT_ICB     = 'QKS'
KENT_NAME    = 'NHS KENT AND MEDWAY INTEGRATED CARE BOARD'
EKHUFT_CODE  = 'RVV'  # East Kent Hospitals University NHS Foundation Trust

SITREP_PAGES = [
    ('https://www.england.nhs.uk/statistics/statistical-work-areas/discharge-delays/'
     'acute-discharge-situation-report/'),
]

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
    )
}

FORCE_RERUN = os.environ.get('FORCE_RERUN', '').lower() in ('1', 'true', 'yes')

MONTH_NAMES = {
    'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
    'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12',
}


# ── STEP 1: DISCOVER XLSX URL ─────────────────────────────────────────
def discover_latest_xlsx():
    print('Step 1: Discovering latest SitRep XLSX from NHS England...')
    candidates = []

    for page_url in SITREP_PAGES:
        try:
            r = requests.get(page_url, timeout=20, headers=HEADERS)
            print(f'  HTTP {r.status_code}: {page_url[-60:]}')
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'Daily-discharge-sitrep-monthly' not in href:
                    continue
                if not (href.endswith('.xlsx') or href.endswith('.xls')):
                    continue
                # Extract month/year from filename
                # e.g. Daily-discharge-sitrep-monthly-data-webfile-01-April2026
                m = re.search(r'(\d{2})-([A-Za-z]+)(\d{4})', href)
                if m:
                    day, mon, yr = m.groups()
                    mon_num = MONTH_NAMES.get(mon[:3].lower())
                    if mon_num:
                        period = f'{yr}-{mon_num}'
                        period_nice = f'{mon} {yr}'
                        full_url = href if href.startswith('http') else \
                                   'https://www.england.nhs.uk' + href
                        candidates.append((period, period_nice, full_url))
                        print(f'  Found: {period_nice} — ...{href[-50:]}')
        except Exception as e:
            print(f'  Warning: {e}')

    if not candidates:
        raise RuntimeError(
            'No SitRep XLSX found. NHS England page structure may have changed.\n'
            'Check: https://www.england.nhs.uk/statistics/statistical-work-areas/'
            'discharge-delays/acute-discharge-situation-report/'
        )

    candidates.sort(key=lambda x: x[0], reverse=True)
    period, period_nice, url = candidates[0]
    print(f'\n  Selected: {period_nice} ({period})')
    return period, period_nice, url


# ── STEP 2: ALREADY COMMITTED? ────────────────────────────────────────
def already_committed(period, token):
    if FORCE_RERUN:
        print(f'\nStep 2: FORCE_RERUN — bypassing snapshot check for {period}.')
        return False
    api_url = (f'https://api.github.com/repos/{GITHUB_REPO}/contents/'
               f'history/kent-discharge-{period}.json')
    r = requests.get(api_url, headers={
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json'
    })
    if r.status_code == 200:
        print(f'\nStep 2: Snapshot for {period} already committed — skipping.')
        return True
    print(f'\nStep 2: No snapshot for {period} — proceeding.')
    return False


# ── STEP 3: FETCH XLSX ────────────────────────────────────────────────
def fetch_xlsx(url, period_nice):
    print(f'\nStep 3: Fetching {period_nice} SitRep XLSX...')
    r = requests.get(url, timeout=60, headers=HEADERS)
    print(f'  HTTP {r.status_code} | Size: {len(r.content):,} bytes')
    if r.status_code != 200:
        raise RuntimeError(f'Download failed: HTTP {r.status_code}')
    return io.BytesIO(r.content)


# ── STEP 4: EXTRACT KENT METRICS ─────────────────────────────────────
def find_kent_row(df, icb_code):
    """Find the row index where ICB code appears."""
    for i, row in df.iterrows():
        if any(str(v).strip().upper() == icb_code for v in row.dropna()):
            return i
    return None


def extract_metrics(xlsx_bytes, period, period_nice, xlsx_url):
    print(f'\nStep 4: Extracting Kent & Medway ICB ({KENT_ICB}) metrics...')

    xl = pd.ExcelFile(xlsx_bytes)
    print(f'  Sheets: {xl.sheet_names}')

    output = {
        'meta': {
            'generated':      datetime.now(timezone.utc).isoformat(),
            'description':    'NHS Acute Discharge SitRep — Kent & Medway ICB (QKS)',
            'period':         period,
            'period_nice':    period_nice,
            'icb_code':       KENT_ICB,
            'icb_name':       KENT_NAME,
            'ekhuft_code':    EKHUFT_CODE,
            'unit_cost_bed_day': 562,
            'source':         'NHS England Acute Daily Discharge SitRep',
            'source_url':     xlsx_url,
            'note': (
                'Table 2: daily snapshot of patients not discharged despite meeting '
                'criteria to reside. Table 3: delayed bed days (7+/14+/21+ day LOS). '
                'Table 4: discharge destinations by pathway. Table 5: delay reasons '
                '(14+ day LOS, weekly snapshot average). Table 7: estimated cost of '
                'delays at £562/bed day. EKHUFT figures are a subset of Kent ICB.'
            ),
        }
    }

    # ── TABLE 2: Daily discharge counts ──────────────────────────────
    print('  Parsing Table 2 (daily discharge counts)...')
    try:
        t2 = pd.read_excel(xlsx_bytes, sheet_name='Table 2', header=None)

        # Find column headers (dates) — row 2
        date_row = t2.iloc[2]
        dates = [v for v in date_row if isinstance(v, (pd.Timestamp, datetime))]

        kent_i = find_kent_row(t2, KENT_ICB)
        ekhuft_i = find_kent_row(t2, EKHUFT_CODE)

        if kent_i is not None:
            kent_row = t2.iloc[kent_i].dropna().tolist()
            # Cols: Region, ICB Code, ICB Name, then triplets:
            # (CTR, discharged, remaining) per day
            data_vals = [v for v in kent_row if isinstance(v, (int, float))]

            # Monthly average (mean across all daily CTR values)
            ctr_vals    = data_vals[0::3]  # every 3rd starting at 0
            disch_vals  = data_vals[1::3]
            remain_vals = data_vals[2::3]

            avg_ctr     = round(sum(ctr_vals) / len(ctr_vals), 1) if ctr_vals else None
            avg_disch   = round(sum(disch_vals) / len(disch_vals), 1) if disch_vals else None
            avg_remain  = round(sum(remain_vals) / len(remain_vals), 1) if remain_vals else None
            disch_rate  = round(avg_disch / avg_ctr * 100, 1) if avg_ctr else None

            output['table2_daily_discharge'] = {
                'description': 'Patients not discharged despite meeting criteria to reside',
                'days_in_period': len(dates),
                'kent_icb': {
                    'avg_meeting_ctr_per_day':       avg_ctr,
                    'avg_discharged_per_day':        avg_disch,
                    'avg_remaining_per_day':         avg_remain,
                    'discharge_rate_pct':            disch_rate,
                    'monthly_total_not_discharged':  sum(remain_vals),
                },
                'note': 'CTR = Criteria to Reside. Remaining = delayed discharges.'
            }
            print(f'    Kent avg remaining per day: {avg_remain}')
            print(f'    Kent discharge rate: {disch_rate}%')

        if ekhuft_i is not None:
            ekhuft_row = t2.iloc[ekhuft_i].dropna().tolist()
            ekhuft_vals = [v for v in ekhuft_row if isinstance(v, (int, float))]
            ekhuft_remain = ekhuft_vals[2::3]
            output['table2_daily_discharge']['ekhuft'] = {
                'avg_remaining_per_day': round(sum(ekhuft_remain)/len(ekhuft_remain),1) if ekhuft_remain else None,
                'note': 'East Kent Hospitals University NHS FT — subset of Kent ICB'
            }

    except Exception as e:
        print(f'    Table 2 extraction failed: {e}')
        output['table2_daily_discharge'] = {'error': str(e)}

    # ── TABLE 3: Delayed bed days ─────────────────────────────────────
    print('  Parsing Table 3 (delayed bed days)...')
    try:
        t3 = pd.read_excel(xlsx_bytes, sheet_name='Table 3', header=None)
        kent_i = find_kent_row(t3, KENT_ICB)

        if kent_i is not None:
            kent_row = t3.iloc[kent_i].dropna().tolist()
            # Cols after org identifiers: triplets of (7+, 14+, 21+) per week
            data_vals = [v for v in kent_row if isinstance(v, (int, float))]
            # Average across weeks for each LOS band
            n_weeks = len(data_vals) // 3 if len(data_vals) >= 3 else 1
            los_7  = data_vals[0::3]
            los_14 = data_vals[1::3]
            los_21 = data_vals[2::3]

            output['table3_delayed_bed_days'] = {
                'description': 'Additional days patients remain in hospital after CTR decision',
                'weeks_in_period': n_weeks,
                'kent_icb': {
                    'avg_7plus_days_per_week':  round(sum(los_7)/len(los_7),0) if los_7 else None,
                    'avg_14plus_days_per_week': round(sum(los_14)/len(los_14),0) if los_14 else None,
                    'avg_21plus_days_per_week': round(sum(los_21)/len(los_21),0) if los_21 else None,
                }
            }
            print(f'    Kent avg 7+ delayed bed days/week: {output["table3_delayed_bed_days"]["kent_icb"]["avg_7plus_days_per_week"]}')

    except Exception as e:
        print(f'    Table 3 extraction failed: {e}')
        output['table3_delayed_bed_days'] = {'error': str(e)}

    # ── TABLE 4: Discharge destinations ──────────────────────────────
    print('  Parsing Table 4 (discharge destinations)...')
    try:
        t4 = pd.read_excel(xlsx_bytes, sheet_name='Table 4', header=None)
        kent_i = find_kent_row(t4, KENT_ICB)

        if kent_i is not None:
            kent_row = t4.iloc[kent_i].dropna().tolist()
            data_vals = [v for v in kent_row if isinstance(v, (int, float))]
            # Columns: P0_home, P0_care_home, P1_home_rehab, P1_home_eol,
            #          P1_care_home_rehab, P2_short_term_bed, P3_care_home_new, P3_care_home_eol
            labels = ['p0_home', 'p0_care_home_return', 'p1_home_rehab',
                      'p1_home_other', 'p1_care_home_rehab', 'p2_short_term_bed',
                      'p3_care_home_new', 'p3_care_home_eol']
            total = sum(data_vals[:8]) if len(data_vals) >= 8 else sum(data_vals)
            dest = {labels[i]: int(data_vals[i]) for i in range(min(len(labels), len(data_vals)))}
            dest['total'] = int(total)
            dest['p3_pct'] = round((dest.get('p3_care_home_new',0)+dest.get('p3_care_home_eol',0))/total*100,1) if total else None
            output['table4_discharge_destinations'] = {
                'description': f'Total discharges in {period_nice} by pathway',
                'kent_icb': dest
            }
            print(f'    Kent total discharges: {total:,} | P3 (care home): {dest.get("p3_pct")}%')

    except Exception as e:
        print(f'    Table 4 extraction failed: {e}')
        output['table4_discharge_destinations'] = {'error': str(e)}

    # ── TABLE 5: Delay reasons ────────────────────────────────────────
    print('  Parsing Table 5 (delay reasons, 14+ day LOS)...')
    try:
        t5 = pd.read_excel(xlsx_bytes, sheet_name='Table 5', header=None)
        kent_i = find_kent_row(t5, KENT_ICB)

        if kent_i is not None:
            kent_row = t5.iloc[kent_i].dropna().tolist()
            data_vals = [v for v in kent_row if isinstance(v, (int, float))]
            reason_labels = [
                'hospital_therapy_review', 'hospital_medical_review',
                'hospital_care_transfer_hub', 'hospital_patient_transport',
                'hospital_medicines_docs', 'hospital_infection_control',
                'hospital_awaiting_decision', 'wellbeing_patient_family',
                'care_transfer_hub_process', 'interface_awaiting_assessment',
                'interface_awaiting_package', 'capacity_nhs_bed',
                'capacity_social_care_bed'
            ]
            reasons = {reason_labels[i]: round(float(data_vals[i]),1)
                       for i in range(min(len(reason_labels), len(data_vals)))}

            # Categorise
            hosp = sum(v for k,v in reasons.items() if k.startswith('hospital'))
            care = sum(v for k,v in reasons.items() if 'care_transfer' in k or 'interface' in k or 'capacity' in k)
            total_r = hosp + care
            output['table5_delay_reasons'] = {
                'description': f'Avg patients/day 14+ day LOS delayed, by reason — {period_nice}',
                'kent_icb': {
                    'by_reason': reasons,
                    'hospital_process_total': round(hosp,1),
                    'social_care_system_total': round(care,1),
                    'hospital_pct': round(hosp/total_r*100,1) if total_r else None,
                    'social_care_pct': round(care/total_r*100,1) if total_r else None,
                }
            }
            print(f'    Hospital process: {hosp:.1f} | Social care/interface: {care:.1f}')

    except Exception as e:
        print(f'    Table 5 extraction failed: {e}')
        output['table5_delay_reasons'] = {'error': str(e)}

    # ── TABLE 7: Cost of delays ───────────────────────────────────────
    print('  Parsing Table 7 (cost of delays)...')
    try:
        t7 = pd.read_excel(xlsx_bytes, sheet_name='Table 7', header=None)
        kent_i = find_kent_row(t7, KENT_ICB)
        ekhuft_i = find_kent_row(t7, EKHUFT_CODE)

        if kent_i is not None:
            kent_row = t7.iloc[kent_i].dropna().tolist()
            data_vals = [v for v in kent_row if isinstance(v, (int, float))]
            # Cols: avg_remaining_per_day, total_delayed_bed_days, total_cost, then cost by reason...
            output['table7_cost_of_delays'] = {
                'description': f'Estimated cost of delayed discharges — {period_nice}',
                'unit_cost_per_bed_day': 562,
                'kent_icb': {
                    'avg_remaining_per_day':   round(float(data_vals[0]),1) if len(data_vals)>0 else None,
                    'total_delayed_bed_days':  int(data_vals[1]) if len(data_vals)>1 else None,
                    'total_cost_gbp':          int(data_vals[2]) if len(data_vals)>2 else None,
                    'total_cost_gbp_millions': round(data_vals[2]/1_000_000,2) if len(data_vals)>2 else None,
                }
            }
            cost_m = output['table7_cost_of_delays']['kent_icb']['total_cost_gbp_millions']
            days = output['table7_cost_of_delays']['kent_icb']['total_delayed_bed_days']
            print(f'    Kent delayed bed days: {days:,} | Cost: £{cost_m}m')

        if ekhuft_i is not None:
            ekhuft_row = t7.iloc[ekhuft_i].dropna().tolist()
            ekhuft_vals = [v for v in ekhuft_row if isinstance(v, (int, float))]
            if len(ekhuft_vals) >= 3:
                output['table7_cost_of_delays']['ekhuft'] = {
                    'avg_remaining_per_day':   round(float(ekhuft_vals[0]),1),
                    'total_delayed_bed_days':  int(ekhuft_vals[1]),
                    'total_cost_gbp':          int(ekhuft_vals[2]),
                    'total_cost_gbp_millions': round(ekhuft_vals[2]/1_000_000,2),
                }

    except Exception as e:
        print(f'    Table 7 extraction failed: {e}')
        output['table7_cost_of_delays'] = {'error': str(e)}

    # ── SOUTH EAST REGIONAL CONTEXT ──────────────────────────────────
    # Pull South East region row from Table 2 for comparison
    try:
        t2 = pd.read_excel(xlsx_bytes, sheet_name='Table 2', header=None)
        for i, row in t2.iterrows():
            vals = row.dropna().tolist()
            if vals and str(vals[0]).strip().upper() == 'SOUTH EAST' and len(vals) == 1:
                continue
            if vals and str(vals[0]).strip().upper() == 'SOUTH EAST' and len(vals) > 3:
                data_vals = [v for v in vals if isinstance(v, (int, float))]
                remain = data_vals[2::3]
                if remain:
                    output['south_east_context'] = {
                        'avg_remaining_per_day': round(sum(remain)/len(remain),1)
                    }
                break
    except Exception:
        pass

    return output


# ── STEP 5: COMMIT ────────────────────────────────────────────────────
def commit_file(content, filepath, message, token):
    api_url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}'
    hdrs = {'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'}
    b64 = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
    r = requests.get(api_url, headers=hdrs)
    sha = r.json().get('sha') if r.status_code == 200 else None
    payload = {'message': message, 'content': b64, 'branch': 'main'}
    if sha: payload['sha'] = sha
    r = requests.put(api_url, headers=hdrs, json=payload)
    if r.status_code in (200, 201):
        print(f'  ✓ {filepath}')
        return True
    print(f'  ✗ {filepath}: {r.status_code} — {r.json().get("message","")}')
    return False


# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('ASSISTIV_GITHUB_TOKEN')
    if not token:
        try:
            from google.colab import userdata
            token = userdata.get('GITHUB_TOKEN').split('\n')[0].strip()
        except Exception:
            pass
    if not token:
        raise RuntimeError('No GitHub token found.')

    period, period_nice, xlsx_url = discover_latest_xlsx()
    if already_committed(period, token):
        return

    xlsx_bytes = fetch_xlsx(xlsx_url, period_nice)
    output = extract_metrics(xlsx_bytes, period, period_nice, xlsx_url)

    cost = output.get('table7_cost_of_delays',{}).get('kent_icb',{}).get('total_cost_gbp_millions','?')
    remain = output.get('table2_daily_discharge',{}).get('kent_icb',{}).get('avg_remaining_per_day','?')
    msg = (f'Discharge SitRep {period_nice} — Kent avg {remain}/day remaining '
           f'| Cost £{cost}m')

    print(f'\nStep 5: Committing...')
    commit_file(output, 'kent-discharge-data.json', msg, token)
    commit_file(output, f'history/kent-discharge-{period}.json', msg, token)
    print(f'\nDone — {period_nice}')
    print(f'  Avg remaining/day: {remain}')
    print(f'  Monthly cost:      £{cost}m')


if __name__ == '__main__':
    main()
