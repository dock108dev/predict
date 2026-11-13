"""Enumerate eligible financial inputs from working rows without reading the desk result."""
from collections import Counter, defaultdict
from datetime import timedelta
from fractions import Fraction

from app.comparison.ordinary_arb import DEFAULT_FUNDING, current_payoff, evaluate
from app.comparison.sgo_reference import MAX_AGE_SECONDS
from app.storage import comparison_snapshot as snapshots, ordinary_publication as live
from app.storage.ordinary_projection import source_allowed
from app.storage.store import stamp

from .coverage_funnel import NATIVE_VENUES, SGO_OFFER_VENUES, configured_cohorts
from .fee_coverage import source_key
from .snapshot_display import ranking_value


def capture_candidates(db, deps, *, at):
    # An eligible clock cannot be newer than its source receipt. Include every
    # event with a recent offer or reference frame, using the widest existing
    # clock allowance. Exact clock and lifecycle checks happen after capture.
    rows = db.execute('''SELECT DISTINCT c.event_id AS id FROM current_offer o
        JOIN current_contract c ON c.id=o.contract_id
        WHERE c.id=ANY(%s) AND (o.received_order>=extract(epoch FROM %s::timestamptz)
             OR o.facts ? 'book_confirmation')
        UNION SELECT e.id FROM current_event e
        JOIN current_sgo_event_frame f ON f.event_id=e.native_event_id
        WHERE e.provider='sportsgameodds' AND f.received_order>=extract(epoch FROM %s::timestamptz)''',
        (list(deps), at-timedelta(seconds=MAX_AGE_SECONDS), at-timedelta(seconds=MAX_AGE_SECONDS))).fetchall()
    return sorted(row['id'] for row in rows)


def _eligible_scope(row, configured):
    provider = row.get('source', {}).get('provider')
    if provider in NATIVE_VENUES and row['venue'] != provider:
        return False
    if provider not in NATIVE_VENUES and (provider != 'sportsgameodds' or row['venue'] not in SGO_OFFER_VENUES):
        return False
    return any((provider, row['venue'], row['league'], row['market']['market'], row['market']['period'], phase) in configured
               for phase in ('pregame', 'in_game'))


def _phase(row):
    return 'in_game' if row['game_state'] == 'live' else 'pregame'


def _row_key(row):
    return (row['source']['provider'], row['venue'], row['league'], row['market']['market'], row['market']['period'], _phase(row))


def _pair_key(pair, rows):
    if (not snapshots.exact_arb_pair(pair) or not all(leg in rows for leg in pair['legs'])
            or len({rows[leg]['game_state'] for leg in pair['legs']}) != 1):
        return None
    return frozenset(source_key(rows[leg]) for leg in pair['legs'])


def _rate(covered, eligible):
    return round(100 * covered / eligible, 4) if eligible else None


def _observed_opposition(row):
    """Index literal peer prices for diagnostics, without asserting equivalence."""
    record = row.get('original_record') or {}
    event = record.get('event') or {}
    selection = record.get('selection') or {}
    market = row['market']
    family = market['market']
    home, away = event.get('home'), event.get('away')
    if not home or not away or home == away:
        return None
    side = selection.get('predicate')
    line = None
    if family == 'total' and side in ('over', 'under'):
        line = Fraction(selection['signed_line'])
        higher = side == 'over'
    elif family in ('spread', 'winner', 'moneyline'):
        participant = selection.get('participant')
        if participant not in (home, away):
            return None
        higher = participant == home
        if family == 'spread' and side == 'cover':
            signed = Fraction(selection['signed_line'])
            line = signed if higher else -signed
        elif family != 'spread' and side in ('win', 'not_win'):
            higher = higher if side == 'win' else not higher
        else:
            return None
    else:
        return None
    return (row['league'], home, away, stamp(row['start_at']), family, market['period'], line), higher


