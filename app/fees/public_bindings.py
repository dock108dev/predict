"""Offline public fee bindings. Account facts and hypothetical fills stay inputs.

The old registry is immutable. Opt in with public_binding_version to use these
new document snapshots; audits embed the selected registry for exact reopening.
"""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from app.fees.engine import Registry, load_registry, number, stamp, digest

VERSION = 'public-contract-bindings-1'
PATH = Path(__file__).resolve().parents[1] / 'fixtures/public-contracts-v1.json'


def registry():
    data = deepcopy(load_registry().data)
    from app.collection.public_contracts import load
    facts = load()
    # Retain the historical registry and its open-ended interpretation verbatim.
    # This explicit successor alone closes its interval at the published change.
    for row in data['schedules']:
        if row['version'] == 'pmus-2026-07-01':
            row['effective_to'] = '2026-09-25T04:00:00Z'
    data['schedules'] += deepcopy(facts['fee_schedules'])
    return Registry(data)


def bind(context, *, market=None, membership=None, instrument=None):
    """Produce explicit existing-engine context; never fetch account or fills."""
    c = deepcopy(context)
    c['public_binding_version'] = VERSION
    venue = c['venue']
    if venue == 'kalshi' and membership is not None:
        if membership not in ('direct', 'non_direct'):
            raise ValueError('Explicit direct/non_direct membership required')
        precision = '0.0001' if membership == 'direct' else '0.01'
        if c.get('balance_precision', precision) != precision:
            raise ValueError('Account membership / precision conflict')
        c['balance_precision'] = precision
        c['membership_basis'] = dict(value=membership, kind='caller_account_fact_or_scenario',
            document='https://docs.kalshi.com/getting_started/fee_rounding')
    if venue == 'polymarket_us':
        if market is not None:
            if str(market.get('id')) != c['market_id']:
                raise ValueError('US fee listing identity conflict')
            if c.get('product')=='combo_contract':
                if market.get('isCombo') is not True:
                    raise ValueError('Explicit whole-combo association required')
                c['schedule_version']=('pmus-combo-2026-10-01' if stamp(c['trade_time'])>=stamp('2026-10-01T14:00:00Z') else 'pmus-combo-observed-20260930')
            elif str(market.get('feeCoefficient')) != '0.0695':
                raise ValueError('US selected coefficient conflicts with standard schedule')
            else:
                from app.collection.public_contracts import load
                typed=market.get('sportsMarketType') in load()['us_types']
                if market.get('isCombo') is True or not (market.get('isCombo') is False or typed):
                    raise ValueError('Exact typed single instrument or explicit non-combo association required')
                c['schedule_version'] = 'pmus-standard-2026-09-25'
            if c.get('product')!='combo_contract' and stamp(c['trade_time']) < stamp('2026-09-25T04:00:00Z'):
                raise ValueError('US standard schedule not effective at trade time')
            # Preserve a fingerprint of the complete original interpreted record;
            # only relevant decimal facts enter fee arithmetic. comboEnabled is
            # eligibility for a ticket, not evidence this single instrument is a combo.
            c['applicability_evidence']=dict(market_id=c['market_id'],feeCoefficient=str(market.get('feeCoefficient')),
                sportsMarketType=market.get('sportsMarketType'),isCombo=market.get('isCombo'),
                normalized_record_fingerprint=digest(market),binding_kind='explicit_single_or_whole_combo_association')
        if instrument is not None:
            if instrument.get('market_id') != c['market_id'] or not instrument.get('source'):
                raise ValueError('Exact source instrument quantity association required')
            scale = integer_scale(instrument.get('fractionalQtyScale', '1'))
            c['quantity_scale'] = str(scale)
            c['quantity_scale_evidence'] = deepcopy(instrument)
    if venue == 'novig' and c.get('api_regime') == 'v3':
        if market is None or str(market.get('marketId')) != c['market_id']:
            raise ValueError('Exact Novig v3 market required')
        fee = market.get('fee', {})
        if set(fee) != {'coefficient', 'makerCredit', 'charged'}:
            raise ValueError('Complete native v3 market.fee object required')
        if fee['charged'] not in ('WHEN_LIVE', 'ALWAYS'):
            raise ValueError('Unrecognized Novig v3 charge condition')
        if not 0 <= number(fee['makerCredit']) <= 1 or number(fee['coefficient']) < 0:
            raise ValueError('Invalid Novig v3 fee coefficients')
        c.update(product='v3_market', schedule_version='novig-v3-observed-20260930',
                 market_fee=deepcopy(fee), applicability_evidence=deepcopy(market))
    if venue == 'prophetx':
        if c['product'] != 'straight':
            raise ValueError('Public ProphetX binding supports straight markets only')
        if c.get('channel')=='api':
            raise ValueError('Public site fee cannot establish separately negotiated API/account fee terms')
        c['schedule_version'] = 'prophetx-public-v1.2-20260924'
        c['netting_scope'] = 'per_market'
    return c


def integer_scale(value):
    if not isinstance(value, str) or not value.isdigit() or not 1 <= int(value) <= 10**9:
        raise ValueError('Positive bounded integer scale string required')
    return int(value)


def us_execution(native):
    """Decode documented fixed-point units, independently of fee estimation."""
    order = native['order']
    ps = integer_scale(order['priceScale'])
    qs = integer_scale(order['fractionalQuantityScale'])
    def integer(key, obj):
        value = obj[key]
        if not isinstance(value, str) or not value.lstrip('-').isdigit():
            raise ValueError('Exact wire integer required: ' + key)
        return Decimal(value)
    # Proto3 omits zero commission. This documented default is not an exemption.
    commission = integer('commissionNotionalCollected',
                         dict(commissionNotionalCollected=native.get('commissionNotionalCollected', '0')))
    return dict(price=str(integer('lastPx', native) / ps),
                quantity=str(integer('lastShares', native) / qs),
                commission_usd=str(commission / (ps * qs)),
                fee_kind='maker_rebate' if commission < 0 else 'collected_fee',
                quantity_scale=str(qs), price_scale=str(ps),
                evidence_kind='decoded_report_not_estimated_fee')


def us_taker_volume(fills):
    """Explicit historical or hypothetical fills; risk, not contract face volume."""
    months={};seen=set()
    for f in fills:
        if f['fill_id'] in seen:raise ValueError('Duplicate fill in monthly volume')
        seen.add(f['fill_id'])
        if f['role'] not in ('maker','taker') or f['action'] not in ('buy','sell'):
            raise ValueError('Explicit liquidity role and buy/sell action required')
        p=number(f['price']);q=number(f['quantity'])
        if not 0<p<1 or q<=0:raise ValueError('Invalid volume scenario')
        month=stamp(f['trade_time']).astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m')
        if f['role']=='taker':months[month]=months.get(month,Decimal(0))+q*(p if f['action']=='buy' else 1-p)
    def tier(n):return '0.50' if n>=10000000 else '0.25' if n>=1000000 else '0.10' if n>=250000 else '0'
    return dict(version=VERSION,months={m:dict(taker_risk_usd=str(n),next_month_documented_rate=tier(n)) for m,n in months.items()},
                scope='Supplied complete monthly fills or explicit hypothetical volume; accelerated eligibility and weekly payout rounding separate',
                source='https://docs.polymarket.us/fees')
