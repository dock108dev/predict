# Retained native evidence coverage — comparison v4

September 30, 2026. Local engineering and offline verification only. The work-order authority is `/Users/michaelfuscoletti/Desktop/prediction_arb_next_steps.md`. Source journals, original interpretations, consumed attempts and the accepted layout remain preserved. Owner walkthroughs and commercial validation are deferred.

## Corpus and admissions

The complete accounting is `evidence/native-retained-coverage-20260930-v1/corpus-accounting.json`. Its receipt, native-object and reviewed-event ledgers identify exact native event/market/outcome IDs, metadata revisions, source body hashes, original receipt times, journal chains and capture provenance. Inspection included 23 unique session packages (22 native acquisitions and one reference package), plus six pre-session discovery journals. Two physical copies of the Pinnacle package count once. Fifteen native sessions contain books; seven contain discovery only. Six pre-session journals do not become priced sessions.

| Measure | Exact count |
| --- | ---: |
| Native session HTTP receipts | 631 |
| Pre-session discovery HTTP receipts | 37 |
| Complete usable native receipt identities | 661 |
| Incomplete/unsuccessful receipt identities excluded | 7 |
| Unique event associations | 45 |
| Fully reviewed events | 37: 35 NFL, 1 NHL, 1 NCAAF |
| Newly reviewed events | 36 |
| Fully reviewed native market pairs | 74 |
| Newly reviewed market pairs | 73 |
| Immutable records | 313, including 312 new records |
| Unique pairs with paired retained books | 71 |
| Ordinary outcome cards across unique events | 72, including 70 additional NFL cards |
| Fully reviewed pairs with no paired books in any retained capture | 3 |
| Event-only associations without sufficient market orientation | 8 |

Records count capture-specific reviews and nonoverlapping metadata revisions, not unique markets. Repeated captures retain their separate receipt origins and observation cutoffs. The original WKU–NMSU record accounts for one previously reviewed pair and two cards. The second Kalshi contract for that event is newly reviewed but lacks a retained Kalshi book. The 35 NFL events provide two Kalshi alternative contracts and one US contract each; cards group the same event/outcome and expose the alternative contract separately. They do not combine liquidity. The new NHL event has two reviewed Kalshi contracts, neither priced.

At final original session cutoffs there are 202 native card occurrences and 187 priced native contract-pair occurrences. Those repeated-session counts are not additional unique events. A market missing books in one capture remains unpriced there even if another capture has them. No unrelated sessions are merged into simultaneous prices.

## Observations and independent checks

The wire oracle checked all 5,631 retained native book rows against their actual source frames, source IDs and Decimal prices/quantities. These contain 361 initial images, 4,797 actual ladder updates, 105 unchanged ladder observations and 368 health reemissions. Updates comprise 4,553 quantity-only changes and 244 price-level changes; 52 updates change a top buy price. The oracle normalizes Decimal representation so textual precision differences are not counted as price changes. Missing native source clocks and uncertain market-state continuity remain unknown. Book display and actual updates establish historical observations, not contemporaneous execution or profitable economics.

Older US observations omitted Short purchase asks even though explicit Long bids and Long/Short orientation were retained. v4 derives complementary Short purchase depth with the existing native purchase-book engine. The original ladder and receipt remain embedded. Independent wire arithmetic verifies that derivation; original v3 outputs remain reproducible.

All 313 admitted records passed independent original-source checks of exact event/market/outcome IDs, structured team IDs where present, primary rule orientation, US side directions, Kalshi binary $1 structure, scheduled start and full-game market semantics. Fresh processes reproduced 23 saved packages and checked 748 comparison leg/depth results against per-session wire prices. One original r4 projection's existing market-bound failure is reproduced explicitly; v4 applies the existing compact catalog operation before the unchanged bound. Its 1,841 unsupported US markets and unresolved Kalshi listings gain no native approval.

Focused tests cover real four-event/eight-card feed, each alternative's Details, depth/sizing, watches, history, downloads, selected-record download, missing/tampered records, changed metadata, reference isolation, cutoff changes, disjoint revisions and exact reopening. Existing versioned synthetic controls exercise differing settlement/fee states and all 63 required cells; they do not contribute real coverage. Final verification records identify the passing Python batches and six JavaScript suites. Preliminary failed verification runs are retained, including a cumulative-memory source-check process repaired by per-session fresh processes without raising the existing memory gate.

