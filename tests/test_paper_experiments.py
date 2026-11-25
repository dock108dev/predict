"""Paper policy: threshold, sized fees, stable tickets, cross-venue selection and cash exposure."""

from contextlib import nullcontext
import asyncio
from copy import deepcopy
from fractions import Fraction as F
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.comparison import fee_mode, fixed_profit
from app.dashboard.paper_api import mount
from app.dashboard.request_guard import dashboard_guard
from app.research import paper, paper_evidence
from app.storage.store import stamp
from tests.test_ev_movement import offer, checkpoint

AT = "2026-11-23T17:50:00Z"


def priced(odds="-110", ev=".04", venue="kalshi", line="-3"):
    b = F(odds)/100 if F(odds)>0 else 100/-F(odds)
    p = (1+F(ev))/(1+b)
    row = offer(str(100*(1+b)), probability=str(p), book=venue, line=line)
    row["record"]["quote"]["original"]["value"] = odds
    row["fee_input"] = dict(available=True)
    return row


def linear(record, reference, fee, *, at, game_key, amount):
    odds = F(record["quote"]["original"]["value"])
    b = odds/100 if odds>0 else 100/-odds
    p = F(reference["probability"])
    return dict(reference=reference, fee=dict(committed_usd=str(amount), purchase_usd=str(amount),
        cashflows=dict(win=dict(net_receipt_usd=str(amount*(1+b))),loss=dict(net_receipt_usd="0"))),
        raw=dict(net_ev=str(p*(1+b)-1)), display=dict(posted_odds=str(odds)))


def entries(*rows):
    with patch.object(paper.math,"calculate",side_effect=linear):
        return paper.candidates(checkpoint(*rows), game_id="g",checkpoint_id="late-frozen",at=AT)


def frozen_priced(odds, *, venue="prophetx", ev=".08", rule=None, fee=None, grid=None,
                  line="-3", side="home", main=True):
    row = priced(odds, ev=ev, venue=venue, line=line)
    record = row["record"]
    record["selection"]["participant"] = side
    record["comparison_source_metadata"]["alternate"] = not main
    quote = record["quote"]
    quote["source"].update(native_market_id="market", native_outcome_id="home", native_side="bookmaker_outcome")
    if grid:
        quote["source"].update(provider=venue, native_side="Long")
        quote["original"].update(units="usd_per_contract", value="0.2")
        record["comparison_source_metadata"]["public_retail_observation"] = dict(
            market_id="market", instrument_id="home", material_sha256="x" * 64,
            values=dict(minimumTradeQty=grid[0], orderPriceMinTickSize=grid[1]))
    ref = row["calculation_payload"]["reference"]
    ref.update(fair_decimal_odds=str(1/F(ref["probability"])), fair_odds="fair")
    if fee is None:
        fee = dict(available=True, classification="fixture", evidence=dict(database_fee_rule=rule)) if rule else (
            fee_mode.zero_fee(record, fee_mode.state(False)))
    row.update(fee_input=fee, calculation_payload=paper.math.calculate(
        record, ref, fee, at=stamp(AT), game_key="g"))
    return row


def fixed_policy(target="10"):
    return dict(paper.POLICY, sizing_mode="fixed_profit", target_profit_usd=target,
                sizing_rule=paper.FIXED_PROFIT_RULE)


@pytest.mark.parametrize("odds,target,ideal,stake,won", [
    ("-110", "10", "11", "11", "10"), ("+500", "10", "2", "2", "10"),
    ("+300", "10", "10/3", "3.33", "9.99"), ("+200", ".03", ".015", ".01", ".02"),
    ("+200", ".01", ".005", ".01", ".02"),
])
def test_fixed_profit_at_saved_stake_grid(odds, target, ideal, stake, won):
    tickets, gaps = paper.candidates(checkpoint(frozen_priced(odds)), game_id="g", checkpoint_id="frozen",
                                      at=AT, policy=fixed_policy(target))
    ticket, = tickets
    assert not gaps
    assert ticket["sizing"]["rule"] == paper.FIXED_PROFIT_RULE
    assert F(ticket["sizing"]["ideal_purchase_usd"]) == F(ideal)
    assert F(ticket["cash_commitment_usd"]) == F(stake)
    assert F(ticket["sizing"]["modeled_win_profit_usd"]) == F(won)
    assert F(ticket["sizing"]["profit_difference_usd"]) == F(won) - F(target)
    assert ticket["kelly_budget_usd"] is None
    fee = ticket["witness"]["sized_calculation"]["fee"]
    assert F(fee["cashflows"]["win"]["net_receipt_usd"]) == F(stake) + F(won)
    assert F(fee["cashflows"]["loss"]["net_profit_usd"]) == -F(stake)


