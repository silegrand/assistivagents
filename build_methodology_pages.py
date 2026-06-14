#!/usr/bin/env python3
"""
build_methodology_pages.py, Assistiv Cloud
Generates one rigorous methodology & rationale page per intelligence tool.

Each page follows the same scholarly structure:
  1. What this tool claims to do
  2. Rationale, why this matters in frailty epidemiology
  3. The data and the proxies (with justification for each)
  4. Method, how the score/output is constructed
  5. Signal weighting (where applicable, with real values)
  6. Strengths
  7. Weaknesses and honest caveats
  8. How to read the output responsibly
  9. Provenance & references

House style matched to methodology.html (Source Serif 4 / Cormorant / DM Mono,
the blue palette). Run from repo root: `python build_methodology_pages.py`
Outputs: method-<slug>.html for each tool, plus methodology-hub.html index.
"""

import html

PALETTE_CSS = """
:root{
  --forest:#0f2318; --forest-mid:#365EBF; --sage:#365EBF; --sage-mid:#2a4d9e;
  --sage-light:#7a9ee0; --sage-pale:#eef2fb; --cream:#eef2fb; --cream-mid:#dde5f5;
  --cream-dark:#c8d5ee; --amber:#365EBF; --amber-pale:#eef2fb; --ink:#1a2e1e;
  --ink-mid:#3d5245; --ink-muted:#6b7f71; --ink-dim:#9aaa9e; --white:#fff;
  --warn:#9e5412; --warn-pale:#fbf0e3;
  --mono:'DM Mono',monospace; --serif:'Source Serif 4',Georgia,serif;
  --display:'Cormorant Garamond',Georgia,serif; --tr:.18s ease;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--cream);color:var(--ink);font-family:var(--serif);
  line-height:1.75;-webkit-font-smoothing:antialiased}
nav{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(238,242,251,.96);
  backdrop-filter:blur(10px);border-bottom:1px solid var(--cream-dark);
  padding:0 2rem;height:54px;display:flex;align-items:center;justify-content:space-between}
.nav-home{font-family:var(--display);font-size:1rem;font-weight:600;
  color:var(--forest-mid);text-decoration:none;letter-spacing:-.01em}
.nav-right{display:flex;gap:1.5rem;align-items:center}
.nav-right a{font-family:var(--mono);font-size:.65rem;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-muted);text-decoration:none;transition:color var(--tr)}
.nav-right a:hover{color:var(--sage)}
.page{max-width:780px;margin:0 auto;padding:100px 2rem 6rem}
.eyebrow{font-family:var(--mono);font-size:.65rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--sage);margin-bottom:1rem}
.page-title{font-family:var(--display);font-size:clamp(2.2rem,4.5vw,3.4rem);
  line-height:1.05;color:var(--forest-mid);margin-bottom:1.1rem;font-weight:600}
.page-title em{font-style:italic;color:var(--sage)}
.lede{font-size:1.1rem;color:var(--ink-mid);line-height:1.7;margin-bottom:1.5rem}
.meta-bar{display:flex;flex-wrap:wrap;gap:1.5rem;padding:1rem 0;
  border-top:1px solid var(--cream-dark);border-bottom:1px solid var(--cream-dark);margin-bottom:2.5rem}
.meta-item{font-family:var(--mono);font-size:.62rem;color:var(--ink-dim);line-height:1.5}
.meta-item strong{color:var(--ink-muted);display:block;margin-bottom:.2rem;font-weight:500}
.badge{display:inline-block;font-family:var(--mono);font-size:.58rem;letter-spacing:.08em;
  text-transform:uppercase;padding:.2rem .55rem;border-radius:4px;font-weight:500}
.badge.live{background:rgba(45,107,71,.1);color:#2d6b47}
.badge.proto{background:var(--amber-pale);color:var(--warn)}
.badge.sim{background:var(--cream-mid);color:var(--ink-muted)}
section{margin-bottom:2.6rem}
h2{font-family:var(--display);font-size:1.7rem;font-weight:600;color:var(--forest-mid);
  margin-bottom:.9rem;letter-spacing:-.01em}
h3{font-family:var(--serif);font-size:1.05rem;font-weight:600;color:var(--ink);
  margin:1.4rem 0 .5rem}
p{margin-bottom:1rem;color:var(--ink-mid)}
.section-kicker{font-family:var(--mono);font-size:.58rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink-dim);margin-bottom:.6rem}
ul,ol{margin:0 0 1rem 1.2rem;color:var(--ink-mid)}
li{margin-bottom:.5rem}
.callout{background:var(--white);border:1px solid var(--cream-dark);border-left:3px solid var(--sage);
  border-radius:6px;padding:1.1rem 1.3rem;margin:1.3rem 0}
.callout.warn{border-left-color:var(--warn);background:var(--warn-pale)}
.callout .section-kicker{margin-bottom:.4rem}
.weight-table{width:100%;border-collapse:collapse;margin:1rem 0;font-size:.9rem}
.weight-table th{font-family:var(--mono);font-size:.6rem;letter-spacing:.06em;
  text-transform:uppercase;color:var(--ink-muted);text-align:left;padding:.5rem .6rem;
  border-bottom:2px solid var(--cream-dark);font-weight:500}
.weight-table td{padding:.55rem .6rem;border-bottom:1px solid var(--cream-mid);
  color:var(--ink-mid);vertical-align:top}
.weight-table td.w{font-family:var(--mono);font-size:.85rem;color:var(--sage);white-space:nowrap}
.pull{font-family:var(--display);font-size:1.5rem;font-style:italic;color:var(--sage);
  line-height:1.35;margin:1.6rem 0;padding-left:1.1rem;border-left:3px solid var(--sage-light)}
.ref{font-family:var(--mono);font-size:.72rem;color:var(--ink-muted);line-height:1.7}
.ref li{margin-bottom:.45rem}
.toolnav{display:flex;justify-content:space-between;gap:1rem;margin-top:3rem;
  padding-top:1.5rem;border-top:1px solid var(--cream-dark)}
.toolnav a{font-family:var(--mono);font-size:.65rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--sage);text-decoration:none}
.toolnav a:hover{color:var(--sage-mid)}
.crumb{font-family:var(--mono);font-size:.62rem;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-dim);margin-bottom:1.5rem}
.crumb a{color:var(--sage);text-decoration:none}
footer{background:var(--forest);color:rgba(255,255,255,.6);padding:2rem;text-align:center;
  font-family:var(--mono);font-size:.62rem;line-height:1.8}
footer a{color:var(--sage-light);text-decoration:none}
.hub-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:1rem;margin-top:1.5rem}
.hub-card{background:var(--white);border:1px solid var(--cream-dark);border-radius:8px;
  padding:1.2rem 1.3rem;text-decoration:none;display:block;transition:border-color var(--tr),transform var(--tr)}
.hub-card:hover{border-color:var(--sage-light);transform:translateY(-2px)}
.hub-card h3{font-family:var(--display);font-size:1.25rem;color:var(--forest-mid);margin:.3rem 0 .4rem}
.hub-card p{font-size:.85rem;margin-bottom:0;color:var(--ink-muted)}
@media(max-width:640px){.page{padding:80px 1.3rem 4rem}nav{padding:0 1rem}.nav-right{gap:.9rem}}
"""

