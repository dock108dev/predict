# HOU-JAC selected settlement review

## October 17, 13:43 UTC resolution addendum

The subsequent authorized three-response series/event metadata operation closes
the selected Kalshi governing-document/OT linkage. Current `KXNFLGAME` points to
the exact retained FOOTBALLGAMEWIN terms URL and verified current PDF hash; the
selected wording has no OT exclusion. All OT is included, with the selected
`$0.50` tie rule preserved. This establishes current selected applicability
without inventing an amendment-effective instant. The
[independent resolution](../test-results/sc07-execution/source/selected-series-fee-and-ot-resolution.json)
retains exact original bytes, hashes and response clocks. No additional PDF fetch
occurred. The original review below remains historical; its OT-linkage gap is
superseded. Its asymmetric terminal-state limits and unestablished covered-outcome
guarantee remain applicable. [Current evidence package](sc07-hou-jac-evidence-package.md).

## Original retained review

Reviewed October 17, 2026, against the retained ordinary SQL intake at
`2026-10-17T13:08:37.330439+00:00` (09:08:37 Eastern). This review made zero
network/provider requests, changed no application code or production
applicability records, and opened no genuine observation window. It is a retained
documentary and cashflow-bound review, not a current executable ticket.

**Decision:** the retained material supports the same completed-game direction,
with overtime expressly included on Polymarket US and consistently included by
both retained Kalshi family documents unless the exact period says otherwise.
The exact Kalshi selected wording contains no regulation-only override, but a
governing-document/version binding for this selected series remains unproved.
The venues' exceptional cashflows are different. No positive covered-outcome
guarantee is established. The retained asks do not even show a positive
decisive-only margin before nonnegative costs and the one buffer.

## Exact selection and changed bindings

The selected occurrence is Houston Texans at Jacksonville Jaguars, NFL 2026
regular season, scheduled `2026-10-18T13:30:00+00:00` (09:30 Eastern). Both
admitted event records retain Sportradar occurrence
`0bddea0c-7e26-4dff-a967-85ef8e5156cc` and occurrence ID
`event:defd10973ca3a181b48c2157bc7454c0`.

| Venue/action | Native identity | Selected predicate |
| --- | --- | --- |
| Kalshi Buy YES | `KXNFLGAME-26OCT18HOUJAC` / `KXNFLGAME-26OCT18HOUJAC-JAC` / `yes` / `yes` | Jacksonville wins |
| Polymarket US Long | event `141502` / market `1198902` / instrument `2397286` / `Long` | Houston wins |

Kalshi NO and Polymarket US Short are outside this selection. They are not
substituted for these two positions; unsupported Short collateral remains
unsupported.

The fresh observed native contract IDs are
`native-contract:e47a0eba1479181a1ac2689fa20f82b4b7d3d6483e01a6c529b565f5a531959c`
and
`native-contract:4442272ce3c03ee518e8fb274e0e9adc7efab1a98f05d72cc03c867cb2170ed4`.
Their terms digests are respectively
`6a4f916089b97bfeacb4b66bf624486299621b44a57a67d84e51b4810b3666af`
and `f5df6540348835ace5f99e614c426a4211c7923de63c5da50e2f68bfa632b1f0`.
These differ from the previous SC07 candidate bindings. The exact original
selected settlement wording is byte-for-byte equal across the two retained
intakes. This establishes unchanged wording only; it does not make the old
binding current or establish the cause of every changed digest.
[Exact old/current attachments and comparison](../test-results/sc07-hou-jac/settlement/selected-original-comparison.json).

## Overtime and document precedence

Polymarket US's selected description expressly includes overtime if played. It
specifies a half-dollar tie settlement and its two-week rescheduling condition.
Its [retained settlement guidance](../test-results/sc07/source-review/primary/us-settlement.md)
directs alternative settlements to the specific market's rules; the
[retained sports guidance](../test-results/sc07/source-review/primary/us-sports.md)
also treats a contract-specific exception as controlling. The selected express
overtime statement therefore supplies stronger evidence than a family default.

Kalshi's selected primary and secondary text describes the winner of the named
game, a half-dollar tie, a first start within 48 hours of the originally scheduled
start, and fair-price settlement if it does not start within that time. The exact
selected text is silent on overtime. Silence is not an overtime exclusion.

The [older retained FOOTBALLGAMEWIN PDF](../evidence/public-contract-bindings-20260930-v1/public/kalshi-football-win.pdf)
was retrieved October 1; the
[later retained PDF](../test-results/sc07/source-review/primary/kalshi-football.pdf)
was retrieved October 17, with the same bytes already retained October 9. Both
documents define the default full-game period to include overtime and separately
say that all overtime periods count unless otherwise specified. All six PDF pages
were rendered and visually inspected. The overtime rule is the same in both
versions; it is not a rule newly inferred from the later document's modification
timestamp.

The versions do differ in tie-strike wording and venue-change handling. Their
creation/retrieval/HTTP modification dates do not establish an amendment's
effective time or its application to an already listed market. This review does
not let a family default override conflicting selected terms. In particular, the
selected market's explicit half-dollar tie text is retained; the later generic
Tie-strike branch cannot silently replace it.

The remaining narrow overtime authority gap is the retained exact
`KXNFLGAME`-to-governing-contract-document/version linkage and any selected-period
exception or applicable amendment. The public profile itself requires an exact
contract URL plus instantiated predicate and has `runtime_ready=false`. Until
that link is supported, the application's `overtime=unknown` remains an honest
production admission state. The documentary conclusion is **consistent support
for including overtime, with selected applicability still incomplete**.
[Source hashes, retrieval times and visual-review record](../test-results/sc07-hou-jac/settlement/retained-source-manifest.json),
[retained document differences](../test-results/sc07-hou-jac/settlement/family-version-diff.txt).

