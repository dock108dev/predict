"""Compact immutable publication members and validate their read-time authority."""
from datetime import timedelta

from . import comparison_snapshot as snapshots
from .current_rows import event_id
from .store import stamp
from app.collection.current_policy import aggregate_provider
from app.comparison.display_identity import canonical_key
from app.comparison.game_phase import scheduled_phase, sporting_clock
from app.fees import product_schedules, schedule_lifecycle
from app.fees.evidence import applies
from app.comparison.sgo_reference import BEST_BOOKS, BEST_VERSION
from app.comparison.source_clock import CURRENT_DESK_MAX_AGE_SECONDS


def publication_runtime(owner):
    reason = owner.get('reason_code')
    if not reason and owner.get('calculations', {}).get('board') == 'unavailable':
        reason = 'ordinary_publication_failed'
    return dict(healthy=bool(owner.get('healthy')), active=bool(owner.get('active')),
                state=owner.get('service_state'), reason=reason,
                stopped=bool(owner.get('global_stopped')), paused_sources=owner.get('paused_sources', []))


def compact_row(row):
    """Keep list/drawer inputs; full semantic proof stays in the exact member."""
    row = dict(row)
    if 'display_outcome_key' not in row:
        display_key = canonical_key(row)
        row['display_outcome_key'] = list(display_key) if display_key is not None else None
    for key in ('common_odds', 'reference_odds', 'snapshot_identity'):
        row.pop(key, None)
    row['selection'] = {k:v for k,v in row.get('selection', {}).items()
        if k in ('participant','predicate','signed_line','result_interpretation','label')}
    row['same_outcome'] = {k:v for k,v in row.get('same_outcome', {}).items() if k != 'key'}
    if row.get('reference_calculation'):
        row['reference_calculation'] = {k:v for k,v in row['reference_calculation'].items()
            if k not in ('authority','occurrence')}
    return row


def compact_member(part):
    """Same exact list projection as legacy root composition; private input."""
    paired = {leg for pair in part['pairs'] for leg in pair['legs']}
    for row in part['rows']:
        # Ordinary sorting needs compact prices/results. Full binding,
        # depth and provenance graphs remain in this immutable member,
        # reached by evidence_result_id instead of duplicated per head.
        for field in ('binding','observed_depth','occurrence_match','occurrence_link',
                      'provider_clocks','observation_time_evidence','source_health',
                      'input_basis','native_contract_id','observation_revision'):
            row.pop(field,None)
        if row['id'] not in paired:
            row.pop('fee_applicability', None)
        # Full financial provenance belongs to the immutable selected
        # member. The root keeps exact numeric inputs, IDs and clocks,
        # without copying the same rules/occurrence graph on every row.
        if row.get('snapshot_benchmark'):
            row['snapshot_benchmark']={k:v for k,v in row['snapshot_benchmark'].items()
                if k in ('bookmaker','ids','odds','selected','selected_odds','probability',
                    'source_at','received_at','method','conditioning','selected_predicate')}
            row['reference']=None
        disclosure=row.get('reference_calculation')
        if disclosure and disclosure.get('occurrence'):
            disclosure['occurrence']={k:v for k,v in disclosure['occurrence'].items()
                if k in ('occurrence','method','scoring','scoring_basis','equality_basis')}
        for name in ('conditional_trade_benchmark','conservative_trade_benchmark'):
            metric=row.get(name)
            if not metric:continue
            for field in ('applicability','fee_scenarios','rounding_trace','policy'):
                metric.pop(field,None)
            if metric.get('evidence'):
                metric['evidence']={k:v for k,v in metric['evidence'].items()
                    if k in ('version','source_url','sha256','path','reviewed_at','review_before',
                        'standing_public_terms','recheck_due_at','verification_scope',
                        'fee_rate','series_id','event_id','metadata_revision')}
        if row.get('book_confirmation'):
            row['book_confirmation']={k:row['book_confirmation'][k] for k in ('confirmed_at','basis')}
        row['evidence_result_id']=part['id']
        row['captured_at']=part['captured_at']
    part['rows'] = [compact_row(row) for row in part['rows']]
    for pair in part['pairs']:
        pair['evidence_result_id']=part['id']
    part['references']=[{k:v for k,v in r.items() if k!='original_record'} for r in part['references']]
    for row in part['rows']:
        row['publication_policy']=part['publication']['policy']
        row['publication_epoch']=part['publication']['epoch']
    return part


