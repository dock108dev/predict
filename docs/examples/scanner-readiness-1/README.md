# Readiness consumer examples

All examples here are **authored offline fixtures**, using historical retained shapes with explicit synthetic current clocks/grids/second-leg assumptions. They establish protocol behavior, never live sources, model renewal, profitable opportunities or customer acceptance.

- `waiting.json`: no observations; not evaluated.
- `ready-missing-ev-reference.json`: ready authored cashflow input pair with an EV-reference refusal; no profitability claim.
- `partial-with-blocked-scope.json`: one healthy pair and another blocked observed instrument; causes overlap.
- `authoritative-evaluated-zero.json`: a complete trusted authored scanner receipt set reports zero qualifying pairs for its selected admitted set.
- `authored-sc02-evaluation-receipt.json`: the exact fixture receipt, not an HTTP write request.

Validate these authored examples with the [readiness schema](../../contracts/predict-scanner-readiness-1.schema.json). Current source qualification and actual customer acceptance require separate evidence.