FONT_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
  '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
  '<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400;1,600&'
  'family=DM+Mono:wght@400;500&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">')


def nav():
    return ('<nav><a class="nav-home" href="index.html">Assistiv Cloud</a>'
            '<div class="nav-right"><a href="index.html#tools">Tools</a>'
            '<a href="methodology.html">Master methodology</a>'
            '<a href="methodology-hub.html">Tool methods</a>'
            '<a href="index.html#contact">Contact</a></div></nav>')


def footer():
    """Compact footer for the per-tool method pages."""
    return ('<footer>Assistiv Systems Limited · Faversham, Kent · &copy; 2026<br>'
            'Methodology pages are for research and commissioning intelligence purposes only. '
            'Open data, no patient identifiers.<br>'
            '<a href="https://www.assistiv.co/governance.html">Governance</a> &middot; '
            '<a href="privacy.html">Privacy</a> &middot; '
            '<a href="methodology.html">Master methodology</a></footer>')


# Full homepage-style footer + its scoped CSS, for the hub page.
HOMEPAGE_FOOTER_CSS = """
footer.site{background:var(--white);padding:4rem 0 2.25rem;border-top:1px solid var(--cream-dark);
  text-align:left;font-family:var(--serif)}
footer.site a{color:var(--ink-mid)}
.footer-inner{max-width:1200px;margin:0 auto;padding:0 2rem}
.footer-top{display:grid;grid-template-columns:240px 1fr;gap:4rem;padding-bottom:3rem;
  border-bottom:1px solid var(--cream-dark);margin-bottom:2rem}
.footer-brand{display:flex;align-items:center;gap:.75rem;margin-bottom:.75rem}
.footer-tagline{font-size:.82rem;color:var(--ink-muted);line-height:1.75;max-width:220px}
.footer-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}
.footer-nav-col h5{font-family:var(--mono);font-size:.66rem;font-weight:500;letter-spacing:.18em;
  text-transform:uppercase;color:var(--sage);margin-bottom:1rem}
.footer-nav-col a{display:block;font-size:.82rem;color:var(--ink-mid);margin-bottom:.55rem;
  text-decoration:none;transition:color var(--tr)}
.footer-nav-col a:hover{color:var(--sage)}
.footer-bottom{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem}
.footer-copy{font-family:var(--mono);font-size:.65rem;color:var(--ink-dim);line-height:1.6}
.footer-links{display:flex;gap:1.5rem}
.footer-links a{font-size:.75rem;color:var(--ink-dim);text-decoration:none;transition:color var(--tr)}
.footer-links a:hover{color:var(--sage)}
@media(max-width:700px){.footer-top{grid-template-columns:1fr;gap:2rem}.footer-nav{grid-template-columns:repeat(2,1fr)}}
@media(max-width:480px){.footer-nav{grid-template-columns:1fr}.footer-bottom{flex-direction:column;text-align:center}}
"""

def homepage_footer():
    """Full footer matching www.assistiv.cloud homepage."""
    return ('<footer class="site"><div class="footer-inner"><div class="footer-top"><div>'
      '<div class="footer-brand">'
      '<div style="position:relative;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0">'
      '<div style="border-radius:50%;position:absolute;width:9px;height:9px;background:#365EBF;z-index:2"></div>'
      '<div style="border-radius:50%;position:absolute;width:20px;height:20px;border:1.5px solid #365EBF;opacity:.55;background:none"></div>'
      '<div style="border-radius:50%;position:absolute;width:33px;height:33px;border:1.5px solid #365EBF;opacity:.22;background:none"></div></div>'
      '<div style="display:flex;flex-direction:column;gap:2px">'
      '<span style="font-family:\'Cormorant Garamond\',serif;font-size:1.3rem;font-weight:600;letter-spacing:-.02em;line-height:1.1;color:#1e3a7a">Assistiv</span>'
      '<span style="font-family:\'DM Mono\',monospace;font-size:.5rem;letter-spacing:.18em;text-transform:uppercase;line-height:1;color:#365EBF;opacity:.85">Cloud</span></div></div>'
      '<p class="footer-tagline">Frailty intelligence for the NHS. Finding older adults at risk before the system has to respond.</p>'
      '<p style="font-size:.72rem;color:var(--ink-dim);margin-top:.75rem">Powered by Anthropic technologies</p></div>'
      '<div class="footer-nav">'
      '<div class="footer-nav-col"><h5>Platform</h5>'
      '<a href="index.html#tools">Tools</a><a href="index.html#how-it-works">How it works</a>'
      '<a href="index.html#evidence">Evidence</a><a href="datastatus.html">Data status</a>'
      '<a href="https://www.assistiv.co/governance.html" target="_blank" rel="noopener">Governance &amp; Assurance</a></div>'
      '<div class="footer-nav-col"><h5>Methodology</h5>'
      '<a href="methodology.html">Master methodology</a><a href="methodology-hub.html">Tool methods</a></div>'
      '<div class="footer-nav-col"><h5>Ecosystem</h5>'
      '<a href="https://www.assistiv.services" target="_blank" rel="noopener">assistiv.services</a>'
      '<a href="https://www.assistiv.tools" target="_blank" rel="noopener">assistiv.tools</a>'
      '<a href="https://www.assistiv.co" target="_blank" rel="noopener">assistiv.co</a></div></div></div>'
      '<div class="footer-bottom"><p class="footer-copy">&copy; 2026 Assistiv Systems Limited. '
      'Registered in England and Wales. Company number 17082597. Open Data: NHS Fingertips, NHSBSA EPD, '
      'ONS Census 2021, MHCLG IMD 2025. For research and commissioning intelligence purposes only.</p>'
      '<div class="footer-links"><a href="privacy.html">Privacy</a><a href="terms.html">Terms</a>'
      '<a href="accessibility.html">Accessibility</a></div></div></div></footer>')


