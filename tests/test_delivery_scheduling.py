"""A late finance visit cannot pretend a newer source receipt was captured."""
from datetime import datetime,timezone,timedelta
from app.storage.ordinary_publication import awaiting_aggregate,prioritize_current


def test_component_binding_ignores_only_sources_absent_from_its_contract_population():
    from app.storage.ordinary_publication import component_binding
    from copy import deepcopy
    binding=['policy','settings','epoch',{'paused_sources':[]},{'kalshi':'available','polymarket_us':'available','pinnacle':'available'}]
    original=component_binding(binding,['kalshi','pinnacle'])
    changed=deepcopy(binding);changed[4]['polymarket_us']='resyncing'
    assert component_binding(changed,['kalshi','pinnacle'])==original
    changed[4]['kalshi']='resyncing'
    assert component_binding(changed,['kalshi','pinnacle'])!=original
    changed=deepcopy(binding);changed[3]['paused_sources']=['kalshi']
    assert component_binding(changed,['kalshi','pinnacle'])!=original
    assert component_binding(binding,['kalshi','pinnacle','polymarket_us'])!=original


def test_receipt_watermark_not_calculation_visit_owns_first_delivery():
    at=datetime(2026,11,8,tzinfo=timezone.utc)
    receipts={'event':at-timedelta(seconds=3)}
    facts={'visited_at':at.isoformat(),'aggregate_receipts':{'event':(at-timedelta(minutes=15)).isoformat()}}
    assert awaiting_aggregate(facts,['event'],receipts,at)
    facts['aggregate_receipts']['event']=receipts['event'].isoformat()
    assert not awaiting_aggregate(facts,['event'],receipts,at)
    assert not awaiting_aggregate({},['event'],receipts,at+timedelta(minutes=16))


def test_whole_aggregate_batch_advances_with_rotation_and_both_native_sources():
    at=datetime(2026,11,8,tzinfo=timezone.utc)
    pending=['old','api0','kalshi','us']+[f'quiet{i}' for i in range(8)]+[f'api{i}' for i in range(1,8)]
    scope={k:[k] for k in pending}
    evidence=[dict(event_id=k,venue=v,at=at.isoformat()) for k,v in [('kalshi','kalshi'),('us','polymarket_us')]]
    order=prioritize_current(pending,scope,evidence,at,undelivered={f'api{i}' for i in range(8)})
    assert order[:4]==['old','api0','kalshi','us']
    assert order[4:10]==['quiet0','api1','quiet1','api2','quiet2','api3']
    assert sorted(order)==sorted(pending)


def test_native_slots_advance_undelivered_games_without_losing_fair_work():
    at=datetime(2026,11,8,tzinfo=timezone.utc)
    pending=['old','api0','hot_k','hot_us','api1','api2']
    scope={k:[k] for k in pending}
    evidence=[dict(event_id=k,venue=v,at=(at-timedelta(seconds=age)).isoformat())
        for k,v,age in [('hot_k','kalshi',0),('hot_us','polymarket_us',0),
                        ('api1','kalshi',5),('api2','polymarket_us',5)]]
    order=prioritize_current(pending,scope,evidence,at,material=set(pending),undelivered={'api0','api1','api2'})
    assert order[:4]==['old','api0','api1','api2']
    assert set(order)==set(pending)
    # Once their exact batch watermark advances, ordinary freshest ordering resumes.
    order=prioritize_current(pending,scope,evidence,at,material=set(pending),undelivered=set())
    assert order[:3]==['old','hot_k','hot_us']


def test_novig_fresh_slot_uses_the_live_quote_deadline():
    at=datetime(2026,11,8,tzinfo=timezone.utc)
    pending=['old','quiet','novig']
    scope={key:[key] for key in pending}
    evidence=[dict(event_id='novig',venue='novig',at=(at-timedelta(seconds=15)).isoformat())]
    assert prioritize_current(pending,scope,evidence,at)==['old','novig','quiet']
    assert prioritize_current(pending,scope,evidence,at+timedelta(microseconds=1))==pending


def test_reference_only_capture_advances_aggregate_receipt_watermark():
    from app.storage.ordinary_publication import captured_aggregate_receipts
    from app.storage.store import hashed
    source=dict(provider='the_odds_api',native_event_id='reference-only')
    receipt='2026-11-08T02:30:00+00:00'
    inputs=dict(quotes=[],references=[dict(source=source,times=dict(received_at=receipt))])
    assert captured_aggregate_receipts(inputs)=={hashed(['the_odds_api','reference-only']):receipt}
