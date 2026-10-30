# Executive memo — CredResolve collections performance

**Scope.** Supplied extract, 1 January–8 August 2026. This is eight observed calendar months, with August partial; it is not a full 12-month history. Recovery is defined here as deduplicated payment rows with `payment_status = SUCCESS`, assigned to month after converting the provider's declared timezone to Asia/Kolkata. This is a transparent working definition, not proof that every event is settled cash; reversals and settlement confirmation should be reconciled with the payment ledger.

## What happened?
- Deduplicated successful payments total **₹131.56 Cr** across the observed period.
- January recovery/day was **₹0.60 Cr**; July was **₹0.60 Cr**, a change of **+0.09%**.
- February→March deduplicated total recovery rises **+11.46%**, close to the reported claim, but daily-normalized recovery rises only **+0.68%** because March has 31 days versus February's 28. Other months move in both directions.
- August contains only eight observed days. Comparing its raw total with full months would understate performance.

## Why / data forensics
- **Duplicate payment IDs (strong evidence):** 500 later duplicate rows were found in 25,500 raw payment rows. Duplicate successful rows account for **₹2.59 Cr** repeated amount; raw successful amount is ₹134.15 Cr versus ₹131.56 Cr after deduplication. This is a correction, not incremental recovery.
- **Duplicate calls / digital events (strong evidence):** 1,350 duplicate `call_id` rows and 600 duplicate WhatsApp event IDs.
- **Timezone classification (strong evidence):** 310 of 91,350 calls (0.34%) change calendar month, and 60,865 (66.63%) change hour when normalized to IST.
- **Identity/version risk:** 19,585 repeated borrower IDs and 29,000 repeated agent IDs exist in versioned tables. Select latest valid records and preserve history; do not merge agents solely on name.
- **Attribution-window bias:** the naive latest-target record occurs after payment for 8,448 of 17,534 successful payment events; only 3,108 events have a target record in the prior 30 days. Under this definition, ₹108.12 Cr of successful amount has no 30-day prior targeting record. Targeting is not proof of a delivered contact or causal credit.

## Is the 11% claim real?
**Not established as a sustained operational improvement.** February-to-March total recovery rose +11.46%, but daily-normalized recovery rose only +0.68%; January-to-July daily-normalized recovery changed +0.09%. Monthly daily-normalized changes are 2026-02: +0.53%, 2026-03: +0.68%, 2026-04: -4.71%, 2026-05: +2.40%, 2026-06: -1.58%, 2026-07: +2.98%. Verification requires the original metric definition, original report and complete 12-month history. Use a fixed denominator, exclude duplicate/pending/failed/reversed events from recovery, and compare full months only.

## What should we do with ₹10 Cr?
**Recommendation: do not allocate the full amount yet.** The observational extract cannot reliably identify the causal return of AI voice, more agents, telephony, targeting, digital engagement or field operations. Run a staged randomized or phased pilot for one candidate intervention, stratified by DPD, loan type, client and geography, with a holdout group. Pre-register incremental successful recovery net of reversals and incremental cost as the primary outcome; track complaints and borrower outcomes as guardrails.

Estimate incremental recovery as treatment-minus-control per eligible account × eligible volume, net of costs. Report a confidence interval and downside case. Break-even occurs when incremental net recovery equals fully loaded pilot and scale costs. Expand only if the conservative confidence bound on incremental ROI is positive and guardrails remain acceptable.

## Confidence and limitations
- **High confidence:** duplicate event counts and arithmetic under the stated rules.
- **Moderate confidence:** monthly recovery after deduplication and timezone normalization, conditional on correct provider timezone metadata and SUCCESS meaning settled payment.
- **Low / not identified:** causal channel lift, targeting effect and investment ROI. Account DPD is a current snapshot, targeting is not delivered contact, and the extract ends in August.