def test_fixed_profit_uses_captured_native_price_and_quantity_grid():
    row = frozen_priced("+400", venue="polymarket_us", grid=("0.25", "0.01"))
    model = fixed_profit.calculate(row, at=stamp(AT), game_key="g", target=F("1.1"))
    assert F(model["sizing"]["quantity_increment"]) == F("0.25")
    assert F(model["sizing"]["price_increment"]) == F("0.01")
    assert F(model["sizing"]["modeled_win_profit_usd"]) == F(1)
    assert F(model["fee"]["quantity"]) == F("1.25")
    row["record"]["comparison_source_metadata"]["public_retail_observation"]["values"]["orderPriceMinTickSize"] = "0.03"
    with pytest.raises(ValueError, match="price_or_quantity_grid_conflict"):
        fixed_profit.calculate(row, at=stamp(AT), game_key="g", target=F("1.1"))


def test_fixed_profit_reprices_frozen_fees_and_handles_nonmonotone_win_grid():
    rule = dict(formula="polymarket_taker", rate="0.09", quantity_step="0.01")
    row = frozen_priced("+100", venue="polymarket_us", rule=rule)
    model = fixed_profit.calculate(row, at=stamp(AT), game_key="g", target=F("0.11"))
    fee = model["fee"]
    # 22 ticks gross $0.11 with no fee. Tick 23 adds $0.005 gross and
    # moves the fee from zero to one cent. Tick 24 also nets $0.11.
    assert F(fee["quantity"]) == F("0.22")
    assert F(fee["entry_usd"]) == 0
    assert F(row["calculation_payload"]["fee"]["entry_usd"]) > 0
    assert F(fee["cashflows"]["win"]["net_profit_usd"]) == F("0.11")


def test_fixed_profit_can_cross_large_quantity_intervals_at_the_same_rounded_fee():
    rule = dict(formula="polymarket_taker", rate="0.09", quantity_step="0.000000001")
    row = frozen_priced("+100", venue="polymarket_us", rule=rule)
    model = fixed_profit.calculate(row, at=stamp(AT), game_key="g", target=F("0.125"))
    assert F(model["fee"]["quantity"]) == F("0.27")
    assert F(model["fee"]["entry_usd"]) == F("0.01")
    assert F(model["sizing"]["modeled_win_profit_usd"]) == F("0.125")


def test_fixed_profit_reprices_winning_commission_on_the_actual_stake():
    rule = dict(formula="prophetx_commission", rate="0.025", quantity_step="1")
    row = frozen_priced("+300", rule=rule)
    model = fixed_profit.calculate(row, at=stamp(AT), game_key="g", target=F(10))
    fee, sizing = model["fee"], model["sizing"]
    # At $3.42, $10.26 gross profit incurs $0.26 rounded winning commission.
    assert F(fee["committed_usd"]) == F("3.42")
    assert F(fee["cashflows"]["win"]["settlement_fee_usd"]) == F("0.26")
    assert F(fee["cashflows"]["win"]["net_receipt_usd"]) == F("13.42")
    assert F(fee["cashflows"]["loss"]["net_receipt_usd"]) == 0
    assert F(sizing["modeled_win_profit_usd"]) == 10


