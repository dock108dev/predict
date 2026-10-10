"""Exact public retail metadata observations, independent of price freshness.

No acquisition. Retail decimal contracts are not institutional wire integers.
An observation may explain an older quote, but cannot qualify its historical grid.
"""
from copy import deepcopy
import json
from functools import lru_cache
from pathlib import Path
from fractions import Fraction
from datetime import timedelta

from .current_dependencies import digest, instant, public_tree

VERSION = 'comparison-public-retail-1'


@lru_cache(maxsize=1)
def _retained():
    return json.loads((Path(__file__).resolve().parents[1] /
        'fixtures/comparison-public-retail-v1.json').read_text())


def retained():
    return deepcopy(_retained())


@lru_cache(maxsize=1)
def _fresh():
    return validate(json.loads((Path(__file__).resolve().parents[1] /
        'fixtures/comparison-public-retail-fresh-v1.json').read_text()))


def fresh_retained():
    return deepcopy(_fresh())


def exact_fresh(q, value=None):
    from .source_inputs import observation
    value = _fresh() if value is None else validate(value)
    row = value['binding']
    return row['observation'] == observation(q) and row['quote_revision'] == q['revision']


@lru_cache(maxsize=1)
def _charge_audit():
    value = json.loads((Path(__file__).resolve().parents[1] /
        'fixtures/comparison-retail-charge-audit-v1.json').read_text())
    public_tree(value)
    if value.get('audit_version') != digest({k: v for k, v in value.items() if k != 'audit_version'}):
        raise ValueError('source_retail_charge_audit_revision_conflict')
    # This diagnostic cannot confer numeric cost authority or a selected exemption.
    if (value['settlement_status'] != 'unknown' or value['mandatory_charges_known'] is not False or
            value['net_qualified'] is not False or value['published_clearing']['selected_total_cost_exemption'] is not False):
        raise ValueError('source_retail_charge_audit_authority_conflict')
    fresh = _fresh()
    if (value['selected_binding_version'] != fresh['binding_version'] or
            value['observation'] != fresh['binding']['observation'] or
            value['quote_revision'] != fresh['binding']['quote_revision'] or
            value['retained_evaluation_at'] != fresh['retained_evaluation_at']):
        raise ValueError('source_retail_charge_audit_observation_conflict')
    return value


def charge_audit(q):
    """Explain the exact retained refusal; never attach a cost profile or extend time."""
    return deepcopy(_charge_audit()) if exact_fresh(q) else None


@lru_cache(maxsize=1)
def _direct_site():
    value = json.loads((Path(__file__).resolve().parents[1] /
        'fixtures/comparison-direct-site-retail-v1.json').read_text())
    public_tree(value)
    if value.get('case_version') != digest({k: v for k, v in value.items() if k != 'case_version'}):
        raise ValueError('source_direct_site_revision_conflict')
    fresh = _fresh()
    if (value['selected_binding_version'] != fresh['binding_version'] or
            value['observation'] != fresh['binding']['observation'] or
            value['quote_revision'] != fresh['binding']['quote_revision'] or
            value['effective_from'] != fresh['binding']['effective_from'] or
            value['effective_until'] != fresh['binding']['effective_until'] or
            value['mandatory_charges_known'] is not False or value['settlement_status'] != 'unknown'):
        raise ValueError('source_direct_site_authority_conflict')
    return value


def direct_site_case(q, at):
    """Selected successor model; never assert independently verified total costs."""
    if not exact_fresh(q):
        return None
    value = _direct_site()
    if not instant(value['effective_from']) <= at < instant(value['effective_until']):
        return None
    return deepcopy(value)


