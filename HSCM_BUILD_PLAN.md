# HSCM Integration — Build Plan & Methodology

**Assistiv Systems · assistiv.cloud**
**Source:** Kent Public Health Observatory Health and Social Care Maps  
**Current version:** V1.6, published March 2026  
**Licence:** Open Government Licence v3.0

---

## What this dataset is

The KPHO Health and Social Care Maps is Kent County Council's comprehensive epidemiological dataset, built and maintained by the Kent Public Health Observatory. It is one of the most data-rich open datasets available for Kent, covering 85 indicators across four geographic levels: Kent-wide, District (13), Primary Care Network (45), and Middle Super Output Area (220).

The dataset is published as a single Excel file (`hscm_combined-VX.X.xlsx`) and as an interactive PowerBI dashboard. The Excel download is the authoritative source for this pipeline.

**Dataset page:** https://www.kpho.org.uk/joint-strategic-needs-assessment/health-and-social-care-maps

---

## Monthly maintenance — the most important thing

KPHO publish new versions of this dataset periodically. The version number and publish date are embedded in the filename (`hscm_combined-V1.6.xlsx` = version 1.6, March 2026).

**When a new version is published:**

1. Go to the dataset page (URL above)
2. Copy the new download URL from the "Download the data" section
3. Update `HSCM_DOWNLOAD_URL` and `HSCM_VERSION` and `HSCM_PUBLISH_DATE` in `fetch_hscm.py`
4. Commit the change and trigger `workflow_dispatch` on `hes_shmi_gp_monthly.yml`
5. Verify `kent-hscm-data.json` is updated in the repo

The pipeline runs automatically on the 12th of each month via `hes_shmi_gp_monthly.yml`. If KPHO have not published a new version, the script re-processes the existing URL and the JSON is refreshed with the same data (no harm done).

**Version history:**
| Version | Published     | Notes |
|---------|---------------|-------|
| V1.6    | March 2026    | Current. Added frailty at PCN level. |
| V1.5    | ~Dec 2025     | Previous version. |

---

## How this integrates with the Assistiv platform

### 1. FEP Score Recalibration (`daily_refresh.py`)

The most important integration. The KPHO frailty indicator uses **GP-recorded Clinical Frailty Scale scores** — actual clinical measurements assigned by GPs to their patients. The existing Assistiv FEP score uses Fingertips proxy signals (deprivation, prescribing rates, mortality indices) to estimate frailty risk.

Where the two diverge, the KPHO clinical measurement is more reliable for absolute frailty prevalence.

**Key divergences discovered in V1.6:**

| District | FEP (proxy) | KPHO Clinical | Direction |
|----------|-------------|---------------|-----------|
| Dartford | 49/100 | 79/100 | FEP **severely underestimates** |
| Folkestone & Hythe | 52/100 | 69/100 | FEP underestimates |
| Tunbridge Wells | 53/100 | 70/100 | FEP underestimates |
| Thanet | 61/100 | 100/100 | FEP underestimates (but correct direction) |
| Maidstone | 60/100 | 44/100 | FEP **overestimates** |
| Swale | 51/100 | 42/100 | FEP overestimates |

Dartford has been consistently ranked near the bottom of every Assistiv tool. Clinical evidence suggests it should not be. Maidstone has been the top WVI district — its prescribing signals are genuinely elevated but the underlying clinical frailty burden is lower than the proxies implied.

**Recalibration method:**
```
kpho_norm = (kpho_frailty_pct - kent_min) / (kent_max - kent_min) × 100
recalibrated_fep = (0.40 × kpho_norm) + (0.60 × existing_fep)
```
Kent min = 2.74% (Swale), Kent max = 6.47% (Thanet). These anchors should be updated each version.

The weight (40% KPHO / 60% proxy) reflects that KPHO data is one-year lagged and at population register level, while the proxy signals are monthly and capture recent change. Revisit this weighting annually.

**In `daily_refresh.py`:** Load `kent-hscm-data.json` and retrieve `districts[name]['kpho_frailty_normalised']`. Blend into FEP calculation before writing `kent-fep-data.json`.

### 2. NHS Pressure Map — MSOA Frailty Layer

220 MSOAs across Kent with GP-recorded frailty prevalence, plus companion indicators:
- Older adults living alone (Census 2021)
- Unpaid care 50+ hours/week (Census 2021)
- Fuel poverty % (2023)
- Winter Mortality Index (2023/24)
- Falls hip admissions rate (2022-25 rolling)
- Pension Credit % (2024)
- Winter fuel payments % (2023/24)
- Physical activity 65+ (2023/24)

**Top frailty hotspots by MSOA (V1.6):**

| Rank | MSOA | Frailty % | Area code |
|------|------|-----------|-----------|
| 1 | Cliftonville West | 13.30% | E02005132 |
| 2 | Folkestone Central | 11.70% | E02006880 |
| 3 | Tunbridge Wells West | 11.20% | E02005168 |
| 4 | Hartley & Hodsoll Street | 9.75% | E02005090 |
| 5 | Brent & Fleet Estate | 9.48% | E02005035 |

These are the specific communities for targeted winter outreach deployment — granularity the pressure map previously lacked entirely.

**In `nhs-pressure-map.html`:** Toggle-able MSOA choropleth layer on the Leaflet map. Click MSOA to show frailty %, falls rate, carer burden, fuel poverty in a pop-up. Requires MSOA GeoJSON (ONS open geography — add `kent-msoa.geojson` to the repo).