## Joint settlement states and justified bounds

Let `nK` and `nP` be positive native $1-face quantities. Let `x` and `y` denote
the separate venues' fair settlement prices. On retained $1-face evidence the
conservative range is `0 <= x,y <= 1`. Neither an actual future fair price nor a
cross-venue relationship between them is known. These are uncertainty bounds,
not forecasts that either endpoint will occur.

| Selected scenario | Kalshi JAX YES gross receipt | US HOU Long gross receipt | What is established |
| --- | --- | --- | --- |
| Normal game under both terms, Jacksonville wins | `nK` | `0` | Opposing decisive cashflows, conditional on matching admitted completed-game treatment |
| Normal game under both terms, Houston wins | `0` | `nP` | Same condition |
| Normal final tie under selected half-tie terms | `nK/2` | `nP/2` | Exact selected descriptions agree on the half-dollar amount |
| First start outside Kalshi's 48-hour window, but rescheduled inside US's two-week window | `nK*x` | `0`, `nP`, or `nP/2` according to the US result | Asymmetric settlement is possible; the later game result does not renew Kalshi's start window |
| Both selected terminal fair-price conditions apply | `nK*x` | `nP*y` | Conservative total gross range `0` through `nK+nP`; no evidenced complement relation |
| Suspension, abandonment, forfeit, disqualification, venue/designation change or outcome review | Separately governed result or fair price; exact applicability partly unknown | Separately governed result or LFMP; exact applicability partly unknown | No complete joint enumeration or guaranteed offset is established |

The Kalshi family documents additionally distinguish early suspension from
55 minutes of play or an official final declaration. The US general guidance
uses the governing body's official threshold and the contract's expiration.
These details cannot be reduced to one shared cancellation/refund state. Kalshi's
selected first-start condition is an elapsed-time condition; the US selected
condition is a rescheduled-date condition. The exact US cutoff timezone,
expiration binding and equality treatment require selected evidence; converting
two weeks into an assumed 336-hour clock is insufficient.

LFMP is not an entry-price refund, the last traded quote, the current bid/ask, or
a shared number across venues. The US guidance identifies the relevant fair
market price around the applicable announcement; Kalshi retains its own fair-price
determination. No `x+y=1` constraint is evidenced for these separately settled,
opposing positions. Their observation and resolution times may differ.

For each state the independent accounting expression remains:

```text
profit = nK*rK + nP*rP + returned holds + fee refunds
         - acquisition - entry fees - funded holds - consumed allowances
         - settlement charges - one buffer
```

Refundable holds consume their own venue funding and return only under supported
state-specific terms. Consumed allowances remain costs. The buffer is applied
once to the actual deployed-funding basis. This review supplies no legal quantity,
actual fee, settlement rounding, hold, refund or actual-net dollar amount. Without
these facts there is no numeric actual-net lower bound. Independent unknown
terminal prices supply only a conservative zero gross lower bound, which cannot
establish a strictly positive funded guarantee.

## Retained-price arithmetic and classification

At the fresh retained intake the asks were Kalshi `$0.5700` and US `$0.4350`.
Their sum is `$1.0050`. At the earlier intake the sum was `$1.0025`. These quotes
are historical observations by the time of this report. The fresh US original was
already older than 30 seconds at its intake and the cross-leg source skew exceeded
30 seconds; no current execution or paired-price authority is asserted.

For any positive quantities, with `pK+pP > 1`:

```text
worst decisive gross receipt = min(nK,nP)
acquisition = pK*nK+pP*nP >= (pK+pP)*min(nK,nP) > min(nK,nP)
```

Thus unequal sizing cannot create a positive decisive margin from these captured
asks under nonnegative incremental costs. With one mathematical unit on each leg,
the fresh prefee loss is `$0.005`; an illustrative single 0.5% acquisition-only
buffer adds `$0.005025`, giving `-$0.010025`. This is an exact algebra example,
not an executable legal quantity or a substituted fee/funding model. The
[bounded arithmetic receipt](../test-results/sc07-hou-jac/settlement/cashflow-bounds.json)
retains the formulas and historical branch bounds.

**Covered outcome arb:** unqualified; exceptional joint cashflows and mandatory
execution/accounting inputs are incomplete, and no positive complete minimum is
established. **Conditional hedge:** a future fully qualified allocation could earn
this category only with a positive decisive minimum and explicit adverse/unknown
states. These captured asks fail that positive decisive test before costs. They
are not a positive conditional hedge. **EV:** remains separate and unavailable
without supported current reference/probability facts. Reference absence does not
block these reference-free cashflow bounds, and probabilities cannot remove a
feasible adverse cashflow state.

## Smallest remaining implementation/evidence step

No production model expiry, selected facet, native scope or catalog was changed.
The templates and native source-rule horizons still expired October 16 at
04:00 UTC; retained selected facts still do not provide complete selected facets.
The existing terminal entry-mark proxy is disclosed estimated content and cannot
be promoted to actual fair-price settlement. The current joint evaluator's refusal
to claim complete cashflows for incomparable completion clauses is appropriate.

If the already authorized source owner can retain the exact selected series'
governing contract URL/version through its permitted existing path, review that
binding and any selected override before a narrowly scoped overtime attachment.
Keep distinct elapsed-start and rescheduled-date conditions and independent fair
price unknowns; never replace them with a common refund. Unknown terminal payout
may stay null with a range and a reason. Any later interval-capable evaluation
would need explicit reviewed bounds and a complete feasible joint-state proof.

No additional public-document URL is proposed by this retained-only audit. The
known primary URLs are already retained; fetching the same PDF again would not
establish selected linkage, amendment applicability, current fees or legal sizing.
