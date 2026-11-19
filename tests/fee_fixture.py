"""Explicit fee outcomes for isolated payoff tests; never installed with the app."""

from copy import deepcopy
from functools import wraps
from fractions import Fraction
from unittest.mock import patch

from app.comparison.cashflows import exact_wire


def authored_fee_outcomes(test):
    """Inject captured fee outcomes while exercising ordinary allocation logic.

    These tests vary hypothetical fees to check ranking, reserves and publication
    identity. Production code must never interpret their fictional rate.
    """

    @wraps(test)
    def run(*args, **kwargs):
        from app.comparison import snapshot_pair_fees as module

        original = module._leg_fee

        def captured(row, **allocation):
            fee = row.get("trade_fee") or {}
            if (
                (row.get("source") or {}).get("provider") == "practice"
                and fee.get("classification") == "synthetic"
                and fee.get("available")
            ):
                row = deepcopy(row)
                fee = row["trade_fee"]
                fee["quantity"] = exact_wire(allocation["quantity"])
                fee["fee_cashflows"]["at_fill_usd"] = exact_wire(
                    Fraction(fee["evidence"]["fictional_rate"]) * allocation["stake"]
                )
            return original(row, **allocation)

        with patch.object(module, "_leg_fee", captured):
            return test(*args, **kwargs)

    return run