def weight_table(rows):
    body = "".join(
        f'<tr><td>{html.escape(n)}</td><td class="w">{w}</td><td>{html.escape(j)}</td></tr>'
        for n, w, j in rows)
    return ('<table class="weight-table"><thead><tr><th>Signal / proxy</th>'
            f'<th>Default weight</th><th>Why it earns its place</th></tr></thead><tbody>{body}</tbody></table>')


def render(tool):
    secs = []
    secs.append(f'<div class="crumb"><a href="index.html">Cloud</a> / '
                f'<a href="methodology-hub.html">Tool methods</a> / {html.escape(tool["short"])}</div>')
    secs.append(f'<div class="eyebrow">{html.escape(tool["layer"])} &middot; Methodology &amp; rationale</div>')
    secs.append(f'<h1 class="page-title">{tool["title_html"]}</h1>')
    secs.append(f'<p class="lede">{tool["lede"]}</p>')
    badge_note = ('Live data feed; not yet outcome-validated'
                  if tool["badge"][0] == "live"
                  else 'Working prototype; not yet validated'
                  if tool["badge"][0] == "proto"
                  else 'Illustrative / simulated data')
    secs.append('<div class="meta-bar">'
                f'<div class="meta-item"><strong>Status</strong><span class="badge {tool["badge"][0]}">{tool["badge"][1]}</span>'
                f'<span style="display:block;margin-top:.35rem;color:var(--ink-dim)">{badge_note}</span></div>'
                f'<div class="meta-item"><strong>Live tool</strong><a href="{tool["url"]}" style="color:var(--sage);text-decoration:none">{tool["url"]} &#8599;</a></div>'
                f'<div class="meta-item"><strong>Geography</strong>{html.escape(tool["geo"])}</div>'
                f'<div class="meta-item"><strong>Refreshed</strong>{html.escape(tool["refresh"])}</div></div>')

    for s in tool["sections"]:
        secs.append('<section>')
        if s.get("kicker"):
            secs.append(f'<div class="section-kicker">{html.escape(s["kicker"])}</div>')
        secs.append(f'<h2>{html.escape(s["h"])}</h2>')
        secs.append(s["body"])
        secs.append('</section>')

    if tool.get("weights"):
        secs.append('<section><div class="section-kicker">Signal weighting</div>'
                    '<h2>What the model weights, and why</h2>'
                    f'<p>{tool["weights_intro"]}</p>' + weight_table(tool["weights"]) +
                    f'<p>{tool.get("weights_after","")}</p></section>')

    if tool.get("refs"):
        ref_items = "".join(f'<li>{r}</li>' for r in tool["refs"])
        secs.append(f'<section><div class="section-kicker">Provenance</div>'
                    f'<h2>Sources &amp; references</h2><ul class="ref">{ref_items}</ul></section>')

    secs.append('<div class="toolnav">'
                '<a href="methodology-hub.html">&#8592; All tool methods</a>'
                f'<a href="{tool["url"]}">Open the live tool &#8599;</a></div>')

    return (f'<!DOCTYPE html><html lang="en-GB"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
            f'<title>{html.escape(tool["short"])}, Methodology · Assistiv Cloud</title>'
            f'<meta name="description" content="{html.escape(tool["meta"])}">'
            f'{FONT_LINK}<style>{PALETTE_CSS}</style></head><body>'
            f'{nav()}<div class="page">{"".join(secs)}</div>{footer()}</body></html>')


# ─────────────────────────────────────────────────────────────────────────
# TOOL CONTENT, written as frailty methodology, grounded in each tool's real data
# ─────────────────────────────────────────────────────────────────────────

TOOLS = []

