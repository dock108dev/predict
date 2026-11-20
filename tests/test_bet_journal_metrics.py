"""Independent cashflow/clock examples for personal bet measurement."""

from copy import deepcopy
from fractions import Fraction as F

from app.dashboard.bet_journal_metrics import analyze


CREATED = "2026-11-18T12:00:00+00:00"
CLOSE = "2026-11-18T13:59:00+00:00"
KICKOFF = "2026-11-18T14:00:00+00:00"
AFTER = "2026-11-18T15:00:00+00:00"


def quote(
    *,
    identifier="one",
    side="home",
    probability="0.5",
    clock=CREATED,
    odds="+120",
    cost="100",
    win="220",
    book="fanduel",
):
    row = dict(
        id=identifier,
        bet_id="bet-" + side,
        venue=identifier,
        kickoff=KICKOFF,
        side=side,
        arb_key="same-exact-line",
        game_key="game-one",
        family="moneyline",
        period="full_game",
        selection=dict(participant=side, predicate="win"),
        posted=dict(value=odds, units="american_odds"),
        times=dict(source_at=clock, received_at=clock),
        observed_at=clock,
        reference=dict(
            book=book,
            probability=probability,
            candidate_probabilities={"fanduel": probability, "draftkings": probability},
            prices=[
                dict(side=s, price_american="-110", source_at=clock)
                for s in ("home", "away")
            ],
        ),
        fee=dict(
            committed_usd=cost,
            cashflows=dict(
                win=dict(net_receipt_usd=win), loss=dict(net_receipt_usd="0")
            ),
        ),
        raw=dict(net_ev="0.1"),
    )
    return row


def entry(snapshot=None, trade=None):
    return dict(
        id="entry",
        kind="ev",
        snapshot=snapshot or quote(),
        created_at=CREATED,
        decision="placed" if trade else "observed",
        trade=trade,
    )


def actual():
    return dict(
        legs=[
            dict(
                quote_id="one",
                stake="50",
                price="+110",
                units="american_odds",
                entry_fee="1",
                win_fee="2",
                loss_fee="1",
            )
        ],
        placed_at=CREATED,
    )


def test_outcome_results_use_actual_pre_fee_prices_and_known_charges():
    for outcome, receipt, profit in (
        ("win", "103", "52"),
        ("loss", "-1", "-52"),
        ("push", "50", "-1"),
    ):
        trade = actual()
        trade["result"] = dict(outcomes=[outcome], settled_at=AFTER)
        measured = analyze(entry(trade=trade), [], at=AFTER)
        assert measured["settlement"]["state"] == "calculated"
        assert measured["settlement"]["receipts_usd"] == [receipt]
        assert measured["realized_profit_usd"] == profit
        assert F(measured["realized_roi"]) == F(profit) / 51
        assert measured["legs"][0]["cashflows"] == dict(
            entry_cost_usd="51",
            win_receipt_usd="103",
            loss_receipt_usd="-1",
            push_receipt_usd="50",
        )


def test_two_leg_results_are_per_leg_and_include_push_entry_costs():
    left, right = quote(), quote(identifier="two", side="away")
    trade = actual()
    trade["legs"].append(
        dict(
            quote_id="two",
            stake="40",
            price="0.4",
            units="probability",
            entry_fee="2",
            win_fee="3",
            loss_fee="0",
        )
    )
    saved = entry(dict(id="pair", kickoff=KICKOFF, legs=[left, right]), trade=trade)
    saved["kind"] = "arb"
    for outcomes, receipts, profit in (
        (["win", "loss"], ["103", "0"], "10"),
        (["loss", "win"], ["-1", "97"], "3"),
        (["push", "push"], ["50", "40"], "-3"),
    ):
        trade["result"] = dict(outcomes=outcomes, settled_at=AFTER)
        measured = analyze(saved, [], at=AFTER)
        assert measured["settlement"]["receipts_usd"] == receipts
        assert measured["settlement"]["entry_cost_usd"] == "93"
        assert measured["realized_profit_usd"] == profit


