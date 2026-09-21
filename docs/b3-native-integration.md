# B3 native product integration — engineering progress, qualification blocked

**Current access status (September 21):** owner sent both Novig and ProphetX requests; provider responses are pending. No duplicate request is needed. Credentials/production access remain unconfirmed. [Access status](b3-access-status.md) · [Next independent work: B4](b4-independent-handoff.md).

September 21, 2026. **B3 IN PROGRESS. NOT COMPLETE. Beta NOT READY FOR SIGNOFF.** [Bounded proposal](b3-native-qualification-proposal.md) · [Evidence](../evidence/b3-native-integration-20260920/final-report.md).

B2's 24-file implementation identity matched exactly before this work. Its shared collector, calculation engine, acknowledgement boundary, history formats and ordinary dashboard remain the foundation. Existing uncommitted work and immutable retained evidence were preserved.

Owner selected ProphetX on September 21. Current configuration and UI record selected=true with not_configured until access is supplied; selection does not activate it. [Novig access review](novig-access-review-20260921.md) distinguishes issued NBX credentials from public but sunsetting GraphQL. No new capture occurred.

## Implemented

- Explicit four-source configuration with enabled, disabled, unconfigured and unselected states. Disabled slots remain visible without credentials or requests. Source-specific missing access/disconnection does not suppress healthy sources. Native REST failures retire only the failed market; no automatic retry of that failed request.
- Novig and a provisional ProphetX (owner-selected September 21; activation pending) branch use existing bounded authenticated adapters inside `ContinuousSession`, with native discovery, original REST observations, metadata, health, dated snapshots, common projection/history and Stop. Authentication is lazy; credentials are referenced only through dedicated local Keychain entries.
- Native purchase interpretation is opt-in for B3 sessions, preserving old adapter/replay outputs. US Short asks are one minus Long bids with the same fractional contract quantity. Novig complementary asks divide CASH payout cents by 100 to obtain contracts. Original raw bytes, native books, clocks and unknown synchronization/depth remain intact. ProphetX unsized American-price quotes reach the projection without treating `quantity` or `value` as usable size.
- Kalshi series and US tag acquisition scopes are configurable and bounded. US B3 discovery no longer filters its event/market requests to winners only. Discovered native metadata is retained; sport/competition conflicts are excluded. Six-sport Novig league configuration and explicit ProphetX tournament IDs are supported. Native sport/family/period metadata remains visible; unsupported B5 scopes do not enter winner math. No six-sport production coverage claim.
- Each source has explicit price, quantity, fee and settlement limitation records. Existing fee engines are preserved; unverified Novig/ProphetX applicability and listing rules return unavailable net results. US/Kalshi retain existing pinned source-specific economic paths and conditional assumptions. A current unknown native status is no longer replaced with older active listing metadata in B3.
- The existing ordinary UI shows environment, update path, receipt, native-side price/size and gaps, including unsupported listings. Three-source comparison ordering is deterministic across save/reopen. Fixture environments explicitly say synthetic. History replays native REST prices/quantities against preceding retained HTTP bodies; old stream replay stays unchanged unless the B3 normalization is explicitly recorded in the spec.
- One bounded real allowance can be bound to the exact spec, app files and output, consumed once before access. A separate idle entry point opens the ordinary product. No approved file was created and no real Start occurred.

## Per-source evidence state

| Venue | Implemented | Offline verified | QA/sandbox observed | Production observed | Ordinary comparison participation | Remaining gaps |
|---|---|---|---|---|---|---|
| Kalshi | Existing native stream extended through B3 configuration/health | Yes; native/lifecycle/history and original math checks | No new QA | Retained earlier bounded production only; **no B3 run** | B2/B3 fixtures; retained legacy production path | Fresh approved B3 overlap/updates; broader series listings; fee override/account precision and exceptional settlement |
| Polymarket US | Native stream plus B3 Short purchase conversion and broader returned catalog | Yes; fractional Short conversion independently reconciled from retained production book | No new QA | Retained earlier bounded production only; **no B3 run** | B2/B3 fixtures; retained legacy production path | Fresh Short/overlap qualification; upstream depth/completeness; source fees/settlement limits; broader native sport/period mappings |
| Novig | Auth/discovery/REST/health/history/Stop integrated | Yes; actual adapter against injected HTTP fixture, native unit arithmetic, failure isolation and saved cutoff | **None**; synthetic QA-shaped traffic is not QA evidence | **None** | Ordinary synthetic comparisons; no real participation | Issued access; actual wire contract; listing period/rule association; stream initial-image/handoff guarantee; depth/time/fee applicability/settlement |
| ProphetX — owner-selected September 21 | Provisional bounded REST producer using existing adapter | Adapter tests plus actual retained sandbox quotes projected as unsized dated observations | Earlier Slice 3 only; no new sandbox access | **None** | Historical sandbox quote projection; no newly qualified ordinary production overlap | Production provisioning/tournament scope, quantity/value ownership, source timestamps, fees/rules; no current stream-delivery qualification |