# 1. FEP heat map
TOOLS.append({
  "slug": "fep-heatmap",
  "short": "Frailty Heat Map",
  "layer": "Layer 2",
  "badge": ("live", "Live"),
  "url": "layer2-map-pdf.html",
  "geo": "13 Kent & Medway districts",
  "refresh": "Daily via GitHub Actions",
  "title_html": 'The Frailty Heat Map, <em>explained.</em>',
  "meta": "Rationale and methodology for the Assistiv Frailty Emergence Probability heat map.",
  "lede": "The heat map is the public face of the Frailty Emergence Probability (FEP) engine: a daily, district-level estimate of where emerging frailty is concentrating across Kent and Medway, built entirely on open data with no patient identifiers.",
  "sections": [
    {"kicker":"What it claims","h":"What this tool does, and what it does not",
     "body":"<p>The heat map renders a single composite FEP score per district on a colour scale, alongside the economic cost of inaction, discharge-delay intelligence and prescribing signals. It is a <strong>population-level prioritisation instrument</strong>: it answers the commissioner's question, \"of my thirteen districts, where should I look first?\"</p>"
       "<p>It is explicitly not a clinical tool. It does not score individuals, it does not diagnose, and it does not replace the Electronic Frailty Index (eFI) that every GP system already runs. The eFI tells you where an identified patient sits today; the heat map tells you which <em>populations</em> are drifting toward crisis, and how fast.</p>"},
    {"kicker":"Rationale","h":"Why a population frailty signal is needed at all",
     "body":"<p>Frailty is the strongest predictor of avoidable admission, long length of stay and delayed discharge in older adults, yet it is identified almost entirely reactively, at the front door of the hospital, after the event the system most wanted to prevent. Every Primary Care Network in England is contractually required to identify and manage frailty under the Directed Enhanced Service, but no commissioned tool covers the space <em>between</em> appointments and <em>ahead</em> of presentation.</p>"
       "<p>That gap is the rationale. A daily, open-data population signal lets a system act on geography before it has to act on a person in an ambulance.</p>"},
    {"kicker":"Method","h":"How the composite is built",
     "body":"<p>Each contributing signal is normalised to a 0–100 scale <em>within signal</em>, against England averages as the comparator, so that a district's score expresses relative standing rather than a raw count. Normalised signals are then combined as a weighted sum and the result is itself rescaled across the thirteen districts for display. Because both the inputs and the output are relative, the map is a ranking instrument first and an absolute-risk instrument second, a distinction we return to under weaknesses.</p>"
       "<p>The live engine ingests a broad signal set (the index page describes 21 signals across NHS Fingertips outcomes, NHSBSA prescribing data and ONS synthetic measures). The interactive configurator exposes a deliberately smaller, commissioner-adjustable six-signal model so that a non-technical user can see how the ranking moves as priorities change. Both are legitimate; they trade completeness against transparency.</p>"},
    {"kicker":"Reading it well","h":"How to read the output responsibly",
     "body":"<ul><li><strong>Read rank, not decimal.</strong> A district at 61 versus 58 is a meaningful ordering signal; treating the three-point gap as a precise quantity is not supported by the uncertainty in the inputs.</li>"
       "<li><strong>Read it alongside the trajectory.</strong> A high but stable district may be already known to services; a mid-ranking district climbing quickly is the more actionable finding.</li>"
       "<li><strong>Treat it as a hypothesis generator.</strong> The map tells you where to send a human to look, not what they will find.</li></ul>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Ecological inference.</strong> District-level signals describe places, not people. A district can score high because of a concentrated pocket of need that the average obscures, which is precisely why the Rural Access Vulnerability Index exists to drill below it.</p>"
       "<p><strong>Proxy drift.</strong> Several inputs are proxies (prescribing as a marker of clinical frailty, deprivation as an amplifier). Proxies can move for reasons unrelated to frailty, a formulary change, a coding shift, and the composite cannot tell the difference on its own.</p>"
       "<p><strong>Weight subjectivity.</strong> The default weights encode a defensible but contestable clinical prior. We expose them precisely so they can be argued with rather than trusted blindly.</p>"
       "<p><strong>Lag asymmetry.</strong> Some signals refresh daily, others monthly or annually, so the composite blends data of different vintages. The map is current to its <em>slowest</em> meaningful input, not its fastest.</p></div>"},
  ],
  "weights": [
    ("Over-75s living alone", "25%", "Strongest single demographic frailty proxy; isolation compounds every other risk. ONS Census 2021."),
    ("Unplanned admissions rate", "20%", "Outcome signal, a district already on a crisis trajectory. NHS Fingertips."),
    ("Polypharmacy prevalence (5+ meds)", "20%", "Well-validated clinical frailty marker available at population scale. NHSBSA dispensing."),
    ("Deprivation (IMD)", "15%", "Access and vulnerability amplifier; modifies how quickly risk converts to crisis. MHCLG."),
    ("DWP Attendance Allowance", "10%", "Functional-limitation indicator independent of health-service contact. DWP geographic data."),
    ("Care-home capacity gap", "10%", "High need against low provision marks where the system has least slack. CQC register + population ratio."),
  ],
  "weights_intro": "These are the defaults exposed by the interactive configurator. They are a starting clinical prior, not a fixed truth, every weight is adjustable, and the ranking recomputes live so a commissioner can test their own assumptions.",
  "weights_after": "The choice to make over-75s-living-alone the heaviest single weight reflects the consistent finding that social isolation is both an independent risk and a multiplier of clinical risk; the choice to cap any single signal well below 50% reflects a deliberate refusal to let one proxy dominate the composite.",
  "refs": [
    "Clegg A et al. Development and validation of an electronic frailty index using routine primary care data. Age and Ageing, 2016.",
    "British Geriatrics Society. Fit for Frailty: consensus best-practice guidance. 2014/2015.",
    "NICE. Quality standard QS86: Mental wellbeing and independence in older people.",
    "Lancet Commission on Dementia Prevention, Intervention and Care, 2024.",
    "MHCLG. English Indices of Deprivation 2025; ONS Census 2021; NHS Fingertips; NHSBSA English Prescribing Dataset.",
  ],
})

