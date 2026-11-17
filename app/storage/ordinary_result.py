"""Build ordinary price and financial result packets from a captured snapshot."""

from fractions import Fraction
from uuid import uuid4

from app.comparison.display_identity import canonical_key
from app.comparison.sgo_reference import BEST_VERSION
from app.comparison.source_clock import CURRENT_DESK_MAX_AGE_SECONDS, assess
from app.fees import product_schedules, schedule_lifecycle

from . import comparison_snapshot as snapshots
from .current_rows import contract_id
from .ordinary_projection import counts, without_finance
from .store import hashed, stamp

VERSION = 'ordinary-comparison-1'


def quote_authority(row, inputs, *, reference=False):
    record = row.get('original_record')
    if not record:
        return dict(dependency=None, expected=None, reasons=['source_evidence_missing'], current_until=None)
    q = record['quote']
    if reference:
        from app.collection.current_benchmark import MAXIMUM_AGE
        q=dict(q,freshness_policy=dict(maximum_age_seconds=MAXIMUM_AGE))
    cid = contract_id(record)
    from app.comparison.game_phase import original_price_phase, scheduled_start
    lifecycle = original_price_phase(record, inputs['captured_at'])
    clock = assess(q, stamp(inputs['captured_at']), maximum_age=CURRENT_DESK_MAX_AGE_SECONDS,
                   pregame_until=scheduled_start(record['event']) if lifecycle['state'] == 'scheduled' else None)
    if lifecycle['reason']:clock['reasons'].append(lifecycle['reason'])
    if lifecycle.get('current_until') and clock.get('current_until'):
        clock['current_until']=min(clock['current_until'],lifecycle['current_until'])
    state = q.get('state')
    if state == 'unavailable' or lifecycle['state'] != 'scheduled' and state in ('stopped', 'error', 'resyncing', 'stale'):
        clock['reasons'].append('quote_'+state)
    return dict(dependency=cid, expected=inputs['dependencies'].get(cid),
                venue=row['venue'], provider=q.get('source',{}).get('provider'), lifecycle=lifecycle,
                **({'novig_runtime_id':q['novig_runtime_id']} if q.get('novig_runtime_id') else {}), **clock)


def price_only(inputs, settings, *, db=None):
    """Prepare a price-only result with the same frozen depth used by finance."""
    if db is not None:
        from .pregame_valuation_inputs import freeze
        freeze(db, inputs)
    rows = [];statuses={}
    for q in inputs['quotes']:
        row = {k: v for k, v in q.items() if k not in ('original_record', 'benchmark_quote', 'native_contract')}
        row.update(reference=None, snapshot_benchmark=None,
                   reference_calculation={'available':False, 'venue':'sportsgameodds_books', 'method':BEST_VERSION})
        row.update(kind='single', cost_per_normal_claim=None)
        rows.append(without_finance(row,'finance_pending',status_cache=statuses,copy_row=False))
    result = dict(id=uuid4().hex, snapshot_id=inputs['id'], captured_at=inputs['captured_at'],
                  calculated_at=None, assumptions=settings, rows=rows,
                  pairs=snapshots.before_fee_pairs(inputs['quotes'], at=inputs['captured_at']), games=inputs['games'],
                  references=[], sources=inputs['sources'], issues=inputs['issues'],
                  provider_requests=0, capture_seconds=inputs['capture_seconds'],
                  scope=dict(leagues=list(snapshots.SPORTS), families=['winner', 'spread', 'total'],
                             period='full_game', horizon_hours=72))
    if db is not None:
        from .current_rows import CurrentRowStore
        from .pregame_publication import arb_contracts

        paired = {leg for pair in result['pairs'] for leg in pair['legs']}
        bindings = {q['id']: contract_id(q['original_record']) for q in inputs['quotes']
                    if q['id'] in paired and q.get('original_record')}
        inputs['arb_contracts'] = {
            cid: semantic for cid, (revision, semantic) in arb_contracts(db, set(bindings.values())).items()
            if cid in inputs['dependencies'] and revision == inputs['dependencies'][cid][1]}
        contracts = {q['id']: bindings[q['id']] for q in inputs['quotes']
                     if q['id'] in bindings and q['venue'] in ('kalshi', 'polymarket_us')}
        depth = CurrentRowStore(db).native_top_asks(set(contracts.values()))
        # A price-only and finance turn share the same frozen book receipt.
        # Never read a newer book when recalculating the retained member.
        inputs.pop('arb_depth', None)
        if depth:
            inputs['arb_depth'] = {offer:depth[cid] for offer,cid in contracts.items() if cid in depth}
    return result