def test_unknown_fees_preserve_reported_outcome_and_unknown_profit():
    trade = actual()
    trade["legs"][0].update(
        entry_fee=None, win_fee=None, loss_fee=None, fee_basis="unavailable"
    )
    for outcome in ("win", "loss", "push"):
        trade["result"] = dict(outcomes=[outcome], settled_at=AFTER)
        measured = analyze(entry(trade=trade), [], at=AFTER)
        assert measured["settlement"]["outcomes"] == [outcome]
        assert measured["settlement"]["state"] == "unavailable"
        assert measured["realized_profit_usd"] is None
        assert measured["settlement"]["receipts_usd"] == (
            ["50"] if outcome == "push" else [None]
        )


def test_only_fees_used_by_reported_outcome_are_required():
    trade = actual()
    trade["legs"][0]["win_fee"] = None
    trade["result"] = dict(outcomes=["loss"], settled_at=AFTER)
    measured = analyze(entry(trade=trade), [], at=AFTER)
    assert measured["realized_profit_usd"] == "-52"
    assert measured["legs"][0]["cashflows"]["win_receipt_usd"] is None
    trade["result"] = dict(outcomes=["push"], settled_at=AFTER)
    measured = analyze(entry(trade=trade), [], at=AFTER)
    assert measured["realized_profit_usd"] == "-1"
    trade["result"] = dict(outcomes=["win"], settled_at=AFTER)
    measured = analyze(entry(trade=trade), [], at=AFTER)
    assert measured["settlement"]["state"] == "unavailable"
    assert measured["realized_profit_usd"] is None


def test_closing_alias_ignores_only_label_and_preserves_every_economic_selection_field():
    original = quote()
    original["family"] = "spread"
    original["selection"] = dict(
        participant="home", predicate="cover", signed_line="-1.5", label="Home -1.5"
    )
    alias = deepcopy(original)
    alias.update(
        id="new-native-id",
        times=dict(source_at=CLOSE, received_at=CLOSE),
        observed_at=CLOSE,
    )
    alias["selection"]["label"] = "A different display name"
    measured = analyze(entry(original), [alias], at=AFTER)
    assert measured["legs"][0]["latest_quote"]["id"] == alias["id"]
    assert measured["legs"][0]["close_quote"]["id"] == alias["id"]
    for key, value in (
        ("signed_line", "-2.5"),
        ("participant", "away"),
        ("predicate", "win"),
        ("new_economic_term", "different"),
    ):
        wrong = deepcopy(alias)
        wrong["selection"][key] = value
        measured = analyze(entry(original), [wrong], at=AFTER)
        assert measured["legs"][0]["latest_quote"]["id"] != alias["id"]
        assert measured["legs"][0]["close_quote"]["id"] != alias["id"]


def test_nullable_or_unavailable_references_keep_fee_only_arb_results():
    left, right = quote(), quote(identifier="two", side="away")
    snapshot = dict(
        id="fee-only-pair", kickoff=KICKOFF, legs=[left, right], return_rate="0.1"
    )
    for reference in (
        None,
        {},
        [],
        "unavailable",
        1,
        dict(left["reference"], candidate_probabilities=["0.5", "0.5"]),
        dict(left["reference"], candidate_probabilities="unavailable"),
    ):
        original = deepcopy(snapshot)
        for row in original["legs"]:
            row["reference"] = deepcopy(reference)
        closing = deepcopy(original["legs"])
        for row in closing:
            row.update(
                times=dict(source_at=CLOSE, received_at=CLOSE), observed_at=CLOSE
            )
        saved = entry(original)
        saved["kind"] = "arb"
        measured = analyze(saved, closing, at=AFTER)
        assert measured["entry_probability_basis"]
        assert measured["entry_ev"] is None and measured["close_ev"] is None
        assert measured["entry_min_profit_usd"] == "20"
        assert measured["close_min_profit_usd"] == "20"
        assert all(
            leg["entry_probability"] is None and leg["close_probability"] is None
            for leg in measured["legs"]
        )