## Exact unpriced and excluded evidence

- **NYI–TOR:** Kalshi `KXNHLGAME-26SEP30NYITOR-NYI` and `...-TOR`, US event `127804`, market `1061481`. Complete identity, orientation and normal-winner structure are reviewed; the gap-probe session has no native book observations for either venue. Paired native book receipts tied to this selected metadata in one valid session would enable two outcome cards at that new cutoff. Later books cannot fill the original historical cutoff.
- **WKU–NMSU alternative:** Kalshi `KXNCAAFGAME-26OCT01WKUNMSU-WKU`, US `116584/932924`. Exact structure is reviewed, but the retained book capture selected only the other Kalshi contract. A book for this exact Kalshi ticker plus a contemporaneous US book in the same valid observation session would enable the additional contract alternative. The original NMSU contract remains sealed and available.
- **Eight event-only associations:** seven NFL events (`DALHOU`, `GBTB`, `JACCIN`, `LARPHI`, `NYJCHI`, `TENBAL`, `BUFNE` under the exact `KXNFLGAME-26OCT04...` IDs) and NHL `KXNHLGAME-26SEP30PITPHI` / US event `127796`, market `1061455`. Kalshi event summaries establish association but lack selected-event market records, primary rule orientation and native outcomes. Exact Kalshi market metadata is the smallest missing fact for a full orientation review; paired books would then be needed for pricing. The machine ledger lists each exact US counterpart and capture provenance.
- **MLB:** complete US BOS–NYY market `1081085` does not have a retained same-event Kalshi counterpart with native market/outcome evidence. The retained Kalshi PHI–ATL listing is a different event. Same-event counterpart metadata and outcome evidence, followed by paired books, are required.
- **NBA/CBB and futures:** retained bounded listings/empty pages do not establish provider absence or supported game availability. The r4 catalog has 600 unresolved Kalshi event summaries and 1,841 US markets excluded as unsupported type/period; r3 has 21 unsupported native futures listings. Supported game scope/membership, exact counterpart and market/state/outcome semantics must be evidenced before review. Championship/futures additionally need complete field membership, state/award and payout predicates. The native-object ledger retains each excluded ID, metadata fingerprint, source receipt and exclusion. Existing sport/market engines and all 63 required cells remain in scope.
- **Incomplete receipts:** four session responses have `complete=false` (including the 2 MiB CFB prefix); three older discovery responses have missing success/completeness evidence and capped bodies. None supply parsed native identity or count as coverage. The retained no-journal attempt `feb2bf9e-8afb-47c9-9cb9-8ddc085836a4` supplies no durable source fact. Offline preparations, synthetic controls and replay copies do not count as real coverage.

Each real record carries its own settlement, fee, timing and execution assessments. All 313 selected records currently have an incompatible settlement assessment based on actual retained exceptional clauses, with other material conditions still unknown. Earlier NFL Kalshi “begins within 48 hours” differs from US rescheduled-date wording even where both use two days; later US clauses use two weeks. NHL calendar-day wording differs from the Kalshi elapsed/start rule. These are distinct source facts, not inherited WKU judgments. New fee assessments remain unknown; the original WKU US fee-bound applicability and Kalshi series evidence remain confined to that record. Net/EV stays unavailable. Material settlement compatibility/effective modifications, exceptional payouts, applicable venue fees/overrides/precision and mandatory charges, fair probabilities and qualified contemporaneous clocks/state remain separate source-dependent requirements.

## Version and preservation

Default reopening is `native-book-comparison-4`. Explicit `original`, `native-book-comparison-2` and `native-book-comparison-3` remain supported. The original index and WKU record remain unchanged. `index-v4.json` pins only exact source sessions/acquisitions and content-addressed records; ordinary explicit run-spec/journal records use the same schema. Nonoverlapping metadata revisions have exact historical applicability intervals. Selected records are frozen in calculation inputs and downloads. Historical product-chain anchors reject altered journals, including when a prefix cutoff is selected. No latest-record lookup or cross-session book borrowing is permitted.

The source archive, final implementation identity, per-session projection digests, record manifest and 8,869-file preservation result are sealed in the evidence folder. Original outputs are retained; v4 outputs are separate files under `derived/`. Future changed interpretations require an explicit version/revision and fresh derived outputs. This pass grants no new acquisition authority.