def direct_site_estimate(q, profiles, at, ceiling='100'):
    """Conditional completed win/loss estimate; shared entry arithmetic once.

    This is deliberately separate from actual net EV and executable ranking.
    A cent-rounded single fill is a model, not an observed fill partition.
    """
    from .current_dependencies import references, eligibility
    from .net_costs import wire
    from app.dashboard.current_contract import exact_wire, display_decimal
    refused = dict(eligible=False, display_value=None, reason='direct_site_cost_case_unbound')
    fee = references(q, profiles).get('fee')
    if fee is None or fee['payload'].get('version') != 'comparison-direct-site-retail-case-1':
        return refused
    value = direct_site_case(q, at)
    if value is None or fee['payload'] != value or fee['expires_at'] != value['effective_until']:
        return dict(refused, reason='direct_site_cost_case_expired_or_identity_conflict')
    reasons = [r for r in eligibility(q, profiles, at, kinds=('identity', 'payout', 'quantity'))
        if r != 'source_phase_unknown']
    if reasons or not q['binding']['verified'] or q['state'] != 'available':
        return dict(refused, reason='; '.join(reasons) or 'direct_site_selection_unavailable')
    ref = q.get('sharp_reference')
    if not ref or not q.get('calculations', {}).get('ev', {}).get('eligible'):
        return dict(refused, reason='exact_conditional_pinnacle_probability_unavailable')
    size = Fraction(ceiling)
    if not 0 < size <= 100000:
        return dict(refused, reason='comparison_ceiling_outside_bounds')
    weights = [1 / Fraction(x) for x in ref['odds']]
    probability = weights[ref['selected']] / sum(weights)
    fresh = fresh_retained()
    price = Fraction(q['original']['value']); step = Fraction(fresh['metadata']['minimumTradeQty'])
    def costs(units):
        quantity = step * units
        entry = entry_example(fresh, wire(quantity))
        return quantity, entry, quantity * price + Fraction(entry['entry_fee_usd'])
    low, high = 1, min(100000000, int(size / price / step))
    best = None
    while low <= high:
        middle = (low + high) // 2
        row = costs(middle)
        if row[2] <= size:
            best = row; low = middle + 1
        else:
            high = middle - 1
    if best is None:
        return dict(refused, reason='capital_below_minimum_quantity')
    quantity, entry, deployed = best
    expected = quantity * probability
    ev = (expected - deployed) / deployed * 100
    number = exact_wire(ev)
    return dict(eligible=True, label='Modeled conditional after-cost EV', estimate_class='standard_direct_site_retail_assumption',
        exact=number, display_value=display_decimal(number['decimal_approx'], 2, True) + ' %',
        conditioning='completed_decisive_win_loss', probability=wire(probability),
        quantity=wire(quantity), price=q['original']['value'], acquisition_usd=wire(quantity * price),
        entry_fee_usd=entry['entry_fee_usd'], deployed_usd=wire(deployed), ceiling_usd=ceiling,
        expected_payout_usd=wire(expected), expected_profit_usd=wire(expected - deployed),
        modeled_settlement_fee_usd=value['modeled_settlement_fee_usd'],
        modeled_other_mandatory_costs_usd=value['modeled_other_mandatory_costs_usd'],
        assumption=value['assumption'], remaining_published_fact=value['remaining_published_fact'],
        actual_net_qualified=False, independent_gates=['actual tie/exceptional probability mass',
            'complete payout equivalence', 'execution phase and executable depth'],
        fee_profile_revision=q['comparison_input_refs']['refs']['fee'], quote_revision=q['revision'],
        evaluation_at=at.isoformat(), source_at=q['times']['source_at'], received_at=q['times']['received_at'])


def receiving_metadata(record, q, metadata):
    """Bind an authentic retained receipt only to its exact admitted material.

    This supplies no replacement, execution phase, depth or total-cost authority.
    Matching field values alone never qualify an incoming metadata observation.
    """
    if q['venue'] != 'polymarket_us' or not exact_fresh(q):
        return metadata
    value = _fresh()
    if metadata.get('material_sha256') != value['binding']['material_sha256']:
        return metadata
    result = deepcopy(metadata)
    result['selected_public_retail_data'] = deepcopy(value['metadata'])
    return result


