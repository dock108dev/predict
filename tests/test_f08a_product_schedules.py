"""The public product lifecycle preserves evidence and handles source failure safely."""
import asyncio
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import httpx

from app.collection import public_fee_refresh as refresh
from app.fees import product_schedules as products
from app.storage.store import stamp

AT=stamp('2026-11-10T04:30:00+00:00')
ROOT=Path(__file__).resolve().parents[1]


def attempt(key, body, *, at=AT, state=None, error=False):
    async def retrieve(url, limit):
        if error: raise httpx.ConnectError('offline')
        return body, dict(url=url,http_status=200,retrieved_at=at.isoformat(),
                          bytes=len(body),sha256=sha256(body).hexdigest())
    return asyncio.run(refresh.refresh_product(key,state,retrieve,clock=at.isoformat))


def test_novig_real_reviewed_article_matches_and_renews_prospectively():
    key='novig:pregame_straight'
    old=(ROOT/'app/fixtures/novig-fees-review-20261109.html').read_bytes()
    new=(ROOT/'app/fixtures/novig-fees-review-20261110.html').read_bytes()
    assert sha256(old).digest()!=sha256(new).digest()
    first=attempt(key,old)
    assert first['last_attempt']['state']=='verified'
    later=attempt(key,new,state=first,at=AT+timedelta(hours=6))
    assert later['last_attempt']['state']=='unchanged_verified'
    assert later['last_verified']['review_before']==(AT+timedelta(hours=30)).isoformat()
    row={'venue':'novig'}
    before=products.for_offer({key:first},row,AT)
    after=products.for_offer({key:later},row,AT+timedelta(hours=6))
    assert before['reviewed_at']==AT.isoformat()
    assert after['reviewed_at']==(AT+timedelta(hours=6)).isoformat()
    assert before['review_before']==(AT+timedelta(hours=24)).isoformat()
    assert products.for_offer({key:later},row,AT)['version']=='novig-conditional-20261110-review'


def test_failed_and_changed_retrieval_preserve_review_and_require_explicit_resolution():
    key='novig:pregame_straight'; body=(ROOT/products.PRODUCTS[key]['reference']).read_bytes()
    first=attempt(key,body)
    failed=attempt(key,body,state=first,at=AT+timedelta(hours=6),error=True)
    assert failed['last_attempt']['state']=='failed'
    assert failed['last_verified']==first['last_verified']
    assert failed['next_attempt_at']==(AT+timedelta(hours=6,minutes=15)).isoformat()
    changed=attempt(key,body.replace(b'No fee',b'One fee',1),state=first,at=AT+timedelta(hours=6))
    assert changed['last_attempt']['state']=='review_required'
    assert changed['last_verified']==first['last_verified']
    assert products.for_offer({key:changed},{'venue':'novig'},AT+timedelta(hours=7))['unavailable_reason']==products.REVIEW_REQUIRED
    assert not products.for_offer({key:changed},{'venue':'novig'},AT).get('unavailable_reason')
    still=attempt(key,body,state=changed,at=AT+timedelta(hours=7))
    assert still['last_attempt']['error']=='prior_change_requires_explicit_review'


def test_polymarket_standard_review_is_independent(monkeypatch):
    key='polymarket_us:standard_sports'; body=(ROOT/products.PRODUCTS[key]['reference']).read_bytes()
    prior_spec = {k: v for k, v in products.PRODUCTS[key].items() if not k.startswith('review_receipt')}
    reviewed = products.approved(key)
    assert reviewed['normalized_sha256'] == '90ee55153cac932effbf2264334b0d3f66d6c7eb00e8e4b2fdacd9c2c8fc2495'
    assert attempt(key,body)['review_required']['reason']=='public_product_schedule_changed'
    with monkeypatch.context() as historical:
        historical.setitem(products.PRODUCTS, key, prior_spec)
        changed = attempt(key, body.replace(b'</main>', b'<p>Changed standard terms.</p></main>', 1))
    assert refresh.product_due(key, changed, AT)
    failed = attempt(key,body,state=changed,error=True)
    assert not refresh.product_due(key, failed, AT)
    # The test response stands in for the official body whose full normalized
    # digest matched the browser and the collector's independent receipt.
    def approved_fixture(_name):
        return dict(reviewed, normalized_sha256=sha256(
            products.normalized(body, 'main').encode()).hexdigest())
    monkeypatch.setattr(products, 'approved', approved_fixture)
    verified=attempt(key,body,state=changed)
    model=products.for_offer({key:verified},{'venue':'polymarket_us'},AT)
    assert model['fee_rate']=='0.095' and model['product']=='standard_sports'
    assert model['review_before']==(AT+timedelta(hours=24)).isoformat()
    assert 'product' not in products.for_offer({key:verified},{'venue':'novig'},AT)