def test_post_size_ev_and_venue_selection_use_entire_frozen_candidate_pool():
    rule = dict(formula="polymarket_taker", rate="0.09", quantity_step="0.01")
    a = frozen_priced("+100", venue="polymarket_us", ev=".088", rule=rule)
    b = frozen_priced("+100", venue="prophetx", ev=".041")
    snapshot = checkpoint(a, b)
    kelly_policy = dict(paper.POLICY, sizing_mode="kelly", sizing_scale_usd="250")
    kelly, _ = paper.candidates(snapshot, game_id="g", checkpoint_id="frozen", at=AT, policy=kelly_policy)
    counts = {"evaluated_offers": 0}
    fixed, gaps = paper.candidates(snapshot, game_id="g", checkpoint_id="frozen", at=AT,
                                    policy=fixed_policy(".12"), counts=counts)
    assert paper.portfolios(kelly, as_of=AT)["best_venue"]["tickets"][0]["venue"] == "polymarket_us"
    assert paper.portfolios(fixed, as_of=AT)["best_venue"]["tickets"][0]["venue"] == "prophetx"
    assert gaps == {"sized_ev_below_4pct": 1}
    match = {ticket["venue"]: ticket for ticket in kelly}
    assert fixed[0]["frozen_quote_id"] == match["prophetx"]["frozen_quote_id"]
    assert fixed[0]["id"] != match["prophetx"]["id"]
    assert counts["sizing_exclusions"][0]["frozen_quote_id"] == match["polymarket_us"]["frozen_quote_id"]
    del b["calculation_payload"]["fee"]["quantity_increment"]
    rejected, gaps = paper.candidates(snapshot, game_id="g", checkpoint_id="frozen", at=AT,
                                       policy=fixed_policy(".12"))
    assert not rejected and gaps["fixed_profit_quantity_increment_unavailable"] == 1


def test_minimum_stake_compares_exact_cash_commitment_including_modeled_fees():
    rule = dict(formula="polymarket_taker", rate="0.09", quantity_step="0.01")
    floor = dict(fixed_policy(), minimum_stake_usd="1")
    for odds, expected in (("+1095", F(5978, 5975)), ("+1100", F(299, 300))):
        snapshot = checkpoint(frozen_priced(odds, venue="polymarket_us", ev=".25", rule=rule))
        inputs = dict(game_id="g", checkpoint_id="frozen", at=AT)
        [unrestricted], _ = paper.candidates(snapshot, **inputs, policy=fixed_policy())
        fee = unrestricted["witness"]["sized_calculation"]["fee"]
        assert F(fee["purchase_usd"]) < 1
        assert F(unrestricted["cash_commitment_usd"]) == expected
        assert unrestricted["stake_usd"] == "1.00"
        counts = {"evaluated_offers": 0}
        tickets, gaps = paper.candidates(snapshot, **inputs, policy=floor, counts=counts)
        if expected >= 1:
            assert len(tickets) == 1 and F(tickets[0]["cash_commitment_usd"]) == expected
            assert not gaps
        else:
            assert not tickets and gaps == {"sized_stake_below_minimum": 1}
            [excluded] = counts["sizing_exclusions"]
            assert excluded == dict(frozen_quote_id=unrestricted["frozen_quote_id"], offer_index=0,
                exact_bet_id=unrestricted["exact_bet_id"], reason="sized_stake_below_minimum",
                cash_commitment_usd=str(expected), minimum_stake_usd="1", sized_ev=unrestricted["ev"])


def test_minimum_stake_reselects_best_venue_and_keeps_stake_exactly_at_floor():
    snapshot = checkpoint(frozen_priced("+1500", venue="prophetx", ev=".15"),
                          frozen_priced("+1000", venue="polymarket_us", ev=".06"))
    inputs = dict(game_id="g", checkpoint_id="frozen", at=AT)
    unrestricted, _ = paper.candidates(snapshot, **inputs, policy=fixed_policy())
    assert len(unrestricted) == 2
    assert paper.portfolios(unrestricted, as_of=AT)["best_venue"]["tickets"][0]["venue"] == "prophetx"
    limited, gaps = paper.candidates(snapshot, **inputs, policy=dict(fixed_policy(), minimum_stake_usd="1"))
    [trade] = paper.portfolios(limited, as_of=AT)["best_venue"]["tickets"]
    assert trade["venue"] == "polymarket_us" and trade["cash_commitment_usd"] == "1"
    assert gaps == {"sized_stake_below_minimum": 1}


