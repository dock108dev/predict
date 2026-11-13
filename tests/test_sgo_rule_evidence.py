from copy import deepcopy
from hashlib import sha256
import json

from app.comparison.sgo_reference import validate_witness
from app.comparison.sgo_rule_evidence import ReviewedBindings, SETTLEMENT, owned_bindings, reviewed_best_payout, reviewed_median

AT='2026-11-11T01:00:00Z'
FRAME='a'*64
CONTRACT=dict(event_id='event',league='NBA',phase='pregame',period='game',market='moneyline',side='home',line=None,
    settlement=SETTLEMENT,settlement_evidence='native-reviewed-scope',occurrence_evidence='explicit-occurrence',
    frame_id=FRAME,frame_received_at=AT)


def reviewed_registry(tmp_path, quotes, *, at=AT):
    from app.comparison.sgo_rule_evidence import settlement_key

    bindings=[]
    jurisdictions = {'draftkings':'US-WV','fanduel':'US-NJ','fanatics':'US-NY'}
    for quote in quotes:
        identity = {key:quote[key] for key in ('provider','venue','event_id','odd_id','frame_id','league','market','period')}
        identity['jurisdiction'] = jurisdictions[quote['venue']]
        if quote['market'] in ('spread', 'total'):
            identity['line'] = quote['line']
        settlement = settlement_key(quote['league'], quote['market'], quote['period'])
        body=json.dumps({'kind':'reviewed_source_market_jurisdiction','identity':identity,
                         'source_url':'https://example.org/fixture','normal_scoring':settlement,
                         'specific_market_terms_reviewed':True}).encode()
        path=tmp_path/(quote['venue']+'-'+quote['odd_id']+'.json');path.write_bytes(body)
        bindings.append(dict(identity,review_class='manual_review',evidence_path=path.name,
            evidence_sha256=sha256(body).hexdigest(),reviewed_at=at,effective_from=at,effective_until=None))
    return ReviewedBindings({'version':'sgo-reviewed-jurisdiction-bindings-1','bindings':bindings},evidence_root=tmp_path)


def fixture(tmp_path):
    quotes=[]
    for venue in ('draftkings','fanduel','fanatics'):
        for side,opposite in [('home','away'),('away','home')]:
            odd=venue+'-'+side
            q=dict(provider='sportsgameodds',venue=venue,event_id='event',odd_id=odd,
                opposing_odd_id=venue+'-'+opposite,frame_id=FRAME,frame_received_at=AT,league='NBA',
                market='moneyline',period='game',phase='pregame',side=side,line=None,
                price_american='-110',source_at=AT,received_at=AT,available=True)
            quotes.append(q)
    return quotes,reviewed_registry(tmp_path,quotes)


def test_three_evidenced_books_produce_reproducible_conditional_median(tmp_path):
    quotes,registry=fixture(tmp_path)
    result,witness=reviewed_median(quotes,CONTRACT,at=AT,evaluated_venue='novig',registry=registry)
    assert result['available'] and result['probability']=='1/2'
    assert {x['venue'] for x in result['contributors']}=={'draftkings','fanduel','fanatics'}
    assert validate_witness(witness,at=AT)['available']
    assert 'exceptional settlement excluded' in result['conditioning']
    result,witness=reviewed_median(quotes,CONTRACT,at=AT,evaluated_venue='fanduel',registry=registry)
    assert not result['available'] and witness is None


def test_jurisdiction_must_bind_exact_source_frame_and_is_not_inferred(tmp_path):
    quotes,registry=fixture(tmp_path)
    assert not reviewed_median(quotes,CONTRACT,at=AT,evaluated_venue='novig',registry=owned_bindings())[0]['available']
    changed=deepcopy(quotes);changed[0]['odd_id']='other'
    result,_=reviewed_median(changed,CONTRACT,at=AT,evaluated_venue='novig',registry=registry)
    assert not result['available']
    changed=deepcopy(CONTRACT);changed['market']='spread'
    assert not reviewed_median(quotes,changed,at=AT,evaluated_venue='novig',registry=registry)[0]['available']
    assert not reviewed_median(quotes,dict(CONTRACT,occurrence_evidence=None),at=AT,evaluated_venue='novig',registry=registry)[0]['available']