# 2. FEP configurator
TOOLS.append({
  "slug": "fep-configurator",
  "short": "FEP Configurator",
  "layer": "Layer 2 · scoring engine",
  "badge": ("live", "Live"),
  "url": "layer2-fep-light.html",
  "geo": "18 Kent PCN zones (illustrative)",
  "refresh": "Recomputes live on weight change",
  "title_html": 'The FEP Configurator, <em>opened up.</em>',
  "meta": "Why the FEP scoring engine exposes adjustable weights, and how to use them honestly.",
  "lede": "The configurator is the FEP engine with the lid off. It lets a commissioner move all twenty-one signal weights and watch the district ranking recompute in real time, a deliberate act of methodological transparency.",
  "sections": [
    {"kicker":"Rationale","h":"Why expose the weights at all",
     "body":"<p>Most risk-stratification products hide their weighting behind a proprietary wall and ask to be trusted. We take the opposite view: in a public-sector context, a score that cannot be interrogated should not move public money. Exposing the weights converts the model from an oracle into an argument, one a commissioner can win, lose, or amend.</p>"
       "<p>It also surfaces the single most important truth about any composite index: <em>the ranking is a function of the weights</em>. Two reasonable people with different clinical priors will produce different maps from identical data, and they should be able to see exactly where and why they diverge.</p>"},
    {"kicker":"Method","h":"What the sliders actually do",
     "body":"<p>Each signal is pre-normalised 0–100 within signal. The configurator computes a weighted sum, renormalises across zones and re-ranks. An uncertainty flag is attached to any zone whose ordering would flip under a small perturbation of the weights, a direct, visible expression of how robust each placement is.</p>"
       "<p>The built-in Ada explainer narrates the effect of a change in plain English, so that the consequence of a weighting decision is legible to a non-statistician.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Freedom is double-edged.</strong> The same adjustability that makes the model honest also lets a user engineer a ranking to fit a predetermined conclusion. The uncertainty flags are a partial guard, but the tool assumes good faith.</p>"
       "<p><strong>Illustrative zones.</strong> The configurator runs on a set of realistic Kent PCN zones for demonstration; the production heat map runs on the full live district data. The configurator teaches method; it is not the operational scoreboard.</p>"
       "<p><strong>Weights are not effect sizes.</strong> A 25% weight does not mean the signal causes 25% of frailty. It is an analyst's statement of relative importance, not an epidemiological coefficient.</p></div>"},
  ],
  "refs": [
    "Clegg A et al. Electronic frailty index. Age and Ageing, 2016.",
    "OHID Public Health Outcomes Framework; NHSBSA English Prescribing Dataset.",
    "Saltelli A et al. Sensitivity analysis practices. (On the duty to test composite indices against weight perturbation.)",
  ],
})

# 3. RAVI
TOOLS.append({
  "slug": "ravi",
  "short": "Rural Access Vulnerability Index",
  "layer": "Layer 2 · LSOA hotspots",
  "badge": ("live", "Live"),
  "url": "rural-access-vulnerability.html",
  "geo": "1,065 Kent & Medway LSOAs",
  "refresh": "On source data release",
  "title_html": 'Rural Access Vulnerability, <em>justified.</em>',
  "meta": "Why district-level frailty scores miss rural need, and how RAVI recovers it at LSOA level.",
  "lede": "RAVI exists because averages lie about the countryside. A district can look unremarkable while containing settlements where an isolated, car-dependent older population is acutely vulnerable. RAVI drills to the 1,065 LSOAs beneath the district to find them.",
  "sections": [
    {"kicker":"Rationale","h":"The problem RAVI solves",
     "body":"<p>District-level scoring is an ecological compromise: it is stable and commissioner-friendly, but it averages away the very concentrations of need that early intervention most wants to find. In rural Kent, a single village of older, isolated, poorly-connected residents disappears inside a district that also contains a prosperous market town.</p>"
       "<p>RAVI restores that detail by scoring at Lower-layer Super Output Area level, roughly 1,500 residents, and by weighting specifically the dimensions that make rural frailty dangerous: distance, isolation and the absence of a car.</p>"},
    {"kicker":"Proxies","h":"Why these proxies, and not others",
     "body":"<p>The geographic barriers sub-domain of IMD is used in its rural-enhanced October 2025 form precisely because the standard IMD under-weights road distance, the thing that most determines whether a frail rural resident can reach a GP or pharmacy. Car access is included as a separate signal because a long distance is survivable with a vehicle and dangerous without one; the interaction matters more than either alone. Limiting long-term illness and the 65+ share anchor the index to a genuinely older, genuinely vulnerable population rather than merely a remote one.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Census vintage.</strong> Car access and long-term-illness measures rest on the 2021 Census; rural populations change, and the data ages between censuses.</p>"
       "<p><strong>Distance is modelled, not travelled.</strong> Road distance to a service is not the same as real journey time on rural bus timetables. RAVI will understate vulnerability where physical distance is short but public transport is absent.</p>"
       "<p><strong>Small-area noise.</strong> The smaller the geography, the noisier the estimate. An LSOA hotspot is a strong prompt to investigate, not a confirmed finding.</p></div>"},
  ],
  "refs": [
    "MHCLG. English Indices of Deprivation 2025, Geographic Barriers sub-domain (rural-enhanced, October 2025).",
    "ONS. 2021 Rural Urban Classification; Census 2021 via Nomis.",
    "Bynner C et al. On ecological fallacy in small-area deprivation analysis.",
  ],
})

# 4. CBI x FEP quadrant
TOOLS.append({
  "slug": "cbi-fep",
  "short": "FEP × Carer Burden Quadrant",
  "layer": "Layer 2 · dual intelligence",
  "badge": ("live", "Live"),
  "url": "cbi-fep-map.html",
  "geo": "13 Kent & Medway districts",
  "refresh": "Daily (FEP) + on release (CBI)",
  "title_html": 'Frailty <em>and</em> carer burden, together.',
  "meta": "Why overlaying carer burden on frailty risk identifies the most urgent intervention targets.",
  "lede": "Frailty rarely fails alone. Behind most frail older adults is a carer whose own capacity is finite, and when both systems are under strain simultaneously, the risk of sudden collapse is highest. This quadrant tool finds the districts where patient and carer pressure coincide.",
  "sections": [
    {"kicker":"Rationale","h":"Why carer burden belongs on the same axis as frailty",
     "body":"<p>Informal carers are the invisible infrastructure of community frailty. When a carer breaks down, through illness, exhaustion or their own ageing, the person they support can convert from stable to crisis within days. A frailty signal that ignores the carer system therefore misses one of the most powerful predictors of imminent admission.</p>"
       "<p>Plotting FEP against a Carer Burden Index on a quadrant makes the interaction visible. The top-right quadrant, high frailty <em>and</em> high carer burden, is where preventative investment buys the most avoided crises.</p>"},
    {"kicker":"Method","h":"How the quadrant is constructed",
     "body":"<p>Each district receives two scores. FEP is the population frailty composite described in the master methodology. The Carer Burden Index is built from open proxies for the prevalence and intensity of informal care and for the carer population's own vulnerability. Districts are placed on the two axes and the quadrant boundaries are set at the cohort medians, so the classification is relative to Kent and Medway rather than to a national absolute.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Carer data is the weakest open signal.</strong> Informal care is chronically under-recorded; many carers never identify as such to any system. The CBI is therefore the most proxy-dependent index in the suite and should carry the widest uncertainty in the reader's mind.</p>"
       "<p><strong>Median boundaries are arbitrary by construction.</strong> A district just inside the high-burden quadrant and one just outside it are barely distinguishable; the quadrant is a communication device, not a hard threshold.</p>"
       "<p><strong>Two relative scores compound relativity.</strong> Both axes are normalised within the cohort, so the tool describes Kent against itself and says nothing about how Kent compares nationally.</p></div>"},
  ],
  "refs": [
    "Carers UK. State of Caring surveys (on systematic under-identification of informal carers).",
    "NICE NG150. Supporting adult carers.",
    "ONS Census 2021, provision of unpaid care.",
  ],
})

