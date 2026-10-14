"""Exact metric ranking and shared-current read model.

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
        funded=row.get('funded_estimate')
        if funded is not None:
            raw=funded.get('buffered_return_percent')
            value=None if raw is None else Fraction(raw)
        else:value=exact_value(row.get(metric))
        return (value is None, -value if value is not None else Fraction(0), row['id'])
    return sorted(rows, key=key)


def best_funded(rows):
    supported=[row for row in rows if row.get('funded_estimate',{}).get('ranking_eligible') and row['funded_estimate'].get('buffered_return_percent') is not None]
    complete=[row for row in supported if row['funded_estimate']['conditioning']=='modeled_complete']
    supported=complete or [row for row in supported if row['funded_estimate']['conditioning']=='modeled_conditional']
    if not supported:return dict(model_available=False,selected_quote_id=None,selected_venue=None,reason='funded_current_estimate_unavailable')
    chosen=ranked(supported)[0]
    return dict(deepcopy(chosen['funded_estimate']),selected_quote_id=chosen['id'],selected_venue=chosen['venue'])


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
                     results='all', search='', copy_graph=True):
    from app.dashboard.current_contract import VENUES, quotes_of
    if venue is not None and venue not in VENUES:
        raise ValueError('Unsupported execution venue filter')
    if results not in ('all','positive','zero','negative','unavailable','reference_free'):
        raise ValueError('Explicit result sign filter required')
    funded_pairs=[]
    from .shared_templates import shared
    compact=shared(snapshot.get('comparison_profiles'))
    clone=deepcopy if copy_graph else lambda value:value
    rows = []
    selections = []
    pairs = []
    for event in snapshot['events']:
        if league and event['league'] != league or search.lower() not in event['title'].lower():continue
        if market in (None,'winner'):
            funded_pairs.extend(dict(clone(pair),event_id=event['id'],title=event['title'],league=event['league'],market='winner',period='full_game') for pair in event.get('funded_pairs',[]) if not venue or any(leg['venue']==venue for leg in pair['legs']))
        for group in event['groups']:
            if market and group['market'] != market:continue
            for outcome in group['outcomes']:
                local = []
                for quote in quotes_of(outcome):
                    if venue and quote['venue'] != venue:continue
                    metric = clone(quote['calculations'].get('net_ev', dict(eligible=False, exact=None,
                        value=None, display_value=None, reason='comparison_inputs_unbound',
                        estimate_class='unavailable', basis={})))
                    gross=clone(quote['calculations'].get('ev'))
                    if not gross or not gross.get('eligible'):
                        gross=clone(metric.get('details',{}).get('gross_decisive_benchmark',gross))
                    row = dict(id=quote['id'], quote_revision=quote['revision'], event_id=event['id'],
                        group_id=group['id'], outcome_id=outcome['id'], title=event['title'],
                        league=event['league'], market=group['market'], period=group['period'],
                        start_at=event['start_at'],predicate=outcome['predicate'],signed_line=outcome['signed_line'],
                        period_boundary=group['period_boundary'],
                        selection=outcome['label'], venue=quote['venue'], venue_odds=quote['display'].get('american'),
                        reference_odds=quote.get('sharp_reference', {}).get('selected_odds') or
                            (metric.get('details',{}).get('reference') or {}).get('selected_odds'),
                        gross=gross, net_ev=metric,
                        conservative=clone(quote['calculations'].get('conservative')), quote=clone(dict(quote,calculations={k:v for k,v in quote['calculations'].items() if not compact or k not in ('net_ev','conservative','ev')})))
                    funded=quote['calculations'].get('funded_estimate')
                    row['funded_estimate']=clone(funded)
                    row['basis_id'] = funded.get('conditioning','unavailable') if funded is not None else basis_key(metric)
                    local.append(row)
                    if basis and row['basis_id'] != basis:continue
                    value = (None if funded.get('buffered_profit_usd') is None else Fraction(funded['buffered_profit_usd'])) if funded is not None else exact_value(metric)
                    if results == 'positive' and (value is None or value <= 0):continue
                    if results == 'unavailable' and value is not None:continue
                    if results == 'zero' and value!=0:continue
                    if results == 'negative' and (value is None or value>=0):continue
                    if results == 'reference_free':continue
                    rows.append(row)
                selections.append(dict(id=outcome['id'], best=best_funded(local) if any(row.get('funded_estimate') is not None for row in local) else best(local, basis=basis)))
            for pair in group.get('comparison_pairs', []):
                if venue and not any(leg['venue'] == venue for leg in pair['legs']):continue
                value=exact_value(pair.get('buffered_minimum_return'))
                if results=='positive' and (value is None or value<=0):continue
                if results=='unavailable' and value is not None:continue
                if basis and basis!=pair['category']:continue
                pairs.append(dict(deepcopy(pair),event_id=event['id'],group_id=group['id'],
                    title=event['title'],league=event['league'],market=group['market'],period=group['period']))
    if any('funded_pairs' in e for e in snapshot['events']):
        def included(pair):
            value=None if pair.get('buffered_profit_usd') is None else Fraction(pair['buffered_profit_usd'])
            if basis and basis not in (pair.get('conditioning'),pair.get('category')):return False
            if results=='reference_free':return pair.get('conditioning')=='reference_free_scenarios'
            if results=='unavailable':return value is None
            if results=='positive':return value is not None and value>0
            if results=='zero':return value==0
            if results=='negative':return value is not None and value<0
            return True
        funded_pairs=[pair for pair in funded_pairs if included(pair)]
    if compact:
        # Rows own each selected quote once. Group membership and selected best
        # use compact summaries, preserving basis isolation and every alternative.
        for row in rows:
            row['quote']['calculations']={k:v for k,v in row['quote']['calculations'].items()
                if k not in ('net_ev','conservative','ev')}
    # Different bases are deliberately separate groups, never one ranked list.
    buckets = {}
    for row in rows:buckets.setdefault(row['basis_id'] or 'unavailable', []).append(row)
    groups = [dict(basis_id=key, rows=ranked(values)) for key, values in sorted(buckets.items())]
    flat_rows=[row for group in groups for row in group['rows']]
    if compact:
        groups=[dict(basis_id=g['basis_id'],row_ids=[r['id'] for r in g['rows']],
            basis=dict(conditioning=g['rows'][0]['funded_estimate']['conditioning']) if g['rows'][0].get('funded_estimate') is not None else g['rows'][0]['net_ev']['basis'],venues=sorted({r['venue'] for r in g['rows']})) for g in groups]
    return dict(schema=VERSION, runtime_id=snapshot['runtime_id'], state_revision=snapshot['state_revision'],
        clock_at=snapshot['clock_at'], estimate_policy=deepcopy(snapshot.get('estimate_policy')), mode=snapshot['mode'], source_status=deepcopy(snapshot['source_status']), groups=groups,
        rows=flat_rows, selections=selections,
        **(dict(funded_pairs=funded_pairs,funded_pair_searches=[dict(event_id=e['id'],**e['funded_pair_search']) for e in snapshot['events'] if 'funded_pair_search' in e and (not league or e['league']==league) and search.lower() in e['title'].lower()]) if any('funded_pairs' in e for e in snapshot['events']) else {}),
        pairs=[pair for category in sorted({p['category'] for p in pairs}) for pair in
            ranked([p for p in pairs if p['category']==category],metric='buffered_minimum_return')],
        pair_groups=[dict(basis_id=category,pairs=ranked([p for p in pairs if p['category']==category],
            metric='buffered_minimum_return')) for category in sorted({p['category'] for p in pairs})],
        limits=dict(candidate_pairs=256, allocation_evaluations=1024, returned_results=128,
                    single_quantity_evaluations=64, single_native_quantity_ceiling=1000000),
        searches=[dict(event_id=e['id'],group_id=g['id'],**deepcopy(g['comparison_search']))
            for e in snapshot['events'] for g in e['groups'] if g.get('comparison_search') and (not league or e['league']==league) and search.lower() in e['title'].lower()],
        acquisition_requests=0)
