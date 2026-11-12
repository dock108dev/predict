from copy import deepcopy
from fractions import Fraction
import pytest

from app.collection.novig_v3_stream import StreamBook, signed_headers, SECRET_REFERENCE
from app.comparison.snapshot_novig_live import live_fee
from tests.test_novig_live_fee import AT, sample

T0='2026-11-09T20:00:07Z';T1='2026-11-09T20:00:08Z';T2='2026-11-09T20:00:09Z'


def snapshot(seq=10, life=4, qty=100, nonce=1):
    return {'ts':1794254407000,'nonce':nonce,'snapshot':{'market':{'eventId':'event',
        'book':{'seq':seq,'orders':{'other':[{'order':'order','price':'0.5','qty':qty}]}},
        'lifecycle':{'seq':life,'status':'OPEN'}}}}


def delta(*, life=None, book=None):
    item={'eventId':'event'}
    if life is not None:item['lifecycle']=life
    if book is not None:item['book']=book
    return {'ts':1794254408000,'delta':{'market':item}}


def life(seq,kind):return {'seq':seq,'deltas':[{'kind':kind,'status':'OPEN'}]}


def ready():
    owner=StreamBook('event','market');owner.apply(snapshot(),T0)
    owner.apply(delta(life=life(5,'GOLIVE')),T1)
    owner.request_snapshot(2);owner.apply(snapshot(seq=11,life=5,nonce=2),T2)
    return owner


def test_real_stream_frames_produce_exact_single_fill_fee():
    row, fixture=sample();owner=ready()
    evidence=owner.evidence(fixture['native_event'],fixture['native_market'],'outcome',at=T2)
    result=live_fee(row,AT,evidence)
    assert result['available'] and Fraction(result['trade_fee_usd'])==Fraction(3,200)
    assert evidence['reset_proof']['frames'][0]['lifecycle']['seq']==5
    assert evidence['reset_proof']['source_book']['seq']==11


def test_signed_current_price_is_retained_when_one_order_is_too_small_for_fee():
    from app.collection.novig_v3_current import records_for_book

    owner = StreamBook('event', 'market')
    owner.apply(snapshot(qty=99), T0)
    owner.apply(delta(life=life(5, 'GOLIVE')), T1)
    owner.request_snapshot(2)
    owner.apply(snapshot(seq=11, life=5, qty=99, nonce=2), T2)
    # The signed transport stamps the validated packet clock after applying it.
    owner.book_source_at = T2
    _, fixture = sample()
    start = int(AT.timestamp() * 1000) - 60_000
    event = dict(fixture['native_event'], league='NCAAB', startsTs=start)
    market = dict(fixture['native_market'], startsTs=start, outcomes=[
        dict(outcomeId='outcome', name='Miami Hurricanes +2.5', status='TBD'),
        dict(outcomeId='other', name='Alabama Crimson Tide -2.5', status='TBD'),
    ])
    participants = dict(eventId='event', homeCompetitorId='mia', awayCompetitorId='ala', competitors=[
        dict(competitorId='mia', name='Miami Hurricanes', marketIds=['market']),
        dict(competitorId='ala', name='Alabama Crimson Tide', marketIds=['market']),
    ])
    row, = records_for_book(owner, event, market, participants, terms_at=T2, at=AT.isoformat(), runtime_id='fixture')
    q = row['quote']
    assert q['original']['value'] == '0.5' and q['state'] == 'available'
    assert q['novig_v3_evidence']['available_native_contracts'] == 99
    trade = dict(q, market=dict(market='spread', period='full_game', line='2.5'))
    assert live_fee(trade, AT, q['novig_v3_evidence'])['reason'] == 'novig_single_price_fill_evidence_missing'


def test_reset_resume_disconnect_and_two_independent_sequence_gaps():
    event, market = sample()[1]['native_event'], sample()[1]['native_market']
    for channel in ('book','lifecycle'):
        owner=ready();bad=delta(book={'seq':13,'deltas':[]}) if channel=='book' else delta(life=life(7,'START'))
        with pytest.raises(ValueError):owner.apply(bad,T2)
        assert owner.evidence(event,market,'outcome',at=T2) is None
    owner=ready();owner.apply(delta(life=life(6,'UNLIVE')),T2)
    assert owner.evidence(event,market,'outcome',at=T2) is None
    owner.apply(delta(life=life(7,'GOLIVE')),T2)
    owner.request_snapshot(3)
    with pytest.raises(ValueError):owner.apply(snapshot(seq=11,life=7,nonce=3),T2)
    assert owner.evidence(event,market,'outcome',at=T2) is None
    owner=ready();owner.disconnect()
    assert owner.evidence(event,market,'outcome',at=T2) is None