# 5. Reachable Neighbourhoods
TOOLS.append({
  "slug": "reachable-neighbourhoods",
  "short": "Reachable Neighbourhoods",
  "layer": "Layer 2 → 3",
  "badge": ("live", "Live"),
  "url": "reachable-neighbourhoods.html",
  "geo": "17 named neighbourhoods (~7,500 residents each)",
  "refresh": "On source data release",
  "title_html": 'From district to <em>doorstep.</em>',
  "meta": "How the shortlist drills below district scores to name the neighbourhoods outreach teams should reach first.",
  "lede": "A district score tells a commissioner where to care. It does not tell an outreach worker where to park the van. Reachable Neighbourhoods bridges that gap, ranking 17 named neighbourhoods by the factors that determine whether outreach will actually find the Missing Middle.",
  "sections": [
    {"kicker":"Rationale","h":"Why a second, finer geography is necessary",
     "body":"<p>The journey from intelligence to action fails most often at the last mile. A commissioner accepts that a district is high-risk, but the team tasked with screening has no basis for choosing one neighbourhood over another. This tool exists to make that operational decision defensible, ranking neighbourhoods of around 7,500 residents by deprivation, solo living, access and, distinctively, three-month prescribing velocity.</p>"},
    {"kicker":"Proxies","h":"Why prescribing velocity earns its place",
     "body":"<p>Most signals describe a static state. Three-month prescribing velocity describes <em>change</em>: a neighbourhood where dispensing of frailty-associated medications is accelerating is a neighbourhood where need is emerging now, not historically. This is the trajectory principle applied at neighbourhood scale, and it is what lets the shortlist point teams at need that district-level snapshots have not yet caught up with.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Velocity is volatile.</strong> Short windows amplify noise; a three-month prescribing spike can reflect a single practice's coding behaviour rather than a real population shift. The signal is a prompt, not proof.</p>"
       "<p><strong>Named neighbourhoods invite over-confidence.</strong> Putting a real place-name on a card makes the analysis feel more certain than the underlying small-area data warrants.</p>"
       "<p><strong>Coverage is partial.</strong> Seventeen neighbourhoods is a shortlist, not a census of need; absence from the list is not evidence of safety.</p></div>"},
  ],
  "refs": [
    "NHSBSA English Prescribing Dataset (practice-level, monthly).",
    "MHCLG IMD 2025; ONS Census 2021 via Nomis.",
    "Public Health England. Productive Healthy Ageing profiles.",
  ],
})

# 6. Community Touchpoints
TOOLS.append({
  "slug": "community-touchpoints",
  "short": "Community Touchpoints",
  "layer": "Layer 3",
  "badge": ("live", "Live"),
  "url": "community-touchpoints.html",
  "geo": "Priority zones, Kent & Medway",
  "refresh": "NHS API + OpenStreetMap",
  "title_html": 'Meeting people <em>where they already are.</em>',
  "meta": "Why effective frailty outreach maps to existing community assets rather than building new ones.",
  "lede": "The Missing Middle do not attend health services, that is what makes them missing. Community Touchpoints maps the GP surgeries, pharmacies, libraries, faith communities and voluntary organisations that this population already visits, so outreach goes to them.",
  "sections": [
    {"kicker":"Rationale","h":"Why assets, not appointments",
     "body":"<p>A screening programme that waits for people to come to it will, by definition, miss the people who do not come. The evidence from social prescribing is unambiguous: older adults at risk are reachable through the trusted, non-clinical places they already use. Mapping those assets within a priority zone turns an abstract \"high-risk district\" into a concrete list of places to set up a conversation.</p>"},
    {"kicker":"Method","h":"How touchpoints are identified",
     "body":"<p>Locations are drawn from the NHS API (for GP surgeries and pharmacies) and OpenStreetMap (for libraries, community centres, faith venues and VCSE organisations), filtered to the priority zones produced by the upstream layers. The output is an outreach-planning map, not a directory: its job is to help a team decide where presence will yield contact.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>OpenStreetMap is uneven.</strong> Crowd-sourced data is excellent in some areas and sparse in others; an absent touchpoint may reflect missing map data rather than a genuine community gap.</p>"
       "<p><strong>Presence is not footfall.</strong> The map shows where assets are, not how many at-risk older adults actually use them. Local knowledge must complete the picture.</p>"
       "<p><strong>No quality signal.</strong> A mapped VCSE organisation may be thriving or dormant; the tool cannot distinguish them.</p></div>"},
  ],
  "refs": [
    "NHS England. Social prescribing and community-based support: summary guide.",
    "NHS Service Search API; OpenStreetMap contributors (ODbL).",
    "Polley M et al. Evidence on social prescribing and frailty.",
  ],
})