def test_prospective_polymarket_review_reaches_current_ordinary_offers(monkeypatch):
    from app.storage import ordinary_publication as live
    from tests.test_f05_polymarket_public import OWNER, SETTINGS, inputs_for, native

    key = 'polymarket_us:standard_sports'
    body = (ROOT / products.PRODUCTS[key]['reference']).read_bytes()
    changed_at = stamp('2026-11-11T22:25:38+00:00')
    renewed_at = changed_at + timedelta(hours=3)
    prior = attempt(key, body, at=changed_at)
    assert prior['last_attempt']['state'] == 'review_required'
    # Stand in for the official HTML matching the newly reviewed digest.
    approved = dict(products.approved(key), normalized_sha256=sha256(
        products.normalized(body, 'main').encode()).hexdigest())
    monkeypatch.setattr(products, 'approved', lambda name: approved)
    renewed = attempt(key, body, at=renewed_at, state=prior)

    def publish(captured_at, review_state):
        row = native('scheduled', 'Short', at=captured_at)
        inputs = inputs_for(row, at=captured_at)
        inputs['fee_products'] = {key: review_state}
        result = live.prices(inputs, SETTINGS)
        projected = live.project(result, inputs['dependencies'], dict(OWNER, fee_products=inputs['fee_products']),
            {'polymarket_us':{'state':'available'}}, at=captured_at, policy='policy', epoch='epoch')
        return projected['rows'][0]

    before = publish(renewed_at - timedelta(seconds=1), prior)
    after = publish(renewed_at, renewed)
    assert before['price_current'] and before['trade_fee']['reason'] == products.REVIEW_REQUIRED
    assert after['price_current'] and after['gross_return_percent'] is None
    fee = after['trade_fee']
    assert fee['trade_fee_usd'] == '0.02' and fee['classification'] == 'conservative'
    assert fee['evidence']['native_side'] == 'Short' and fee['evidence']['acquired_price_usd'] == '0.30'
    assert fee['evidence']['reviewed_at'] == renewed_at.isoformat()
    assert fee['evidence']['review_before'] == (renewed_at + timedelta(days=1)).isoformat()
    assert not publish(renewed_at - timedelta(seconds=1), renewed)['trade_fee']['available']


def test_ordinary_projection_withholds_changed_terms_but_keeps_frozen_capture():
    from app.storage import ordinary_publication as live
    from app.storage.current_rows import contract_id
    from tests.test_trade_desk import quote
    key='novig:pregame_straight'; body=(ROOT/products.PRODUCTS[key]['reference']).read_bytes()
    state=attempt(key,body)
    changed=attempt(key,body.replace(b'No fee',b'One fee',1),state=state,at=AT+timedelta(seconds=1))
    row=quote('f08a-novig','novig')
    row.pop('reference')
    row.update(start_at=(AT+timedelta(hours=2)).isoformat(),source=dict(provider='the_odds_api',
        native_event_id='game',native_market_id='spread',native_outcome_id='team',native_side='bookmaker_outcome'),
        times=dict(source_at=AT.isoformat(),received_at=AT.isoformat()))
    record=dict(event={'start_at':row['start_at']},quote=row.copy());row['original_record']=record
    deps={contract_id(record):['price','contract','event','receipt']}
    inputs=dict(quotes=[row],captured_at=AT.isoformat(),dependencies=deps,policy_identity='policy',
        epoch='epoch',id='capture',games=[],references=[],sources={},issues=[],capture_seconds=0,
        fee_products={key:state})
    result=live.prices(inputs,{'revision':'settings'})
    captured=result['rows'][0]['trade_fee']
    assert captured['available'] and captured['evidence']['reviewed_at']==AT.isoformat()
    projected=live.project(result,deps,dict(healthy=True,active=True,fee_products={key:changed}),
        {'novig':{'state':'available'},'pinnacle':{'state':'unavailable'}},
        at=AT+timedelta(seconds=1),policy='policy',epoch='epoch')['rows'][0]
    assert projected['trade_fee']['reason']==products.REVIEW_REQUIRED
    assert projected['conditional_trade_benchmark']['reason']==products.REVIEW_REQUIRED
    assert result['rows'][0]['trade_fee']==captured


def test_kalshi_429_keeps_existing_review_deadline(monkeypatch):
    from app.collection import kalshi_fee_refresh
    from app.comparison.conditional_benchmark import basis
    monkeypatch.setattr(kalshi_fee_refresh, 'renderer_endpoint', lambda: None)
    key='kalshi:exchange'
    old=basis('kalshi',at=AT)
    async def retrieve(url,limit):
        raise refresh.RetrievalFailed('fee_http_status',dict(url=url,http_status=429,retrieved_at=AT.isoformat()))
    state=asyncio.run(refresh.refresh_product(key,None,retrieve,clock=AT.isoformat))
    assert state['direct_pdf']['http_status']==429
    assert 'failed_request' not in state['last_attempt']['retrieval']
    resolved=products.for_offer({key:state},{'venue':'kalshi'},AT)
    assert resolved['review_before']==old['review_before']
    assert products.summary(key,state,AT)['next_action']=='Connect the official PDF renderer'
