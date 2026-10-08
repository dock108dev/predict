# Native comparison review records

`dashboard/native_reviews.py` validates immutable `native-review-1` records.
Retained session specifications may supply `native_review_records`; journals can
also introduce a new exact ID/revision. Conflicting revisions are excluded and
must be selected explicitly. Empty explicit records mean no reviewed association.

Each record binds canonical participants and event identity, sport/period/line,
source event/market/outcome IDs, native metadata and receipt hashes, orientation,
applicability and a canonical JSON hash. Raw correspondence is distinct from
settlement qualification and fee assessment. Missing or conditional judgments
remain explicit and cannot supply unrelated markets' economics.

Spread/total and period structures reuse shared descriptor and payout logic.
Sizing uses shared depth/fee arithmetic. Net returns and EV additionally require
qualified terms, effective fees, probability and timing.

For older sessions without explicit records, exact versioned indices can bind a
saved session to its review digest. They do not search for the latest review.
Missing or tampered inputs fail closed. Saved readers support original and
versioned derived interpretations without overwriting the source journal.
See [saved data](native-retained-coverage.md) and [architecture](architecture.md).