def saved_facets(q, event, group, outcome, registry, at):
    """Re-run the ordinary selected producer at a retained evaluation boundary."""
    if q['venue'] != 'polymarket_us' or not exact_fresh(q):
        return None
    value = _fresh()
    from .source_inputs import apply_selected
    from .current_dependencies import KINDS
    result = dict(profiles={}, comparison_input_refs=dict(refs={k:None for k in KINDS}, phase='unknown'), gaps={})
    apply_selected(result, value['normalized_record'], dict(quote=q, event=event,
        group=group, outcome=outcome, selected_applicability=registry), at)
    return result


def registry(base, retail=None):
    result = deepcopy(base)
    value = retained() if retail is None else retail
    validate(value)
    result['records'].append(deepcopy(value['binding']))
    result['records'].append(deepcopy(_fresh()['binding']))
    from .public_event import registry as event_registry
    result = event_registry(result)
    return event_registry(result, _fresh()['event_binding'])


def validate(value):
    if value.get('version') != VERSION:
        raise ValueError('source_public_retail_version_invalid')
    public_tree(value)
    content = {k: v for k, v in value.items() if k != 'binding_version'}
    if value.get('binding_version') != digest(content):
        raise ValueError('source_public_retail_revision_conflict')
    data = value['metadata']; row = value['binding']
    if data['market_id'] != row['native_key'][2] or data['instrument_id'] != row['native_key'][3]:
        raise ValueError('source_public_retail_selected_identity_conflict')
    if data['side'] != row['native_key'][4] or data['side'] not in ('Long', 'Short'):
        raise ValueError('source_public_retail_selected_side_conflict')
    if not instant(row['effective_from']) < instant(row['effective_until']):
        raise ValueError('source_public_retail_interval_invalid')
    if row['effective_from'] != value['receipt']['response_at']:
        raise ValueError('source_public_retail_observation_interval_conflict')
    if value['receipt']['status'] != 200 or value['receipt']['outcome'] != 'ok':
        raise ValueError('source_public_retail_incomplete_response')
    if value.get('retained_evaluation_at') is not None:
        from .source_inputs import observation
        from .public_event import validate as validate_event
        if type(row.get('quote_revision')) is not int or row['quote_revision'] <= 0 or row['quote_revision'] != value['normalized_record']['quote']['revision']:
            raise ValueError('source_public_retail_quote_revision_conflict')
        if row['observation'] != observation(value['normalized_record']['quote']):
            raise ValueError('source_public_retail_quote_receipt_conflict')
        receipt = value['receipt']
        event = validate_event(value['event_binding'])
        if (receipt.get('complete') is not True or data['response_sha256'] != receipt['sha256'] or
                event['provenance']['response_sha256'] != receipt['sha256'] or
                event['effective_from'] != receipt['response_at'] or
                event['market_pointer'] != data['market_pointer'] or
                data['side_pointer'] != next(m['pointer'] for m in event['members'] if m['native_key'] == row['native_key'])):
            raise ValueError('source_public_retail_metadata_receipt_conflict')
        if (not instant(receipt['request_at']) <= instant(receipt['response_at']) <=
                instant(row['observation']['received_at']) <= instant(value['retained_evaluation_at']) < instant(row['effective_until']) or
                instant(row['effective_until'])-instant(row['effective_from']) != timedelta(seconds=900)):
            raise ValueError('source_public_retail_receipt_evaluation_conflict')
        if row['material_sha256'] != data['material_sha256']:
            raise ValueError('source_public_retail_material_revision_conflict')
    return value


