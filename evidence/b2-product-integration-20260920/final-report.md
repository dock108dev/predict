# B2 completion evidence

September 20, 2026 (local date; some evidence timestamps are September 21 UTC).

**B2 COMPLETE — fixture-backed product integration. B3 NEXT. Beta NOT READY FOR SIGNOFF.**

The ordinary dashboard now consumes acknowledged coverage observations, updates supported comparisons, exposes source gaps and dated references, freezes while saving, and reopens the same verified observations. Current and saved views share the bounded projection. This is engineering validation using fixtures and read-only retained evidence; it is not owner acceptance, current-source qualification or permission for a real scan.

## Exact implementation

- Base HEAD: `4be57ba25b692f1d4fe648d11a209f90caa35c46`.
- Uncommitted implementation SHA-256: `1821c3df3ec7aa1232cf6220a296d8ff428a907de5027367193d469e6a4a33b7`.
- [Per-file identity and aggregate hash definition](implementation-identity.json): 24 changed/new app, test and script files. The aggregate is SHA-256 of the sorted compact JSON file-to-hash map.
- [Implementation, acceptance contract and limits](../../docs/b2-product-integration-handoff.md).

## Acceptance results

| Check | Evidence | Result |
|---|---|---|
| Full local CI with exact locked dependencies, Python 3.11.7 on macOS | [CI log](ci311-locked-final.txt), [dependency setup](ci311-dependency-setup.txt) | 46 existing Python tests, 10 B2 tests and both JavaScript checks PASS |
| Independent original-input arithmetic, 18 Arb / 96 EV scenarios | [Math reconciliation](math-acceptance-final.txt) | PASS |
| Durable projection, three prediction identities/two events, non-Kalshi pairing, fourth not configured, identity isolation, no economic fallback | [B2 checks](b2-final-checks.txt), [CI B2 rerun](ci311-locked-final.txt) | PASS |
| Per-market failure, aging, inventory replacement, required fresh resync, failed initial discovery and refresh recovery | [Coverage checks](coverage-acceptance-final.txt), [B2 checks](b2-final-checks.txt) | PASS |
| Reference roles, explicit probability EV, raw-rating rejection, receipt/cutoff isolation, manual-assumption separation | [B2 checks](b2-final-checks.txt), [final UI checks](ui-label-final.txt), [browser reference drilldown](browser-reference-ev-final.txt) | PASS |
| Native collector through ordinary API: current updates, frozen links, Stop/saving/saved, repeated flat and segmented sessions, idle reconstruction | [CI B2 rerun](ci311-locked-final.txt) | PASS |
| Segmented lifecycle and fresh-index recovery, corrupt/interrupted history | [Segmented checks](segmented-final.txt), [recovery checks](recovery-attempt-2.txt), [B2 checks](b2-final-checks.txt) | PASS |
| Legacy saved calculations/history | [Legacy checks](legacy-acceptance.txt), [CI rerun](ci311-locked-final.txt) | PASS |
| Existing failed real coverage package reopened read-only | [Retained history result](retained-coverage-reopen-final.json) | Incomplete, zero games/markets, discovery failure retained |
| Browser filters, Details, stable selection, Stop/saving, saved switching/reopening, narrow layout | [Narrow screenshot](browser-final-narrow.png), [saving state](browser-saving-dom.txt), [saved reopening](browser-final-reopened.txt) | PASS |

The final UI wording correction was subsequently checked with JavaScript syntax checks, both JavaScript tests and a browser reload. The dated model probability now says “Dated reference probability”; editing it creates a separate manual assumption. No Python implementation changed after the locked-dependency CI pass. This local result is not a hosted GitHub Actions rerun; the reported runner used Linux/Python 3.11.16.

## Repairs and preserved failures

The reported `17 != 32` failure came from applying today's clock to historical discovery evidence. Discovery validation now uses the caller's explicit observation clock; live callers still default to the current clock. The existing 32-event assertion remains intact.

The reported missing `ev` field came from a test selecting the first game's ID from one saved session while submitting another session's hash. The API correctly rejected that mismatch. The test now binds the exact session/game identity, asserts HTTP 200 before reading EV, and repeats under reversed saved-session ordering. [The ordering failure was reproduced before repair](page-estimate-reordered-failure.txt).

The first local Python 3.11 attempt with the added collector tests used older globally installed dependencies and failed native stream checks. It is preserved in [the failed attempt](ci-python311-final.txt). The isolated rerun installed `requirements-ci.txt` with required hashes and passed without weakening the stream assertions.

Original E6 recovery indexes reject the host's changed device identity. Tests create fresh indexes over disposable copies; original evidence and validator checks remain unchanged. Earlier failed/intermediate logs remain in this directory. Final rows above identify the superseding results.

## Browser evidence and scope

The isolated preview used numeric loopback port 8794 and disposable synthetic native feeds. Browsing did not start collection. Three explicitly started sessions were finalized, including two explicit Stop cycles. All feeds were idle after Stop and reconstruction. The preview was then shut down and its temporary tab closed; the existing beta was not restarted or mutated.

[Retained browser sessions](browser-sessions/) contain the original fixture journals and finalization packages. Session `07dd921a-3b96-4bde-977d-035cea382478` carries the final model probability `0.57` and delayed Pinnacle native odds `2.15`. The native browser fixture intentionally lacks complete listing/source-time inputs: unavailable economics remain unavailable. Numeric supported-reference EV and three-source/two-event comparisons are independently exercised by the projection/API tests. No positive result was manufactured from missing inputs.

At 390 pixels the page had no horizontal overflow. Selected rows and expanded Details survived polling. Filters, saved-session switching, immutable drilldown, the intermediate saving state, and saved reopening after process restart were verified. [Final reference drilldown](browser-reference-ev-final.txt) shows its receipt date and distinct origin label.

## Remaining boundaries

The reducer is bounded to 512 markets, 128 references and 16 MiB of serialized retained inputs; snapshots to 64 comparisons and 32 MiB; active cached cutoffs to eight and 32 MiB. Older active segmented cutoffs outside the cache reopen after finalization rather than silently advancing. Unsupported market families remain visible without broader winner calculations.

B3 owns additional native prediction-source acquisition, depth, fees and settlement. Novig access remains unresolved; ProphetX is recommended but the fourth venue remains unselected/unconfigured. B4 owns actual independent model and delayed Pinnacle acquisition, access, delay and quota. B5 owns broader sport/market definitions and economic calculations. No new production source was qualified.

No credentials, authenticated requests, external market collection, provider activation, outreach, spending, trading, migrations, commits, pushes or publication occurred. Historical D2/supervised attempt guards remain intact. No beta acceptance is requested.
