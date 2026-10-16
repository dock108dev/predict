"""Transient calculation availability; independent of transport and positive filters.

Prices are captured together and evaluated at read time. The frame preserves
original clocks and never claims a simultaneous historical execution.
"""
from collections import Counter, defaultdict
from .current_dependencies import instant
from copy import deepcopy
import re

VERSION = 'predict-calculation-availability-1'
STATES = ('numeric_current', 'numeric_last_known', 'missing_reference',
          'unsupported_inputs', 'calculation_failed', 'not_evaluated')
METRICS = ('buffered_ev_usd', 'conditional_buffered_ev_usd',
           'buffered_decisive_opposing_margin_usd', 'buffered_complete_modeled_minimum_usd')


def frame(quotes, reference, at):
    rows = [dict(quote_id=q['id'], venue=q['venue'], source_state=q['state'],
                 times=deepcopy(q['times']), source_age_seconds=None if q['times']['source_at'] is None else (at-instant(q['times']['source_at'])).total_seconds()) for q in quotes]
    originals = [] if reference is None else [r.to_dict() for r in reference.outcomes]
    clocks = [q['times']['source_at'] for q in quotes]
    clocks += [r.source_at for r in (() if reference is None else reference.outcomes)]
    return dict(version='predict-last-known-frame-1', evaluated_at=at.isoformat(),
                policy='captured_prices_current_applicability', captured_at=at.isoformat(),
                reference_age_seconds=[] if reference is None else [None if r.source_at is None else (at-instant(r.source_at)).total_seconds() for r in reference.outcomes],
                simultaneous_historical_trade=False,
                mixed_source_times=len(set(clocks)) > 1, quotes=rows,
                reference_originals=originals)


def _reasons(result):
    value = result.get('reasons', [])
    if isinstance(value, dict):
        value = [r for rows in value.values() for r in rows]
    elif isinstance(value, str):
        value = [value]
    benchmark = result.get('benchmark', {})
    if benchmark.get('reason'):
        value = [*value, benchmark['reason']]
    return sorted(set(r.strip() for row in value for r in str(row).split(';') if r.strip()))


def refusal(reasons):
    """Stable categories plus exact existing codes; prose is never a UI parser."""
    if any(any(v in r for v in ('reference_missing', 'reference_inputs_unbound',
            'selected_benchmark_missing', 'pinnacle_reference_missing')) for r in reasons):
        return 'missing_reference', ['selected_reference_missing']
    if any('short_collateral_unresolved' in r for r in reasons):
        return 'unsupported_inputs', ['short_collateral_unresolved']
    codes = [r for r in reasons if re.fullmatch(r'[a-z][a-z0-9_]{0,159}', r)]
    if any(any(v in r for v in ('conflict', 'future', 'clock_unknown', 'clock_invalid')) for r in reasons):
        return 'unsupported_inputs', sorted(set(['invalid_inputs', *codes]))
    if any(any(v in r for v in ('unresolved', 'unbound', 'unknown', 'expired', 'not_effective',
            'unsupported', 'required', 'missing', 'excluded', 'ended', 'invalid', 'off_grid')) for r in reasons):
        return 'unsupported_inputs', sorted(set(['unsupported_model_or_contract', *codes]))
    return 'calculation_failed', sorted(set(['calculation_failed', *codes]))


