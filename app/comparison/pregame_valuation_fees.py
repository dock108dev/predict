"""Adapt frozen retail evidence to the fee engine for a single taker order."""
from fractions import Fraction as F
from hashlib import sha256
import json

from app.fees.engine import Registry, calculate

from .cashflows import exact_wire as wire
from .current_dependencies import instant
from .snapshot_fee_scope import ROOT, kalshi_fee_context
from .snapshot_pair_fees import _leg_fee
from .snapshot_polymarket_fee import CUTOVER, STANDARD_TIERS, order_fee
from .snapshot_conservative import prophetx_public_fee


def _fills(levels):
    return [dict(price=wire(price), quantity=wire(quantity)) for price, quantity in levels]


def _same_entry(audits, field, stake=0):
    amounts = {F(audit[field]) - stake for audit in audits if audit.get(field) is not None}
    if not amounts or any(audit.get(field) is None for audit in audits):
        raise ValueError('unit_fee_schedule_unverified')
    if len(amounts) != 1:
        raise ValueError('unit_fee_retail_rounding_or_tier_unverified')
    return amounts.pop(), F(0), {}, audits[0]['trace']


def retail_order(row, terms, cost, fee):
    if not fee.get('available'):
        raise ValueError('unit_fee_schedule_unverified')
    evidence = fee.get('evidence') or {}
    venue = row['venue']
    provider = (row.get('source') or {}).get('provider')
    if venue == 'novig' and provider == 'sportsgameodds' and fee.get('classification') == 'exact_public':
        # This reviewed pregame zero is independent of amount. _leg_fee
        # verifies the exact catalog link, witness price, phase and schedule.
        quantity = F(fee['quantity'])
        proof = _leg_fee(row, stake=cost * quantity, price=cost, quantity=quantity,
                         receipts={'win': quantity, 'loss': F(0)})
        if proof['available'] and F(proof['at_fill_usd']) == 0 and (
                (evidence.get('catalog_fee_terms') or {}).get('charged') == 'WHEN_LIVE'
                or evidence.get('basis') == 'reviewed_retail_pregame_straight'):
            return lambda _legs, _stake: (F(0), F(0), {}, proof['rounding_trace']), evidence, F(0)
    if terms.get('order_type') != 'taker' or fee.get('liquidity_role') != 'taker':
        raise ValueError('unit_fee_order_type_unverified')
    if venue == provider == 'polymarket_us' and evidence.get('order_inserted_at'):
        # The sealed fee has already validated exact market, side and unit.
        # Use the entire ordered fill, with one rounding/fee history per order.
        if F(evidence['acquired_price_usd']) != cost or evidence['market_id'] != row['source']['native_market_id']:
            raise ValueError('unit_fee_schedule_unverified')
        when = evidence['order_inserted_at']
        tick = F(row['fee_applicability']['retail']['values']['orderPriceMinTickSize'])
        if tick <= 0 or any(F(leg['price']) % tick for leg in terms['asks']):
            raise ValueError('unit_fill_depth_conflict')
        tiers = STANDARD_TIERS if instant(when) >= instant(CUTOVER) else (STANDARD_TIERS[0],)
        def evaluated(levels, stake):
            return _same_entry([order_fee(evidence['market_id'], inserted_at=when,
                evaluated_at=when, fills=_fills(levels), tier=tier) for tier in tiers], 'entry_fees')
        # Cost upper bounds suffice to find the legal fill. If fees differ
        # across public tiers there, report the missing tier instead.
        if len(tiers) > 1:
            def bounded(levels, stake):
                return _same_entry([order_fee(evidence['market_id'], inserted_at=when, evaluated_at=when,
                    fills=_fills(levels), tier=tiers[0])], 'entry_fees')
            evaluated.sizing_bound = bounded
        return evaluated, dict(evidence, public_tiers_considered=list(tiers)), None
    if venue == provider == 'kalshi' and evidence.get('path'):
        body = (ROOT / evidence['path']).read_bytes()
        if sha256(body).hexdigest() != evidence['sha256']:
            raise ValueError('unit_fee_schedule_unverified')
        context, registry, verified = kalshi_fee_context(row, evidence, instant(row['captured_at']), body=json.loads(body))
        if evidence.get('metadata_revision') != verified['metadata_revision']:
            raise ValueError('unit_fee_schedule_unverified')
        registry = Registry(registry)
        def audits(levels):
            fills = [dict(fill, order_id='modeled-order', fill_id=str(i), role='taker', unit='contracts')
                     for i, fill in enumerate(_fills(levels))]
            return [calculate(dict(context, balance_precision=precision, fills=fills,
                applicability_evidence=row['fee_applicability']), registry) for precision in ('0.0001', '0.01')]
        def evaluated(levels, stake):
            return _same_entry(audits(levels), 'entry_cash_requirement', stake)
        def bounded(levels, stake):
            receipts = audits(levels)
            if any(audit['entry_cash_requirement'] is None for audit in receipts):
                raise ValueError('unit_fee_schedule_unverified')
            return max(F(audit['entry_cash_requirement']) for audit in receipts) - stake, F(0), {}, receipts[0]['trace']
        evaluated.sizing_bound = bounded
        return evaluated, dict(evidence, balance_precisions_considered=['0.0001', '0.01']), None
    if venue == 'prophetx' and row['league'] == 'NHL' and evidence.get('nhl_taker_coefficient'):
        def evaluated(levels, stake):
            model = prophetx_public_fee(row, at=row['captured_at'], review=evidence,
                                        quantity=sum(q for _, q in levels), fills=[(q, p) for p, q in levels])
            if not model['available']:
                raise ValueError('unit_fee_schedule_unverified')
            return F(model['trade_fee_usd']), F(0), {}, model['details']['rounding_trace']
        return evaluated, evidence, None
    raise ValueError('unit_fee_schedule_unverified')
