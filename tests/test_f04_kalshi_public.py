from datetime import timedelta
from fractions import Fraction
from unittest.mock import patch
import json

from app.comparison.conditional_benchmark import ROOT, basis
from app.comparison.current_dependencies import instant
from app.comparison.snapshot_conservative import kalshi_public_fee
from app.comparison.snapshot_fee_scope import ACCOUNT_PATH


def input_row():
    evidence=basis('kalshi',at=instant('2026-11-08T02:00:00Z'))
    body=json.loads((ROOT/evidence['path']).read_bytes())
    ticker,metadata=next((ticker,row) for ticker,row in body['series'].items()
        if str(row['response']['series']['fee_multiplier']) in ('1','1.0'))
    event=ticker+'-FIXTURE';market=event+'-HOME'
    row=dict(venue='kalshi',league=metadata['league'],market=dict(market=metadata['family'].replace('moneyline','winner'),period='full_game'),
        source=dict(provider='kalshi',native_event_id=event,native_market_id=market,native_side='yes',native_outcome_id='yes'),
        fee_applicability=dict(series_id=ticker,native_key=['kalshi',event,market,'yes','yes']),
        original=dict(value='0.50',units='usd_per_contract',quantity_units='contracts',payout_units='USD',payout='1'))
    return row,evidence,instant(evidence['reviewed_at'])


def test_public_high_side_examples_do_not_require_membership():
    row,review,at=input_row()
    with patch('app.comparison.snapshot_fee_scope.ACCOUNT_PATH',ROOT/'.local/nonexistent-disposable-account-fact'):
        one=kalshi_public_fee(row,at=at.isoformat(),review=review)
        hundred=kalshi_public_fee(row,at=at.isoformat(),review=review,quantity='100')
    assert one['available'] and Fraction(one['trade_fee_usd'])==Fraction(2,100)
    assert hundred['available'] and Fraction(hundred['trade_fee_usd'])==Fraction(175,100)
    assert one['account_verified'] is False and 'intermediary' in one['assumptions'][-1].lower()


def test_unknown_identity_and_review_expiry_withhold_fee():
    row,review,at=input_row()
    row['source']['native_event_id']='unrelated'
    assert not kalshi_public_fee(row,at=at.isoformat(),review=review)['available']
    row,review,at=input_row()
    assert kalshi_public_fee(row,at=review['review_before'],review=review)['reason']=='conditional_fee_review_expired_or_not_effective'


def test_public_fee_outcome_visible_without_pinnacle_for_live_and_pregame():
    from app.comparison.snapshot_fee_outcome import outcome
    row,review,at=input_row()
    for phase in ('scheduled','live'):
        fee=outcome(row,at=at,phase=phase,review=review)
        assert fee['available'] and fee['classification']=='conservative'
        assert Fraction(fee['trade_fee_usd'])==Fraction(2,100)
        assert fee['fee_cashflows']=={'at_fill_usd':'0.02'}


def test_event_waiver_and_effective_transition(tmp_path, monkeypatch):
    from copy import deepcopy
    from app.comparison import snapshot_fee_scope
    row, review, at = input_row()
    body = json.loads((ROOT / review['path']).read_bytes())
    transition = at + timedelta(hours=1)
    body['event_changes'] = dict(cursor='', event_fee_changes=[dict(
        id='fixture-waiver', series_ticker=row['fee_applicability']['series_id'],
        event_ticker=row['source']['native_event_id'], fee_type_override=None,
        fee_multiplier_override=0, scheduled_ts=transition.isoformat())])
    fixture = tmp_path / 'terms.json'
    fixture.write_text(json.dumps(body))
    monkeypatch.setattr(snapshot_fee_scope, 'ROOT', tmp_path)
    evidence = deepcopy(review)
    evidence['path'] = 'terms.json'
    before = kalshi_public_fee(row, at=(transition-timedelta(microseconds=1)).isoformat(), review=evidence)
    after = kalshi_public_fee(row, at=transition.isoformat(), review=evidence)
    assert before['available'] and Fraction(before['trade_fee_usd']) == Fraction(2, 100)
    assert before['evidence']['review_before'] == transition.isoformat()
    assert after['available'] and Fraction(after['trade_fee_usd']) == 0
    assert after['details']['resolved_terms']['fee_multiplier'] == '0'


def test_official_mlb_series_change_effective_instant():
    from app.fees.engine import kalshi_terms
    body = json.loads((ROOT / 'app/fixtures/kalshi-fees-review-20261109.json').read_bytes())
    change = next(item for item in body['series_changes']['series_fee_change_arr']
                  if item['series_ticker'] == 'KXMLBGAME'
                  and item['scheduled_ts'] == '2026-08-07T04:59:45.131Z')
    event = 'KXMLBGAME-FIXTURE'
    metadata = dict(source='July 7 official schedule and retained official series fee change',
        series_id='KXMLBGAME', event_id=event, event_changes=[], series_changes=[
            dict(series_ticker='KXMLBGAME', scheduled_ts='2026-07-08T00:00:00Z',
                 fee_type='quadratic_with_maker_fees', fee_multiplier='1'), change])
    context = dict(series_id='KXMLBGAME', event_id=event, kalshi_metadata=metadata)
    cutover = instant(change['scheduled_ts'])
    assert str(kalshi_terms(context, (cutover-timedelta(microseconds=1)).isoformat())['fee_multiplier']) == '1'
    assert str(kalshi_terms(context, cutover.isoformat())['fee_multiplier']) == '0.5'