### 3. Winter Readiness — Carer Breakdown Signal

Unpaid carer data at district level (Census 2021, MSOA also available):

| District | Unpaid carers 50+ hrs/week | Count |
|----------|---------------------------|-------|
| Thanet | 3.8% | 5,076 people |
| Folkestone & Hythe | 3.5% | 3,671 people |
| Swale | 3.5% | 4,984 people |
| Dover | 3.4% | 3,794 people |

Carer breakdown events spike in December–January (Carers UK annual survey). Each breakdown typically results in an emergency admission for the cared-for person within 48 hours. The Festive Fortnight panel now surfaces these counts per district.

### 4. Winter Readiness — Thermal Risk Panel Enrichment

Replaces the FEP-proxy-derived cold home estimates with actual KPHO figures:
- **Fuel poverty %** at district and MSOA level (2023)
- **Winter fuel payment recipients %** as proxy for elderly on fixed income
- **Older adults living alone %** at MSOA level

These replace the `dep * 0.4 + alone * 0.4` formula currently used in `renderThermal()` with KPHO-sourced values. The MSOA-level fuel poverty data enables sub-district thermal risk mapping.

### 5. NHS Pressure Map — Disease Prevalence Panel

KPHO provides disease prevalence at MSOA level (December 2025 KMCR data):

| Indicator | England avg | Kent districts: highest |
|-----------|------------|------------------------|
| COPD | 1.89% | Thanet 3.19%, Dover 3.11% |
| Dementia | 0.78% | Folkestone 1.03%, Canterbury 1.00% |
| Depression | 14.3% | Thanet 20.1%, Swale 19.0% |
| Heart failure | 1.1% | Folkestone 1.19%, Swale 1.13% |
| Stroke | 1.89% | Folkestone 2.38%, Thanet 2.36% |
| Hypertension | 15.2% | Thanet 18.8%, Folkestone 18.6% |

Added to the district detail panel in `nhs-pressure-map.html` as a Disease Burden card, enabling commissioners to see clinical prevalence alongside system pressure signals.

### 6. PCN Intelligence (future standalone tool)

45 PCNs with frailty prevalence data. Top PCNs by clinical frailty burden:

| PCN | Frailty % | Frailty patients |
|-----|-----------|-----------------|
| Margate PCN | 7.25% | 941 |
| Swanley and Rural PCN | 6.49% | 396 |
| LMN Care PCN (Folkestone) | 6.42% | 444 |
| Tunbridge Wells PCN | 6.13% | 827 |
| Dartford Central PCN | 5.91% | 181 |

A PCN-level frailty intelligence tool would be the appropriate level for NHS Kent and Medway ICB commissioning conversations. PCN leads are accountable for frailty identification and management under the Primary Care Network DES. This data is ready.

---

## Data notes and caveats

**Frailty indicator:**
- GP-recorded CFS scores assigned during annual frailty reviews. Coverage is not 100% — some practices record more comprehensively than others.
- Denominator = total GP-registered patients (all ages), so frailty % is of the full registered list, not just older adults. This makes cross-district comparison valid.
- Published November 2025. Expect next update approximately February–March 2026.

**Disease prevalence (COPD, dementia etc.):**
- Source is Kent and Medway Care Record (KMCR), labelled "December 2025". This is linked primary care record data — more comprehensive than Fingertips QOF data.
- The `latest` column shows "KMCR" not "Y" — the fetch script handles this correctly by sorting by `timeperiod_sortable` descending.

**Older adults living alone / unpaid carers:**
- Census 2021 data. Now five years old. Use with awareness that post-pandemic demographic shifts may have moved some district figures. The MSOA-level data remains useful for relative targeting even if absolute values have drifted.

**Access to Healthcare index:**
- Relative index, not a percentage. Positive = better access than Kent average, negative = worse. Useful for identifying geographic isolation. Ashford (0.5), Sevenoaks (0.3) have best access; Thanet (-0.31) has worst.

---

## Files produced by this integration

| File | Location | Updated by | Consumed by |
|------|----------|------------|-------------|
| `fetch_hscm.py` | repo root | Manual (URL update) | `hes_shmi_gp_monthly.yml` |
| `kent-hscm-data.json` | repo root | `fetch_hscm.py` monthly | `nhs-pressure-map.html`, `winter-readiness.html`, `daily_refresh.py` |
| `kent-msoa.geojson` | repo root | One-time (ONS source) | `nhs-pressure-map.html` MSOA layer |
| `HSCM_BUILD_PLAN.md` | repo root | As needed | Reference |

---

## Workflow addition

Add to `hes_shmi_gp_monthly.yml` after the GP registration step:

```yaml
- name: Run KPHO HSCM data pipeline
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: python fetch_hscm.py
```

And add `kent-hscm-data.json` to the confirm outputs step:

```bash
for f in kent-hes-data.json kent-shmi-data.json kent-gp-reg-data.json \
          kent-ae-monthly.json kent-hscm-data.json kent-winter-data.json; do
```

---

## Evidence citations

- BGS (2024). Frailty Toolkit. British Geriatrics Society.
- KPHO (2026). Health and Social Care Maps V1.6. Kent Public Health Observatory / Kent County Council.
- ONS (2021). Census 2021 — unpaid carers, older adults living alone.
- BEIS / DLUHC (2023). Fuel poverty statistics.
- NHS Digital (2024). Quality and Outcomes Framework.
- KMCR (2025). Kent and Medway Care Record — disease prevalence data.
- PHE (2023). Cold Weather Plan for England.
