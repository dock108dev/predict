"""Paper policy: threshold, sized fees, stable tickets, cross-venue selection and cash exposure."""

from contextlib import nullcontext
import asyncio
from copy import deepcopy
from fractions import Fraction as F
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.dashboard.paper_api import mount
from app.dashboard.request_guard import dashboard_guard
from app.research import paper
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