def bind(result, inputs, finance, *, load_registry):
    """Attach authority, pricing evidence, fees and payoff to a captured result."""
    from app.comparison.game_phase import sporting_phase
    from app.comparison.snapshot_fee_scope import applicability
    from app.comparison.snapshot_fee_outcome import outcome, reviews, unavailable
    from app.comparison.sgo_native_binding import published_pregame_fee
    from .sgo_native_catalog import dependency_id as catalog_dependency_id
    at = stamp(inputs['captured_at'])
    schedules = reviews(at) if result['rows'] else {}
    fee_state = inputs.get('fee_lifecycle')
    product_states = inputs.get('fee_products') or {}
    fee_revision = schedule_lifecycle.revision(fee_state)
    originals = {q['id']: q for q in inputs['quotes']}
    sgo_mode = inputs.get('reference_provider') == 'sportsgameodds'
    registry = load_registry() if sgo_mode and finance=='ready' else False
    empty_fee_revision=hashed({})
    if finance == 'ready':
        # The manual snapshot may model metadata associations. Ordinary arb
        # publishes only independent exact opposition, in both worker passes.
        scenarios = {pair['id']: pair for pair in result['pairs']}
        result['pairs'] = snapshots.before_fee_pairs(inputs['quotes'], at=inputs['captured_at'])
        for pair in result['pairs']:
            if scenario := scenarios.get(pair['id']):
                pair.update(math=scenario['math'], minimum_return_percent=scenario.get('minimum_return_percent'))
    paired_ids = {leg for pair in result['pairs'] for leg in pair['legs']}
    for row in result['rows']:
        original = originals[row['id']]
        source = quote_authority(original, inputs)
        catalog_authority = None
        sgo = None
        witnesses = []
        fee_witnesses = witnesses
        if finance == 'ready' and 'pregame_reference' in row:
            ref = row['pregame_reference']
            settlement = row['settlement_assessment']
            without_finance(row, ref.get('reason') or settlement.get('reason') or 'unit_size_valuation_pending',
                            copy_row=False)
            row.update(reference=None, snapshot_benchmark=None)
        elif finance == 'ready' and not sgo_mode:
            row.update(reference=None, snapshot_benchmark=None,
                       snapshot_benchmark_reason='eligible_reference_unavailable',
                       snapshot_benchmark_missing=None, reference_calculation={})
            without_finance(row, 'eligible_reference_unavailable', copy_row=False)
        if finance == 'ready' and sgo_mode and 'pregame_reference' not in row:
            from app.comparison.sgo_reference_publication import bind_captured
            row.update(snapshot_benchmark=None, reference=None,
                       snapshot_benchmark_reason='sgo_reference_qualification_unavailable',
                       reference_calculation={})
            without_finance(row, 'SportsGameOdds reference awaits verified occurrence, settlement and current contributor evidence', copy_row=False)
            row['reference_calculation'].update(venue='sportsgameodds_books', method=BEST_VERSION)
            sgo, witnesses = bind_captured(row, source, inputs, best_payout=True, registry=registry, native=original)
            if sgo.get('available'):
                reference = sgo['reference_calculation']
                selected_book = reference['venue']
                contributors = reference['contributors']
                selected_prices = next(item['inputs'] for item in contributors if item['venue'] == selected_book)
                fee_witnesses = [item for item in witnesses if item['venue'] == selected_book]
                if source.get('lifecycle', {}).get('state') == 'live' or not row.get('sportsbook_baseline'):
                    row['sportsbook_baseline'] = dict(verified_native=True, book=selected_book,
                        candidate_books=len(contributors), frame_id=reference['contract']['frame_id'],
                        current_until=min(item['current_until'] for item in witnesses),
                        probability=sgo['probability'], fair_decimal_odds=reference['fair_decimal_odds'],
                        return_percent=sgo['gross_return_percent'], prices=selected_prices)
                row.update(probability=sgo['probability'], probability_missing=None,
                    gross_return_percent=sgo['gross_return_percent'],
                    gross_profit_per_claim=sgo['gross_profit_per_claim'],
                    cost_per_normal_claim=sgo['cost_per_normal_claim'],
                    reference_calculation=sgo['reference_calculation'],
                    conditional_trade_benchmark=sgo['conditional_trade_benchmark'],
                    conditional_return_percent=sgo['conditional_trade_benchmark'].get('return_percent'),
                    snapshot_benchmark_reason=None, snapshot_benchmark_missing=None,
                    snapshot_benchmark=dict(method=sgo['reference_calculation']['method'],
                        probability=sgo['probability'], basis_sha256=sgo['reference_calculation']['basis_sha256'],
                        selected_identity=sgo['selected_identity'], selected_predicate=sgo['selected_predicate']))
            else:
                row['snapshot_benchmark_reason'] = sgo['reason']
                row['reference_calculation']['reason'] = sgo['reason']
            from app.comparison.snapshot_metrics import statuses
            statuses(row)
        fee = row.get('conditional_trade_benchmark', {}).get('evidence', {})
        if source.get('provider') == 'sportsgameodds' and row['venue'] != 'prophetx':
            row['trade_fee'] = unavailable('sgo_offer_native_contract_unverified')
            binding = original.get('sgo_native_contract')
            if binding:
                row['sgo_native_contract'] = binding
                review = product_schedules.for_offer(product_states, row, at, fallback=schedules[row['venue']])
            if binding and not binding['available']:
                row['trade_fee'] = published_pregame_fee(original.get('original_record'), binding, at=at, review=review)
            if binding and binding['available']:
                dependency = catalog_dependency_id(original['source']['native_event_id'])
                expected = inputs['dependencies'].get(dependency)
                if expected and expected[0] == binding['revision']:
                    catalog_authority = dict(dependency=dependency, expected=expected,
                        current_until=binding['current_until'])
                    row['trade_fee'] = published_pregame_fee(original.get('original_record'), binding, at=at, review=review)
        elif row['venue'] in schedules and original.get('original_record'):
            record = original['original_record']
            phase = source.get('lifecycle', {}).get('state')
            if row['venue'] != 'polymarket_us' and sporting_phase(record['event'])['state'] == 'live':
                phase = 'live'
            fee_input = dict(row, fee_applicability=row.get('fee_applicability') or applicability(record),
                             novig_v3_evidence=record['quote'].get('novig_v3_evidence'))
            if row['id'] in paired_ids or row['venue'] in ('kalshi', 'polymarket_us') and phase == 'scheduled':
                row['fee_applicability'] = fee_input['fee_applicability']
            review = (schedule_lifecycle.for_offer(fee_state, fee_input, at, fallback=schedules[row['venue']])
                      if row['venue'] == 'prophetx' else
                      product_schedules.for_offer(product_states, fee_input, at, fallback=schedules[row['venue']]))
            quantity = '1'
            if row['venue'] == 'polymarket_us' and phase == 'scheduled':
                from app.comparison.trade_preview import order_step

                step = order_step(fee_input)
                if step and step > 0 and 1 % step:
                    quantity = step
            row['trade_fee'] = outcome(fee_input, at=at, phase=phase, review=review, quantity=quantity)
            if sgo and sgo.get('available') and review is not None and (phase == 'scheduled' or row['venue'] == 'kalshi'):
                from app.comparison.conditional_benchmark import snapshot_metric
                metric = snapshot_metric(fee_input, at=inputs['captured_at'], review=review, verified_live=phase == 'live')
                row['conditional_trade_benchmark'] = metric
                row['conditional_return_percent'] = metric.get('return_percent')
                if row['venue'] == 'kalshi':
                    from app.comparison.snapshot_conservative import metric as conservative_metric
                    conservative = conservative_metric(fee_input, at=inputs['captured_at'], review=review)
                    row['conservative_trade_benchmark'] = conservative
                    row['conservative_return_percent'] = conservative.get('return_percent')
                    row['kalshi_live_financial_qualified'] = phase == 'live' and (metric['available'] or conservative['available'])
                from app.comparison.snapshot_metrics import statuses
                statuses(row)
                fee = metric.get('evidence') or {}
            if finance == 'ready' and phase == 'live' and row['venue'] == 'novig':
                from app.comparison.snapshot_novig_live import live_metric
                row['conditional_trade_benchmark'] = live_metric(row, row['trade_fee'], fee_witnesses)
                row['conditional_return_percent'] = row['conditional_trade_benchmark'].get('return_percent')
                row['novig_live_financial_qualified'] = bool(row['conditional_trade_benchmark'].get('available'))
                from app.comparison.snapshot_metrics import statuses
                statuses(row)
                fee = row['conditional_trade_benchmark'].get('evidence') or {}
            if (finance == 'ready' and row['venue'] == 'polymarket_us'
                    and row['trade_fee']['classification'] != 'exact_public'):
                from app.comparison.snapshot_polymarket_fee import conservative_metric
                from app.comparison.snapshot_metrics import statuses
                source_scope = (record.get('comparison_source_metadata') or {}).get('scoring_scope')
                row['conservative_trade_benchmark'] = conservative_metric(
                    row, row['trade_fee'], fee_witnesses, phase, source_scope=source_scope)
                row['conservative_return_percent'] = row['conservative_trade_benchmark'].get('return_percent')
                row['polymarket_live_financial_qualified'] = phase == 'live' and row['conservative_trade_benchmark']['available']
                statuses(row)
        baseline = row.get('sportsbook_baseline')
        settlement = row.get('settlement_assessment')
        binary = settlement is None or (settlement.get('available') and
            set(settlement['state_probabilities']) == {'win', 'loss'})
        if finance == 'ready' and source.get('lifecycle', {}).get('state') == 'scheduled' and baseline and binary:
            from app.comparison.cashflows import exact_wire
            from app.dashboard.current_contract import price

            standalone = row.get('trade_fee') or {}
            cashflows = standalone.get('fee_cashflows') or {}
            if standalone.get('available') and set(cashflows) <= {'at_fill_usd', 'winning_settlement_usd',
                                                                  'losing_settlement_usd'} and 'at_fill_usd' in cashflows:
                probability = Fraction(baseline['probability'])
                size = Fraction(standalone['quantity']) if row['venue'] == 'polymarket_us' else 1
                risk = size * price(row) + Fraction(cashflows['at_fill_usd'])
                win = size - Fraction(cashflows.get('winning_settlement_usd', '0'))
                loss = -Fraction(cashflows.get('losing_settlement_usd', '0'))
                if risk > 0:
                    row['sportsbook_after_fee_percent'] = exact_wire(100 * ((probability * win +
                        (1 - probability) * loss) / risk - 1))
        captured_record = original.get('original_record') or {}
        metadata = captured_record.get('comparison_source_metadata') or {}
        if captured_record and source.get('lifecycle', {}).get('state') == 'scheduled':
            row['pregame_contract_authority'] = dict(
                settlement_rules=(captured_record.get('market_identity') or {}).get('rules'),
                scoring_scope=metadata.get('scoring_scope'))
        if isinstance(metadata.get('alternate'), bool):
            row['alternate'] = metadata['alternate']
        reference = row.get('reference_calculation') or {}
        row['current_authority'] = dict(price=source, references=witnesses,
            reference_required=row.get('probability') is not None,
            reference_method=(row.get('reference_calculation') or {}).get('method'),
            exact_pinnacle_reference=bool(reference.get('available') and reference.get('venue')=='pinnacle'),
            public_fee_revision=(fee_revision if row['venue']=='prophetx' else
                product_schedules.revision(product_states.get(product_schedules.key_for(row)))),
            fee_until=fee.get('review_before'),fee_from=fee.get('reviewed_at'),fee_revision=hashed(fee) if fee else empty_fee_revision,
            conservative_fee_until=row.get('conservative_trade_benchmark',{}).get('evidence',{}).get('review_before'),
            start_at=row['start_at'])
        if semantic := inputs.get('arb_contracts', {}).get(source.get('dependency')):
            row['current_authority']['arb_contract'] = semantic
        occurrence = ((original.get('original_record') or {}).get('quote', {}).get('occurrence_match') or {})
        if (occurrence.get('status') == 'matched' and occurrence.get('estimated') is False
                and not occurrence.get('conflicts') and occurrence.get('method') in
                ('shared_provider_id', 'reviewed_source_id', 'local_reviewed_override')):
            row['current_authority']['occurrence_id'] = occurrence.get('occurrence_id')
        if catalog_authority is not None:
            row['current_authority']['sgo_native_contract'] = catalog_authority
        if row.get('reference_calculation',{}).get('available'):
            row['reference_calculation']=dict(row['reference_calculation'],authority=witnesses)
        display_key = canonical_key(row)
        row['display_outcome_key'] = list(display_key) if display_key is not None else None
        row['settings_revision'] = result['assumptions']['revision']
        # Confirmation clocks and publication IDs are deliberately excluded.
        row['price_revision'] = hashed([row['id'], row['original']])
        row['economic_revision'] = None if finance != 'ready' else hashed([row['id'], row['original'], row.get('probability'),
            (row.get('snapshot_benchmark') or {}).get('selected_predicate'),row.get('fee_applicability'),
            row.get('conditional_return_percent'),row.get('conservative_return_percent'),
            row.get('conservative_trade_benchmark',{}).get('evidence'),fee, result['assumptions']['revision'],
            row.get('trade_fee'), row.get('sportsbook_baseline'), row.get('sportsbook_after_fee_percent'),
            row.get('pregame_reference'), row.get('settlement_assessment'), row.get('valuation_fill_terms'),
            (row.get('reference_calculation') or {}).get('basis_sha256'), inputs['policy_identity']])
    if result['pairs']:
        from app.comparison.ordinary_arb import DEFAULT_FUNDING, evaluate, fee_identity

        rows = {row['id']: row for row in result['rows']}
        for pair in result['pairs']:
            proof = pair.get('before_fees')
            if proof and all(leg in rows for leg in pair['legs']):
                proof['depth_evidence'] = [(inputs.get('arb_depth') or {}).get(leg) for leg in pair['legs']]
                legs = [dict(rows[leg], captured_at=inputs['captured_at'],
                             game_state=rows[leg]['current_authority']['price'].get('lifecycle', {}).get('state'))
                        for leg in pair['legs']]
                pair['default_funding_result'] = evaluate(proof, legs, DEFAULT_FUNDING)
                if not proof.get('blocker') and all(leg['game_state'] == 'scheduled' for leg in legs):
                    from app.comparison.inspection_math import pair_math
                    pair['before_fee_inspection'] = pair_math(proof, DEFAULT_FUNDING)
                pair['default_funding_fee_identity'] = fee_identity(legs)
    result['publication'] = dict(schema=VERSION, finance=finance, policy=inputs['policy_identity'],
        epoch=inputs['epoch'], captured_at=inputs['captured_at'], provider_requests=0)
    counts(result)
    return result
