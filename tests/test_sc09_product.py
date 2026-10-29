"""Lossless bulk frames and independent conditional arithmetic boundaries."""
from copy import deepcopy
from fractions import Fraction as F
import json
import pytest
from app.storage.shared_json import pack,unpack
from app.storage.raw_metadata import display
from app.collection.current_benchmark import calculate
from app.dashboard.current_contract import stamp,serialize
from tests import test_current_benchmark as fixtures
AT=fixtures.AT


def test_shared_tree_exact_values_and_detached_branches():
    original={'repeated':[{'clock':'2026-10-28T00:00:00Z','price':'0.0100','literal':['o',3],'empty':None} for _ in range(500)]}
    tree=pack(original);restored=unpack(tree)
    assert restored==original
    assert len(json.dumps(tree))<len(json.dumps(original))/4
    restored['repeated'][0]['price']='changed'
    assert restored['repeated'][1]['price']=='0.0100'
    assert original['repeated'][0]['price']=='0.0100'
    invalid=deepcopy(tree);invalid['nodes'][0]=['a',[0]]
    with pytest.raises(ValueError,match='reference'):unpack(invalid)
    bomb={'encoding':'shared-json-1','nodes':[['v','long string'*100]],'root':29}
    bomb['nodes'] += [['a',[i-1]*8] for i in range(1,30)]
    with pytest.raises(ValueError,match='expansion'):unpack(bomb)


def test_retained_benchmark_independent_arithmetic_and_future_refusal():
    fixture=fixtures.BenchmarkTests();q=fixture.quote(serialize(fixture.raw(),allow_synthetic=True))
    for odds in ('1.0001','1.25','2','1000'):
        value=deepcopy(q);value['original']['value']=odds
        r=calculate(value,stamp('2026-10-03T02:00:00Z'),allow_last_known=True)
        # Independent equivalent closed form, not a second production call.
        a,b=map(F,value['sharp_reference']['odds']);i=value['sharp_reference']['selected']
        p=(b if i==0 else a)/(a+b)
        exact=r['exact'];actual=F(int(exact['numerator']),int(exact['denominator']))
        assert actual==100*(p*F(odds)-1)
    q['state']='unavailable'
    assert calculate(q,stamp(AT))['value'] is None
    assert calculate(q,stamp(AT),allow_last_known=True)['value'] is not None
    q['sharp_reference']['source_at']=[AT,'2027-01-01T00:00:00Z']
    assert calculate(q,stamp(AT),allow_last_known=True)['value'] is None


def test_retained_pm_labels_use_explicit_side_ids_and_team():
    metadata=dict(question='Will Away cover?',sportsMarketType='basketball_team_full_game_spread',marketSides=[
        dict(id='123',long=True,description='+4.5',team={'name':'Away'}),
        dict(id='456',long=False,description='-4.5',team={'name':'Home'})])
    result=display('polymarket_us',metadata)
    assert result['period']=='full_game'
    assert result['sides']==[dict(id='123',role='Long',label='Away · +4.5',line='+4.5'),dict(id='456',role='Short',label='Home · -4.5',line='-4.5')]


def alternate_fixture():
    from tests.test_current_aggregate import body
    from decimal import Decimal
    event=json.loads(body(books=('novig','pinnacle')))[0]
    for book in event['bookmakers']:
        markets=[]
        for market in book['markets']:
            if market['key']=='h2h':continue
            first=deepcopy(market);first['key']='alternate_'+market['key']
            second=deepcopy(first['outcomes'])
            for o in second:
                o['point']=str(Decimal(str(o['point']))+(1 if market['key']=='totals' or o['name']==event['home_team'] else -1))
            first['outcomes']+=second;markets.append(first)
        book['markets']=markets
    return json.dumps(event).encode()


def test_alternate_exact_pairs_keep_receipt_and_clocks():
    from hashlib import sha256
    from app.collection.current_aggregate_admission import admit_alternate,ParsedAggregateFrame
    from app.collection.current_benchmark import attach
    body=alternate_fixture();rows,complete,errors=admit_alternate(body,'MLB',AT)
    assert not errors and set(complete)=={'novig','prophetx','pinnacle'}
    assert len(rows)==16
    assert all(r['quote']['provenance']['sha256']==sha256(body).hexdigest() for r in rows)
    assert all(r['quote']['source']['native_market_id'].startswith('alternate:') for r in rows)
    offers=[r for r in rows if r['quote']['venue']=='novig'];refs=[r for r in rows if r['quote']['venue']=='pinnacle']
    attach(offers,refs)
    assert all(r['quote'].get('sharp_reference') for r in offers)
    retained,_,_=admit_alternate(None,'MLB',AT,frame=ParsedAggregateFrame(json.loads(body),sha256(body).hexdigest()))
    assert [(r['selection'],r['quote']['original'],r['quote']['times']) for r in retained]==[(r['selection'],r['quote']['original'],r['quote']['times']) for r in rows]