def test_one_per_game_prefers_probable_main_bet_then_resolves_best_equivalent_quote():
    snapshot = checkpoint(
        frozen_priced("-110", ev=".06"),
        frozen_priced("+305", line="3", side="away", ev=".12"),
        frozen_priced("-105", venue="polymarket_us", ev=".09", main=False),
        frozen_priced("-250", line="-1", ev=".20", main=False),
    )
    rule = paper.MAIN_FIRST_ONE_PER_GAME
    policy = dict(fixed_policy(), portfolio_rule=rule)
    rows, _ = paper.candidates(snapshot, game_id="g", checkpoint_id="frozen", at=AT, policy=policy)
    assert len(rows) == 4
    [picked] = paper.best_tickets(rows, rule)
    assert [picked] == paper.best_tickets(reversed(rows), rule)
    assert picked["line"] == "-3" and picked["side"] == "home" and picked["venue"] == "polymarket_us"
    evidence = picked["portfolio_selection"]
    assert evidence["tier"] == "main" and evidence["ranked_quote_venue"] == "prophetx"
    assert evidence["selected_quote_line_role"] == "alternate"


def test_one_per_game_uses_ineligible_main_anchor_and_compares_away_spreads_on_home_scale():
    snapshot = checkpoint(
        frozen_priced("+102", line="3", side="away", ev=".01"),
        frozen_priced("+150", line="-4", main=False),
        frozen_priced("+110", line="-7", main=False, ev=".20"),
        frozen_priced("+100", line="-3", venue="polymarket_us", main=False),
    )
    rule = paper.MAIN_FIRST_ONE_PER_GAME
    policy = dict(fixed_policy(), portfolio_rule=rule)
    rows, gaps = paper.candidates(snapshot, game_id="g", checkpoint_id="frozen", at=AT, policy=policy)
    assert gaps == {"below_minimum_ev": 1}
    cross_venue = next(t for t in rows if t["venue"] == "polymarket_us")
    assert cross_venue["portfolio_selection"]["basis"] == "other_venue_main_line"
    [picked] = paper.best_tickets([t for t in rows if t is not cross_venue], rule)
    assert picked["line"] == "-4"
    assert picked["portfolio_selection"]["distance_points"] == "1"
    assert picked["portfolio_selection"]["anchor"] == {"line": "-3", "venue": "prophetx", "offer_index": 0}
    [picked] = paper.best_tickets(rows, rule)
    assert picked["id"] == cross_venue["id"]


def test_one_per_game_leaves_unanchored_and_conflicting_lines_in_candidate_evidence():
    alternate = frozen_priced("+130", line="-4", main=False)
    mains = (frozen_priced("+102", ev=".01"), frozen_priced("+102", line="-6", ev=".01"))
    rule = paper.MAIN_FIRST_ONE_PER_GAME
    policy = dict(fixed_policy(), portfolio_rule=rule)
    for snapshot, reason in ((checkpoint(alternate), "main_line_anchor_unavailable"),
                             (checkpoint(alternate, *mains), "main_line_anchor_conflict")):
        rows, _ = paper.candidates(snapshot, game_id="g", checkpoint_id="frozen", at=AT, policy=policy)
        [unranked] = rows
        assert unranked["portfolio_selection"] == {"tier": "unranked", "line_role": "alternate", "reason": reason}
        report = paper.assemble("2026-11-22", AT, policy, [dict(game_id="g", status="captured")], rows, {})
        assert report["portfolios"]["best_venue"]["count"] == report["games"][0]["tickets"] == 0
        assert report["portfolios"]["all_venues"]["count"] == 1
        assert report["portfolios"]["all_venues"]["candidate_pool_only"]
        assert report["games"][0]["selection_audit"] == {"unranked": 1}