# 7. NHS Pressure Intelligence Map
TOOLS.append({
  "slug": "nhs-pressure",
  "short": "NHS Pressure Intelligence Map",
  "layer": "Layer 2 · system pressure",
  "badge": ("live", "Live"),
  "url": "nhs-pressure-map.html",
  "geo": "13 districts · 4 acute trusts",
  "refresh": "Monthly (corridor, SHMI, HES) + daily (FEP)",
  "title_html": 'Where demand <em>meets</em> capacity.',
  "meta": "How the pressure map joins Missing-Middle risk to acute-system strain, by district and by trust.",
  "lede": "Frailty risk is only half the story; the other half is whether the local acute system has any slack to absorb it. This map joins district frailty to four NHS open data sources on system pressure, and offers a second lens that recolours the map by the hospital trust actually serving each area.",
  "sections": [
    {"kicker":"Rationale","h":"Why pressure and risk belong on one map",
     "body":"<p>A high-frailty district served by a resilient hospital is a different commissioning problem from an identical district served by a trust already in corridor care. Demand-side intelligence (who is getting frail) is only actionable alongside supply-side intelligence (whether the system can cope). Joining them shows commissioners where unmet need and system strain converge, the points of greatest leverage and greatest danger.</p>"},
    {"kicker":"Method","h":"Two honest lenses",
     "body":"<p><strong>District pressure</strong> shades each district by its frailty signal, preserving the granular FEP detail that is Assistiv's distinctive contribution. <strong>Hospital systems</strong> recolours the map by acute trust catchment, scoring each trust on corridor-care intensity, SHMI mortality banding and 65+ emergency admissions per 1,000 registered 75-and-overs, a demand-adjusted rate that is fair between large and small trusts. Catchments are aligned to predominant acute patient flows; the tool states openly that boundary areas overlap in practice.</p>"
       "<p>Unknown inputs score the moderate midpoint rather than penalising a trust for data it has not yet published, a deliberate choice to avoid manufacturing false reassurance from missing data.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Catchments are approximations.</strong> Real patient flows cross every boundary; the hospital lens is a planning aid, not a statement of where any individual will be treated.</p>"
       "<p><strong>Mixed vintages.</strong> Corridor care, SHMI and admissions publish monthly or annually while FEP updates daily, so the composite blends data of different ages.</p>"
       "<p><strong>Corridor care is experimental.</strong> The corridor-care definition was introduced in March 2026 and remains an experimental statistic; early data should be read as indicative.</p></div>"},
  ],
  "refs": [
    "NHS England. Corridor Care monthly publication (experimental statistics, 2026).",
    "NHS England. Summary Hospital-level Mortality Indicator (SHMI).",
    "NHS England. Hospital Episode Statistics, emergency admissions.",
    "NHSBSA; ONS GP registration data.",
  ],
})

# 8. Winter Readiness
TOOLS.append({
  "slug": "winter-readiness",
  "short": "Winter Readiness Intelligence",
  "layer": "2026-27 planning",
  "badge": ("live", "Live"),
  "url": "winter-readiness.html",
  "geo": "13 Kent districts",
  "refresh": "Live NHS data",
  "title_html": 'Planning for the <em>predictable</em> crisis.',
  "meta": "Why a forward-looking, multi-component winter vulnerability index helps commissioners act before the season turns.",
  "lede": "Winter pressure is the most predictable crisis in the health calendar, yet it is planned for reactively almost every year. This tool produces a forward-looking Winter Vulnerability Index across five components, pairing NICE-evidenced interventions with a modelled estimate of when each is best deployed.",
  "sections": [
    {"kicker":"Rationale","h":"Why a dedicated winter index",
     "body":"<p>Cold weather converts manageable frailty into admission through a well-understood chain: cold homes, respiratory illness, falls on ice, and the seasonal collapse of informal care networks over the holidays. Because the mechanism is predictable and the interventions are evidenced, winter is the clearest case where acting on a forecast beats reacting to an outcome.</p>"},
    {"kicker":"Method","h":"Five components, forward-looking",
     "body":"<p>The index scores each district across frailty load, seasonal amplifiers, prescribing signals, system headroom and social isolation. Crucially it is <em>forward-looking</em>, built to inform deployment before the season rather than to describe it afterward. Each high-risk district carries a suggested intervention window: the interventions themselves are NICE-evidenced, while the timing of the window is a modelling inference from the seasonal pattern, not an empirically established optimum. It is a planning prompt, not a clinical instruction.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Forecasts inherit weather uncertainty.</strong> The index models seasonal risk structurally; it cannot predict the severity of a given winter, and a mild season will make it look over-cautious in hindsight.</p>"
       "<p><strong>Component weighting is a planning judgement.</strong> The relative weight of, say, cold-home risk versus system headroom is a defensible prior, not an empirical constant.</p>"
       "<p><strong>System headroom is the hardest component to measure openly.</strong> Capacity data lags and is incomplete, so this component carries the most uncertainty.</p></div>"},
  ],
  "refs": [
    "NICE NG6. Excess winter deaths and illness and the health risks associated with cold homes.",
    "UKHSA. Cold Weather Plan / Adverse Weather and Health Plan.",
    "NHS England. Winter planning guidance.",
  ],
})