def test_actual_odds_fees_expected_value_close_and_cash_result():
    trade = actual()
    trade["result"] = dict(receipts_usd=["103"], settled_at=AFTER)
    saved = entry(trade=trade)
    original = deepcopy(saved)
    closing = quote(probability="0.6", clock=CLOSE, odds="+100", win="200")
    measured = analyze(saved, [closing], at=AFTER)
    assert measured["basis"] == "reported_trade"
    assert measured["observed_ev"] == "0.1"
    assert measured["entry_cost_usd"] == "51"
    assert measured["entry_ev"] == "0"  # .5*103 + .5*(-1) - 51
    assert F(measured["close_ev_usd"]) == F("10.4")
    assert F(measured["close_ev"]) == F(52, 255)
    assert F(measured["close_market_ev"]) == F("0.2")
    assert measured["legs"][0]["clv"] == "0.05"  # 2.1 / 2 - 1
    assert measured["legs"][0]["fair_clv"] == "0.26"  # 2.1 * .6 - 1
    assert measured["legs"][0]["probability_move"] == "0.1"
    assert measured["legs"][0]["close_gap_seconds"] == 60
    assert measured["realized_profit_usd"] == "52"
    assert F(measured["realized_roi"]) == F(52, 51)
    assert saved == original  # Measuring never edits the saved model or trade.


def test_pre_kickoff_quotes_are_latest_observations_until_close():
    measured = analyze(
        entry(), [quote(clock=CLOSE, probability="0.6")], at="2026-11-18T13:59:30+00:00"
    )
    assert measured["close_state"] == "tracking"
    assert measured["close_ev"] is None
    assert measured["legs"][0]["close_quote"] is None
    assert measured["legs"][0]["latest_quote"]["observed_at"] == CLOSE
    assert measured["legs"][0]["clv"] is None


def test_post_kickoff_receipts_and_late_imports_cannot_become_closes():
    bad_source = quote(clock=KICKOFF, probability="0.9")
    bad_receipt = quote(clock=CLOSE, probability="0.9")
    bad_receipt["times"]["received_at"] = KICKOFF
    bad_receipt["observed_at"] = AFTER
    late_import = quote(clock=CLOSE, probability="0.9")
    late_import["observed_at"] = AFTER
    measured = analyze(entry(), [bad_source, bad_receipt, late_import], at=AFTER)
    # Original quote remains the last proven pregame observation, with a 2h gap.
    assert measured["legs"][0]["close_gap_seconds"] == 7200
    assert measured["legs"][0]["close_probability"] == "0.5"
    assert measured["entry_ev"] == "0.1"


def test_missing_source_time_does_not_masquerade_as_a_closing_quote():
    original = quote()
    original["times"]["source_at"] = None
    measured = analyze(entry(original), [], at=AFTER)
    assert measured["close_state"] == "missing"
    assert measured["legs"][0]["close_quote"] is None
    assert measured["close_ev"] is None


def test_exact_line_alias_allowed_but_other_line_and_occurrence_rejected():
    alias = quote(identifier="alias", clock=CLOSE, probability="0.6")
    alias["venue"] = "one"
    other_line = quote(clock="2026-11-18T13:59:50+00:00", probability="0.9")
    other_line["id"] = "different"
    other_line["bet_id"] = "different-line"
    other_line["selection"] = dict(
        participant="home", predicate="cover", signed_line="-1.5"
    )
    other_game = quote(clock="2026-11-18T13:59:55+00:00", probability="0.9")
    other_game["kickoff"] = "2026-11-19T14:00:00+00:00"
    measured = analyze(entry(), [alias, other_line, other_game], at=AFTER)
    assert measured["legs"][0]["close_quote"]["id"] == "alias"
    assert measured["legs"][0]["close_probability"] == "0.6"


def test_opposite_sportsbook_template_bet_id_is_not_the_same_selection():
    opposite = quote(
        identifier="book-alias", side="away", clock=CLOSE, probability="0.9"
    )
    opposite["venue"] = "one"
    opposite["bet_id"] = "bet-home"  # inherited template identity, not its selection
    measured = analyze(entry(), [opposite], at=AFTER)
    assert measured["legs"][0]["close_probability"] == "0.5"
    assert measured["legs"][0]["close_quote"]["id"] == "one"


