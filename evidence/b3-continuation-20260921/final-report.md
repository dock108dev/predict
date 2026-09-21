# B3 continuation — independent engineering verified

September 21, 2026. **B3 IN PROGRESS. Beta NOT READY FOR SIGNOFF.** No live market endpoint query, credentials accessed, provider messages, trading, spending, migrations, commits, pushes or publication.

[Current identity](implementation-identity.json) · [Starting identity](baseline.json) · [Implementation](../../docs/b3-native-integration.md) · [Access/setup](../../docs/b3-access-setup.md).

## Completed

- Native REST replay now feeds the existing incremental grouped segmented verifier and finalization. Copied retained synthetic data crosses multiple forced segments; prices, quantities and whole projection reproduce. Corrupt/incomplete packages and altered normalized quantities fail. Stop/cleanup and immutable cutoffs are tested in both formats.
- Listing associations bind source event/market IDs, receipt, raw-body hash, explicit ProphetX subtype periods and native descriptions. Missing Novig period and listing settlement rules remain unknown. Native descriptions are not promoted to settlement rules. All supported association work from currently available contracts/retained data is complete; unavailable native meanings are evidence gaps.
- ProphetX selected=true/not_configured is shown in the ordinary UI, with tests proving no secret lookup or activation. Current documents no longer ask for selection. Old evidence remains historical.
- Minimal public GraphQL source interface added for discovery and dated display. Original successful bodies/query and derived excluded catalog replay in flat/segmented history. Available and last trade stay distinct; no NBX quantity semantics, purchase books or sized comparisons. [Assessment](../../docs/b3-graphql-assessment.md) and [separate unapproved sample](../../docs/b3-graphql-sample-proposal.md).
- Owner-local hidden Keychain setup helper for both venues; no credential was entered or read. [Unsent Novig provisioning request](../../docs/novig-access-request.md) addresses the documented contact and unresolved contracts.

## Validation

| Check | Result |
|---|---|
| [CI](ci.txt) | 46 existing tests, including 18-Arb/96-EV; 23 B2/B3/projection checks; both UI scripts and syntax/compile checks PASS |
| [Native/lifecycle](native-lifecycle.txt) | 124 adapter, retained ProphetX, coverage, continuous and segmented lifecycle tests PASS |
| [Final projection/integration](final-projection.txt) | 23 tests PASS after final GraphQL catalog replay and receipt-label changes |
| [Cross-segment test](cross-segment.txt) | Forced boundaries, original projection equality, incomplete/corrupt rejection, altered quantity rejection and original evidence hash preservation PASS |
| [Browser](browser-verification.md) | Repaired segmented synthetic current/saved view; two healthy K/US pairs plus Novig display catalog; selected/unconfigured ProphetX |
| [Repaired package](browser-repaired/sessions/c89130da-28fd-45ed-8112-6d750d6f22cc/replay.json) | 29 K + 29 US books and one GraphQL observation, exact reconstruction; no production inference |

Initial failures are retained: period-association Decimal parsing, current versus frozen age comparison, source ordering/health projection differences and missing shared matching annotations in GraphQL replay. Each was repaired within scope. The first browser package remains failed; it was not rewritten. The final receipt-label change was checked by focused tests and reopening, not relabeled as new collection.

## Per-source status

| Source | Implemented/offline verified | QA/sandbox | Production | Ordinary participation | Remaining |
|---|---|---|---|---|---|
| Kalshi | Existing stream + shared native segmented path; PASS | No new | Earlier retained only | Synthetic current/saved comparisons | Fresh approved B3 overlap, applicable fees/rules/depth |
| Polymarket US | Native stream + Short conversion; PASS | No new | Earlier retained only | Synthetic current/saved comparisons | Fresh Short/overlap and depth/fees/rules |
| Novig | NBX source plus temporary GraphQL display; PASS fixtures | None | None | NBX synthetic comparisons; GraphQL catalog only | Issued NBX provisioning, native period/rules, source-clock/depth/fees; GraphQL host/schema sample unapproved |
| ProphetX | Selected, unconfigured; native REST/history/association PASS | Earlier retained only | None | Historical unsized sandbox projection | Production API type/key, tournament identity, quantity/value units and rules; no new streaming-delivery proof |

## Smallest next action

The owner can request NBX and ProphetX production credentials using the linked setup instructions. Keys are not needed for any unfinished offline test. Optional GraphQL sampling requires its own explicit approval after exact identity/output freeze, never inferred from choosing GraphQL. The existing authenticated four-source proposal remains unapproved and unchanged in its limits.

ProphetX now documents a separate affiliate Market Data API. Its single-key auth and instrument identity differ from the implemented Trading API contract. Do not put an affiliate key into the Trading credential slot; adapting that source is optional independent work if that API is provisioned. Additional supported-scope fixtures are also possible. No required independent engineering from this continuation remains, but source meanings unavailable in documentation/retained evidence and actual four-source production qualification remain open. B4 model/Pinnacle and B5 broader economics are separate.