def quantity_authority(metadata, q, unit, value):
    """Validate decimal fields under the public order contract, never guess scales."""
    data = metadata.get('selected_public_retail_data')
    if not isinstance(data, dict) or data.get('version') != VERSION:
        raise ValueError('source_public_retail_selected_metadata_absent')
    s = q['source']
    if (data['market_id'] != s['native_market_id'] or
            data['instrument_id'] != s['native_outcome_id'] or data['side'] != s['native_side']):
        raise ValueError('source_public_retail_selected_identity_conflict')
    if unit.unit != 'dollar_face_contracts' or unit.face_usd_per_native != '1':
        raise ValueError('source_public_retail_decimal_contract_units_required')
    grid = value['quantity_grid']
    expected = {'minimum_native': data['minimumTradeQty'],
        'increment_native': data['minimumTradeQty'],
        'legal_price_tick': data['orderPriceMinTickSize']}
    for field, number in expected.items():
        if Fraction(grid[field]) != Fraction(number) or Fraction(number) <= 0:
            raise ValueError('source_public_retail_decimal_grid_conflict')
    if data.get('quantity_alignment_authority') != 'public_orders_minimumTradeQty_alignment':
        raise ValueError('source_public_retail_quantity_increment_unqualified')
    if data.get('material_sha256', data['response_sha256']) != metadata.get('material_sha256'):
        raise ValueError('source_public_retail_material_revision_conflict')


def entry_example(value, quantity='100'):
    """One disclosed hypothetical fill, entry only; reuse shared fee arithmetic."""
    from app.fees.engine import calculate, Registry
    validate(value)
    data=value['metadata']
    if Fraction(quantity)/Fraction(data['minimumTradeQty']) % 1:
        raise ValueError('source_public_retail_quantity_off_grid')
    schedule='public-retail-single-taker-20261007'
    rules=Registry(dict(schema=1,schedules=[dict(venue='polymarket_us',product='event_contract',
        version=schedule,effective_from=data['entry_fee_effective_from'],
        effective_to=value['binding']['effective_until'],coefficient=data['feeCoefficient'],maker_coefficient='0.0125')]))
    result=calculate(dict(venue='polymarket_us',product='event_contract',environment='hypothetical',
        market_id=data['market_id'],trade_time=value['receipt']['response_at'],
        calculation_time=value['receipt']['response_at'],schedule_version=schedule,
        public_binding_version=VERSION,complete_order_history=True,
        public_retail_quantity=dict(market_id=data['market_id'],
            authority=data['quantity_alignment_authority'],response_sha256=data['response_sha256'],
            minimum_contracts=data['minimumTradeQty'],increment_contracts=data['minimumTradeQty'],
            price_tick_usd=data['orderPriceMinTickSize']),
        fills=[dict(fill_id='hyp:single',order_id='hyp:order',role='taker',unit='contracts',
            price=data['price'],quantity=quantity)],outcomes=dict(win='1',loss='0',tie='0.50')),rules)
    if result['unsupported']:
        raise ValueError('source_public_retail_entry_engine_refused')
    return dict(quantity=quantity,price=data['price'],entry_fee_usd=result['entry_fees'],
        raw_entry_fee_usd=result['trace'][0]['raw'],basis='hypothetical_one_order_one_fill',
        settlement_fee_usd=None,other_mandatory_costs_usd=None,
        effective_schedule_from=data['entry_fee_effective_from'],
        rounding='half_even_cents_cumulative_order_cap',
        authority='public_single_taker_entry_only',net_qualified=False)


def observation_audit(q, value=None):
    """Current public facts beside an exact older side; never financial authority."""
    if q['venue'] != 'polymarket_us':return None
    value = fresh_retained() if value is None and exact_fresh(q) else retained() if value is None else value
    validate(value)
    data = value['metadata']; s = q['source']
    if (q['venue'] != 'polymarket_us' or s['native_market_id'] != data['market_id'] or
            s['native_outcome_id'] != data['instrument_id'] or s['native_side'] != data['side']):
        return None
    return deepcopy(dict(version=VERSION, metadata=data,
        observed_at=value['receipt']['response_at'],
        effective_from=value['binding']['effective_from'],
        effective_until=value['binding']['effective_until'],
        historical_applicability=False,
        retained_observation_bound=bool(value.get('retained_evaluation_at') and exact_fresh(q,value)),
        quote_revision=value['binding'].get('quote_revision'),
        metadata_receipt=deepcopy(value['receipt']),
        event_linkage='exact_event_membership_retained' if value.get('retained_evaluation_at') else 'current_event_response_incomplete',
        binding_version=value['binding_version']))