def _native_pair_input_gaps(selected, current, raw_pairs, displayed, *, at):
    """Classify one missing condition per current direct offer, with exact proofs."""
    native = {id_: row for id_, row in selected.items() if row['source']['provider'] in NATIVE_VENUES}
    current_native = native.keys() & current.keys()
    if not current_native:
        return []
    present, pending, phased, stale = set(), set(), set(), set()
    for pair in raw_pairs:
        if not all(leg in native for leg in pair['legs']):
            continue
        key = _pair_key(pair, current)
        if key:
            (present if key in displayed else pending).update(pair['legs'])
        elif all(leg in current for leg in pair['legs']):
            phased.update(pair['legs'])
        else:
            stale.update(pair['legs'])

    unexplained = current_native - present - pending - phased - stale
    observed, anchors, keys = defaultdict(list), {}, {}
    for id_, row in native.items():
        source = row['source']
        anchors.setdefault((source['provider'], source['native_event_id']), row)
        try:
            key = _observed_opposition(row)
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        if key:
            keys[id_] = key
            observed[key].append(id_)
    potential_stale, peers = set(), set()
    for id_ in unexplained & keys.keys():
        key, higher = keys[id_]
        for peer in observed[(key, not higher)]:
            if native[peer]['venue'] == native[id_]['venue']:
                continue
            peers.add(id_)
            if peer not in current:
                potential_stale.update((id_, peer))

    if potential_stale:
        # The exact matcher sees every native event in the captured scope
        # through identity anchors. Only plausible rows need payout evaluation.
        rows = [native[id_] for id_ in sorted(potential_stale)]
        rows.extend(dict(row, binding={'verified': False}) for row in anchors.values()
                    if row['id'] not in potential_stale)
        for pair in snapshots.before_fee_pairs(rows, at=at.isoformat()):
            if any(leg not in current for leg in pair['legs']):
                stale.update(pair['legs'])

    gaps = defaultdict(Counter)
    for id_ in current_native - present:
        reason = ('pair_awaiting_publication' if id_ in pending else
                  'opposing_phase_mismatch' if id_ in phased else
                  'exact_opposing_price_not_current' if id_ in stale else
                  'opposing_occurrence_or_settlement_unverified' if id_ in peers else
                  'opposing_price_not_observed' if id_ in keys else
                  'selected_contract_unverified')
        gaps[_row_key(current[id_])][reason] += 1
    return [dict(zip(('provider', 'venue', 'league', 'family', 'period', 'phase'), key), reasons=dict(counts))
            for key, counts in sorted(gaps.items())]


def _retail_payoff(pair, rows, *, captured_at=None):
    legs = [snapshots.expand_row(rows[leg]) for leg in pair['legs']]
    if captured_at is not None:
        legs = [dict(leg, captured_at=captured_at) for leg in legs]
        return evaluate(pair['before_fees'], legs, DEFAULT_FUNDING)['retail_payoff']
    return current_payoff(pair, legs, DEFAULT_FUNDING)['retail_payoff']


