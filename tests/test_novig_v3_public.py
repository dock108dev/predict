import asyncio
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from app.collection.novig_v3_public import NovigPublicDiscovery
from app.comparison.snapshot_novig_live import live_fee
from tests.test_novig_live_fee import AT, sample


def test_public_cached_snapshot_cannot_prove_reset():
    row, evidence = sample()
    for changes in ({'reset_proof': {}},
                    {'reset_proof': {'transport': 'public', 'continuous': True}},
                    {'reset_proof': dict(evidence['reset_proof'], continuous=False)}):
        untrusted = dict(deepcopy(evidence), **changes)
        assert live_fee(row, AT, untrusted)['reason'] == 'novig_post_reset_sequence_evidence_missing'
    for value in (0, 1):
        untrusted = deepcopy(evidence)
        untrusted['reset_proof']['book']['position'] = value
        assert live_fee(row, AT, untrusted)['reason'] == 'novig_post_reset_sequence_evidence_missing'


def test_bounded_public_source_reports_sequence_gap_and_respects_stop():
    asyncio.run(bounded_public_source())


async def bounded_public_source():
    calls=[]
    def server(req):
        calls.append(req)
        if req.url.path.endswith('/events'):
            return httpx.Response(200, json={'items':[{'eventId':'e','league':'NBA','status':'OPEN_INGAME'}], 'next':None},headers={'cache-control':'public,max-age=15'})
        if req.url.path.endswith('/markets'):
            return httpx.Response(200,json={'items':[{'marketId':'m','eventId':'e'}], 'next':None})
        return httpx.Response(200,json={'marketId':'m','seq':5,'orders':{}})
    service=SimpleNamespace(dispatch=True)
    worker=NovigPublicDiscovery(service, transport=httpx.MockTransport(server))
    async with httpx.AsyncClient(transport=worker.transport) as client:
        worker.client=client
        result=await worker.poll()
        assert (result['events'],result['markets'],result['books'],result['live_qualified'])==(1,1,1,0)
        assert result['gap']=='novig_post_reset_sequence_evidence_missing'
        assert len(calls)==3 and all(req.method=='GET' for req in calls)
        service.dispatch=False
        with pytest.raises(asyncio.CancelledError):await worker.poll()


def test_public_cached_and_out_of_order_books_never_qualify():
    asyncio.run(public_sequence_case())


async def public_sequence_case():
    book = {'marketId':'m','seq':5,'orders':{'other':[{'orderId':'o','price':'0.5','qty':100}]}}
    def server(req):
        if req.url.path.endswith('/events'):
            return httpx.Response(200,json={'items':[{'eventId':'e','league':'NBA','status':'OPEN_INGAME'}], 'next':None})
        if req.url.path.endswith('/markets'):
            return httpx.Response(200,json={'items':[{'marketId':'m','eventId':'e'}], 'next':None})
        return httpx.Response(200,json=book,headers={'age':'4','cache-control':'public,max-age=5'})
    worker=NovigPublicDiscovery(SimpleNamespace(dispatch=True),transport=httpx.MockTransport(server))
    async with httpx.AsyncClient(transport=worker.transport) as client:
        worker.client=client
        assert (await worker.poll())['live_qualified']==0
        assert (await worker.poll())['gap']=='novig_post_reset_sequence_evidence_missing'
        book['seq']=4
        assert (await worker.poll())['gap']=='novig_public_book_sequence_regressed'
        book['seq']=5;book['orders']['other'][0]['qty']=99
        assert (await worker.poll())['gap']=='novig_public_book_sequence_conflict'
        book['seq']=6
        assert (await worker.poll())['gap']=='novig_post_reset_sequence_evidence_missing'


def test_market_and_one_resting_order_are_bound():
    row, evidence=sample()
    cases = [
        ('event', lambda x: x['native_event'].update(eventId='different'), 'novig_native_source_identity_conflict'),
        ('market', lambda x: x['native_market'].update(marketId='different'), 'novig_native_source_identity_conflict'),
        ('line', lambda x: x['native_market'].update(strike='3.5'), 'novig_native_source_identity_conflict'),
        ('book', lambda x: x['reset_proof']['source_book'].update(seq=12), 'novig_post_reset_sequence_evidence_missing'),
        ('short order', lambda x: x['reset_proof']['source_book']['orders']['other'][0].update(qty=99), 'novig_post_reset_sequence_evidence_missing'),
        ('price', lambda x: x['reset_proof']['source_book']['orders']['other'][0].update(price='0.4'), 'novig_post_reset_sequence_evidence_missing'),
    ]
    for _, mutate, reason in cases:
        value=deepcopy(evidence);mutate(value)
        assert live_fee(row,AT,value)['reason']==reason


def test_reset_sequence_rejects_an_intervening_unlive_and_sequence_gap():
    row, evidence=sample()
    for seq, kind in ((9, 'UNLIVE'), (10, 'START')):
        value=deepcopy(evidence)
        value['reset_proof']['frames'][-1]['position']=3
        value['reset_proof']['book']['position']=3
        value['reset_proof']['frames'].insert(1,dict(position=2,market_id='market',
            lifecycle=dict(seq=seq,deltas=[dict(kind=kind,status='OPEN')])))
        assert live_fee(row,AT,value)['reason']=='novig_post_reset_sequence_evidence_missing'
