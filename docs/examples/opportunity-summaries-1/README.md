# Authored observed-summary examples

These are invented protocol examples for [summaries v1](../../scanner-summary-contract.md), not market evidence. All use the [versioned schema](../../contracts/predict-opportunity-summaries-1.schema.json). The independent counting example is:

| Observations | Episode count | Censoring / observed span |
| --- | --- | --- |
| Pair A is already an arb at 14:00:00; still qualifies at 14:00:40, then loses coverage. | 1 | Left- and right-censored; observed span 40s. |
| Pair B was completely evaluated without an arb, qualifies at 14:00:10 and last at 14:00:20, then is completely evaluated without the category. | 1 | Observed new, authoritative withdrawal; observed span 10s. |
| Pair C was completely evaluated without an arb, qualifies at 14:00:30 and still qualifies at 14:01:00. | 1 | Observed new and still open; observed span 30s. |

`observed.json` therefore has 3 retained arb episodes, 2 observed new, 1 left-censored, 2 ended, 1 open, 1 gap-censored, observed spans 10–40s and 1 episode with both onset and authoritative withdrawal observed. Repeated publications, reads, reloads and page/filter changes add no episode. A simultaneous EV category would remain in its own EV scope. Independent observed edge extrema are 0.5–3%; supported funding extrema are $25–$80. Those maxima are not a jointly witnessed allocation.

`checked-zero.json` is a separate complete selected scope with three evaluated compatible pairs and no current matches or retained episodes. `unavailable.json` has never obtained a publication; identity, window, evaluated denominator and checked-zero are null. Empty observations cannot be reported as checked-zero.

`joint-threshold-incomplete.json` requests edge ≥2% and funding ≥$70. Suppose the episode observed `(3%, $25)` and `(0.5%, $80)`, with other Pareto witnesses subsequently exceeding the four-witness bound. Independent maxima cannot establish that both thresholds held together. The returned observed count is zero with `threshold_history_complete=false`. Current complete coverage supports `checked_zero=true` for the latest publication; this does not establish that no matching opportunity occurred earlier. The historical threshold answer remains explicitly incomplete.
