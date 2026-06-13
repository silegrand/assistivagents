# Assistiv Systems — Strategic Roadmap

> A working handoff document. Captures the concept review and the five priority
> moves identified in June 2026. Pick up from here in any future session.
> Status markers: `[ ]` not started · `[~]` in progress · `[x]` done.

---

## Where Assistiv stands (June 2026)

Four-platform closed-loop ecosystem for the "Missing Middle" — older adults with
emerging frailty, living at home, not yet eligible for formal care, invisible to
existing pathways until crisis.

- **assistiv.co** — corporate front door, the concept and the case
- **assistiv.cloud** — population intelligence (FEP engine, 9 tools, live NHS open data)
- **assistiv.tools** — community frailty screening (voice-first, 12 questions, 6 domains)
- **assistiv.services** — preventative care platform (Triple Tap, Inner Circle, passive sensing)

The closed-loop framing is the core strategic insight: intelligence without
screening finds no one; screening without intervention creates wait-lists;
intervention without feedback never improves. The loop is the product.

---

## Honest position: between "working prototype" and "scalable business"

The concept is sound, the execution credible, the problem real and evidenced
(Lancet Commission 2024, NICE, BGS). The gap is **proof at scale**. Roughly
6–12 months of focused work converts concept into a fundable, commissionable
proposition.

### Gaps investors will see
1. No observed outcomes data — the 14:1 ROI is modelled, not measured.
2. Referral pathway (Layer 5) incomplete — screening with nowhere to refer
   creates clinical friction; this is the lynch-pin.
3. Services funding model (Layer 6) unstated — who pays? ICB prevention budget,
   housing association, private pay, social prescribing?
4. No published validation of own tools against standard instruments.
5. Go-to-market vague — what is the commercial unit and who signs?

### Gaps NHS will see
1. One geography proven (Kent & Medway), scalability unproven elsewhere.
2. No deployed clinical champion — advisors, not users on the record.
3. Referral outcomes unmeasured — what happens after a referral is produced?
4. Team thin for enterprise delivery — two technical founders + academic advisors.
5. Regulatory status (MHRA SaMD) unstated.

---

## The five priority moves

### 1. Make the FEP falsifiable — THE BACKTEST  `[ ]`  ★ do first
The single highest-leverage move. Every "modelled" weakness traces to one word.
The validation study needed for investors is **already in the git history**.

- The FEP engine makes implicit daily predictions; `history/` has been committing
  daily snapshots for months.
- Freeze each month's FEP scores as a formal forecast. Score against what
  actually happened when lagged outcomes publish (falls admissions, emergency
  admissions, Fingertips indicators arriving 3–6 months later).
- Publish accuracy openly — Brier scores, hit rates, calibration curves, misses
  included.
- The genius is the posture: not "trust our model" but "here is our model tested
  in public, monthly, against reality."
- Converts "14:1 modelled" into "validated against N months of observed outcomes"
  using only open data. No pilot, no patients, no ethics approval, no budget.
- VERA evolves from disclaimer into a verdict engine.
- **Effort: days, not months. Materials already exist in the commit log.**

### 2. Ship the derivative, not the level — TRAJECTORY  `[ ]`
"The eFI tells you where someone *is*; Assistiv tells you which direction a
population is *travelling*." The product still mostly ships levels.

- "Thanet 61" is broadly known. "Swale deteriorated 8 points in 90 days while
  prescribing velocity doubled" is something **only Assistiv can produce** — it
  needs a daily time series nobody else holds.
- Velocity and acceleration are the actual moat, deepening every day the
  workflows run.
- Make trajectory the headline: deterioration leaderboard, threshold-crossing
  alerts, per-district forecast cone.
- The dataset compounds; the level does not.

### 3. Make the person the API — PORTABLE OUTPUT  `[ ]`
The graveyard of NHS startups is integration. Invert it.

- Screening output already belongs to the person (consent architecture).
- Make it genuinely portable: a clean PDF **plus a structured FHIR bundle** the
  person can hand to any GP in the country.
- No integration contract, no DTAC negotiation up front, no waiting for ICB
  data-sharing agreements. The citizen carries their own referral across the
  boundary — GDPR-native.
- Every GP who receives one becomes a warm lead. Routes around the single
  biggest structural barrier in NHS tech.

### 4. Red-team Margaret before anyone meets her — SYNTHETIC SAFETY  `[ ]`
Aim the adversarial red-teaming method (previously used on Reason to Stay) at the
screening tool, industrially.

- Synthetic cohort as test personas: the minimiser; early cognitive decline;
  hearing difficulty; carer who answers over the person; mid-question
  safeguarding disclosure.
- Run thousands of simulated conversations; measure detection rates and failure
  modes; publish the safety performance as a technical paper.
- Clinical evidence with zero patients. Exactly what an MHRA pre-engagement
  conversation wants to see. Makes "responsible AI by design" the only such page
  in the sector backed by published adversarial results.

### 5. Own the metric, not just the tool — THE INDEX  `[ ]`
The deepest moat in measurement businesses is becoming the reference index.

- Publish a quarterly **State of the Missing Middle** report for Kent & Medway —
  journalist-readable, MP-citable, built from live data.
- When the local paper writes "frailty risk in Thanet rose this quarter,
  according to Assistiv's index," and an MP quotes it in a parliamentary
  question, FEP stops being a product and becomes the field's vocabulary.
- The prevention agenda and Neighbourhood Health Service push leave an open seat
  for whoever measures this population credibly.
- Tools get procured; indices get adopted.

**The thread through all five:** stop asking the system to believe you; build the
apparatus that proves you in public. The instinct so far has been to build
capability — and a remarkable amount exists. The move now is to build
*credibility* with the same machinery. Number one first.

---

## Supporting workstreams

### Methodology & rationale pages (per tool)  `[~]`
Started June 2026. One page per cloud tool: rationale, methodology, proxy
justification, signal weights, strengths, **and stated weaknesses**. A page that
volunteers its own limitations is more trustworthy than one that doesn't. These
are the credibility apparatus at tool level — what a commissioner reads before
moving resource on a score.

### Validation paper (50–100 person feasibility)  `[ ]`
Small published study: screening tool vs standard instruments (PRISMA-7, FRAIL)
in community settings. Materially changes clinical perception.

### Referral pathway completion (Layer 5)  `[ ]`
Formal PCN handoff agreements before scaling screening. The lynch-pin.

### Commercial model definition  `[ ]`
Commercial unit, contract model (per-capita / per-screened / per-outcome),
signatory (ICB / PCN / housing / consortium).

### Regulatory position (MHRA SaMD)  `[ ]`
State clearly whether tools require SaMD classification and the chosen pathway.

---

## Funding narrative (when ready)

**Investors:** "We validated the concept (public backtest). We proved the tool
works (synthetic safety paper + feasibility study). Now we scale the pathway and
the business." Seed round for: referral pathway + two-geography feasibility with
published outcomes + commercial/delivery team.

**NHS:** Commission a 3-month pilot in the highest-FEP district. "We screened X
in social prescribing networks; Y referred to the PCN; Z remained home-supported
at 3 months." Small, real, peer-tellable. One PCN believing you seeds the rest.

---

*Maintained as a living document. Update status markers as moves complete.*
