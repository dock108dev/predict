"""Exact financial disclosure and typed per-metric availability for current reads."""
from fractions import Fraction as F
from copy import deepcopy
from app.comparison.cashflows import exact_wire as wire


def statuses(row, *, withdrawn=()):
    """Never confuse unsupported financial inputs with withdrawn currentness."""
    reason=row.get('probability_missing')
    reference_reason=(row.get('snapshot_benchmark_reason') or 'exact_reference_pair_unavailable') if reason else None
    fee=row.get('conditional_trade_benchmark') or {}
    def status(value, missing):
        reasons=list(withdrawn) if withdrawn else ([missing] if missing else [])
        return dict(state='withdrawn' if withdrawn or missing and 'expired' in missing else 'available' if value is not None else 'unavailable',
            reasons=reasons if value is None else [],detail=reason if value is None and missing==reference_reason else None)
    row['metric_status']=dict(
        reference_probability=status(row.get('probability'),reference_reason),
        before_fee_ev=status(row.get('gross_return_percent'),reference_reason or 'source_price_or_selection_unsupported'),
        after_trade_fee_ev=status(row.get('conditional_return_percent'),fee.get('reason') or reference_reason or 'trade_fee_inputs_unavailable'),
        conservative_trade_fee_ev=status(row.get('conservative_return_percent'),
            row.get('conservative_trade_benchmark',{}).get('reason') or 'conservative_fee_inputs_unavailable'),
        assumed_net_ev=status(row.get('net_return_percent'),'explicit_scenario_fee_sizing_inputs_required'))
    return row


def disclose(row, original, refs):
    from app.comparison.snapshot_named_benchmark import selected_references
    witnesses=selected_references(row,original,refs)
    ref=row.get('snapshot_benchmark') or row.get('reference') or {}
    p=None if row.get('probability') is None else F(row['probability'])
    pair=[dict(id=r['id'],source=deepcopy(r['original_record']['quote']['source']),original=deepcopy(r['original_record']['quote']['original']),
        selection=deepcopy(r['original_record']['selection']),times=deepcopy(r['original_record']['quote']['times']),
        provider_clocks=deepcopy(r['original_record']['quote'].get('provider_clocks')),
        receipt_sha256=r['original_record']['quote'].get('provenance',{}).get('sha256')) for r in witnesses]
    selected=ref.get('selected')
    row['reference_calculation']=dict(available=p is not None and len(pair)==2,venue=ref.get('bookmaker'),
        pair=pair,selected=selected,selected_id=pair[selected]['id'] if pair and selected is not None else None,
        selected_predicate=deepcopy(ref.get('selected_predicate')),
        selected_equality=deepcopy(ref.get('selected_equality')),
        occurrence=deepcopy(ref.get('selected_identity')),
        method='proportional_no_vig',probability=wire(p),
        fair_decimal_odds=wire(None if p is None else 1/p),
        fair_american_odds=wire(None if p is None else -100*p/(1-p) if p>=F(1,2) else 100*(1-p)/p),
        overround=wire(sum((1/F(w['original']['value']) for w in pair),F(0))-1) if len(pair)==2 else None,
        conditioning='decisive win/loss only; equality, ties, pushes and exceptional settlement excluded',
        full_state_probability=False,provenance='exact retained pair; original provider prices and clocks')
    return statuses(row)
