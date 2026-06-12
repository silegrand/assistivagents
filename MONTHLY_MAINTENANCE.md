# assistiv.cloud — Monthly Data Maintenance
Last updated: June 2026

## Overview
The NHS Pressure Intelligence Map (`nhs-pressure-map.html`) pulls from four
JSON files updated by GitHub Actions. Three of the four update automatically.
One requires a manual URL update each month.

---

## Every month — Manual actions required

### 1. Corridor Care CSV (publishes ~11th each month)
**Publication page:**
https://www.england.nhs.uk/statistics/statistical-work-areas/corridor-care-urgent-and-emergency-care-daily-situation-reports/

**What to do:**
1. Go to the page above
2. Find the new monthly CSV link (e.g. `Corridor-Care-Publication-2026.06-June-prov-vX-csv.csv`)
3. Copy the URL
4. Open `fetch_corridor_care.py` in the repo
5. Add a new entry to `KNOWN_RELEASES`:
```python
"2026-06": {
    "period_label": "June 2026",
    "pub_url": "https://www.england.nhs.uk/statistics/...",
    "csv_url": "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/07/Corridor-Care-Publication-2026.06-June-prov-vX-csv.csv",
},
```
6. Commit and run **Corridor Care Weekly Refresh** workflow manually

---

### 2. GP Registration ZIP (publishes ~11th each month)
**Publication page:**
https://digital.nhs.uk/data-and-information/publications/statistical/patients-registered-at-a-gp-practice

**What to do:**
1. Go to the latest monthly publication (e.g. `/july-2026`)
2. Find the **"5-year age groups (Commissioning Regions-ICBs-SICBLs-PCNs-GP practice)"** ZIP link
3. Copy the URL from `files.digital.nhs.uk`
4. Open `fetch_shmi_gp.py` in the repo
5. Add a new entry to `KNOWN_GP_REG`:
```python
"2026-07-01": {
    "snapshot_date": "2026-07-01",
    "pub_url":    "https://digital.nhs.uk/.../july-2026",
    "zip_url":    "https://files.digital.nhs.uk/XX/XXXXXX/gp-reg-pat-prac-quin-age.zip",
},
```
6. Commit — the **HES + SHMI + GP Registration Monthly Refresh** workflow runs automatically on the 12th

---

### 3. SHMI CSV (publishes monthly, ~6-month lag)
**Publication page:**
https://digital.nhs.uk/data-and-information/publications/statistical/shmi

**What to do:**
1. Go to the latest publication page
2. Download the ZIP
3. Extract `SHMI_data_at_trust_level_[period]_csv.csv`
4. Upload that CSV to the repo root
5. Open `fetch_shmi_gp.py` and add a new entry to `KNOWN_SHMI`:
```python
"March 2025 - February 2026": {
    "period":  "March 2025 - February 2026",
    "pub_url": "https://digital.nhs.uk/.../2026-07",
    "csv_url": "https://raw.githubusercontent.com/silegrand/assistiv_cloud/main/SHMI_data_at_trust_level_Mar25-Feb26_csv.csv",
},
```
6. Commit — workflow runs automatically on the 12th

---

### 4. HES MAR CCG by Provider (publishes ~11th each month)
**Publication page:**
https://digital.nhs.uk/data-and-information/publications/statistical/provisional-monthly-hospital-episode-statistics-for-admitted-patient-care-outpatient-and-accident-and-emergency-data/

**What to do:**
1. Download the **"CCG by Provider"** ZIP from the latest publication
2. Run this Python snippet to extract Kent rows:
```python
import csv, io, zipfile
with zipfile.ZipFile('HES_MAR_[period]_CCG_by_Provider.zip') as zf:
    fname = [n for n in zf.namelist() if n.endswith('.csv')][0]
    content = zf.read(fname).decode('utf-8-sig')
reader = csv.DictReader(io.StringIO(content))
rows = list(reader)
kent = [r for r in rows if r.get('Provider code','').strip().upper() in ('RVV','RWF','RPA','RN7')]
# Write kent rows to new CSV and upload to repo
```
3. Upload the Kent-filtered CSV to the repo root as `HES_MAR_[M-number]_Kent_Trusts.csv`
4. Open `fetch_hes_monthly.py` and add a new entry to `KNOWN_RELEASES`:
```python
"May 2025 - April 2026 (M1)": {
    "kent_csv": "https://raw.githubusercontent.com/silegrand/assistiv_cloud/main/HES_MAR_M1_Kent_Trusts.csv",
    "pub_url":  "https://digital.nhs.uk/...",
},
```
5. Commit — workflow runs automatically on the 12th

---

## Automatic (no action needed)

| Workflow | Schedule | What it does |
|---|---|---|
| `daily_refresh.yml` | Daily 08:00 UTC | FEP scores from NHS Fingertips — district frailty intelligence |
| `corridor_care_weekly.yml` | Thursday 10:00 UTC | Corridor care CSV (once URL added to KNOWN_RELEASES) |
| `hes_shmi_gp_monthly.yml` | 12th of month 08:00 UTC | HES admissions + SHMI + GP registration |

---

## Data sources quick reference

| Data | Source | Lag | Format |
|---|---|---|---|
| Corridor care | NHS England UEC SitRep | ~1 month | CSV — direct URL |
| GP registration | NHS Digital | ~10 days | ZIP — direct URL |
| SHMI | NHS Digital | ~5-6 months | ZIP download → CSV to repo |
| HES MAR | NHS Digital | ~10 weeks | ZIP download → Kent CSV to repo |
| FEP / Fingertips | NHS Fingertips via API | Daily | Automated via fingertips_py |
| EPD prescribing | NHSBSA | Monthly manual | Colab pipeline → JSON |

---

## Kent trust ODS codes
- **RVV** — East Kent Hospitals University NHS Foundation Trust (Thanet, Dover, Folkestone & Hythe, Canterbury, Ashford)
  - Serves: Thanet, Dover, Folkestone & Hythe, Canterbury, Swale, Medway
- **RWF** — Maidstone and Tunbridge Wells NHS Trust (Maidstone, Tonbridge & Malling, Tunbridge Wells, Sevenoaks)
- **RPA** — Medway NHS Foundation Trust (Medway, Swale)
- **RN7** — Dartford and Gravesham NHS Trust (Dartford, Gravesham)
  - Serves: Maidstone, Tonbridge & Malling, Tunbridge Wells, Sevenoaks, Ashford, Gravesham, Dartford