def source_allowed(state, league=None):
    if state.get('state')=='budget_delayed' and (state.get('reason_code')=='aggregate_scope_observed'
            or 'observed_sports' in state and state.get('reason_code') in ('aggregate_budget_delayed','aggregate_outside_window')):
        scopes=state.get('observed_sports',{})
        healthy=('aggregate_observed','aggregate_partial_admission')
        return any(code in healthy for code in scopes.values()) if league is None else scopes.get(league) in healthy
    return state.get('state') == 'available' or (
        state.get('state') == 'budget_delayed' and state.get('reason_code') in
        ('aggregate_budget_delayed', 'aggregate_outside_window', 'sgo_cycle_complete',
         'sgo_daily_pacing', 'sgo_request_rate'))


def without_finance(row, reason, *, status_cache=None, copy_row=True):
    if copy_row:
        row = dict(row)
    status_key = (reason, row.get('snapshot_benchmark_reason'))
    if status_cache is not None and status_key in status_cache:
        row.update(status_cache[status_key])
        row['reference_calculation']=dict(row.get('reference_calculation') or {}, available=False,reason=reason)
        return row
    for field in ('probability', 'gross_return_percent', 'conditional_return_percent',
                  'net_return_percent', 'gross_profit_per_claim', 'price_difference_cents', 'conservative_return_percent'):
        row[field] = None
    row['probability_missing'] = reason
    row['math'] = dict(available=False, missing=[reason])
    row['conditional_trade_benchmark'] = dict(available=False, reason=reason)
    row['conservative_trade_benchmark'] = dict(available=False, reason=reason)
    row['reference_calculation']=dict(row.get('reference_calculation') or {}, available=False,reason=reason)
    from app.comparison.snapshot_metrics import statuses
    statuses(row,withdrawn=reason.split(', ') if reason!='finance_pending' else ())
    if status_cache is not None:
        status_cache[status_key] = {key:row[key] for key in (
            'probability','gross_return_percent','conditional_return_percent','net_return_percent',
            'gross_profit_per_claim','price_difference_cents','conservative_return_percent',
            'probability_missing','math','conditional_trade_benchmark','conservative_trade_benchmark','metric_status')}
    return row


def counts(result):
    rows = result['rows']
    result['counts'] = dict(observations=len(rows), gross_numeric=sum(r.get('gross_return_percent') is not None for r in rows),
        conditional_numeric=sum(r.get('conditional_return_percent') is not None for r in rows),
        conservative_numeric=sum(r.get('conservative_return_percent') is not None for r in rows),
        net_numeric=sum(r.get('net_return_percent') is not None for r in rows), pairs=len(result['pairs']),
        unmatched=sum(not r.get('same_outcome', {}).get('supported') for r in rows))


def authority_deadline(witness):
    deadline = witness.get('current_until')
    source = witness.get('clock_at')
    if deadline and source and (witness.get('lifecycle') or {}).get('state') != 'scheduled':
        # Older committed publications can predate the board cap.
        return min(stamp(deadline), stamp(source) + timedelta(seconds=CURRENT_DESK_MAX_AGE_SECONDS)).isoformat()
    return deadline


def validity(witness, current, at):
    reasons = list(witness.get('reasons', []))
    expected=witness.get('expected')
    actual=current.get(witness.get('dependency'))
    if (expected is None or actual is None or actual[:3] != expected[:3]
            or witness.get('exact_frame') and actual != expected):
        reasons.append('input_replaced_or_removed')
    deadline = authority_deadline(witness)
    if deadline is None or at >= stamp(deadline):
        reasons.append('source_expired' if deadline else 'source_unknown')
    return reasons


