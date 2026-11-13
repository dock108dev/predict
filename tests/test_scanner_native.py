"""Current public venue models through the actual Scanner allocation path."""

from fractions import Fraction

from app.comparison.current_dependencies import digest
from app.comparison.scanner_finance import evaluate
from app.comparison.scanner_native import VERSION
from tests.test_scanner_kalshi import inputs as kalshi_inputs
from tests.test_scanner_polymarket import AT, inputs as polymarket_inputs


def test_current_native_fees_and_observed_depth_yield_only_conditional_hedge():
    from app.comparison import scanner_kalshi, scanner_polymarket

    detached = {}
    for venue, (quote, evidence), adapter, direction in (
            ('kalshi', kalshi_inputs(), scanner_kalshi, 'home'),
            ('polymarket_us', polymarket_inputs('Short'), scanner_polymarket, 'away')):
        quote['original']['value'] = '0.4'
        quote['original']['native_value'] = '0.6'
        quote['depth'] = [dict(price='0.4',quantity='29')]
        quote.setdefault('binding',dict(verified=True))['selection'] = dict(predicate='win')
        raw = adapter.resolve(quote,evidence,at=AT)
        if venue=='kalshi':
            raw['payout'].update(below='0',above='1')
        model = dict(raw, version=VERSION, venue=venue, direction=direction, phase='pregame',
                     scoring=dict(shootout='not_applicable',extra_innings='not_applicable'),
                     partition=dict(domain='home_margin',threshold='0'),equality_feasible=True)
        model['revision'] = digest(model)
        detached[venue] = dict(quote=quote,native_execution=model,group=evidence['group'],event=evidence['event'])

    instruments = {key:dict(checks=dict(ev=dict(state='unsupported'))) for key in detached}
    value = evaluate(dict(legs=list(detached)),instruments,detached,at=AT.isoformat())
    assert value['evaluated'] and value['partial_evaluation'] and not value['qualifying']
    assert [row['category'] for row in value['rows']] == ['conditional_hedge']
    row = value['rows'][0]
    assert row['state_profits']['terminal_noncompletion'] is None
    assert not row['settlement_complete']
    assert all(Fraction(leg['entry_fee_bound_usd']) > 0 for leg in row['allocation'])
    assert all(Fraction(leg['native_quantity']) <= 29 for leg in row['allocation'])