def test_retained_receipt_offset_keeps_same_instant_and_is_utc():
    from app.collection.current_aggregate_admission import admit_alternate
    rows,_,_=admit_alternate(alternate_fixture(),'MLB','2026-10-02T20:00:00-04:00')
    assert rows and all(r['quote']['times']['received_at']=='2026-10-03T00:00:00+00:00' for r in rows)


def test_incomplete_alternate_pair_does_not_hide_later_valid_lines():
    from app.collection.current_aggregate_admission import admit_alternate
    value=json.loads(alternate_fixture())
    value['bookmakers'][0]['markets'][0]['outcomes'].pop(0)
    rows,_,errors=admit_alternate(json.dumps(value).encode(),'MLB',AT)
    assert errors and len([r for r in rows if r['quote']['venue']=='novig'])==6


def test_captured_read_compression_preserves_exact_values_and_bounds_expansion():
    from app.storage.slate_reads import CapturedReads,MAX_READ_BYTES
    from app.storage.store import encoded
    reads=CapturedReads(resource_bytes=lambda:0)
    value={'inputs':[{'odds':'1.0100','clock':AT,'text':'exact input '*100} for _ in range(200)]}
    packed=reads.freeze(encoded(value))
    assert len(packed)<len(encoded(value))/10
    assert reads.decode(packed)==value
    with pytest.raises(ValueError,match='capacity'):
        reads.decode(packed[:3]+(MAX_READ_BYTES+1).to_bytes(4,'big')+packed[7:])
    with pytest.raises(ValueError,match='capacity'):
        reads.decode(packed[:3]+(1).to_bytes(4,'big')+packed[7:])


def test_shared_decoder_releases_tree_without_cyclic_gc():
    import gc,weakref
    from app.storage.shared_json import pack,unpack
    class Nodes(list):pass
    tree=pack({'prices':[{'value':'0.4900'}]*20})
    tree['nodes']=Nodes(tree['nodes']);reference=weakref.ref(tree['nodes'])
    enabled=gc.isenabled();gc.disable()
    try:
        decoded=unpack(tree)
        del tree
        assert reference() is None
        assert decoded['prices'][0]['value']=='0.4900'
    finally:
        if enabled:gc.enable()


def test_selected_shared_decode_preserves_evidence_and_bounds_real_allocation():
    import tracemalloc
    value={'financial':{'rows':[{'price':'0.0100','terms':'unchanged source '*1000,'levels':[1,2,3]} for _ in range(100)]},
           'observed':{'rows':[{'price':'0.0200'} for _ in range(100)]},'epoch':4}
    tree=pack(value);reservations=[]
    tracemalloc.start()
    try:
        result=unpack(tree,fields=('financial','epoch'),guard=reservations.append)
        _,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    assert result=={k:value[k] for k in ('financial','epoch')}
    assert reservations[0]>peak
    result['financial']['rows'][0]['levels'][0]=99
    assert result['financial']['rows'][1]['levels']==[1,2,3]
    assert value['financial']['rows'][0]['levels']==[1,2,3]
    # Even an unselected branch must pass structural validation.
    tree['nodes'][0]=['a',[0]]
    with pytest.raises(ValueError,match='reference'):
        unpack(tree,fields=('epoch',))


@pytest.mark.parametrize('damage',['price','point','name'])
def test_malformed_alternate_line_keeps_independent_later_pairs(damage):
    from hashlib import sha256
    from app.collection.current_aggregate_admission import admit_alternate
    value=json.loads(alternate_fixture())
    value['bookmakers'][0]['markets'][0]['outcomes'][0][damage]='invalid'
    body=json.dumps(value).encode()
    rows,complete,errors=admit_alternate(body,'MLB',AT)
    assert 'novig' in errors and 'novig' not in complete
    assert len([r for r in rows if r['quote']['venue']=='novig'])==6
    assert len([r for r in rows if r['quote']['venue']=='pinnacle'])==8
    assert all(r['quote']['provenance']['sha256']==sha256(body).hexdigest() for r in rows)


def test_event_route_report_distinguishes_started_unknown_and_empty_receipts():
    from datetime import datetime,timezone
    from app.collection.acquisition_report import event_route_status
    census=dict(sport='NCAAB',cycle_id='new',received_at=datetime(2026,10,28,23,tzinfo=timezone.utc))
    event=dict(id='e',commence_time='2026-10-28T22:00:00Z')
    assert event_route_status(census,event,None)['reason']=='started_before_census_not_requested'
    event['commence_time']='2026-10-29T22:00:00Z'
    prior=dict(cycle_id='old',disposition='admitted_exact_lines',payload={'bookmakers':[]})
    assert event_route_status(census,event,prior)['reason']=='event_route_pending_or_interrupted'
    prior['cycle_id']='new'
    current=event_route_status(census,event,prior)
    assert current['reason']=='received_current_cycle' and current['returned_markets']==0