def price_reasons(row, current, owner, states, *, at, epoch, publication_epoch, common=()):
    """Validate the exact stored price revision under ordinary display authority."""
    from app.comparison.public_sportsbook_estimate import SOURCE as ODDSLINK, allowed
    auth = row['current_authority']['price']
    reasons = list(common) + validity(auth, current, at)
    if row.get('publication_epoch', publication_epoch) != epoch:
        reasons.append('input_epoch_replaced')
    provider = auth.get('provider') or row.get('source', {}).get('provider')
    config = owner.get('config', {})
    if provider in ('the_odds_api', 'sportsgameodds') and provider != aggregate_provider(config):
        reasons.append('aggregate_provider_replaced')
    if (row['venue'] in owner.get('paused_sources', ())
            or provider in ('the_odds_api', 'sportsgameodds') and config.get('aggregate_enabled') is False):
        reasons.append('updates_stopped')
    state = states.get(provider if provider in ('sportsgameodds', ODDSLINK) else row['venue'], {})
    if provider == ODDSLINK and (not allowed(owner) or 'prophetx' in owner.get('paused_sources', ())):
        reasons.append('updates_stopped')
    native_owner = auth.get('novig_runtime_id')
    if native_owner:
        if native_owner != str(owner.get('runtime_id')) or {'novig', 'the_odds_api'} & set(owner.get('paused_sources', ())):
            reasons.append('novig_native_authority_withdrawn')
    elif not source_allowed(state, row.get('league')):
        reasons.append(state.get('reason_code') or 'source_unavailable')
    if at >= stamp(row['start_at']) and auth.get('lifecycle', {}).get('state') != 'live':
        reasons.append('post_start_game_state_unverified')
    return reasons


def event_owners(db, rows, *, at):
    """Read sporting authority even when its most recent market was withdrawn."""
    from app.collection.oddslink_prophetx import SOURCE as ODDSLINK, live_occurrences

    event_ids = {event_id(source['provider'], source['native_event_id'])
                 for row in rows if (source := row.get('source')) and source.get('provider')
                 and source.get('native_event_id')}
    if not event_ids:
        return {}
    current = {}
    native_live = {}
    for row in db.execute('SELECT provider,native_event_id,facts FROM current_event WHERE id=ANY(%s)',
                          (list(event_ids),)):
        event = row['facts']
        if row['provider'] == ODDSLINK and (event.get('status') or {}).get('live') is True:
            league = event['competition']
            if league not in native_live:
                native_live[league] = live_occurrences(db, league, at)
            if (stamp(event['scheduled_start']), event['home'], event['away']) not in native_live[league]:
                event = dict(event, status=dict(status='unknown'))
        current[(row['provider'], row['native_event_id'])] = event
    return current


def event_signature(event):
    if event.get('competition') and event.get('scheduled_start') and event.get('home') and event.get('away'):
        # A numbered doubleheader needs a stronger identity than teams and start.
        return (event['competition'], stamp(event['scheduled_start']), event['home'], event['away'],
                event.get('game_number') if event['competition'] == 'MLB' else None)
    return None


def withdrawn_events(db, *, at):
    """Find explicitly withdrawn occurrences even after all their offers leave the head."""
    withdrawn = {}
    for row in db.execute("""SELECT facts FROM current_event
        WHERE scheduled_start::timestamptz BETWEEN %s AND %s
          AND (lower(facts#>>'{status,status}') IN
             ('cancelled','canceled','abandoned','postponed','delayed','suspended','final','completed','complete','finished')
              OR facts#>>'{status,ended}'='true')""",
        (at - timedelta(hours=24), at + timedelta(hours=72))).fetchall():
        event = row['facts']
        signature = event_signature(event)
        if not signature or signature[0] == 'MLB' and signature[-1] is None:
            continue
        phase = scheduled_phase(event, at)
        if phase['state'] in ('cancelled', 'final', 'suspended'):
            withdrawn[signature] = dict(phase, observed_at=sporting_clock(event))
    return withdrawn


