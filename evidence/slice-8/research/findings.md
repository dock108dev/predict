# Slice 8 official rule review

Reviewed September 12, 2026 UTC by **Codex (engineering technical assessment)**.
No owner acceptance or compatible-pair approval is recorded. Exact retrieved bytes,
URLs, capture times and hashes are in `sources.json`. Effective dates were not
published in these retrieved documents; retrieval time is not an effective date.

## Kalshi

The current [FOOTBALLGAMEWIN terms](https://assets.kalshi.com/contract_terms/FOOTBALLGAMEWIN.pdf)
have SHA-256 `19578b71cd63da63cc2894c60542ef06bb5de56b9366add56f07cee645cfca4b`,
identical to the preserved Phase 0 PDF. The captured KXNFLGAME series explicitly
links this document; the five confirmed event records identify Game scope.
Pages 1–2 establish full-game overtime as the default. Market-specific primary
criteria identify the YES team. The NO subtitle is not the opposing team identity:
these captures repeat the same team in both subtitles.

Listing terms establish a half-dollar two-team tie and commencement within 48 hours
of original start. General terms distinguish suspension before/after 55 minutes,
official final results, pre-kickoff forfeits at discretionary fair value, and
home/away reversal. They also specify source hierarchy and review exceptions.
These clauses are retained in each profile's general source, without pretending
that the counterpart venue has equivalent exceptional branches.

## Polymarket US

The [market schema](https://docs.polymarket.us/api-reference/markets/get-market-by-slug)
defines `marketSides.id`, `marketId`, `long` and `teamId`. Captures supply both
team IDs and associated team objects; their consistency is checked against the
existing normalization registry. Display order, prices and stringified outcomes
are unused.

The [sports guidance](https://docs.polymarket.us/faqs/sports-faqs) describes fractional
ties, overtime, source fallbacks, result review and venue-determined fair value.
Its general rescheduling guidance uses expiration, while these exact listings
instead specify rescheduling to a date within two days. The listing takes priority.
The public wording does not establish that this requires actual commencement
within 48 hours of the original instant. Broad forfeit-winner guidance and
pre-event-withdrawal treatment also leave the precise pre-kickoff NFL branch
unclear. General guidance cannot resolve these listing-specific questions alone.

## Narrow remaining questions

1. Does each PMUS listing's two-day clause require commencement, and what timezone
   and date boundary apply? How does it interact with suspension and expiration?
2. Do shortened/suspended-game branches agree at the Kalshi 55-minute threshold,
   including an official final result before that threshold?
3. Which PMUS clause controls a pre-kickoff NFL forfeit? How do cancellation,
   abandonment and home/away reversal interact with listing exceptions?
4. Do fallback source priority, first-final/corrected results, early expiration
   and outcome-review extensions yield the same controlling result?
5. What evidence, if any, makes independently determined fair-value payouts equal
   or complementary? No numeric fair value can be inferred from a market quote.

All ten production structural pairs remain UNKNOWN. No specific conflicting
terminal payout is proved for these pairs by the currently pinned assessment;
this does not imply all their rules agree. Synthetic refund/fraction and different
postponement windows demonstrate INCOMPATIBLE separately. These unresolved
pair-specific conditions do not block completion of Slice 8 or implementation of
Slice 9. No venue contact or support letter is required for this handoff.