def result_availability(result, *, pair=False):
    reasons = _reasons(result)
    stale = sorted(set(result.get('freshness', {}).get('reasons', []) + result.get('eligibility_reasons', [])))
    state, codes = refusal(reasons)
    current = not stale
    numeric_state = 'numeric_current' if current else 'numeric_last_known'
    metrics = result.get('financial_metrics', {})
    fields = METRICS if pair else METRICS[:2]
    per_metric = {}
    for field in fields:
        numeric = metrics.get(field) is not None
        metric_state, metric_codes = state, codes
        if numeric:
            metric_state, metric_codes = numeric_state, stale
        elif field == 'buffered_ev_usd' and metrics.get('conditional_buffered_ev_usd') is not None:
            metric_state, metric_codes = 'unsupported_inputs', ['complete_probability_partition_unsupported']
        elif pair and not reasons:
            metric_state, metric_codes = 'unsupported_inputs', ['complete_probability_partition_unsupported']
        per_metric[field] = dict(state=metric_state, reason_codes=metric_codes)
    primary = 'buffered_decisive_opposing_margin_usd' if pair else (
        'buffered_ev_usd' if metrics.get('buffered_ev_usd') is not None else 'conditional_buffered_ev_usd')
    chosen = per_metric[primary]
    return dict(version=VERSION, state=chosen['state'], reason_codes=sorted(set([*chosen['reason_codes'], *stale])),
                numeric_metrics=[k for k in fields if metrics.get(k) is not None],
                metrics=per_metric, current_opportunity_eligible=bool(
                    result.get('classification', {}).get('main_positive_eligible') or
                    result.get('classification', {}).get('positive_rule_sensitive_eligible')))


def summary(items, *, games=1, evaluated=True, failures=()):
    """Count the entire evaluated scope before result filtering, never displayed rows."""
    counts = Counter({state: 0 for state in STATES})
    causes = defaultdict(lambda: dict(results=0, games=set(), venues=set()))
    positive = 0
    for game, venues, value in items:
        counts[value['state']] += 1
        positive += value['current_opportunity_eligible']
        for code in value['reason_codes']:
            cause = causes[code]; cause['results'] += 1; cause['games'].add(game); cause['venues'].update(venues)
    for game, code in failures:
        counts['calculation_failed'] += 1
        cause = causes[code]; cause['results'] += 1; cause['games'].add(game)
    total = sum(counts.values()); numeric = counts['numeric_current'] + counts['numeric_last_known']
    outcome = ('not_evaluated' if not evaluated else 'unavailable' if not numeric and total else
               'evaluated_no_positive' if not total else 'positive' if positive else
               'partial' if numeric < total else 'last_known_only' if not counts['numeric_current'] else
               'evaluated_no_positive')
    return dict(version=VERSION, scope='evaluated_results_before_filter', games=games,
                total_results=total, numeric_results=numeric, current_results=counts['numeric_current'],
                positive_results=positive, counts=dict(counts), outcome=outcome,
                causes=[dict(code=k, affected_results=v['results'], affected_games=len(v['games']),
                             venues=sorted(v['venues'])) for k, v in sorted(causes.items())])


def combine(summaries, *, games, failures=(), evaluated=True):
    """Combine page summaries without retaining individual calculations."""
    counts = Counter({state: 0 for state in STATES}); causes = {}; positive = 0
    for value in summaries:
        counts.update(value['counts']); positive += value['positive_results']
        for c in value['causes']:
            aggregate = causes.setdefault(c['code'], dict(code=c['code'], affected_results=0, affected_games=0, venues=set()))
            aggregate['affected_results'] += c['affected_results']; aggregate['affected_games'] += c['affected_games']; aggregate['venues'].update(c['venues'])
    base = summary([], games=games, evaluated=evaluated, failures=failures)
    counts.update(base['counts'])
    for c in base['causes']:
        a = causes.setdefault(c['code'], dict(code=c['code'], affected_results=0, affected_games=0, venues=set()))
        a['affected_results'] += c['affected_results']; a['affected_games'] += c['affected_games']
    total = sum(counts.values()); numeric = counts['numeric_current'] + counts['numeric_last_known']
    base.update(total_results=total, numeric_results=numeric, current_results=counts['numeric_current'],
                positive_results=positive, counts=dict(counts),
                outcome='not_evaluated' if not evaluated else 'unavailable' if not numeric and total else
                'evaluated_no_positive' if not total else 'positive' if positive else 'partial' if numeric < total else
                'last_known_only' if not counts['numeric_current'] else 'evaluated_no_positive',
                causes=[dict(c, venues=sorted(c['venues'])) for c in causes.values()])
    return base