def occurrence_key(row):
    return row['game_key'], stamp(row['start_at'])


def current_events(rows, events, at, *, withdrawn=None):
    """Resolve explicit withdrawals across the same bound occurrence and start."""
    resolved, blocked = {}, {}
    for row in rows:
        source = row.get('source') or {}
        key = (source.get('provider'), source.get('native_event_id'), row['start_at'])
        if key not in resolved:
            event = events.get(key[:2])
            latest = None
            if event:
                if stamp(event['scheduled_start']) != stamp(row['start_at']):
                    latest = dict(state='unknown', reason='event_schedule_replaced', basis='current_source_schedule')
                else:
                    latest = (withdrawn or {}).get(event_signature(event)) or dict(
                        scheduled_phase(event, at), observed_at=sporting_clock(event))
            resolved[key] = latest
        published = row['current_authority']['price'].get('lifecycle', {})
        state = resolved[key] or published
        if state.get('state') in ('final', 'cancelled', 'suspended'):
            blocked[occurrence_key(row)] = state
    return resolved, blocked


def published_phase(row, at, latest, blocked, *, event_replaced=False):
    captured = row['current_authority']['price'].get('lifecycle') or {}
    start = stamp(row['start_at'])
    if blocked:
        return blocked
    if latest and latest.get('reason'):
        return latest
    if captured.get('reason'):
        return captured
    if start > at:
        if latest and latest['state'] == 'scheduled':
            return latest
        if not event_replaced and captured.get('state', 'scheduled') == 'scheduled':
            return dict(state='scheduled', reason=None, basis=captured.get('basis'))
    elif (captured.get('state') == 'live' and not event_replaced
          and (latest is None or latest['state'] == 'live'
               or captured.get('basis') == 'post_start_market_update' and latest['basis'] == 'source_state_absent')):
        return dict(captured, **({'observed_at': latest['observed_at']}
                                if latest and latest.get('observed_at') else {}))
    return dict(state='unknown', reason='post_start_game_state_unverified' if start <= at
                else 'event_schedule_unverified', basis='no_current_occurrence_evidence')


