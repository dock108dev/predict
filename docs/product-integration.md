# Coverage sessions in ordinary Predict comparisons

September 20, 2026. **product integration COMPLETE — fixture-backed product integration. Venue integration NEXT. Beta NOT READY FOR SIGNOFF.**

The ordinary dashboard now follows an explicitly started coverage session, shows discovery before books arrive, updates compatible comparison rows, freezes during Stop/saving, and reopens verified saved cutoffs. This does not qualify new production sources or authorize a real Start.

[Acceptance report and exact implementation identity](../evidence/b2-product-integration-20260920/final-report.md) · [Source/dependency matrix](coverage-matrix.md) · [Delivery plan](data-coverage-plan.md).

## Delivered implementation

- `session_projection.py` reduces acknowledged retained observations into bounded market state. Inventory generations replace atomically; observations, health, native sides and IDs remain scoped to source/event/market. Snapshot copies cannot mutate the reducer. Stable cursors bind ordinal plus the cumulative logical observation hash, identical across compressed flat and segmented reopening.
- `TransportSession.save_observed` notifies only after journal acknowledgement, before queue insertion. A queue rejection does not lose an acknowledged row; projection errors become unavailable and flat sessions can rebuild from the acknowledged prefix. Failed storage cannot publish current data or reopen an unacknowledged failure tail as successful history.
- `session_history.py` dispatches legacy packages to `saved_rows`, coverage flat packages to the established journal verifier plus their manifest checks, and segmented packages to `SegmentedReader`. Corrupt/unsupported packages remain visible as incomplete. Verified interrupted prefixes remain incomplete. Original packages and historical cutoff IDs are unchanged.
- `CoverageOwner(product_mode=True)` uses the ordinary spec factory, separate product run records and output, the shared collector, and the existing Stop/finalizer lock. Explicit repeatable fixture sessions require validated numeric-loopback endpoints, mock mode and no credentials. Real product Start remains unavailable. bounded collection defaults, consumed markers and supervised authorization checks remain intact.
- `multi_game_server.py` exposes coverage sessions through `/api/dashboard`, `/api/sessions` and immutable `/api/calculate` cutoffs. Old legacy IDs/calculation inputs retain their compatibility path. The product Start detour is removed. Browsing does not own collection.
- `product_view.py` enumerates complementary outcomes across source identities using the existing depth, fee and settlement engines. Unknown source economics return unsupported/null, including the Novig fixture; they never use the US schedule by fallback. Origin identity prevents two frontends to one source from forming an independent pair.
- The additive identity envelope carries sport, competition, season, event/schedule, family, period, line, subject, rules, outcome set and futures category/horizon. Unsupported sports/families/periods stay in the catalog; product integration economic dispatch stays within the supported NFL full-game winner scope. NO remains a native proposition complement, not an arbitrary other outcome.
- Reference records preserve provider/origin, role, dates, delay, value kind, conversion and provenance. Explicit supported probabilities can enter labeled EV. Ratings/native odds are not silently converted. Reference-based drilldown is kept out of stored manual assumptions; historical research remains on its existing saved path. References are never Arb legs.
- The UI exposes source filters, source/market gaps, current/saving/saved/incomplete states, dated reference Details and frozen drilldown. Row selection and expanded Details survive polling; narrow layout was verified at 390 pixels.

## Focused acceptance

All checks use disposable synthetic outputs and read-only retained observations. See the linked report for individual logs and browser images.

| Check | Result |
|---|---|
| Independent original-input reconciliation: 18 Arb / 96 EV scenarios | PASS |
| Ordinary API current inventory → metadata → books → same-row updates | PASS |
| Three prediction identities, two events, non-Kalshi pair, fourth not configured | PASS; third-source net economics explicitly unsupported |
| Competition/season/line/full-game/H1/H2/innings/period/futures isolation | PASS; unsupported scopes displayed without winner math |
| Group failure, clock-only aging, required fresh resync, inventory changes and partial refresh recovery | PASS |
| Reference role/provenance/date isolation; explicit probability EV; raw ratings rejected; no future receipt leakage | PASS |
| Acknowledgement/queue failure and failed-write publication boundaries | PASS |
| Start → update → Stop → saving → saved; repeatable flat and segmented sessions; idle reconstruction | PASS |
| Legacy, coverage flat and segmented readers; corrupt and interrupted packages | PASS |
| Browser filters, Details, stable selection, Stop, saved switching/reopening and narrow layout | PASS |

The full local CI script passes with locked dependencies on Python 3.11.7: 46 existing Python tests, 10 product integration tests and both JavaScript checks. The reported CI failures were repaired without reducing assertions: historical discovery uses its supplied clock, and page-estimate tests bind the exact session/game identity and also run with reversed saved-session order. This is a local result, not a hosted runner rerun.

## Explicit limits and next slice

The reducer retains at most 512 markets, 128 references and 16 MiB of serialized retained market/reference inputs. A snapshot has at most 64 comparison groups and 32 MiB of measured resident state. The active cutoff cache has at most eight snapshots and 32 MiB; an older active segmented cutoff outside that cache becomes reopenable after Stop through verified history. Cutoffs never silently advance. Excess comparison groups remain counted; their native markets remain in coverage. Existing collector duration/resource bounds are unchanged.

Product integration supplies an integration contract, not new native acquisition or broader economics. New prediction-source handlers and actual Novig/fourth-venue depth/fee/rule contracts are **venue integration**. ProphetX is recommended but remains unselected; production access and quantity/update semantics remain unresolved. Actual model independence/acquisition and free delayed Pinnacle access/delay/quota are **reference integration**. Native sport/competition/period/futures definitions and calculations are **market support**. No reference provider or third prediction venue is newly production-qualified.

The unmodified old recovery indexes still reject a changed host device identity; product integration did not rebind historical evidence. Recovery tests use fresh indexes over disposable copies and retain all original validation assertions. The existing beta process was not restarted or mutated. No credentials, provider activation, external collection, outreach, spending, trading, migrations, commits, pushes or publication occurred. **Beta remains NOT READY FOR SIGNOFF.**