def test_one_per_game_treats_two_way_moneyline_as_main_across_multiple_games():
    row = frozen_priced("-125")
    record = row["record"]
    record["market_identity"].update(family="moneyline", line=None)
    record["selection"].update(signed_line=None, predicate="win")
    del record["comparison_source_metadata"]["alternate"]
    reference = row["calculation_payload"]["reference"]
    row["calculation_payload"] = paper.math.calculate(record, reference, row["fee_input"], at=stamp(AT), game_key="g")
    rule = paper.MAIN_FIRST_ONE_PER_GAME
    policy = dict(fixed_policy(), portfolio_rule=rule)
    rows = []
    for game_id in ("other", "g"):
        candidates, gaps = paper.candidates(checkpoint(row), game_id=game_id, checkpoint_id="frozen", at=AT, policy=policy)
        assert not gaps
        rows.extend(candidates)
    picks = paper.best_tickets(rows, rule)
    assert picks == paper.best_tickets(reversed(rows), rule)
    assert [t["game_id"] for t in picks] == ["g", "other"]
    assert all(t["portfolio_selection"]["basis"] == "two_way_moneyline" for t in picks)


@pytest.mark.parametrize("odds,expected", [("-110","110"),("+300","33.33"),("+3000","3.33")])
def test_agreed_kelly_scale_at_4pct(odds,expected):
    tickets,gaps=entries(priced(odds))
    assert not gaps
    assert F(tickets[0]["stake_usd"])==F(expected)
    assert F(tickets[0]["ev"])==F(1,25)


def test_unrounded_threshold_and_no_early_inputs():
    tickets,gaps=entries(priced(ev=".03999999999999999"),priced(ev=".04",line="-4"))
    assert len(tickets)==1
    assert tickets[0]["line"]=="-4"
    assert gaps==dict(below_minimum_ev=1)


def test_best_venue_and_all_share_stable_tickets_but_different_exposure():
    rows=[priced(ev=".07"),priced(ev=".05",venue="polymarket_us"),priced(ev=".04",line="-4")]
    tickets,_=entries(*rows)
    first=paper.portfolios(tickets,as_of=AT)
    assert first["best_venue"]["count"]==2
    assert first["all_venues"]["count"]==3
    assert {t["venue"] for t in first["best_venue"]["tickets"]}=={"kalshi"}
    again,_=entries(*reversed(rows))
    assert {t["id"] for t in again}=={t["id"] for t in tickets}
    assert F(first["all_venues"]["turnover_usd"])>F(first["best_venue"]["turnover_usd"])


def test_material_settlement_differences_prevent_deduplication():
    left,right=priced(),priced(venue="polymarket_us")
    right["record"]["result_policy"]="regulation_only"
    tickets,_=entries(left,right)
    assert paper.portfolios(tickets,as_of=AT)["best_venue"]["count"]==2


def test_duplicate_offer_is_not_another_trade_and_conflicts_are_excluded():
    row=priced()
    tickets,gaps=entries(row,deepcopy(row))
    assert len(tickets)==1 and gaps["duplicate_offer"]==1
    tickets,gaps=entries(row,priced(ev=".05"))
    assert not tickets and gaps["conflicting_duplicate_offer"]==1


def test_actual_sized_fee_change_below_threshold_excludes_ticket():
    def charged(*args,**kwargs):
        value=linear(*args,**kwargs)
        value["fee"]["cashflows"]["win"]["net_receipt_usd"]=str(F(value["fee"]["cashflows"]["win"]["net_receipt_usd"])-5)
        p=F(value["reference"]["probability"])
        value["raw"]["net_ev"]=str(p*F(value["fee"]["cashflows"]["win"]["net_receipt_usd"])/F(value["fee"]["committed_usd"])-1)
        return value
    with patch.object(paper.math,"calculate",side_effect=charged):
        tickets,gaps=paper.candidates(checkpoint(priced()),game_id="g",checkpoint_id="late",at=AT)
    assert tickets==[] and gaps==dict(sized_ev_below_4pct=1)


def test_peak_cash_uses_result_availability_and_keeps_unresolved_open():
    tickets,_=entries(priced(),priced(line="-4"),priced(line="-5"))
    tickets[0]["grading"]=dict(state="win",pnl_usd="100",released_at="2026-11-23T20:00:00Z")
    tickets[1]["decision_at"]="2026-11-23T21:00:00Z"
    tickets[2]["decision_at"]="2026-11-23T21:00:00Z"
    result=paper.summarize(tickets,as_of="2026-11-24T01:00:00Z")
    assert result["turnover_usd"]=="330.00"
    assert result["peak_committed_usd"]=="220.00"
    assert result["outstanding_usd"]=="220.00"
    assert result["resolved"]==1 and result["unresolved"]==2


