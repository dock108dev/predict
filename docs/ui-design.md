# Interface design

The ordinary SQL-backed interface presents saved server calculations. Browser
code validates context and renders values; it does not calculate fees, allocation
or settlement. See [saved-board API](comparison-board-api-contract.md).

## Views and financial meaning

**Odds** groups available winner prices by game and participant, with a separate
named fair benchmark. Original native alternatives remain inspectable; missing
prices do not become synthetic offers.

**EV** shows single-trade expected value after modeled costs, rule effects and one
buffer. Complete-state EV and conditional decisive-outcome EV have different
labels. Negative and unavailable results remain available through All comparisons.

**Arbs** shows opposing legs and their shared funding, decisive margin and minimum
over modeled outcomes. Rule-sensitive hedges are separate from pairs positive
across every modeled state. No positive opportunity is a normal result.

The policy line names requested dollars, fees and buffer. A pair shares the amount
across both legs. Reduced size or residual funding has a stated reason. Details
starts with the result and quantities, then reconciles gross value, rule adjustment,
fees, net estimate and one buffer. It discloses exceptional states, provisional
probabilities and modeled liquidity; original evidence sits in expandable sections.

## Interaction and accessibility

Apply and Enter submit the same settings; Restore returns to defaults. Navigation
preserves settings and selected game. Changing settings withholds mismatched old
results. Saved Details stays pinned to exact result and quote/pair identities;
new arrivals cannot silently replace the selection. Reads do not acquire data.

Use light surfaces, slate text, restrained blue actions, 16px body text and controls
at least 44px high. Preserve visible focus, wrap long names and financial strings,
and respect reduced motion. Do not rely on color alone. Desktop venue columns
align; narrow layouts label values. Dialogs support a focus loop, Escape/Close
and focus return to the opening control.

First use offers the Admin source screen when no game is available. Positive-only
empty states offer All comparisons. Failed reads offer Retry with a useful reason;
pending calculations remain explicit. Normal boards keep source/as-of labels
simple; detailed quota, journal and recovery information belongs in Admin. A
connection heartbeat or saved-calculation timestamp never renews an old quote.

[Development](development.md#frontend-sources) explains readable frontend modules,
generated public assets and the tests for these boundaries.