def measure_inputs(inputs, publication, published_pairs, deps, owner, states, *, settings, policy, epoch, at,
                   phase='', sportsbook_observations=None):
    from app.comparison.public_sportsbook_estimate import select as sportsbook_estimate
    from app.comparison.sgo_reference_publication import bind_captured
    from app.comparison.sgo_rule_evidence import owned_bindings
    from .trade_desk import direct_venue_offer, phase_matches

    configured = configured_cohorts(owner.get('config') or {})
    # Source selection and clock verification use the same policy as the desk.
    # The input universe comes from working rows in this transaction and can
    # include proofs the comparison owner has not visited or published yet.
    selected = {row['id']: row for row in inputs['quotes'] if _eligible_scope(row, configured)}
    price_candidates = [row for row in selected.values() if not live.quote_authority(row, inputs)['reasons']]
    raw = live.prices(dict(inputs, quotes=price_candidates), settings)
    current = live.project(raw, deps, owner, states, at=at, policy=policy, epoch=epoch, settings=settings)
    def current_in_scope(row):
        return row['price_current'] and (not phase or direct_venue_offer(row) and phase_matches(row, phase, at))

    current_rows = {row['id']: row for row in current['rows'] if current_in_scope(row)}
    published_current = {row['id']: row for row in publication['rows'] if current_in_scope(row) and _eligible_scope(row, configured)}
    published_gross = {source_key(row) for row in published_current.values()
                       if ranking_value(row, 'gross_return_percent', current=True) is not None}
    published_indicative = {source_key(row) for row in published_current.values()
                            if ranking_value(row, 'sportsbook_return_percent', current=True) is not None}
    published_after_fee = {source_key(row) for row in published_current.values()
                           if any(ranking_value(row, metric, current=True) is not None for metric in
                                  ('conditional_return_percent', 'conservative_return_percent'))}

    qualified = set()
    indicative = set()
    indicative_sgo = set()
    after_fee = set()
    cohorts = defaultdict(Counter)
    gaps = Counter()
    cohort_gaps = defaultdict(Counter)
    seen = set()
    registry = owned_bindings()
    for row in current_rows.values():
        key = _row_key(row)
        source = row['current_authority']['price']
        cid = source_key(row)
        if cid in seen:
            continue
        seen.add(cid)
        cohorts[key]['current_input_keys'] += 1
        reason = None
        native_indicative = (phase != 'live' and row['source']['provider'] in NATIVE_VENUES and sportsbook_observations and
                             sportsbook_estimate(selected[row['id']], source, sportsbook_observations, at=at))
        if native_indicative:
            indicative.add(cid)
            cohorts[key]['eligible_indicative_native'] += 1
            cohorts[key]['published_indicative_native'] += cid in published_indicative
        if row['source']['provider'] == 'sportsgameodds':
            if ranking_value(row, 'sportsbook_return_percent', current=True) is None:
                reason = 'source_local_reference_pair_unavailable'
            else:
                indicative.add(cid)
                indicative_sgo.add(cid)
                cohorts[key]['eligible_indicative_sgo'] += 1
                cohorts[key]['published_indicative_sgo'] += cid in published_indicative
        elif not source_allowed(states.get('sportsgameodds', {}), row['league']):
            reason = 'reference_source_unavailable'
        else:
            reference, witnesses = bind_captured(selected[row['id']], source, inputs, best_payout=True, registry=registry)
            if reference['available']:
                qualified.add(cid)
                cohorts[key]['eligible_native_before_fee'] += 1
                cohorts[key]['published_native_before_fee'] += cid in published_gross
                if (row.get('trade_fee') or {}).get('available'):
                    from app.comparison.conditional_benchmark import snapshot_metric
                    from app.comparison.snapshot_conservative import metric as kalshi_conservative
                    from app.comparison.snapshot_fee_outcome import reviews
                    from app.comparison.snapshot_fee_scope import applicability
                    from app.comparison.snapshot_polymarket_fee import conservative_metric as pmus_conservative
                    from app.fees.product_schedules import for_offer

                    fee = row['trade_fee']
                    record = selected[row['id']]['original_record']
                    calculation = reference['reference_calculation']
                    economics = dict(snapshots.expand_row(row), probability=reference['probability'],
                        cost_per_normal_claim=reference['cost_per_normal_claim'], reference_calculation=calculation,
                        gross_return_percent=reference['gross_return_percent'],
                        fee_applicability=applicability(record),
                        snapshot_benchmark={'method': calculation['method'], 'probability': reference['probability'],
                            'selected_identity': reference['selected_identity'], 'selected_predicate': reference['selected_predicate']})
                    state = source['lifecycle']['state']
                    review = for_offer(inputs.get('fee_products') or {}, economics, at, fallback=reviews(at)[row['venue']])
                    reviewed = snapshot_metric(economics, at=at.isoformat(), review=review, verified_live=state == 'live')
                    modeled = {}
                    if row['venue'] == 'kalshi':
                        modeled = kalshi_conservative(economics, at=at.isoformat(), review=review)
                    elif row['venue'] == 'polymarket_us':
                        modeled = pmus_conservative(economics, fee,
                            [item for item in witnesses if item['venue'] == calculation['venue']], state,
                            source_scope=(record.get('comparison_source_metadata') or {}).get('scoring_scope'))
                    if modeled.get('available') or reviewed.get('available'):
                        after_fee.add(cid)
                        cohorts[key]['eligible_native_after_fee'] += 1
                        cohorts[key]['published_native_after_fee'] += cid in published_after_fee
            else:
                reason = reference['reason']
        if reason:
            gaps[reason] += 1
            cohort_gaps[key][reason] += 1

    pairs, exact_proofs = {}, {}
    for pair in raw['pairs']:
        key = _pair_key(pair, current_rows)
        if key and len(key) == 2:
            legs = [current_rows[leg] for leg in pair['legs']]
            pairs[key] = (pair['league'], pair['market']['market'], pair['market']['period'],
                          tuple(sorted(_phase(row) for row in legs)),
                          tuple(sorted((row['source']['provider'], row['venue']) for row in legs)))
            exact_proofs[key] = pair
    displayed_pair_rows = {id_: row for id_, row in published_current.items() if row.get('publication_policy') == policy}
    displayed_pairs = {key: pair for pair in published_pairs
                       if (key := _pair_key(pair, displayed_pair_rows)) and len(key) == 2}
    fees = {source_key(row) for row in current_rows.values() if (row.get('trade_fee') or {}).get('available')}
    qualified_with_fee = qualified & fees
    pair_with_fees = {pair for pair in pairs if pair <= fees}
    pair_cohorts = defaultdict(Counter)
    payoff_totals = Counter()
    payoff_gaps = Counter()
    for key, cohort in pairs.items():
        counts = pair_cohorts[cohort]
        counts.update(eligible_before_fee=1, published_before_fee=int(key in displayed_pairs),
                      eligible_with_both_numeric_fees=int(key in pair_with_fees))
        if key not in pair_with_fees:
            continue
        model = _retail_payoff(exact_proofs[key], current_rows, captured_at=inputs['captured_at'])
        published = model['available'] and key in displayed_pairs and _retail_payoff(
            displayed_pairs[key], displayed_pair_rows)['available']
        metrics = dict(calculated_modeled_payoff=int(model['available']),
                       published_calculated_modeled_payoff=int(published))
        counts.update(metrics)
        payoff_totals.update(metrics)
        if model['available']:
            minimum = Fraction(model['minimum_net_profit_usd'])
            sign = 'positive' if minimum > 0 else 'negative' if minimum < 0 else 'zero'
            counts[f'modeled_payoff_{sign}'] += 1
            payoff_totals[f'modeled_payoff_{sign}'] += 1
        else:
            payoff_gaps[model['reason']] += 1
    published_before_fee = len(qualified & published_gross)
    published_indicative_count = len(indicative & published_indicative)
    published_pairs_count = len(pairs.keys() & displayed_pairs.keys())
    return dict(evidence_scope='eligible inputs independently reconstructed from retained working rows',
        read_at=at.isoformat(), captured_quotes=len(inputs['quotes']), current_quote_keys=len({source_key(r) for r in current_rows.values()}),
        excluded_price_inputs=len(selected)-len(current_rows), capture_issues=len(inputs['issues']), provider_universe_complete=False,
        ev=dict(eligible_native_before_fee=len(qualified), published_of_eligible_native_before_fee=published_before_fee,
            native_before_fee_coverage_percent=_rate(published_before_fee, len(qualified)),
            eligible_native_before_fee_with_numeric_fee=len(qualified_with_fee),
            eligible_native_after_fee=len(after_fee), published_of_eligible_native_after_fee=len(after_fee & published_after_fee),
            native_after_fee_coverage_percent=_rate(len(after_fee & published_after_fee), len(after_fee)),
            eligible_indicative_total=len(indicative), published_of_eligible_indicative_total=published_indicative_count,
            indicative_coverage_percent=_rate(published_indicative_count, len(indicative)),
            eligible_indicative_sgo=len(indicative_sgo), published_of_eligible_indicative_sgo=len(indicative_sgo & published_indicative),
            indicative_sgo_coverage_percent=_rate(len(indicative_sgo & published_indicative), len(indicative_sgo)),
            missing_reference_reasons=dict(gaps), by_cohort=[dict(zip(
                ('provider', 'venue', 'league', 'family', 'period', 'phase'), key), **counts,
                missing_reference_reasons=dict(cohort_gaps[key]))
                for key, counts in sorted(cohorts.items())]),
        arb=dict(eligible_before_fee=len(pairs), published_of_eligible_before_fee=published_pairs_count,
            before_fee_coverage_percent=_rate(published_pairs_count, len(pairs)),
            eligible_with_both_numeric_fees=len(pair_with_fees),
            published_of_eligible_with_both_numeric_fees=len(pair_with_fees & displayed_pairs.keys()),
            modeled_prestake_usd=100, calculated_modeled_payoff=payoff_totals['calculated_modeled_payoff'],
            published_calculated_modeled_payoff=payoff_totals['published_calculated_modeled_payoff'],
            modeled_payoff_by_sign={sign: payoff_totals[f'modeled_payoff_{sign}']
                                    for sign in ('positive', 'zero', 'negative')},
            modeled_payoff_unavailable_reasons=dict(payoff_gaps),
            native_offer_gap_reasons_by_cohort=_native_pair_input_gaps(
                selected, current_rows, raw['pairs'], displayed_pairs, at=at),
            by_cohort=[dict(league=key[0], family=key[1], period=key[2], phases=key[3],
                           sources=[dict(provider=provider, venue=venue) for provider, venue in key[4]], **counts)
                       for key, counts in sorted(pair_cohorts.items())]))


def measure(db, publication, published_pairs, deps, owner, states, *, settings, policy, epoch, at, phase=''):
    if owner.get('config', {}).get('aggregate_provider') != 'sportsgameodds':
        return dict(evidence_scope='SportsGameOdds working inputs', state='sgo_not_selected')
    event_ids = capture_candidates(db, deps, at=at)
    # Preserve normal league and component boundaries in the snapshot reader.
    # The result is never written back to a publication or source owner.
    inputs = snapshots.capture(db, at=at.isoformat(), ordinary=True, event_ids=event_ids, _frame_dependencies=deps)
    inputs['policy_identity'] = policy
    inputs['fee_products'] = owner.get('fee_products', {})
    inputs['fee_lifecycle'] = owner.get('fee_lifecycle')
    observations = live.pregame_sportsbooks(db, owner, states, at) if phase != 'live' else None
    return dict(measure_inputs(inputs, publication, published_pairs, deps, owner, states,
        settings=settings, policy=policy, epoch=epoch, at=at, phase=phase,
        sportsbook_observations=observations), candidate_events=len(event_ids))