def test_push_is_unresolved_instead_of_inventing_venue_refund():
    tickets,_=entries(priced())
    result=paper.grade(tickets[0]["identity"],dict(data=dict(final=True,result="completed",home_score=80,away_score=77)),tickets[0]["witness"]["sized_calculation"])
    assert result["state"]=="unresolved"
    assert "push" in result["reason"]


class ReadDB:
    def __init__(self): self.statements=[]
    def __enter__(self): return self
    def __exit__(self,*_): pass
    def transaction(self): return nullcontext()
    def execute(self,sql): self.statements.append(sql)


def test_api_is_read_only_validates_dates_and_binds_export_revision():
    asyncio.run(api_contract())


async def api_contract():
    db=ReadDB()
    app=web.Application(middlewares=[dashboard_guard(None,logger=__name__)])
    mount(app)
    client=TestClient(TestServer(app))
    value=dict(report_revision="a"*64,provider_requests=0,orders_submitted=0)
    await client.start_server()
    with patch("app.dashboard.paper_api.connect",return_value=db),patch.object(paper,"report",return_value=value) as report:
        response=await client.get("/api/research/paper?date=2026-11-23")
        assert response.status==200 and await response.json()==value
        assert "READ ONLY" in db.statements[0]
        response=await client.get("/api/research/paper?date=2026-11-23&export=1&revision="+"a"*64)
        assert response.status==200 and "attachment" in response.headers["Content-Disposition"]
        response=await client.get("/api/research/paper?export=1&revision="+"b"*64)
        assert response.status==409
        for query in ("date=wrong","date=2026-11-31","place_bets=1","export=yes"):
            response=await client.get("/api/research/paper?"+query)
            assert response.status==422
        assert report.call_count==3
    await client.close()


def test_quote_receipt_age_gross_ev_and_modeled_size_use_frozen_witness():
    ticket = dict(venue="novig", posted_odds="+300", probability="13/50", ev="1/25", screen_ev="1/25",
        cash_commitment_usd="33.33", kelly_budget_usd="33.33", fee_mode=dict(enabled=False),
        times=dict(source_at="2026-11-23T18:50:00Z", received_at="2026-11-23T18:50:10.250Z"))
    quote = dict(source=dict(provider="sportsgameodds", native_market_id="derived-market-id", native_outcome_id="odd-id"))
    checkpoint = dict(requested_at="2026-11-23T18:50:09Z", received_at="2026-11-23T18:50:10.250Z")
    sized = dict(raw=dict(posted_decimal="4"), fee=dict(committed_usd="33.33", entry_usd="0",
        cashflows=dict(win=dict(net_receipt_usd="133.32"), loss=dict(net_receipt_usd="0"))))
    value = paper_evidence.inspect(ticket, checkpoint, dict(record=dict(quote=quote)), sized, paper.POLICY)
    assert value["clocks"]["quote_age_at_receipt_seconds"] == 10.25
    assert value["clocks"]["requested_at"] == checkpoint["requested_at"]
    assert value["quote"]["venue_contract_id"] is None
    assert value["quote"]["source_market_key"] == "derived-market-id"
    assert value["gross_ev"] == "1/25"
    assert value["kelly"]["outcome_returns"] == {"win": "3", "loss": "-1"}
    assert value["kelly"]["commitment_usd"] == "33.33"
    assert value["fees"]["paper_assumption"] == "zero_assumed"
    assert value["fees"]["actual_fee_evidence"] == "unknown"
    assert value["size"]["executable_size_usd"] is None
    assert paper_evidence.clock_counts([ticket, dict(times=dict(received_at=ticket["times"]["received_at"]))]) == {
        "tickets": 2, "quote_ages_known": 1, "verified_executable_size": 0, "verified_actual_fees": 0,
    }