def test_best_payout_reports_quote_timing_before_missing_rules(tmp_path):
    quotes, _ = fixture(tmp_path)
    registry = owned_bindings()
    result, witness = reviewed_best_payout(quotes, CONTRACT, at=AT, evaluated_venue='kalshi', registry=registry)
    assert witness is None
    assert result['exclusions'] == {
        'draftkings': 'exact_jurisdiction_binding_unavailable',
        'fanduel': 'exact_jurisdiction_binding_unavailable',
    }
    stale = [dict(quote, source_at='2026-11-10T23:00:00Z') for quote in quotes]
    result, witness = reviewed_best_payout(stale, CONTRACT, at=AT, evaluated_venue='kalshi', registry=registry)
    assert witness is None
    assert result['exclusions'] == {'draftkings': 'source_stale', 'fanduel': 'source_stale'}
    incomplete = [quote for quote in quotes if quote['side'] == 'home']
    result, witness = reviewed_best_payout(incomplete, CONTRACT, at=AT, evaluated_venue='kalshi', registry=registry)
    assert witness is None
    assert result['exclusions'] == {
        'draftkings': 'exact_opposing_pair_missing', 'fanduel': 'exact_opposing_pair_missing',
    }


def test_owned_median_capture_binds_sql_rows_and_revision_dependencies(tmp_path,monkeypatch):
    from tests.test_snapshot_benchmark import execution, references
    from app.comparison.line_reference import scoring
    from app.comparison import sgo_rule_evidence, sgo_reference_publication
    from app.storage.ordinary_publication import validity
    from app.dashboard.current_contract import stamp
    quotes,registry=fixture(tmp_path)
    monkeypatch.setattr(sgo_rule_evidence,'owned_bindings',lambda:registry)
    monkeypatch.setattr(sgo_reference_publication,'owned_reference_evidence',lambda *args, **kwargs:None)
    native=execution(family='moneyline',line='0')
    native.update(league='NBA',quote_revision=3,binding={'verified':True},start_at='2026-11-11T03:00:00Z',cost_per_normal_claim='2/5')
    nr=native['original_record'];nr.update(verified=True,orientation_evidence=[])
    nr['event'].update(competition='NBA',season='2026',stage='regular',scheduled_start=native['start_at'],shared_provider_ids={'sportradar':'game'})
    nr['market_identity']['competition']='NBA'
    nr['comparison_source_metadata'].pop('comparison_admission',None)
    nr['comparison_source_metadata']['scoring_scope']['scoring']=scoring('NBA')
    nr['quote']['source']['native_market_id']='native'
    nr['quote']['provenance']['sha256']='b'*64
    native['source']=nr['quote']['source']
    anchor=references('moneyline','0')[0]
    ar=anchor['original_record'];ar.update(verified=False,orientation_evidence=[])
    ar['event'].update(id='event',competition='NBA',season='unverified',stage='unverified',scheduled_start=native['start_at'],shared_provider_ids={'sportradar':'game'})
    ar['market_identity']['competition']='NBA'
    ar['quote']['source'].update(provider='sportsgameodds',native_event_id='event')
    ar['quote']['provenance']['sha256']=FRAME
    rows=[];dependencies={}
    for i,q in enumerate(quotes):
        entry={'id':'row-'+str(i),'revision':'revision-'+str(i),'facts':dict(q,settlement='unverified')}
        rows.append(entry);dependencies['sgo-reference:'+entry['id']]=[entry['revision'],entry['id'],'event-rev','receipt']
    frame={'facts':{'provider':'sportsgameodds','event_id':'event','receipt_sha256':FRAME,'received_at':AT,
                    'members':[[x['id'],x['revision']] for x in rows]}}
    inputs={'quotes':[native],'references':[anchor],'dependencies':dependencies,'captured_at':AT,
            'sgo_reference_events':{'event':{'frame':frame,'rows':rows}}}
    source={'dependency':'native','expected':['r','c','e'],'reasons':[],'current_until':'2026-11-11T01:30:00Z',
            'lifecycle':{'state':'scheduled'}}
    result,witnesses=sgo_reference_publication.bind_captured(native,source,inputs)
    assert result['available'] and result['probability']=='1/2' and len(witnesses)==6
    assert result['reference_calculation']['selection_policy']=='sgo-pinnacle-then-reviewed-median-1'
    changed=deepcopy(dependencies);changed[witnesses[0]['dependency']][0]='changed'
    assert 'input_replaced_or_removed' in validity(witnesses[0],changed,stamp(AT))
    nr['event']['shared_provider_ids']={'sportradar':'different'}
    assert not sgo_reference_publication.bind_captured(native,source,inputs)[0]['available']
