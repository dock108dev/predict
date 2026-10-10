"""S06 exact metric ranking and shared-current read model.

The calculator supplies exact values; this consumer never derives a financial
number from display text and never acquires. Opportunity IDs survive revisions.
"""
from copy import deepcopy
from fractions import Fraction
from .current_dependencies import digest

VERSION = 'comparison-metrics-1'


def exact_value(metric):
    if not metric or metric.get('eligible') is not True:
        return None
    exact = metric.get('exact')
    if not isinstance(exact, dict) or set(exact) - {'numerator','denominator','decimal_approx'}:
        raise ValueError('Eligible metric requires exact rational value')
    if int(exact['denominator']) <= 0:
        raise ValueError('Positive metric denominator required')
    value = Fraction(int(exact['numerator']), int(exact['denominator']))
    return value


def basis_key(metric):
    basis = metric.get('basis', {})
    required = ('conditioning','probability_basis','size_basis','fee_basis')
    if not metric.get('eligible'):
        return None
    if any(basis.get(k) is None for k in required):
        raise ValueError('Complete comparable metric basis required')
    return digest({k:basis[k] for k in required})


def ranked(rows, *, metric='net_ev'):
    def key(row):
        value = exact_value(row.get(metric))
        return (value is None, -value if value is not None else Fraction(0), row['id'])
    return sorted(rows, key=key)


def best(rows, *, basis=None):
    eligible = [row for row in rows if exact_value(row.get('net_ev')) is not None]
    bases = {basis_key(row['net_ev']) for row in eligible}
    if basis is not None:
        eligible = [row for row in eligible if basis_key(row['net_ev']) == basis]
    elif len(bases) > 1:
        return dict(eligible=False, selected_quote_id=None, selected_venue=None,
                    reason='incomparable_metric_bases', value=None)
    if not eligible:
        return dict(eligible=False, selected_quote_id=None, selected_venue=None,
                    reason='net_inputs_unavailable', value=None)
    chosen = ranked(eligible)[0]
    return dict(deepcopy(chosen['net_ev']), selected_quote_id=chosen['id'], selected_venue=chosen['venue'])


def snapshot_metrics(snapshot, *, venue=None, league=None, market=None, basis=None,
                     results='all', search=''):
    from app.dashboard.current_contract import VENUES, quotes_of
    if venue is not None and venue not in VENUES:
        raise ValueError('Unsupported execution venue filter')
    if results not in ('all','positive','unavailable'):
        raise ValueError('Explicit result sign filter required')
    rows = []
    selections = []
    pairs = []
    for event in snapshot['events']:
        if league and event['league'] != league or search.lower() not in event['title'].lower():continue
        for group in event['groups']:
            if market and group['market'] != market:continue
            for outcome in group['outcomes']:
                local = []
                for quote in quotes_of(outcome):
                    if venue and quote['venue'] != venue:continue
                    metric = deepcopy(quote['calculations'].get('net_ev', dict(eligible=False, exact=None,
                        value=None, display_value=None, reason='comparison_inputs_unbound',
                        estimate_class='unavailable', basis={})))
                    gross=deepcopy(quote['calculations'].get('ev'))
                    if not gross or not gross.get('eligible'):
                        gross=deepcopy(metric.get('details',{}).get('gross_decisive_benchmark',gross))
                    row = dict(id=quote['id'], quote_revision=quote['revision'], event_id=event['id'],
                        group_id=group['id'], outcome_id=outcome['id'], title=event['title'],
                        league=event['league'], market=group['market'], period=group['period'],
                        start_at=event['start_at'],predicate=outcome['predicate'],signed_line=outcome['signed_line'],
                        period_boundary=group['period_boundary'],
                        selection=outcome['label'], venue=quote['venue'], venue_odds=quote['display'].get('american'),
                        reference_odds=quote.get('sharp_reference', {}).get('selected_odds') or
                            (metric.get('details',{}).get('reference') or {}).get('selected_odds'),
                        gross=gross, net_ev=metric,
                        conservative=deepcopy(quote['calculations'].get('conservative')), quote=deepcopy(quote))
                    row['basis_id'] = basis_key(metric)
                    local.append(row)
                    if basis and row['basis_id'] != basis:continue
                    value = exact_value(metric)
                    if results == 'positive' and (value is None or value <= 0):continue
                    if results == 'unavailable' and value is not None:continue
                    rows.append(row)
                selections.append(dict(id=outcome['id'], best=best(local, basis=basis)))
            for pair in group.get('comparison_pairs', []):
                if venue and not any(leg['venue'] == venue for leg in pair['legs']):continue
                value=exact_value(pair.get('buffered_minimum_return'))
                if results=='positive' and (value is None or value<=0):continue
                if results=='unavailable' and value is not None:continue
                if basis and basis!=pair['category']:continue
                pairs.append(dict(deepcopy(pair),event_id=event['id'],group_id=group['id'],
                    title=event['title'],league=event['league'],market=group['market'],period=group['period']))
    # Different bases are deliberately separate groups, never one ranked list.
    buckets = {}
    for row in rows:buckets.setdefault(row['basis_id'] or 'unavailable', []).append(row)
    groups = [dict(basis_id=key, rows=ranked(values)) for key, values in sorted(buckets.items())]
    return dict(schema=VERSION, runtime_id=snapshot['runtime_id'], state_revision=snapshot['state_revision'],
        clock_at=snapshot['clock_at'], mode=snapshot['mode'], source_status=deepcopy(snapshot['source_status']), groups=groups,
        rows=[row for group in groups for row in group['rows']], selections=selections,
        pairs=[pair for category in sorted({p['category'] for p in pairs}) for pair in
            ranked([p for p in pairs if p['category']==category],metric='buffered_minimum_return')],
        pair_groups=[dict(basis_id=category,pairs=ranked([p for p in pairs if p['category']==category],
            metric='buffered_minimum_return')) for category in sorted({p['category'] for p in pairs})],
        limits=dict(candidate_pairs=256, allocation_evaluations=1024, returned_results=128,
                    single_quantity_evaluations=64, single_native_quantity_ceiling=1000000),
        searches=[dict(event_id=e['id'],group_id=g['id'],**deepcopy(g['comparison_search']))
            for e in snapshot['events'] for g in e['groups'] if g.get('comparison_search')],
        acquisition_requests=0)