def test_atomic_batch_rejects_partial_book_update_and_first_order_size():
    owner=ready(); before=deepcopy(owner.orders)
    with pytest.raises(ValueError):
        owner.apply(delta(book={'seq':12,'deltas':[{'kind':'remove','order':'order'}, {'kind':'remove','order':'missing'}]}),T2)
    assert owner.orders is None and before['other'][0]['qty']==100
    owner=StreamBook('event','market');owner.apply(snapshot(qty=99),T0);owner.apply(delta(life=life(5,'GOLIVE')),T1);owner.request_snapshot(2);owner.apply(snapshot(seq=11,life=5,qty=99,nonce=2),T2)
    _, e=sample();assert owner.evidence(e['native_event'],e['native_market'],'outcome',at=T2) is None


def test_signer_allows_read_only_get():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key=Ed25519PrivateKey.generate();headers=signed_headers('fixture',key,'GET','/v3/ws',timestamp_ms=1)
    assert set(headers)=={'Novig-Key-Id','Novig-Timestamp','Novig-Signature'}
    with pytest.raises(ValueError):signed_headers('fixture',key,'POST','/v3/orders',timestamp_ms=1)
    assert 'v3.production' in SECRET_REFERENCE


def test_multi_market_frame_is_atomic_and_disconnect_revokes_all():
    from app.collection.novig_v3_stream import StreamSession
    session=StreamSession({'market':'event','market2':'event'})
    s=snapshot();second=deepcopy(s['snapshot']['market']);second['book']['orders']={}
    s['snapshot']['market2']=second;session.apply(s,T0)
    before=session.markets['market'].lifecycle_seq
    mixed={'delta':{'market':{'eventId':'event','lifecycle':life(5,'START')},
                    'market2':{'eventId':'event','lifecycle':life(7,'START')}}}
    with pytest.raises(ValueError):session.apply(mixed,T1)
    assert session.markets['market'].lifecycle_seq==before
    assert all(m.orders is None for m in session.markets.values())
    session.disconnect();assert all(not m.connected for m in session.markets.values())


def test_read_only_transport_requests_snapshot_and_revokes_on_disconnect():
    import asyncio, json
    from app.collection.novig_v3_stream import read_only_stream
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    frames=[snapshot(),delta(life=life(5,'GOLIVE')),snapshot(seq=11,life=5,nonce=2)]
    class Socket:
        def __init__(self):self.sent=[]
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return None
        async def send(self,value):self.sent.append(json.loads(value))
        def __aiter__(self):return self
        async def __anext__(self):
            if not frames:raise StopAsyncIteration
            return json.dumps(frames.pop(0))
    socket=Socket();observed=[]
    async def observe(session,frame,at):observed.append((frame is None,session.connected,session.markets['market'].orders is not None))
    def factory(*args,**kwargs):return socket
    asyncio.run(read_only_stream({'market':'event'},observe,key=('fixture',Ed25519PrivateKey.generate()),connect_factory=factory))
    assert ['subscribe','snapshot']==[next(k for k in message if k!='nonce') for message in socket.sent]
    assert observed[-1]==(True,False,False)


def test_old_or_unsolicited_snapshot_cannot_restore_authority():
    for issue_request,nonce in ((False,1),(True,1)):
        owner=StreamBook('event','market');owner.apply(snapshot(),T0);owner.apply(delta(life=life(5,'GOLIVE')),T1)
        if issue_request:owner.request_snapshot(2)
        with pytest.raises(ValueError,match='snapshot_request_unbound'):
            owner.apply(snapshot(seq=11,life=5,nonce=nonce),T2)
        _, fixture=sample()
        assert owner.evidence(fixture['native_event'],fixture['native_market'],'outcome',at=T2) is None


def test_book_change_withdraws_offer_until_a_new_bound_image():
    event, market = sample()[1]['native_event'], sample()[1]['native_market']
    owner=ready()
    owner.apply(delta(book={'seq':12,'deltas':[
        {'kind':'remove','order':'order'}, {'kind':'add','order':'new','outcome':'other','price':'0.4','qty':100}]}), T2)
    assert owner.evidence(event,market,'outcome',at=T2) is None
    owner.request_snapshot(3)
    replacement=snapshot(seq=12,life=5,nonce=3)
    replacement['snapshot']['market']['book']['orders']['other'][0].update(order='new', price='0.4')
    owner.apply(replacement,'2026-11-09T20:00:10Z')
    evidence=owner.evidence(event,market,'outcome',at='2026-11-09T20:00:10Z')
    assert evidence['price']=='0.6' and evidence['reset_proof']['book']['nonce']==3


@pytest.mark.parametrize('channel', ['lifecycle', 'book'])
def test_same_sequence_snapshot_conflict_revokes_offer(channel):
    owner=ready()
    owner.request_snapshot(3)
    conflicting=snapshot(seq=11,life=5,nonce=3)
    if channel == 'lifecycle':
        conflicting['snapshot']['market']['lifecycle']['status']='CLOSED'
    else:
        conflicting['snapshot']['market']['book']['orders']['other'][0]['qty']=101
    with pytest.raises(ValueError,match=f'novig_{channel}_sequence_conflict'):
        owner.apply(conflicting,T2)
    _,fixture=sample()
    assert owner.evidence(fixture['native_event'],fixture['native_market'],'outcome',at=T2) is None