def test_reported_entry_uses_latest_reference_retained_by_placement():
    trade = actual()
    trade["placed_at"] = "2026-11-18T13:00:00+00:00"
    before_fill = quote(clock="2026-11-18T12:59:00+00:00", probability="0.6")
    after_fill = quote(clock="2026-11-18T13:01:00+00:00", probability="0.9")
    measured = analyze(entry(trade=trade), [before_fill, after_fill], at=AFTER)
    assert measured["observed_ev"] == "0.1"
    assert measured["legs"][0]["entry_probability"] == "0.6"
    assert measured["legs"][0]["entry_reference_at"] == before_fill["observed_at"]
    assert measured["legs"][0]["entry_reference_gap_seconds"] == 60
    assert measured["entry_ev_usd"] == "10.4"


def test_reference_retained_after_placement_cannot_backfill_entry_knowledge():
    trade = actual()
    trade["placed_at"] = "2026-11-18T11:00:00+00:00"
    measured = analyze(entry(trade=trade), [quote(clock=CLOSE)], at=AFTER)
    assert measured["entry_ev"] is None
    assert measured["legs"][0]["entry_reference_quote"] is None


def test_saved_draft_with_settlement_does_not_enter_realized_profit():
    trade = actual()
    trade["result"] = dict(receipts_usd=["103"], settled_at=AFTER)
    saved = entry(trade=trade)
    saved["decision"] = "saved"
    measured = analyze(saved, [], at=AFTER)
    assert measured["realized_profit_usd"] is None


def test_reference_knowledge_does_not_travel_back_to_entry_or_close():
    original = quote()
    for price in original["reference"]["prices"]:
        price["source_at"] = CLOSE
    closing = quote(clock=CLOSE, probability="0.8")
    for price in closing["reference"]["prices"]:
        price["received_at"] = AFTER
    measured = analyze(entry(original), [closing], at=AFTER)
    assert measured["entry_ev"] is None
    assert measured["close_ev"] is None
    assert measured["legs"][0]["clv"] is not None


def test_missing_actual_fee_never_uses_original_model_fee():
    trade = actual()
    del trade["legs"][0]["loss_fee"]
    measured = analyze(entry(trade=trade), [quote(clock=CLOSE)], at=AFTER)
    assert measured["entry_cost_usd"] is None
    assert measured["entry_ev"] is None
    assert "incomplete" in " ".join(measured["reasons"])


def test_contract_probability_price_and_fractional_cash_are_exact():
    trade = actual()
    trade["legs"][0].update(
        price="0.4",
        units="probability",
        stake="10",
        entry_fee="0",
        win_fee="0.03",
        loss_fee="0",
    )
    measured = analyze(
        entry(trade=trade), [quote(clock=CLOSE, odds="+100", win="200")], at=AFTER
    )
    assert measured["legs"][0]["entry_decimal"] == "2.5"
    assert measured["entry_ev_usd"] == "2.485"
    assert measured["legs"][0]["clv"] == "0.25"


def test_arb_retains_negative_closing_margin_without_inventing_ev():
    left = quote(odds="+110", cost="50", win="105")
    right = quote(identifier="two", side="away", odds="+110", cost="50", win="105")
    for row in (left, right):
        row.pop("reference")
    saved = entry(
        dict(id="pair", kickoff=KICKOFF, legs=[left, right], return_rate="0.05")
    )
    saved["kind"] = "arb"
    close_left = quote(clock=CLOSE, odds="-110", win="2100/11")
    close_right = quote(
        identifier="two", side="away", clock=CLOSE, odds="-110", win="2100/11"
    )
    close_left.pop("reference")
    close_right.pop("reference")
    measured = analyze(saved, [close_left, close_right], at=AFTER)
    assert measured["entry_min_profit_usd"] == "5"
    assert measured["entry_arb_return"] == "0.05"
    assert F(measured["close_min_profit_usd"]) == F(-100, 11)
    assert F(measured["close_arb_return"]) == F(-1, 22)
    assert measured["entry_ev"] is None
    assert measured["close_ev"] is None