# 9. Voice-First Frailty Screen (Layer 4 bridge to assistiv.tools)
TOOLS.append({
  "slug": "voice-screen",
  "short": "Voice-First Frailty Screen",
  "layer": "Layer 4 · screening",
  "badge": ("proto", "Prototype"),
  "url": "https://www.assistiv.tools",
  "geo": "Any community setting",
  "refresh": "Per conversation",
  "title_html": 'The screen that <em>listens.</em>',
  "meta": "Why a conversational, voice-first frailty screen captures what standardised forms miss.",
  "lede": "The screening layer is where population intelligence meets a person. It is deliberately a conversation, not a form, twelve questions across six life domains, scored against validated instruments in real time, with the district's own FEP score used to calibrate the referral threshold.",
  "sections": [
    {"kicker":"Rationale","h":"Why conversation beats the clipboard",
     "body":"<p>Older adults systematically under-report difficulty, for two well-documented reasons: the fear of being a burden, and the fear of what honest disclosure might trigger. A tick-box form gives that minimisation nowhere to surface. A conversation that listens to <em>how</em> something is said, hesitation, qualification, the things skirted around, can detect the gap between what is reported and what is true.</p>"
       "<p>This is not a soft preference. It is consistent with emerging evidence that subjective signals carry real predictive weight: a 2025 study in Geriatric Nursing testing nine machine-learning models found that self-reported experience (pain, mood, functional confidence) predicted frailty at least as well as objective physical measures. A single study does not settle the question, but it points the same way as the clinical rationale, that what a standardised form cannot elicit may be exactly what matters most.</p>"},
    {"kicker":"Method","h":"Validated instruments, invisibly embedded",
     "body":"<p>PRISMA-7 and the FRAIL Scale are mapped across the twelve questions and scored in real time, so the person experiences a natural conversation while the system produces a defensible clinical score. The upstream district FEP score is injected as context: in higher-risk districts the referral threshold is lowered, reflecting a higher prior probability of genuine need. The output is three things from one conversation, a Wellness Guide for the person, a structured referral for the frailty team, and, with explicit consent only, an anonymised population signal.</p>"},
    {"kicker":"Honesty","h":"Weaknesses and honest caveats",
     "body":"<div class=\"callout warn\"><div class=\"section-kicker\">Stated limitations</div>"
       "<p><strong>Prototype, not validated instrument.</strong> The screen is a working prototype grounded in validated frameworks; it has not yet been formally validated against those instruments in a published community study. That study is the necessary next step.</p>"
       "<p><strong>Interpretation by a language model carries risk.</strong> Detecting minimisation is the tool's strength and its hazard: it must be tested adversarially against minimisers, cognitive impairment, hearing difficulty and carers answering over the person before it can be trusted at scale.</p>"
       "<p><strong>Threshold calibration by FEP is a design choice.</strong> Lowering the referral bar in high-FEP districts is clinically defensible but will, by construction, generate more referrals there, a feature that must be matched by downstream capacity.</p></div>"},
  ],
  "refs": [
    "Raîche M et al. PRISMA-7, case-finding for frailty in community-dwelling older adults.",
    "Morley JE et al. The FRAIL scale. J Nutr Health Aging.",
    "Zhang et al. Explainable machine learning for frailty prediction. Geriatric Nursing, 2025. DOI:10.1016/j.gerinurse.2024.10.025.",
    "British Geriatrics Society. Fit for Frailty.",
  ],
})


def build_hub():
    cards = "".join(
        f'<a class="hub-card" href="method-{t["slug"]}.html">'
        f'<span class="badge {t["badge"][0]}">{t["badge"][1]}</span>'
        f'<h3>{html.escape(t["short"])}</h3>'
        f'<p>{html.escape(t["layer"])}</p></a>'
        for t in TOOLS)
    return (f'<!DOCTYPE html><html lang="en-GB"><head><meta charset="UTF-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1.0">'
            f'<title>Tool methodologies · Assistiv Cloud</title>'
            f'<meta name="description" content="Per-tool rationale and methodology for every Assistiv Cloud intelligence tool.">'
            f'{FONT_LINK}<style>{PALETTE_CSS}{HOMEPAGE_FOOTER_CSS}</style></head><body>{nav()}<div class="page">'
            f'<div class="eyebrow">Methodology &amp; rationale</div>'
            f'<h1 class="page-title">How each tool <em>works</em>, and where it doesn\'t.</h1>'
            f'<p class="lede">Every intelligence tool in the Assistiv Cloud suite has a dedicated methodology page: '
            f'the rationale, the data and proxies with justification, the method, the signal weights where they apply, '
            f'and, stated plainly, the weaknesses. A score that cannot be interrogated should not move public money.</p>'
            f'<div class="callout"><div class="section-kicker">Start here</div>'
            f'<p>For the cross-cutting methodology, the FEP composite, normalisation, the economic model and overall '
            f'limitations, see the <a href="methodology.html" style="color:var(--sage)">master methodology</a>. '
            f'The pages below go deeper on each individual tool.</p></div>'
            f'<div class="callout warn"><div class="section-kicker">One honest caveat, stated once</div>'
            f'<p>Every tool below is built the same way: open public data is turned into <em>proxies</em> for frailty '
            f'(prescribing, deprivation, isolation, access), those proxies are combined as a weighted sum, and the '
            f'result is ranked relative to the other Kent and Medway districts. This is a deliberate, defensible design, '
            f'but it means two things a reader should hold in mind on every page. First, the uncertainty <em>compounds</em>: '
            f'each proxy is imperfect, and stacking several into one composite can move a ranking more than any single '
            f'"stated limitation" box suggests in isolation. Second, the engine is <em>not yet validated against observed '
            f'outcomes</em>, so the figures it produces are modelled, not measured. The "Live" badge means the data feed '
            f'updates automatically; it does not mean a tool has been formally validated. Closing that gap, by scoring each '
            f'month of predictions against what actually happens when lagged NHS outcomes publish, is the active priority, '
            f'and these pages will say so plainly until it is done.</p></div>'
            f'<p style="font-family:var(--mono);font-size:.62rem;color:var(--ink-muted);line-height:1.9;margin-bottom:.5rem">'
            f'<span class="badge live">Live</span> live data feed, not yet outcome-validated &nbsp;&middot;&nbsp; '
            f'<span class="badge proto">Prototype</span> working prototype, not yet validated &nbsp;&middot;&nbsp; '
            f'<span class="badge sim">Simulation</span> illustrative or simulated data</p>'
            f'<div class="hub-grid">{cards}</div></div>{homepage_footer()}</body></html>')


if __name__ == "__main__":
    written = []
    for t in TOOLS:
        fn = f'method-{t["slug"]}.html'
        with open(fn, "w") as f:
            f.write(render(t))
        written.append(fn)
    with open("methodology-hub.html", "w") as f:
        f.write(build_hub())
    written.append("methodology-hub.html")
    print("Wrote:")
    for w in written:
        print(" ", w)