def project(result, current, owner, states, *, at, policy, epoch, settings=None, sportsbook_frames=(),
            current_desk=False, retain_sportsbook_ev=False, event_facts=None, lifecycle_rows=None, withdrawn=None):
    """Fail-closed rank withdrawal; no reference/fee/math is recomputed here."""
    from app.comparison.snapshot_fee_outcome import EXPIRED, unavailable
    from app.comparison.sgo_sportsbook_baseline import current as sportsbook_current
    from app.comparison.public_sportsbook_estimate import SOURCE, allowed, clocks_current, index, read_captures
    from .store import ROOT
    baseline_inputs = set()
    if allowed(owner) and any((row.get('sportsbook_baseline') or {}).get('indicative') and not (row.get('sportsbook_baseline') or {}).get('source_local') for row in result['rows']):
        baseline_inputs.update((SOURCE, match['event_id'], match['revision'])
                               for match in index(read_captures(ROOT, at=at), at=at).values() if match['scheduled'])
        baseline_inputs.update(('sportsgameodds', item['native_event_id'], item['frame'])
                               for item in sportsbook_frames if source_allowed(
                                   states.get('sportsgameodds', {}), item['competition']))
    out = dict(result, rows=[], pairs=[])
    failed_captures = set(out.pop('_failed_price_members', ()))
    common = []
    settings=settings or result['assumptions']
    out['assumptions']=settings
    if result['publication']['epoch'] != epoch: common.append('input_epoch_replaced')
    if not owner.get('healthy'): common.append('data_runtime_unhealthy')
    if not owner.get('active') or owner.get('global_stopped'): common.append('updates_stopped')
    # A failed successor cannot invalidate an already committed witness.
    # Runtime controls, component failures and exact input clocks still apply.
    ready = set()
    pair_ready = {}
    # Identical withdrawal statuses are read-only within this response. Share
    # their small trees instead of allocating five per each of 20k source rows.
    withdrawal_statuses = {}
    current_prices = 0
    fee_state = owner.get('fee_lifecycle')
    product_states = owner.get('fee_products') or {}
    current_fee_revision = schedule_lifecycle.revision(fee_state)
    event_states, blocked_occurrences = current_events(
        result['rows'] if lifecycle_rows is None else lifecycle_rows, event_facts or {}, at, withdrawn=withdrawn)
    active_provider = aggregate_provider(owner.get('config'))
    for original in result['rows']:
        row = dict(original)
        auth = row['current_authority']
        deadline = authority_deadline(auth['price'])
        if deadline != auth['price'].get('current_until'):
            row['current_authority'] = dict(auth, price=dict(auth['price'], current_until=deadline))
        if current_desk and deadline and at >= stamp(deadline):
            # An expired quote can still be shown with its original price.
            # No dependency lookup or calculation is needed to withdraw it.
            reasons = [*common, 'source_expired']
        else:
            reasons = ((common if current_desk else []) or
                       price_reasons(row, current, owner, states, at=at, epoch=epoch,
                                     publication_epoch=result['publication']['epoch'], common=common))
        start = stamp(row['start_at'])
        actual = current.get(auth['price'].get('dependency'))
        expected = auth['price'].get('expected')
        event_replaced = bool(actual and expected and actual[2] != expected[2])
        source = row.get('source') or {}
        latest = event_states[(source.get('provider'), source.get('native_event_id'), row['start_at'])]
        lifecycle = published_phase(row, at, latest, blocked_occurrences.get(occurrence_key(row)),
                                    event_replaced=event_replaced)
        if lifecycle.get('reason'):
            reasons = [*reasons, lifecycle['reason']]
        row['game_state']=lifecycle['state']
        row['game_state_reason']=lifecycle.get('reason')
        row['game_state_basis']=lifecycle.get('basis')
        row['game_state_observed_at']=lifecycle.get('observed_at')
        row['price_current'] = not reasons
        if current_desk and reasons:
            # Preserve observable prices and identity as last-known evidence.
            row['trade_fee'] = unavailable('fee_source_price_not_current')
            row['current_reasons'] = sorted(set(reasons))
            out['rows'].append(row)
            continue
        row['price_reasons'] = sorted(set(reasons))
        current_prices += not reasons
        policy_replaced = row.get('publication_policy', result['publication']['policy']) != policy
        capture_failed = row.get('evidence_result_id') in failed_captures
        if capture_failed:
            row['comparison_capture_failed'] = True
        if not reasons and not policy_replaced and not capture_failed:
            pair_ready[row['id']] = row['game_state']
        baseline = row.get('sportsbook_baseline')
        if baseline and not baseline.get('verified_native'):
            if baseline.get('indicative') and not baseline.get('source_local'):
                refs = baseline.get('reference_inputs') or {}
                current_baseline = bool(refs and all(tuple(ref) in baseline_inputs for ref in refs.values())
                                        and at <= stamp(baseline['current_until']))
            else:
                current_baseline = sportsbook_current(baseline, current.get(auth['price']['dependency']), at=at)
            if row['game_state'] == 'scheduled':
                current_baseline = current_baseline and clocks_current(baseline.get('prices', ()), at=at, start=start)
            if reasons or policy_replaced or capture_failed or not current_baseline:
                if baseline.get('current_until') and at >= stamp(baseline['current_until']):
                    row['sportsbook_reference_reason'] = 'reference_price_stale'
                row['sportsbook_baseline'] = None
            else:
                if baseline.get('candidates') and row['game_state'] == 'scheduled':
                    row['sportsbook_baseline'] = dict(baseline, candidates={
                        book: prices for book, prices in baseline['candidates'].items()
                        if clocks_current(prices, at=at, start=start)})
                row['sportsbook_return_percent'] = baseline['return_percent']
        fee = row.get('trade_fee')
        product_key = product_schedules.key_for(row)
        relevant_state = product_states.get(product_key) if product_key else fee_state
        relevant_revision = (product_schedules.revision(relevant_state) if product_key else current_fee_revision)
        fee_replaced = ((row['venue']=='prophetx' and 'fee_lifecycle' in owner or
                         product_key and 'fee_products' in owner)
                        and auth.get('public_fee_revision') != relevant_revision)
        fee_reason = (schedule_lifecycle.REVIEW_REQUIRED if (relevant_state or {}).get('review_required')
                      else 'public_fee_schedule_refresh_pending')
        catalog = auth.get('sgo_native_contract')
        catalog_replaced = bool(catalog and (policy_replaced or validity(catalog, current, at)))
        if catalog_replaced:
            row['sgo_native_contract'] = dict(available=False, reason='sgo_native_catalog_replaced_or_expired')
        if reasons or policy_replaced or fee is None:
            row['trade_fee'] = unavailable(
                'fee_source_price_not_current' if reasons else
                'fee_policy_replaced' if policy_replaced else 'fee_outcome_not_published')
        elif fee_replaced:
            row['trade_fee'] = unavailable(fee_reason)
        elif catalog_replaced:
            row['trade_fee'] = unavailable('sgo_native_catalog_replaced_or_expired')
        elif fee['available']:
            evidence = fee['evidence']
            if not applies(evidence, at):
                row['trade_fee'] = unavailable(EXPIRED, evidence=evidence)
        financial = list(reasons)
        if capture_failed:
            financial.append('ordinary_price_capture_failed')
        if policy_replaced:
            financial.append('policy_replaced')
        if row.get('settings_revision') != settings['revision']:
            financial.append('settings_replaced')
        for witness in auth['references']:
            witness_provider = witness.get('provider') or 'the_odds_api'
            if witness_provider in ('the_odds_api','sportsgameodds') and witness_provider != active_provider:
                financial.append('reference_provider_replaced')
            financial.extend(validity(witness, current, at))
            reference_source = witness.get('provider') if witness.get('provider') == 'sportsgameodds' else witness.get('venue')
            if not source_allowed(states.get(reference_source, {}),row.get('league')):
                financial.append('reference_source_unavailable')
        references = auth['references']
        multi = auth.get('reference_method') == 'sgo-book-median-proportional-1'
        best = auth.get('reference_method') == BEST_VERSION
        minimum = 6 if multi else 2
        maximum = len(BEST_BOOKS) * 2 if best else None if multi else 2
        if auth['reference_required'] and (len(references) < minimum or len(references) % 2
                or maximum is not None and len(references) > maximum
                or len({r.get('dependency') for r in references}) != len(references)):
            financial.append('reference_evidence_missing')
        if baseline and baseline.get('verified_native'):
            pregame_baseline_expired = row['game_state'] == 'scheduled' and not clocks_current(
                baseline.get('prices', ()), at=at, start=start)
            if financial or pregame_baseline_expired:
                if pregame_baseline_expired or any('source_expired' in validity(w, current, at) for w in references):
                    row['sportsbook_reference_reason'] = 'reference_price_stale'
                row['sportsbook_baseline'] = None
            else:
                row['sportsbook_return_percent'] = baseline['return_percent']
        if retain_sportsbook_ev and baseline and not row.get('sportsbook_baseline') and not capture_failed:
            # Browse can show the captured result after current authority ends.
            # Keep it outside the metric used for current ranking.
            price = auth['price']
            if (price.get('expected') and not price.get('reasons') and price.get('current_until')
                    and baseline.get('current_until') and row.get('captured_at')
                    and stamp(row['captured_at']) <= min(stamp(price['current_until']), stamp(baseline['current_until']))):
                row['last_known_sportsbook_ev'] = baseline['return_percent']
        row['exact_pinnacle_reference_current'] = not financial and auth.get('exact_pinnacle_reference', False)
        live_fee_unqualified = row['game_state']=='live' and not (
            (row.get('novig_live_financial_qualified') or row.get('kalshi_live_financial_qualified')
             or row.get('polymarket_live_financial_qualified')) and (row.get('trade_fee') or {}).get('available'))
        if financial:
            row = without_finance(row, ', '.join(sorted(set(financial))), status_cache=withdrawal_statuses, copy_row=False)
        elif fee_replaced or (auth['fee_until'] and at >= stamp(auth['fee_until']) or
                auth.get('fee_from') and at < stamp(auth['fee_from'])):
            row = snapshots.expand_row(row)
            row['conditional_return_percent'] = None
            row['conditional_trade_benchmark'] = dict(available=False, reason=fee_reason if fee_replaced else 'conditional_fee_review_expired_or_not_effective')
            from app.comparison.snapshot_metrics import statuses
            statuses(row)
        else:
            ready.add(row['id'])
        if live_fee_unqualified and not financial:
            row = snapshots.expand_row(row)
            row['conditional_return_percent'] = None
            row['conditional_trade_benchmark'] = dict(available=False, reason='live_financial_model_unverified')
            if row['venue'] != 'polymarket_us' or row.get('conservative_return_percent') is not None:
                row['conservative_return_percent'] = None
                row['conservative_trade_benchmark'] = dict(available=False, reason='live_financial_model_unverified')
            from app.comparison.snapshot_metrics import statuses
            statuses(row)
        pmus_fee_withdrawn = (row['venue'] == 'polymarket_us' and row.get('conservative_return_percent') is not None
                              and not row['trade_fee']['available'])
        if fee_replaced or pmus_fee_withdrawn or auth.get('conservative_fee_until') and at>=stamp(auth['conservative_fee_until']):
            row = snapshots.expand_row(row)
            row['conservative_return_percent']=None
            row['conservative_trade_benchmark']=dict(available=False,
                reason=fee_reason if fee_replaced else row['trade_fee']['reason'] if pmus_fee_withdrawn else EXPIRED)
            from app.comparison.snapshot_metrics import statuses
            if not financial:
                statuses(row)
        row['current_reasons'] = sorted(set(financial))
        out['rows'].append(row)
    for pair in result['pairs']:
        phases = {pair_ready.get(leg) for leg in pair['legs']}
        if snapshots.exact_arb_pair(pair) and len(phases) == 1 and phases <= {'scheduled', 'live'}:
            out['pairs'].append(pair)
    # Peer-price differences cannot borrow a withdrawn peer's offer.
    if len(ready) != len(result['rows']):
        for row in out['rows']:
            row['price_difference_cents'] = None
    held = owner.get('global_stopped') or owner.get('paused_sources') or any(s.get('state') == 'held' for s in states.values())
    required_sources = ('kalshi', 'polymarket_us', 'sportsgameodds') if active_provider == 'sportsgameodds' else ('kalshi', 'polymarket_us', 'novig', 'prophetx', 'pinnacle')
    healthy_sources = all(source_allowed(states.get(v, {})) for v in required_sources)
    state = ('held' if held else 'failed' if not owner.get('healthy') else
             'initializing' if not result['rows'] else
             'ready' if healthy_sources and len(ready) == len(result['rows']) and result['publication']['finance'] == 'ready' else 'partial')
    out['publication'] = dict(result['publication'], state=state, sources=states, current_prices=current_prices,
        data_runtime=publication_runtime(owner),
        retained_prices=len(result['rows'])-current_prices, coverage_complete=False,
        read_at=at.isoformat(), poll_after_ms=2000, provider_requests=0)
    if not current_desk:
        counts(out)
    return out