def test_arb_ev_requires_same_complementary_probability_model():
    left = quote(odds="+110", cost="50", win="105", probability="0.6")
    right = quote(
        identifier="two",
        side="away",
        odds="+110",
        cost="50",
        win="105",
        probability="0.4",
    )
    saved = entry(
        dict(id="pair", kickoff=KICKOFF, legs=[left, right], return_rate="0.05")
    )
    saved["kind"] = "arb"
    measured = analyze(saved, [], at=AFTER)
    assert measured["entry_ev"] == "0.05"
    saved["snapshot"]["legs"][1]["reference"]["book"] = "different"
    measured = analyze(saved, [], at=AFTER)
    assert measured["entry_ev"] is None


def test_closing_basis_prefers_monitored_source_over_saved_arb_allocation():
    left = quote(odds="+120", cost="48", win="105.6")
    right = quote(identifier="two", side="away", odds="+100", cost="52", win="104")
    saved = entry(
        dict(id="pair", kickoff=KICKOFF, legs=[left, right], return_rate="0.04")
    )
    saved["kind"] = "arb"
    canonical_left = quote(odds="+120", cost="100", win="220")
    canonical_right = quote(
        identifier="two", side="away", odds="+100", cost="100", win="200"
    )
    # All clocks are exactly equal. The source comparison must win the tie,
    # regardless of insertion order or the saved pair's 48/52 budget allocation.
    measured = analyze(saved, [canonical_left, canonical_right], at=AFTER)
    assert measured["entry_cost_usd"] == "100"
    assert measured["entry_min_profit_usd"] == "4"
    assert measured["close_cost_usd"] == "200"
    assert measured["close_min_profit_usd"] == "0"
    assert measured["legs"][0]["close_quote"]["fee"]["committed_usd"] == "100"
    assert measured["legs"][1]["close_quote"]["fee"]["committed_usd"] == "100"


def test_same_contract_id_cannot_override_conflicting_exact_selection():
    wrong = quote(clock=CLOSE, probability="0.9", side="away")
    measured = analyze(entry(), [wrong], at=AFTER)
    assert measured["legs"][0]["close_probability"] == "0.5"


def test_result_is_only_realized_after_reported_settlement_time():
    trade = actual()
    trade["result"] = dict(receipts_usd=["103"], settled_at="2026-11-19T15:00:00+00:00")
    measured = analyze(entry(trade=trade), [], at=AFTER)
    assert measured["realized_profit_usd"] is None


def test_single_trusted_book_cannot_supply_entry_or_closing_ev():
    original = quote()
    original["reference"]["candidate_probabilities"] = {
        "fanduel": "0.5",
        "casumo": "0.4",
    }
    measured = analyze(entry(original), [], at=AFTER)
    assert measured["entry_ev"] is None
    assert measured["close_ev"] is None
    assert measured["legs"][0]["fair_clv"] is None


def test_closing_fair_odds_and_book_prices_keep_independent_market_clock():
    original = quote()
    market = quote(clock=CLOSE, odds="+115")
    reference = quote(
        clock="2026-11-18T13:58:00+00:00", probability="0.4", book="draftkings"
    )
    reference["journal_reference_only"] = True
    reference["reference"]["selected_outcome"] = "home"
    reference["observed_at"] = CLOSE
    result = analyze(entry(original), [market, reference], at=AFTER)
    leg = result["legs"][0]
    assert leg["close_quote"]["posted"]["value"] == "+115"
    fair = leg["closing_fair"]
    assert fair["book"] == "draftkings"
    assert fair["fair_odds"] == "+150"
    assert fair["posted_odds"] == "-110"
    assert fair["source_at"] == "2026-11-18T13:58:00+00:00"
    assert leg["close_quote"]["times"]["source_at"] == CLOSE


def test_alternate_estimate_is_a_closing_model_not_a_reported_entry_reference():
    trade = actual()
    trade["placed_at"] = "2026-11-18T12:01:00+00:00"
    estimate = quote(clock="2026-11-18T12:00:30+00:00", probability="0.4")
    estimate["journal_reference_only"] = True
    estimate["reference"]["closing_basis"] = "alternate_line_interpolation"
    result = analyze(entry(trade=trade), [estimate], at=AFTER)
    assert result["legs"][0]["entry_probability"] == "0.5"
    assert result["legs"][0]["close_probability"] == "0.4"
