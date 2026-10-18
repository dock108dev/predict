"""Readiness adapters for existing native semantics and financial model owners."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction

from .current_dependencies import digest, instant, references, link_reasons
from .scanner_readiness import LIMITS, check, clock_reasons


def interval_reasons(value, at, kind):
    reasons = []
    for start in ('effective_from', 'model_effective_from'):
        if value.get(start) is not None and at < instant(value[start]):
            reasons.append(kind + '_not_effective')
    for end in ('effective_to', 'effective_until', 'expires_at'):
        if value.get(end) is not None and at >= instant(value[end]):
            reasons.append(kind + '_expired')
    return reasons


def _intervals(value):
    """Bounded public profiles may nest exact rule/schedule applicability."""
    if isinstance(value, dict):
        if any(k in value for k in ('effective_from', 'model_effective_from', 'effective_until', 'effective_to', 'expires_at', 'scheduled_ts')):
            yield value
        for child in value.values():
            yield from _intervals(child)
    elif isinstance(value, list):
        for child in value:
            yield from _intervals(child)


def model_checks(q, profiles, event, group, at):
    """Validate model inputs without sizing, classifying or ranking a trade.

    Named hypothetical quantity grids cannot establish legal execution. Retained
    original profiles, selected content and actual unknowns keep their meanings.
    """
    from .domain import CanonicalSelection
    from .estimated_consumer import AllocationInputs, _unit, _selected_fee
    from .estimated_ev import _scope, _grid, _reference
    from .estimated_content import native_contract, catalog
    from .payouts import PayoutProfile, CompletionContext, bind_profile
    reasons, ev, versions, deadlines = [], [], {}, []
    direction = None
    identity_bound = False
    contract = None
    values = references(q, profiles)
    for kind, value in values.items():
        versions[kind] = q['comparison_input_refs']['refs'][kind]
        destination = ev if kind in ('reference', 'probability') else reasons
        if kind == 'buffer':
            continue  # SC02's exact policy binds its own buffer.
        for interval in _intervals(value):
            destination.extend(interval_reasons(interval, at, kind))
            deadlines.extend(v for k, v in interval.items() if k in ('effective_from', 'model_effective_from', 'effective_to', 'effective_until', 'expires_at', 'scheduled_ts') and v is not None)
    if event.get('stage') != 'regular_season':
        reasons.append('contract_stage_unknown')
    quantity = values.get('quantity', {}).get('payload', {})
    if not quantity:
        reasons.append('quantity_missing')
    elif quantity.get('actual_grid_qualified') is False or 'unqualified' in quantity.get('grid_qualification','') or 'hypothetical' in quantity.get('grid_qualification',''):
        reasons.append('quantity_grid_unqualified')
    reasons.extend(link_reasons(q, at))
    if q.get('occurrence_link'):
        deadlines.extend(v for k, v in q['occurrence_link'].items() if k in ('effective_from', 'effective_until') and v)
    for t in catalog()['templates']:
        if t['venue'] == q['venue']:
            reasons.extend(interval_reasons(t, at, 'execution_model'))
            deadlines.extend([t['model_effective_from'], t['expires_at']])
            versions['execution_template'] = t['id']
    identity = values.get('identity', {}).get('payload', {})
    if identity.get('selection') is None:
        reasons.append('identity_missing')
    else:
        selected = CanonicalSelection.from_dict(identity['selection'])
        native = [q['venue'], *[q['source'][k] for k in ('native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')]]
        if list(selected.native.key) != native or identity.get('current_selection_binding') != q['binding']['selection'] or not q['binding']['verified']:
            reasons.append('identity_conflict')
        else:
            identity_bound = True
        if selected.event.occurrence_id != event['id'] or selected.event.league != event['league'] or selected.scope.period != group['period']:
            reasons.append('occurrence_identity_conflict')
        home = q['binding']['selection']['participant'] == selected.event.home_id
        pred = q['binding']['selection']['predicate']
        expected = ('gt' if home else 'lt') if pred == 'win' else ('le' if home else 'ge') if pred == 'not_win' else None
        if selected.predicate.operator != expected:
            reasons.append('identity_predicate_conflict')
        if selected.predicate.domain != 'home_margin' or selected.predicate.threshold.value != 0:
            reasons.append('contract_predicate_unsupported')
        else:
            direction = {'gt': 'home', 'ge': 'home', 'lt': 'away', 'le': 'away'}.get(selected.predicate.operator)
    if q['venue'] == 'polymarket_us' and q['source']['native_side'] == 'Short':
        reasons.append('short_collateral_unsupported')
    try:
        contract = native_contract(q, group)
        if contract['scope']['overtime'] != 'included':
            reasons.append('contract_overtime_unknown')
        if any(contract['predicate'].get(k) != q['binding']['selection'].get(k) for k in ('participant', 'predicate', 'signed_line')):
            reasons.append('contract_predicate_conflict')
        inputs = AllocationInputs(q, profiles, at)
        for kind, c in inputs.content.items():
            if not c['available']:
                reasons.append(kind + '_model_unsupported')
                reasons.extend(c['reasons'])
            recipe = c.get('recipe', {})
            for interval in _intervals(recipe):
                reasons.extend(interval_reasons(interval, at, kind))
                deadlines.extend(v for k, v in interval.items() if k in ('effective_from', 'model_effective_from', 'effective_to', 'effective_until', 'expires_at', 'scheduled_ts') and v is not None)
        if all(c['available'] for c in inputs.content.values()):
            roles, _ = _scope(q, event, group, inputs.content, at)
            if event.get('stage') != 'regular_season':
                reasons.append('contract_stage_unknown')
            if inputs.content['payout']['recipe']['overtime'] != 'included':
                reasons.append('contract_overtime_unknown')
            unit = _unit(q, inputs.content['fee'])
            grid = _grid(q, values, unit, inputs.content, at)
            quantity = values.get('quantity', {}).get('payload', {})
            if (not values.get('quantity') or quantity.get('actual_grid_qualified') is False or
                'unqualified' in grid.get('qualification', '') or 'hypothetical' in grid.get('qualification', '')):
                reasons.append('quantity_grid_unqualified')
            if Fraction(grid['minimum_native']) <= 0 or Fraction(grid['increment_native']) <= 0:
                reasons.append('quantity_grid_unsupported')
            _selected_fee(q, inputs.content['fee'], at)
            payout = inputs.content['payout']
            if payout['original_profile'] and payout['original_status']['status'] == 'available_and_bound' and identity.get('completion_context'):
                bind_profile(CanonicalSelection.from_dict(identity['selection']),
                             PayoutProfile.from_dict(payout['original_profile']['payload']), at=at,
                             rule_revision=identity['rule_revision'],
                             context=CompletionContext.from_dict(identity['completion_context']))
            elif payout['recipe'].get('selected'):
                reasons.append('settlement_model_unsupported')
    except (ValueError, KeyError, TypeError) as exc:
        code = str(exc)
        reasons.append(code if code.replace('_', '').isalnum() and len(code) <= 160 else 'contract_model_unsupported')
    try:
        from .estimated_policy import DEFAULT_POLICY
        reference_venue = values.get('reference', {}).get('payload', {}).get('venue', DEFAULT_POLICY.benchmark_venue)
        roles = {p['role']: p['id'] for p in event['participants']}
        _, reference = _reference(q, values, roles, at=at, policy=replace(DEFAULT_POLICY, benchmark_venue=reference_venue))
        for row in reference.outcomes:
            clocks = [c for c in (row.book_at, row.market_at) if c is not None]
            if not clocks:
                ev.append('reference_clock_unknown')
            for source in clocks:
                ev.extend('reference_expired' if c == 'reference_price_expired' else c for c in
                          clock_reasons(source, row.received_at, at, 1800, 'reference'))
                deadlines.append((instant(source)+timedelta(seconds=1800)).isoformat())
    except (ValueError, KeyError, TypeError):
        ev.append('reference_missing')
    if 'reference' not in values:
        ev.append('reference_missing')
    if 'probability' not in values:
        ev.append('complete_probability_missing')
    from .current_dependencies import temporal_revision
    temporal = temporal_revision(q, profiles, at)
    if temporal is not None:versions['temporal_applicability'] = temporal
    return dict(contract=check(reasons), ev=check(ev), direction=direction, identity_bound=identity_bound,
                native_contract=contract, model_versions=versions, deadlines=deadlines)


def instrument(q, profiles, event, group, *, at, source_status, authorized, book=None):
    moment = instant(at)
    m = model_checks(q, profiles, event, group, moment)
    venue = q['venue'];limits = LIMITS[venue]
    execution = []
    status = source_status.get('state', q.get('state', 'unavailable'))
    code = source_status.get('reason_code')
    if not authorized:
        execution.append('scope_not_authorized')
    if code in ('aggregate_transport_uncertain', 'ambiguous_dispatch_unresolved'):
        execution.append(code)
    if status in ('failed', 'error'):
        execution.append('source_failed')
    elif status not in ('available', 'budget_delayed'):
        execution.append('source_disconnected' if status in ('disconnected', 'stopped') else 'source_unavailable')
    execution.extend(clock_reasons(q['times'].get('source_at'), q['times'].get('received_at'), moment, limits['price_age_seconds']))
    if q['times'].get('projected_at') and instant(q['times']['projected_at']) > moment:
        execution.append('projection_clock_conflict')
    # Native transport/confirmation/heartbeat clocks never supply this header.
    for original in (q.get('provider_clocks', {}).get(k) for k in ('book','market')):
        if original is not None:
            execution.extend(clock_reasons(original, q['times'].get('received_at'), moment, limits['price_age_seconds']))
    native = venue in ('kalshi', 'polymarket_us')
    synchronized = bool(native and book and book.get('sync') == 'synchronized' and book.get('state') == 'active')
    deadlines = [event['start_at'], *m['deadlines']]
    if native:
        if not synchronized:
            execution.append('book_unsynchronized')
        if book:
            execution.extend(clock_reasons(book.get('source_at'), book.get('received_at'), moment, limits['book_age_seconds'], 'book'))
            if book.get('quantity_unit') != 'contracts':
                execution.append('book_units_conflict')
            if book.get('source_at'):
                deadlines.append((instant(book['source_at'])+timedelta(seconds=limits['book_age_seconds'])).isoformat())
            if book.get('source_at') != q['times'].get('source_at'):
                execution.append('book_offer_clock_conflict')
        depth = q.get('depth', [])
        try:
            if any(Fraction(d['quantity']) <= 0 or not 0 <= Fraction(d['price']) <= 1 for d in depth):
                execution.append('observed_depth_unsupported')
            observed = sum((Fraction(d['quantity']) for d in depth if Fraction(d['quantity']) > 0), Fraction(0))
            if observed <= 0:
                execution.append('observed_depth_missing')
            elif depth and Fraction(depth[0]['price']) != Fraction(q['original']['value']):
                execution.append('book_offer_price_conflict')
        except (ValueError, KeyError, TypeError, ZeroDivisionError):
            execution.append('observed_depth_unsupported')
        if q.get('comparison_input_refs'):
            values = references(q, profiles)
            minimum = values.get('quantity', {}).get('payload', {}).get('grid', {}).get('minimum_native')
            if minimum is not None and 'observed' in locals() and observed < Fraction(minimum):
                execution.append('observed_depth_insufficient')
    else:
        # Aggregated odds disclose neither a synchronized native book nor an
        # observed legal amount. Research prices stay visible; execution waits.
        execution.append('observed_depth_missing')
    for original in (q.get('provider_clocks', {}).get(k) for k in ('book','market')):
        if original is not None:
            try:deadlines.append((instant(original)+timedelta(seconds=limits['price_age_seconds'])).isoformat())
            except (ValueError,TypeError):pass
    source = q['times'].get('source_at')
    if source:
        deadlines.append((instant(source)+timedelta(seconds=limits['price_age_seconds'])).isoformat())
    if moment >= instant(event['start_at']):
        execution.append('pregame_ended')
    future = [d for d in deadlines if instant(d) > moment]
    contract = m['native_contract']
    scope = dict(venue=venue, sport='football', league=event['league'], market=group['market'], period=group['period'])
    return dict(id=digest([q['venue'], q['source']]), scope_key=digest(scope), **scope,
                occurrence_id=event['id'], direction=m['direction'],
                overtime=None if contract is None else contract['scope']['overtime'],
                native_key=[venue, *[q['source'][k] for k in ('native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')]],
                predicate=deepcopy(q['binding']['selection']), native_contract_id=None if contract is None else contract['id'],
                units=q['original']['units'], terms_sha256=None if contract is None else digest(contract),
                identity_bound=m['identity_bound'], price_present=True, synchronized_depth=synchronized and bool(q.get('depth')),
                clocks=dict(source_at=source, received_at=q['times'].get('received_at'),
                            book_at=None if book is None else book.get('source_at'),
                            book_received_at=None if book is None else book.get('received_at'),
                            ingress_projected_at=q['times'].get('projected_at'),
                            sql_committed_at=None,
                            provider_book_at=q.get('provider_clocks',{}).get('book'),
                            provider_market_at=q.get('provider_clocks',{}).get('market')),
                model_versions=m['model_versions'], limits=limits,
                expires_at=min(future, key=instant) if future else at,
                checks=dict(execution=check(execution), contract=m['contract'], ev=m['ev']))