A synthesized fixture `full_game` period was explicitly supplied for the Novig comparison test. The real NBX parser still leaves period unknown. This fixture demonstrates the product contract, not native period verification. Broader native rule/period mapping belongs to B5, but sufficient native full-game identity for B3 real overlap remains an explicit B3 prerequisite.

## Public contract reconciliation

Official public documentation was read without market API collection:

- [Novig data model](https://docs.novig.com/api-reference/data-model), [REST book](https://docs.novig.com/api-reference/markets/get-order-book) and [liquidity example](https://docs.novig.com/affiliates/odds-screens) establish binary outcomes, native bids, payout-cent quantity and opposite purchase arithmetic. In the published example, 45,000 payout cents at .36 supply the opposite side at .64 for 450 contracts, costing $288. This does not establish full depth or a source clock.
- [Novig order-book channel](https://docs.novig.com/api-reference/WSS/orderbook-channel) distinguishes market-specific initial `book` images from updates-only global tape, bare PLACE/CANCEL ticks and lifecycle implicit cancellation. Existing offline stream logic remains; no new wire observation validates its initial envelope or handoff. Dated REST is the proposed first integrated path.
- [ProphetX current event contract](https://docs.prophetx.co/docs/websocket-events) describes change-triggered selection arrays and event/submarket scope. It still does not establish quantity/value ownership. Retained sandbox +146 converts to 100/246; −164 converts to 164/264. The size stays null. REST image replacement is not a streaming-delivery claim.
- [US book schema](https://docs.polymarket.us/api-reference/markets/get-market-book) and retained exact native side IDs underpin B3's Short conversion. It retains the input ladder's depth classification rather than promoting it to complete.

## Remaining actions

Await Novig NBX and ProphetX production provisioning references, then finalize and request approval of the **single** linked qualification proposal. Enter secrets locally, never in chat. No provider message is authorized. If one venue remains unavailable, retain its blocked row while continuing independent engineering. Do not mark B3 complete on fixture or sandbox success.

Native listing association now binds event/market IDs, receipt and raw-body hash, plus explicit ProphetX subtype period and native description. Novig period remains unknown because checked contracts provide no period/rule field. Descriptions are not promoted to settlement rules. Production tournament identity still requires issued or newly approved source evidence. B4 owns model/Pinnacle acquisition; B5 owns broader canonical sport/period/futures and economic support. No commits, pushes, trading, spending or publication.

## September 21 continuation

Native REST replay now runs incrementally inside existing grouped segmented verification/finalization. Existing readers validate chains before projection; original price/quantity packets, catalog metadata, health and immutable cutoffs reproduce. Corrupt/incomplete packages and altered normalized size are rejected. Forced cross-segment replay uses copied historical synthetic inputs, not new production observations. Current and saved projection ordering/JSON types/health fields are consistent. Production segmented activation is not added to or approved by the existing flat four-source proposal.

A small [GraphQL display bridge](b3-graphql-assessment.md) is implemented at the owner's request. It uses the same source interface/history/Stop and shows discovery plus dated available/last values under explicit unsupported reasons. It never supplies NBX quantity conversion, purchase books or sized comparisons. Native metadata without period stays unknown. [Public sample proposal](b3-graphql-sample-proposal.md) is separate, unapproved and unexecuted.

[Continuation evidence](../evidence/b3-continuation-20260921/final-report.md) records focused tests, 124 native/lifecycle checks, B2 and 18-Arb/96-EV reconciliation, and isolated browser verification. Historical evidence above is not promoted. [Access and local setup instructions](b3-access-setup.md) and the [unsent NBX request](novig-access-request.md) are ready. The owner can obtain keys when needed; no issued production provisioning was confirmed, no credentials were inspected and no live collection occurred.

Remaining independent work is optional additional scope fixtures or an affiliate ProphetX adapter if that is the API ultimately provisioned. The requested independent replay, selection and supported listing-association work is complete; unresolved native meanings remain explicit evidence gaps. B3 exit still requires four actual production sources and useful ordinary overlap.
