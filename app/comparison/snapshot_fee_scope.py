"""Captured instrument fee applicability; never infer private account terms."""
from copy import deepcopy
from fractions import Fraction as F
from hashlib import sha256
import json
from pathlib import Path

from app.comparison.current_dependencies import instant
from app.fees.evidence import earliest_end
from app.storage.store import hashed

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_PATH = ROOT / '.local/trade-fee-account-facts.json'
RANKING_BASIS = 'decisive_taker_one_usd_claim_one_fill_total_risk_v1'


def applicability(record):
    meta = record.get('comparison_source_metadata', {})
    retail = meta.get('public_retail_observation') or {}
    return dict(series_id=meta.get('series_id'), native_market_type=meta.get('native_market_type'),
        native_key=meta.get('native_key'), phase=meta.get('phase'),
        retail=deepcopy(retail), source=deepcopy(record['quote']['source']))


def kalshi_account(at):
    """Optional evidenced local fact, separate from hypothetical Admin rates.

    An absent or invalid file never defaults to direct membership. Account facts
    and their evidence bytes join ordinary policy identity, including removal.
    """
    if not ACCOUNT_PATH.exists():
        raise ValueError('kalshi_account_membership_unbound')
    data=json.loads(ACCOUNT_PATH.read_bytes())
    fact=data['kalshi']
    if data.get('version')!='trade-fee-account-facts-1' or fact.get('channel')!='direct_api':
        raise ValueError('kalshi_account_channel_unbound')
    if not instant(fact['effective_from']) <= at < instant(fact['review_before']):
        raise ValueError('kalshi_account_fact_expired_or_not_effective')
    evidence=fact['evidence'];path=Path(evidence['path'])
    if not path.is_absolute():path=ROOT/path
    if sha256(path.read_bytes()).hexdigest()!=evidence['sha256']:
        raise ValueError('kalshi_account_evidence_changed')
    if fact.get('membership')!='direct':
        raise ValueError('kalshi_non_direct_intermediary_trade_fees_unbound')
    return deepcopy(fact)


def kalshi_scenarios(q, evidence, at, *, quantity='1'):
    """Resolve source metadata once, then use the existing fee engine for rounding."""
    from app.collection.native_fee_metadata import context
    from app.fees.engine import Registry, calculate
    body=json.loads((ROOT/evidence['path']).read_bytes())
    scope=q.get('fee_applicability') or {};source=q['source']
    series_id=scope.get('series_id');event_id=source['native_event_id']
    market_id=source['native_market_id']
    row=body['series'].get(series_id)
    if not row or row['league']!=q['league'] or row['family']!=q['market']['market'].replace('winner','moneyline'):
        raise ValueError('kalshi_series_fee_scope_unbound')
    if (source['provider']!='kalshi' or source['native_side'] not in ('yes','no')
            or source['native_outcome_id']!=source['native_side']
            or not event_id.startswith(series_id+'-') or not market_id.startswith(event_id+'-')
            or scope.get('native_key')!=['kalshi',event_id,market_id,source['native_outcome_id'],source['native_side']]):
        raise ValueError('kalshi_native_fee_identity_conflict')
    quantity=F(quantity)
    if quantity <= 0:
        raise ValueError('kalshi_positive_quantity_required')
    original=q['original']
    if (original['units']!='usd_per_contract' or original.get('quantity_units')!='contracts'
            or original.get('payout_units')!='USD' or F(original.get('payout','0'))!=1):
        raise ValueError('kalshi_binary_claim_required')
    changes=dict(series_fee_change_arr=[r for r in body['series_changes']['series_fee_change_arr'] if r['series_ticker']==series_id])
    events=body['event_changes']
    if events.get('cursor')!='':raise ValueError('kalshi_event_fee_history_incomplete')
    events=dict(cursor='',event_fee_changes=[r for r in events['event_fee_changes'] if r['event_ticker']==event_id])
    metadata=context(row['response']['series'],changes,events,series_id,event_id,evidence['reviewed_at'])
    future=[r['scheduled_ts'] for r in [*metadata['series_changes'],*metadata['event_changes']]
        if instant(r['scheduled_ts'])>at]
    until=earliest_end(evidence['review_before'],*future)
    evidence=dict(evidence,review_before=until,series_id=series_id,event_id=event_id,
        metadata_revision=hashed(metadata))
    registry=Registry(dict(schema=1,schedules=[dict(venue='kalshi',product='event_contract',
        version=evidence['version'],coefficient=evidence['fee_rate'],
        effective_from=evidence['reviewed_at'],effective_to=until,sources=[evidence])]))
    scenarios=[]
    for membership,precision in [('direct','0.0001'),('non_direct','0.01')]:
        audit=calculate(dict(venue='kalshi',environment='production',market_id=market_id,
            product='event_contract',trade_time=at.isoformat(),calculation_time=at.isoformat(),
            series_id=series_id,event_id=event_id,kalshi_metadata=metadata,balance_precision=precision,
            applicability_evidence=scope,complete_order_history=True,
            fills=[dict(fill_id='modeled-single-fill',order_id='modeled-single-order',role='taker',
                price=original['value'],quantity=str(quantity),unit='contracts')]),registry)
        if audit['entry_cash_requirement'] is None:raise ValueError('; '.join(audit['unsupported']))
        scenarios.append(dict(membership=membership,balance_precision=precision,
            risk=audit['entry_cash_requirement'],fee=str(F(audit['entry_cash_requirement'])-F(original['value'])*quantity),
            rounding_trace=audit['trace'],resolved_terms=audit['resolved_terms'],
            account_verified=False,ranking_eligible=False,intermediary_charges='not included'))
    return scenarios,evidence
