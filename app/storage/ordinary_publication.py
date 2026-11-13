"""Replaceable ordinary comparisons, using the existing snapshot math owner.

A data-owned turn seals prices before optional finance. HTTP only validates
committed dependencies/expiry and reads a revision; it never acquires or computes.
"""
from datetime import timedelta
from pathlib import Path
import json
import gc
import gzip
from hashlib import sha256
from time import monotonic
from uuid import uuid4
from psycopg.types.json import Jsonb

from . import comparison_snapshot as snapshots
from .store import hashed, stamp
from .current_games import utc
from .current_rows import contract_id
from .comparison_policy import read as current_settings
from .ordinary_projection import (
    compact_member, compact_row, counts, without_finance,
    project as project, source_allowed as source_allowed, validity as validity,
)
from .ordinary_scheduling import (
    awaiting_aggregate, captured_aggregate_receipts, prioritize_current, receipt_watermarks, sgo_live_deliveries,
)
from app.comparison.display_identity import canonical_key
from app.comparison.source_clock import assess
from app.comparison.sgo_reference import BEST_BOOKS, BEST_VERSION
from app.fees import schedule_lifecycle
from app.fees import product_schedules

VERSION = 'ordinary-comparison-1'
MAX_RETAINED = 32
MAX_BYTES = 128 * 1024 * 1024
POLICY_ROOT = Path(__file__).resolve().parents[2]


def aggregate_provider(db=None, *, owner=None):
    """Use the committed collection config when a data owner has published it."""
    if owner is None and db is not None:
        row = db.execute("SELECT config->>'aggregate_provider' AS provider FROM data_runtime WHERE singleton").fetchone()
        if row and row['provider']:
            return row['provider']
    provider = (owner or {}).get('config', {}).get('aggregate_provider')
    if provider:
        return provider
    from app.collection.current_policy import DEFAULT, load
    return DEFAULT['aggregate_provider'] if db is not None or owner is not None else load()['aggregate_provider']


def policy_identity(provider=None):
    # Content, not file mtime: a read/restart cannot renew model authority.
    from .current_games import engine_binding, observation_binding
    paths = sorted((POLICY_ROOT / 'app/fixtures').glob('*conditional-fees*.json'))
    for path in list(paths):
        witness=json.loads(path.read_text()).get('path')
        if witness and not Path(witness).is_absolute() and '..' not in Path(witness).parts:
            paths.append(POLICY_ROOT/witness)
    paths += sorted((POLICY_ROOT / 'app/comparison').glob('snapshot*.py'))
    paths += [Path(__file__), Path(snapshots.__file__),
        POLICY_ROOT/'app/storage/capture_structure.py',
        POLICY_ROOT/'app/storage/capture_materialization.py',
        POLICY_ROOT/'app/storage/capture_price.py',POLICY_ROOT/'app/storage/member_packet.py',
        POLICY_ROOT/'app/storage/ordinary_fragments.py',
        POLICY_ROOT/'app/storage/ordinary_projection.py', POLICY_ROOT/'app/storage/comparison_policy.py',
        POLICY_ROOT/'app/comparison/conditional_benchmark.py',
        POLICY_ROOT/'app/comparison/snapshot_conservative.py', POLICY_ROOT/'app/comparison/snapshot_fee_outcome.py',
        POLICY_ROOT/'app/comparison/display_identity.py',
        POLICY_ROOT/'app/comparison/ordinary_arb.py',
        POLICY_ROOT/'app/comparison/game_phase.py',
        POLICY_ROOT/'app/dashboard/snapshot_api.py',
        POLICY_ROOT/'app/comparison/line_reference.py',
        POLICY_ROOT/'app/fees/engine.py',
        POLICY_ROOT/'app/fees/evidence.py',
        POLICY_ROOT/'app/fees/schedule_lifecycle.py', POLICY_ROOT/'app/fees/product_schedules.py',
        *(POLICY_ROOT/spec['reference'] for spec in product_schedules.PRODUCTS.values()),
        POLICY_ROOT/'app/fixtures/pinnacle-rules-20261028.html']
    from app.comparison.snapshot_fee_scope import ACCOUNT_PATH
    if ACCOUNT_PATH.exists():
        paths.append(ACCOUNT_PATH)
        try:
            account=json.loads(ACCOUNT_PATH.read_bytes())['kalshi']['evidence']['path']
            evidence=Path(account)
            if not evidence.is_absolute():evidence=POLICY_ROOT/evidence
            if evidence.exists():paths.append(evidence)
        except (ValueError,KeyError,TypeError):pass
    paths += [POLICY_ROOT/'app/comparison/sgo_reference.py', POLICY_ROOT/'app/comparison/sgo_reference_publication.py',
              POLICY_ROOT/'app/comparison/sgo_fair_display.py', POLICY_ROOT/'app/storage/sportsgameodds_reference.py',
              POLICY_ROOT/'app/comparison/sgo_native_binding.py',
              POLICY_ROOT/'app/comparison/sgo_sportsbook_baseline.py',
              POLICY_ROOT/'app/comparison/public_sportsbook_estimate.py',
              POLICY_ROOT/'app/collection/oddslink_prophetx.py',
              POLICY_ROOT/'app/comparison/sgo_rule_evidence.py', POLICY_ROOT/'app/comparison/sgo_median_publication.py',
              POLICY_ROOT/'app/fixtures/sgo-reviewed-market-rules-20261110.json',
              POLICY_ROOT/'app/fixtures/sgo-reviewed-jurisdiction-bindings.json']
    return hashed([VERSION, snapshots.ORDINARY_ARB_POLICY, engine_binding(), observation_binding(), provider or aggregate_provider(),
                   [(str(p.relative_to(POLICY_ROOT)) if p.is_relative_to(POLICY_ROOT) else str(p), sha256(p.read_bytes()).hexdigest()) for p in paths]])


def reviewed_reference_registry():
    from app.comparison.sgo_rule_evidence import owned_bindings

    try:
        return owned_bindings()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def sportsbook_dependencies(db, event_ids=None):
    registry = reviewed_reference_registry()
    if not registry or not registry.rows:
        return []
    keys = [{key: identity.get(key) for key in ('event_id', 'venue', 'odd_id', 'frame_id', 'line')}
            for identity, _ in registry.rows if identity['venue'] in BEST_BOOKS]
    at = stamp(utc())
    return db.execute('''SELECT DISTINCT 'sgo-reference:'||r.id id, r.revision price, r.id contract,
        e.id event_id, e.revision event, concat(r.received_order,':',review.frame_id) receipt
        FROM jsonb_to_recordset(%s) AS review(event_id text,venue text,odd_id text,frame_id text,line numeric)
        JOIN current_sgo_reference r ON (r.event_id,r.bookmaker_id,r.facts->>'odd_id') =
            (review.event_id,review.venue,review.odd_id)
            AND (r.facts->>'line')::numeric IS NOT DISTINCT FROM review.line
        JOIN current_sgo_event_frame f ON f.event_id=r.event_id AND f.facts->>'receipt_sha256'=review.frame_id
        JOIN current_event e ON e.provider='sportsgameodds' AND e.native_event_id=r.event_id
        WHERE ((%s::text[] IS NULL AND e.scheduled_start::timestamptz >= %s AND e.scheduled_start::timestamptz < %s)
            OR e.id=ANY(%s)) ORDER BY id''',
        (Jsonb(keys),event_ids,at-timedelta(hours=24),at+timedelta(hours=72),event_ids)).fetchall()


def sportsbook_frames(db, at):
    rows = db.execute("""SELECT e.id, e.native_event_id, e.competition, e.scheduled_start,
                                e.facts->>'home' home, e.facts->>'away' away,
                                f.facts->>'receipt_sha256' AS frame
                         FROM current_event e JOIN current_sgo_event_frame f ON f.event_id=e.native_event_id
                         WHERE e.provider='sportsgameodds' AND e.scheduled_start::timestamptz > %s
                           AND e.scheduled_start::timestamptz <= %s""", (at, at+timedelta(hours=72)))
    return list(rows)


def pregame_sportsbooks(db, owner, states, at, *, frames=None):
    from app.comparison.public_sportsbook_estimate import allowed, index, read_captures, sgo_observation
    from .sportsgameodds_reference import read_event, read_event_frame
    from collections import defaultdict

    if not allowed(owner):
        return {}
    matches = {key: [value] for key, value in index(read_captures(POLICY_ROOT, at=at), at=at).items()}
    candidates = defaultdict(list)
    for row in sportsbook_frames(db, at) if frames is None else frames:
        if source_allowed(states.get('sportsgameodds', {}), row['competition']):
            key = (row['competition'], stamp(row['scheduled_start']), row['home'], row['away'])
            candidates[key].append(row['native_event_id'])
    for key, ids in candidates.items():
        if len(ids) != 1:
            continue
        event = ids[0]
        try:
            frame = read_event_frame(db, event)
            if frame and stamp(frame['facts']['received_at']) >= at - timedelta(minutes=15):
                value = sgo_observation(frame, read_event(db, event, bookmakers=BEST_BOOKS,
                    source_since=at - timedelta(minutes=15)), at=at, occurrence=key)
                if value:
                    matches.setdefault(key, []).append(value)
        except (KeyError, ValueError):
            continue
    return matches


def dependencies(db, event_ids=None, *, sportsbook_rows=None, catalog_rows=None, provider=None):
    frames = ((provider or aggregate_provider(db))=='sportsgameodds' and
        bool(db.execute("SELECT to_regclass('public.current_sgo_event_frame') AS name").fetchone()['name']))
    frame_join = "LEFT JOIN current_sgo_event_frame f ON e.provider='sportsgameodds' AND f.event_id=e.native_event_id" if frames else ''
    receipt = "concat(o.revision,':',o.received_at,':',coalesce(f.facts->>'receipt_sha256',''))" if frames else "concat(o.revision,':',o.received_at)"
    rows = db.execute('''SELECT c.id, '''+receipt+''' receipt,
        o.price_dependency price,
        c.revision contract,
        e.revision event FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id
        '''+frame_join+'''
        WHERE ((%s::text[] IS NULL AND e.scheduled_start::timestamptz >= %s
                AND e.scheduled_start::timestamptz < %s)
            OR c.event_id=ANY(%s)) ORDER BY c.id''',
        (event_ids,stamp(utc())-timedelta(hours=24),stamp(utc())+timedelta(hours=72),event_ids)).fetchall()
    if frames:
        from .sgo_native_catalog import dependencies as catalog_dependencies
        rows += sportsbook_dependencies(db, event_ids) if sportsbook_rows is None else sportsbook_rows
        rows += catalog_dependencies(db, event_ids, at=utc()) if catalog_rows is None else catalog_rows
    if len(rows) > 32768:
        raise snapshots.SnapshotOperationError('ordinary_dependency_capacity')
    # The fourth field schedules genuine new confirmation evidence. Only the
    # first three invalidate captured economics: a newer identical confirmation
    # cannot invalidate a still-current old proof, nor extend its deadline.
    return {r['id']: [r['price'], r['contract'], r['event'], r['receipt']] for r in rows}


def capture_structure_ids(deps):
    # Membership first. Contract/event fingerprints cover the same keyed
    # sequence and can reject a successor without loading its original packet.
    keys=sorted(deps)
    return dict(offer_membership=hashed(keys),contract_revision=hashed([deps[k][1] for k in keys]),
                event_revision=hashed([deps[k][2] for k in keys]))


def governing_fields(binding):
    policy,settings,epoch,controls,sources=binding
    return dict(policy=policy,settings=settings,epoch=epoch,
                **{'owner.'+key:value for key,value in controls.items()},
                **{'source.'+key:value for key,value in sources.items()})


def component_binding(binding,venues):
    """Only sources present in this exact contract component govern its reuse."""
    return [*binding[:4],{venue:binding[4].get(venue) for venue in sorted(set(venues))}]


def owned_refresh(owner, quota):
    """Exact live-task + ledger witness; never grants acquisition authority."""
    if (quota.get('blocking_reason')!='ambiguous_dispatch_unresolved' or quota.get('pause')
            or not owner.get('healthy') or not owner.get('active') or owner.get('global_stopped')
            or 'the_odds_api' in owner.get('paused_sources',[])):
        return False
    pending=quota.get('publication_pending')
    panel=next((p for p in owner.get('status',{}).get('sources',[]) if p.get('provider')=='the_odds_api'),{})
    progress=panel.get('publication_progress')
    if pending and (not progress or progress.get('id')!=pending.get('id')):
        progress=next((p for p in panel.get('publication_completions',[]) if p.get('id')==pending.get('id')),None)
    return bool(pending and progress and pending.get('id')
        and pending.get('runtime_id')==owner.get('runtime_id')
        and all(pending.get(k)==progress.get(k) for k in ('id','runtime_id','candidate_digest'))
        and pending.get('state') in ('reserved','uncertain')
        and progress.get('stage') in ('reserved','transport','received','accounted')
        and not panel.get('worker_done'))


def authority(db, *, at=None):
    from app.collection.runtime_status import read_runtime, source_states
    owner = dict(read_runtime(db, at=at), fee_lifecycle=schedule_lifecycle.read(db),
                 fee_products=product_schedules.read_all(db))
    committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status')}
    # The legacy transport exposes four execution venues. Its shared aggregate
    # receipt also reports Pinnacle independently, including a reference-only sport.
    reference_scopes=committed.get('novig',{}).get('reference_sports')
    if reference_scopes is not None:
        committed['pinnacle']=dict(state='budget_delayed',reason_code='aggregate_scope_observed',
            observed_sports=reference_scopes)
    states=source_states(committed,owner)
    if 'sportsgameodds' in committed:
        states['sportsgameodds']=committed['sportsgameodds']
    if 'sportsgameodds' in owner.get('paused_sources', []) or owner.get('global_stopped'):
        states['sportsgameodds']=dict(state='stopped',reason_code='sgo_paused_or_stopped')
    odds_active = owner.get('config', {}).get('aggregate_provider', 'the_odds_api') == 'the_odds_api'
    if odds_active and 'the_odds_api' in owner.get('paused_sources', []):
        for venue in ('novig', 'prophetx', 'pinnacle'):
            states[venue] = dict(state='stopped', reason_code='aggregate_paused')
    quota = owner.get('status', {}).get('quota', {})
    block = quota.get('blocking_reason')
    if odds_active and block and not owned_refresh(owner,quota):
        for venue in ('novig', 'prophetx', 'pinnacle'):
            states[venue] = dict(state='held', reason_code=block)
    # Pinnacle has no separate transport; all three share the aggregate owner.
    if 'pinnacle' not in states:
        states['pinnacle'] = (states.get('novig', dict(state='initializing')) if odds_active else
                              dict(state='unavailable', reason_code='pinnacle_source_not_established'))
    return owner, states


def quote_authority(row, inputs, *, reference=False):
    record = row.get('original_record')
    if not record:
        return dict(dependency=None, expected=None, reasons=['source_evidence_missing'], current_until=None)
    q = record['quote']
    if reference:
        from app.collection.current_benchmark import MAXIMUM_AGE
        q=dict(q,freshness_policy=dict(maximum_age_seconds=MAXIMUM_AGE))
    cid = contract_id(record)
    clock = assess(q, stamp(inputs['captured_at']))
    from app.comparison.game_phase import original_price_phase
    lifecycle=original_price_phase(record,inputs['captured_at'])
    if lifecycle['reason']:clock['reasons'].append(lifecycle['reason'])
    if lifecycle.get('current_until') and clock.get('current_until'):
        clock['current_until']=min(clock['current_until'],lifecycle['current_until'])
    if q.get('state') in ('stopped','unavailable','error','resyncing','stale'):
        clock['reasons'].append('quote_'+q['state'])
    return dict(dependency=cid, expected=inputs['dependencies'].get(cid),
                venue=row['venue'], provider=q.get('source',{}).get('provider'), lifecycle=lifecycle,
                **({'novig_runtime_id':q['novig_runtime_id']} if q.get('novig_runtime_id') else {}), **clock)


def prices(inputs, settings):
    rows = [];statuses={}
    for q in inputs['quotes']:
        row = {k: v for k, v in q.items() if k not in ('original_record', 'benchmark_quote', 'native_contract')}
        if inputs.get('reference_provider') == 'sportsgameodds':
            row.update(reference=None, snapshot_benchmark=None,
                reference_calculation={'available':False, 'venue':'sportsgameodds_books',
                    'method':BEST_VERSION})
        row.update(kind='single', cost_per_normal_claim=None)
        rows.append(without_finance(row,'finance_pending',status_cache=statuses,copy_row=False))
    result = dict(id=uuid4().hex, snapshot_id=inputs['id'], captured_at=inputs['captured_at'],
                  calculated_at=None, assumptions=settings, rows=rows,
                  pairs=snapshots.before_fee_pairs(inputs['quotes'], at=inputs['captured_at']), games=inputs['games'],
                  references=[] if inputs.get('reference_provider') == 'sportsgameodds' else inputs['references'], sources=inputs['sources'], issues=inputs['issues'],
                  provider_requests=0, capture_seconds=inputs['capture_seconds'],
                  scope=dict(leagues=list(snapshots.SPORTS), families=['winner', 'spread', 'total'],
                             period='full_game', horizon_hours=72))
    return bind(result, inputs, 'pending')


def bind(result, inputs, finance):
    from app.comparison.game_phase import sporting_phase
    from app.comparison.snapshot_fee_scope import applicability
    from app.comparison.snapshot_fee_outcome import outcome, reviews, unavailable
    from app.comparison.sgo_native_binding import pregame_fee
    from .sgo_native_catalog import dependency_id as catalog_dependency_id
    from app.comparison.snapshot_named_benchmark import references, selected_references
    at = stamp(inputs['captured_at'])
    schedules = reviews(at) if result['rows'] else {}
    fee_state = inputs.get('fee_lifecycle')
    product_states = inputs.get('fee_products') or {}
    fee_revision = schedule_lifecycle.revision(fee_state)
    originals = {q['id']: q for q in inputs['quotes']}
    sgo_mode = inputs.get('reference_provider') == 'sportsgameodds'
    registry = reviewed_reference_registry() if sgo_mode and finance=='ready' else False
    refs = references(inputs['quotes'], inputs['references'], result['assumptions']) if finance=='ready' and not sgo_mode else []
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
        selected = selected_references(row, original, refs) if finance == 'ready' and not sgo_mode else []
        witnesses = [quote_authority(ref, inputs, reference=True) for ref in selected]
        fee_witnesses = witnesses
        if finance == 'ready' and sgo_mode:
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
            if binding and binding['available']:
                dependency = catalog_dependency_id(original['source']['native_event_id'])
                expected = inputs['dependencies'].get(dependency)
                if expected and expected[0] == binding['revision']:
                    catalog_authority = dict(dependency=dependency, expected=expected,
                        current_until=binding['current_until'])
                    row['trade_fee'] = pregame_fee(binding)
                    if row['trade_fee']['available']:
                        review = product_schedules.for_offer(product_states, row, at, fallback=schedules[row['venue']])
                        if review and review.get('unavailable_reason'):
                            row['trade_fee'] = unavailable(review['unavailable_reason'])
        elif row['venue'] in schedules and original.get('original_record'):
            record = original['original_record']
            phase = source.get('lifecycle', {}).get('state')
            if row['venue'] != 'polymarket_us' and sporting_phase(record['event'])['state'] == 'live':
                phase = 'live'
            fee_input = dict(row, fee_applicability=row.get('fee_applicability') or applicability(record),
                             novig_v3_evidence=record['quote'].get('novig_v3_evidence'))
            if row['id'] in paired_ids:
                row['fee_applicability'] = fee_input['fee_applicability']
            review = (schedule_lifecycle.for_offer(fee_state, fee_input, at, fallback=schedules[row['venue']])
                      if row['venue'] == 'prophetx' else
                      product_schedules.for_offer(product_states, fee_input, at, fallback=schedules[row['venue']]))
            row['trade_fee'] = outcome(fee_input, at=at, phase=phase, review=review)
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
        metadata = (original.get('original_record') or {}).get('comparison_source_metadata') or {}
        if metadata.get('alternate') is True:
            row['alternate'] = True
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
            [(r['source'], r['original']) for r in selected],
            (row.get('snapshot_benchmark') or {}).get('selected_predicate'),row.get('fee_applicability'),
            row.get('conditional_return_percent'),row.get('conservative_return_percent'),
            row.get('conservative_trade_benchmark',{}).get('evidence'),fee, result['assumptions']['revision'],
            row.get('trade_fee'), (row.get('reference_calculation') or {}).get('basis_sha256'), inputs['policy_identity']])
    if result['pairs']:
        from app.comparison.ordinary_arb import DEFAULT_FUNDING, evaluate, fee_identity

        rows = {row['id']: row for row in result['rows']}
        for pair in result['pairs']:
            proof = pair.get('before_fees')
            if proof and all(leg in rows for leg in pair['legs']):
                legs = [dict(rows[leg], captured_at=inputs['captured_at'],
                             game_state=rows[leg]['current_authority']['price'].get('lifecycle', {}).get('state'))
                        for leg in pair['legs']]
                pair['default_funding_result'] = evaluate(proof, legs, DEFAULT_FUNDING)
                pair['default_funding_fee_identity'] = fee_identity(legs)
    result['publication'] = dict(schema=VERSION, finance=finance, policy=inputs['policy_identity'],
        epoch=inputs['epoch'], captured_at=inputs['captured_at'], provider_requests=0)
    counts(result)
    return result


def status(db):
    return db.execute("SELECT generation,result_id,facts FROM comparison_publication WHERE kind='live' AND id=''").fetchone()


def retained_bytes(db):
    return db.execute('''SELECT
        (SELECT COALESCE(sum(CASE WHEN automatic THEN octet_length(result) ELSE 0 END
            + COALESCE(octet_length(read_fragment),0)::bigint),0) FROM comparison_snapshot_result) +
        (SELECT COALESCE(sum(octet_length(inputs)),0) FROM comparison_snapshot WHERE automatic) n''').fetchone()['n']


def compact_retention(db, required):
    """Recover encoding headroom without changing a single retained JSON byte.

    Older level-three blobs can strand two component generations behind the head.
    Re-encode one blob at a time under the publication lock. Preserve the
    physical bytes of explicit review pins and their inputs. Leased evidence
    keeps exact decoded contents, identities and clocks when re-encoded.
    """
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage
    from .storage_maintenance import REWRITE_RUNWAY_BYTES
    retained = retained_bytes(db)
    if retained + required <= MAX_BYTES:
        return
    pinned_results = "SELECT result_id FROM comparison_result_reference WHERE kind='review'"
    pinned_inputs = f"SELECT snapshot_id FROM comparison_snapshot_result WHERE id IN ({pinned_results})"
    for table, column, pinned in (('comparison_snapshot', 'inputs', pinned_inputs),
                                  ('comparison_snapshot_result', 'result', pinned_results)):
        sizes = db.execute(f'''SELECT id,octet_length({column}) size FROM {table}
            WHERE automatic AND id NOT IN ({pinned}) ORDER BY size DESC''').fetchall()
        for item in sizes:
            if retained + required <= MAX_BYTES:
                return
            if sql_usage(db) + 2*item['size'] + REWRITE_RUNWAY_BYTES >= SQL_BYTE_CAP:
                raise snapshots.SnapshotOperationError('ordinary_sql_headroom')
            packed = db.execute(f'SELECT {column} data FROM {table} WHERE id=%s', (item['id'],)).fetchone()['data']
            if not packed.startswith(b'\x1f\x8b'):
                continue
            raw = gzip.decompress(packed)
            replacement = gzip.compress(raw, compresslevel=6, mtime=0)
            if len(replacement) < len(packed):
                assert gzip.decompress(replacement) == raw
                changed = db.execute(f'UPDATE {table} SET {column}=%s WHERE id=%s AND id NOT IN ({pinned})',
                                     (replacement, item['id'])).rowcount
                retained -= changed*(len(packed)-len(replacement))


def seal(db, inputs, result, facts, *, insert_inputs=False, component=None, members=(), prior_parts=None, costs=None):
    # Automatic replacements favor bounded low-latency encoding; manual saved
    # captures retain their denser encoding. Both use the same checked decoder.
    started_pack=monotonic();reused=0
    if component and insert_inputs and inputs.get('_price_basis'):
        from .member_packet import encode
        packed_inputs,reused=encode(inputs,prior_parts)
    else:packed_inputs = snapshots.pack(inputs, fast=True) if insert_inputs else b''
    input_time=monotonic()-started_pack;result_start=monotonic()
    packed_result = (snapshots.pack_read(snapshots.defer_details(result)) if members
        else snapshots.pack(result, fast=True))
    if costs is not None:costs.update(input_encode_seconds=round(input_time,6),input_bytes=len(packed_inputs),
        reused_input_bytes=reused,result_bytes=len(packed_result),result_encode_seconds=round(monotonic()-result_start,6))
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage
    from .storage_maintenance import REWRITE_RUNWAY_BYTES
    snapshots.prune(db)
    retained = retained_bytes(db)
    if retained + len(packed_inputs) + len(packed_result) > MAX_BYTES:
        raise snapshots.SnapshotOperationError('ordinary_retention_capacity')
    if sql_usage(db) + 2*(len(packed_inputs)+len(packed_result)) + REWRITE_RUNWAY_BYTES >= SQL_BYTE_CAP:
        raise snapshots.SnapshotOperationError('ordinary_sql_headroom')
    with db.transaction():
        if insert_inputs:
            db.execute('''INSERT INTO comparison_snapshot(id,captured_at,inputs,lease_until,automatic)
                VALUES(%s,%s,%s,clock_timestamp()+interval '10 seconds',true)''', (inputs['id'], inputs['captured_at'], packed_inputs))
        snapshots.insert_result(db, result, inputs['id'], packed_result, automatic=True)
        if component is not None:
            if insert_inputs:
                from .delivery_clocks import captured
                captured(db,inputs['quotes'],inputs['captured_at'])
            db.execute('''INSERT INTO comparison_publication(kind,id,result_id,facts) VALUES('component',%s,%s,%s)
                ON CONFLICT(kind,id) DO UPDATE SET result_id=excluded.result_id,facts=excluded.facts''',
                (component, result['id'], Jsonb(facts)))
            row=dict(generation=None)
        else:
            from .delivery_clocks import published
            delivery = facts.pop('_delivery_receipts', [])
            live_sportsbook = facts.pop('_live_sportsbook_deadlines', [])
            if members:
                db.execute('''INSERT INTO comparison_result_reference (kind,holder,result_id,position)
                    SELECT 'member',%s,member_id,position FROM unnest(%s::text[]) WITH ORDINALITY AS m(member_id,position)''',
                    (result['id'], list(members)))
            # Grace starts when a displayed head is superseded, not when it was
            # first assembled. A long-lived head must remain selectable while
            # a browser receives/renders its replacement.
            db.execute("""UPDATE comparison_snapshot_result
                SET lease_until=greatest(lease_until,clock_timestamp()+interval '10 seconds')
                WHERE id=(SELECT result_id FROM comparison_publication WHERE kind='live' AND id='')""")
            row = db.execute('''UPDATE comparison_publication SET generation=generation+1,result_id=%s,facts=%s
                WHERE kind='live' AND id='' RETURNING generation''', (result['id'], Jsonb(dict(facts, published_at=utc())))).fetchone()
            published(db, delivery, live_sportsbook=live_sportsbook)
        snapshots.prune(db)
    return row['generation']


def lease(db, result_id):
    """Bound explicit evidence leases; ordinary notifications never retain history."""
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(901154)')
        row = db.execute('SELECT automatic,lease_until FROM comparison_snapshot_result WHERE id=%s', (result_id,)).fetchone()
        if row is None: return False
        if row['automatic'] and row['lease_until'] <= stamp(utc())+timedelta(seconds=30):
            n = db.execute("SELECT count(*) n FROM comparison_snapshot_result WHERE automatic AND lease_until>now()+interval '30 seconds'").fetchone()['n']
            if n >= MAX_RETAINED: raise snapshots.SnapshotOperationError('Selected evidence lease capacity reached')
        db.execute("UPDATE comparison_snapshot_result SET lease_until=now()+interval '2 hours' WHERE id=%s", (result_id,))
        db.execute("UPDATE comparison_snapshot SET lease_until=now()+interval '2 hours' WHERE id=(SELECT snapshot_id FROM comparison_snapshot_result WHERE id=%s)", (result_id,))
    return True


def compose(db, settings, *, scope, policy, epoch, started):
    """Atomic manifest of immutable compact members; no whole-root rewrite."""
    from .ordinary_fragments import VERSION as FRAGMENTS
    result = dict(id=uuid4().hex, snapshot_id=uuid4().hex, captured_at=utc(), calculated_at=utc(),
        assumptions=settings, rows=[], pairs=[], games=[], references=[], sources={}, issues=[],
        provider_requests=0, capture_seconds=0,
        scope=dict(leagues=list(snapshots.SPORTS),families=['winner','spread','total'],period='full_game',horizon_hours=72))
    components=db.execute('''SELECT c.id,c.result_id,c.facts,r.read_summary AS summary FROM comparison_publication c
        JOIN comparison_snapshot_result r ON r.id=c.result_id
        WHERE c.kind='component' AND c.id=ANY(%s) ORDER BY c.id''',(list(scope),)).fetchall()
    missing=[c['result_id'] for c in components if c['summary'] is None]
    blobs={r['id']:r['result'] for r in db.execute(
        'SELECT id,result FROM comparison_snapshot_result WHERE id=ANY(%s)',(missing,))}
    members=[];captured=[];boundaries=[];pending=0;failed=0;written=0;delivery=[];live_sportsbook=[]
    totals=dict(observations=0,gross_numeric=0,conditional_numeric=0,conservative_numeric=0,net_numeric=0,pairs=0,unmatched=0)
    for c in components:
        summary=c['summary']
        if summary is None:
            part=compact_member(snapshots.unpack(blobs.pop(c['result_id'])))
            packed=snapshots.pack_read(snapshots.defer_details(part))
            from app.collection.current_storage_policy import SQL_BYTE_CAP,sql_usage
            from .storage_maintenance import REWRITE_RUNWAY_BYTES
            if retained_bytes(db)+len(packed)>MAX_BYTES:
                raise snapshots.SnapshotOperationError('ordinary_retention_capacity')
            if sql_usage(db)+2*len(packed)+REWRITE_RUNWAY_BYTES>=SQL_BYTE_CAP:
                raise snapshots.SnapshotOperationError('ordinary_sql_headroom')
            from .delivery_clocks import live_sportsbook_deadlines, receipts
            from .ordinary_evidence import event_id
            summary=dict(captured_at=part['captured_at'],finance=part['publication']['finance'],counts=part['counts'],
                         event_ids=sorted({event_id(r['source']) for r in part['rows']}),
                         delivery_receipts=receipts(part['rows']), live_sportsbook_deadlines=live_sportsbook_deadlines(part['rows']))
            db.execute('''UPDATE comparison_snapshot_result SET read_summary=%s,read_fragment=%s
                WHERE id=%s AND read_fragment IS NULL''', (Jsonb(summary),packed,c['result_id']))
            written+=len(packed)
        delivery.extend(summary.get('delivery_receipts',[]))
        live_sportsbook.extend(summary.get('live_sportsbook_deadlines', []))
        members.append(c['result_id']);captured.append(summary['captured_at'])
        pending+=summary['finance']!='ready';failed+=c['facts'].get('finance')=='failed'
        for key in totals:totals[key]+=summary['counts'][key]
        if c['facts'].get('next_boundary'):boundaries.append(c['facts']['next_boundary'])
    pending+=len(scope)-len(members)
    result['_read_fragments']='publication-members-v1'
    result['publication']=dict(schema=VERSION,finance='failed' if failed else 'pending' if pending else 'ready',policy=policy,
        epoch=epoch,component_count=len(members),expected_components=len(scope),pending_components=pending,
        oldest_capture=min(captured,key=stamp) if captured else None,provider_requests=0)
    result['counts']=totals
    _,states=authority(db)
    inputs=dict(id=result['snapshot_id'],captured_at=result['captured_at'],quotes=[],references=[],
        games=[],sources=states,issues=[],capture_seconds=0)
    facts=dict(state='partial' if pending else 'ready',finance=result['publication']['finance'],
        component_count=len(members),expected_components=len(scope),pending_components=pending,
        next_boundary=min(boundaries,key=stamp) if boundaries else None,
        _delivery_receipts=delivery,_live_sportsbook_deadlines=live_sportsbook,
        representation=FRAGMENTS,fragment_bytes_written=written,new_fragments=len(missing),
        total_seconds=round(monotonic()-started,3))
    return seal(db,inputs,result,facts,insert_inputs=True,members=members)


def turn(db, *, turn_seconds=8, capture_cache=None):
    """Latest-only component work; unchanged games reuse their exact evidence.

    This replaces the old board observation/estimate loops, reusing their complete
    matching-component partition. No component is excluded for being slow.
    """
    from .board_capture import capture_batches
    from app.comparison.calculation_control import checkpoint
    if not db.execute('SELECT pg_try_advisory_lock(901153) held').fetchone()['held']:
        return dict(published=False,reason='snapshot_operation_running')
    started=monotonic();changed=0;computed=0;price_generation=None;price_published_at=None;timings={}
    try:
        from . import capture_structure,capture_materialization
        if capture_cache is not None:
            capture_structure.load(capture_cache)
            capture_materialization.load(capture_cache.with_suffix('.material.json'))
        else:
            capture_structure.clear();capture_materialization.clear()
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            db.execute('SET LOCAL jit=off')
            epoch=str(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'])
            settings=current_settings(db)
            owner,source_states=authority(db)
            reference_provider=aggregate_provider(owner=owner)
            policy=policy_identity(reference_provider)
            fee_state=owner['fee_lifecycle']
            product_states=owner['fee_products']
            fee_revision=schedule_lifecycle.publication_revision(fee_state)
            capture_binding=[policy,settings['revision'],epoch,
                {k:owner.get(k) for k in ('runtime_id','global_stopped','paused_sources','dispatch')},
                {k:v.get('state') for k,v in source_states.items()}]
            frame_binding=capture_binding
            finance_available=(reference_provider == 'sportsgameodds' or source_allowed(source_states.get('pinnacle',{})))
            at=stamp(utc())
            from app.comparison.public_sportsbook_estimate import identity as reference_identity
            frames_exist = reference_provider == 'sportsgameodds' and db.execute(
                "SELECT to_regclass('public.current_sgo_event_frame') AS name").fetchone()['name']
            frames = sportsbook_frames(db, at) if frames_exist else []
            public_matches = pregame_sportsbooks(db, owner, source_states, at, frames=frames)
            public_events = {}
            if public_matches:
                for event in db.execute("""SELECT id,competition,scheduled_start,facts->>'home' home,facts->>'away' away
                    FROM current_event WHERE provider IN ('kalshi','polymarket_us') AND competition=ANY(%s)""",
                    (sorted({key[0] for key in public_matches}),)):
                    match = public_matches.get((event['competition'], stamp(event['scheduled_start']), event['home'], event['away']))
                    if match:
                        public_events[event['id']] = [reference_identity(item, at=at) for item in match]
            selected={r['id'] for r in db.execute('''SELECT id FROM current_event WHERE competition=ANY(%s)
                AND scheduled_start::timestamptz >= %s AND scheduled_start::timestamptz < %s''',
                (list(snapshots.SPORTS),at-timedelta(hours=24),at+timedelta(hours=72)))}
            # Include the complete peer component when any member is in scope.
            batches=[b for b in capture_batches(db) if selected.intersection(b)]
            scope={hashed(sorted(b)):b for b in batches}
            old={c['id']:c for c in db.execute("SELECT id,result_id,facts FROM comparison_publication WHERE kind='component'")}
            sportsbook_rows = sportsbook_dependencies(db) if frames_exist else []
            from .sgo_native_catalog import dependencies as catalog_dependencies
            catalog_rows = catalog_dependencies(db, at=utc()) if reference_provider == 'sportsgameodds' else []
            dep=dependencies(db, sportsbook_rows=sportsbook_rows, catalog_rows=catalog_rows, provider=reference_provider)
            contracts=db.execute('SELECT id,event_id,venue FROM current_contract').fetchall()
            membership={r['id']:r['event_id'] for r in contracts}
            membership.update((r['id'], r['event_id']) for r in sportsbook_rows)
            membership.update((r['id'], r['event_id']) for r in catalog_rows)
            event_venues={}
            for r in contracts:event_venues.setdefault(r['event_id'],set()).add(r['venue'])
            per_event={}
            for cid,value in dep.items():per_event.setdefault(membership[cid],{})[cid]=value
            latest_receipts={r['event_id']:r['at'] for r in db.execute('''SELECT c.event_id,max(o.received_at) at
                FROM current_offer o JOIN current_contract c ON c.id=o.contract_id GROUP BY c.event_id''')}
            aggregate_receipts,native_evidence=receipt_watermarks(db, reference_provider)
            prophetx_components={key for key,ids in scope.items()
                                 if any('prophetx' in event_venues.get(eid,()) for eid in ids)}
            product_components={key:{product_key for product_key,spec in product_schedules.PRODUCTS.items()
                if any(spec['venue'] in event_venues.get(eid,()) for eid in ids)} for key,ids in scope.items()}
            def input_identity(key, dependencies):
                return hashed([epoch,policy,settings['revision'],fee_revision if key in prophetx_components else None,
                    {k:product_schedules.revision(product_states.get(k),publication=True) for k in sorted(product_components[key])},
                    [(eid,dependencies.get(eid,{})) for eid in sorted(scope[key])],
                    [public_events[eid] for eid in sorted(scope[key]) if eid in public_events]])
            desired={key:input_identity(key,per_event) for key in scope}
            material={key:hashed([epoch,[(eid,{cid:v[:3] for cid,v in per_event.get(eid,{}).items()})
                for eid in sorted(ids)]]) for key,ids in scope.items()}
        schedule_boundaries=[]
        for path in (POLICY_ROOT/'app/fixtures').glob('*conditional-fees*.json'):
            model=json.loads(path.read_text())
            schedule_boundaries.extend(model[k] for k in ('reviewed_at','review_before') if model.get(k) and stamp(model[k])>at)
        public_boundaries=schedule_lifecycle.boundaries(fee_state,at)
        public_boundaries += [deadline for v in product_states.values()
                              if (deadline := (v.get('last_verified') or {}).get('review_before'))
                              and stamp(deadline) > at]

        removed=set(old)-set(scope)
        def fee_boundary_due(facts):
            return facts.get('next_fee_boundary') and stamp(facts['next_fee_boundary'])<=at

        def needs(key):
            facts=old.get(key,{}).get('facts',{})
            return (facts.get('input_identity')!=desired[key] or fee_boundary_due(facts) or finance_available and (
                    facts.get('finance')!='ready' or
                    facts.get('next_boundary') and stamp(facts['next_boundary'])<=at))
        pending=[key for key in scope if needs(key)]
        # Missing components first, then oldest successful visit: a hot native
        # game cannot starve reference/API updates or quiet leagues.
        pending.sort(key=lambda key:(key in old,old.get(key,{}).get('facts',{}).get('visited_at',''),
            -max((stamp(latest_receipts[e]).timestamp() for e in scope[key] if e in latest_receipts),default=0),key))
        # A repeated confirmation must not win every fresh slot ahead of a real
        # price/contract change. These hashes schedule only; exact captured
        # dependencies and the existing authority checks still own eligibility.
        undelivered = {key for key in pending if awaiting_aggregate(old.get(key, {}).get('facts', {}),
            scope[key], aggregate_receipts, at)}
        live_deliveries = sgo_live_deliveries(pending, scope, native_evidence, at, undelivered)
        native_slots=set()
        pending=prioritize_current(pending,scope,native_evidence,at,material={key for key in pending
            if old.get(key,{}).get('facts',{}).get('material_identity')!=material[key]},
            undelivered=undelivered, live_deliveries=live_deliveries,
            desk_matches={key for key in pending if public_events.keys() & set(scope[key])},
            native_slots=native_slots)
        timings['planning_seconds']=round(monotonic()-started,6)
        work=[];errors=[];component_trace=[]
        live_first_price_seal = False
        native_deadlines=[]
        native_price_seal=False
        snapshots.prune(db)
        head_size=db.execute('''SELECT octet_length(r.result) n FROM comparison_publication p
            JOIN comparison_snapshot_result r ON r.id=p.result_id WHERE p.kind='live' AND p.id='' ''').fetchone()
        # Recover legacy staging pressure before the atomic batch. This reserved
        # margin is a request for lossless compaction, never extra capacity.
        compact_retention(db, 2*(head_size['n'] if head_size else 0)+8*1024*1024)
        # A failed successor seal rolls its staged component pointers/inputs back.
        # It cannot pin a second unpublished slate on each retry.
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            db.execute('SET LOCAL jit=off')
            if removed:
                db.execute("DELETE FROM comparison_publication WHERE kind='component' AND id=ANY(%s)",(list(removed),))
                changed+=len(removed)
            capture_started=monotonic()
            for key in pending:
                checkpoint()
                # Oldest, first aggregate delivery, Kalshi and US can occupy
                # four distinct reserved slots. Cutting after three repeatedly
                # postponed US whenever aggregate and Kalshi work were pending.
                if len(work)>=4 and monotonic()-capture_started>=turn_seconds/2:break
                capture_binding=component_binding(frame_binding,{v for eid in scope[key] for v in event_venues.get(eid,())})
                capture_binding_id=hashed(capture_binding)
                governing=governing_fields(capture_binding)
                prior=old.get(key)
                if (prior and prior['facts'].get('input_identity')==desired[key]
                        and prior['facts'].get('finance')!='ready' and not fee_boundary_due(prior['facts'])):
                    input_id=db.execute('SELECT snapshot_id FROM comparison_snapshot_result WHERE id=%s',(prior['result_id'],)).fetchone()['snapshot_id']
                    work.append((key,input_id,dict(prior['facts'])))
                    native_slots.discard(key)
                    continue
                inputs=None;capture_diagnostics={};prior_parts=None;costs={}
                current_dependencies=dependencies(db,scope[key],provider=reference_provider)
                structure_ids=capture_structure_ids(current_dependencies)
                prior_facts=prior['facts'] if prior else {}
                previous_structure=prior_facts.get('capture_structure_ids',{})
                changed_structure=[field for field,value in structure_ids.items()
                    if field in previous_structure and previous_structure[field]!=value]
                # A known mismatch can only force the complete owner. Reuse
                # still requires the entire new transaction's dependency closure.
                if prior and prior['facts'].get('capture_binding_id',capture_binding_id)!=capture_binding_id:
                    capture_diagnostics['fallback']='governing_binding_changed_before_decode'
                    old_fields=prior_facts.get('governing_fields')
                    capture_diagnostics['changed_fields']=(['legacy_unknown'] if old_fields is None else
                        sorted(k for k in governing.keys()|old_fields.keys() if governing.get(k)!=old_fields.get(k)))
                    costs['input_decode_skipped']=True
                elif changed_structure:
                    capture_diagnostics.update(fallback=changed_structure[0],changed_fields=changed_structure)
                    costs['input_decode_skipped']=True
                elif prior:
                    from .capture_price import capture as capture_price
                    saved=db.execute('SELECT s.inputs FROM comparison_snapshot_result r JOIN comparison_snapshot s ON s.id=r.snapshot_id WHERE r.id=%s',
                        (prior['result_id'],)).fetchone()
                    if saved:
                        from . import member_packet
                        reading=monotonic()
                        if saved['inputs'].startswith(member_packet.MAGIC):previous,prior_parts=member_packet.read(saved['inputs'],borrow=True)
                        else:previous=snapshots.unpack(saved['inputs'])
                        costs['input_decode_seconds']=round(monotonic()-reading,6)
                        del saved
                        inputs=capture_price(db,previous,at=utc(),binding=capture_binding,event_ids=scope[key],diagnostics=capture_diagnostics,_frame_dependencies=current_dependencies)
                        del previous
                if inputs is None:
                    prior_parts=None
                    inputs=snapshots.capture(db,ordinary=True,event_ids=scope[key],capture_binding=capture_binding,
                        price_basis=True,_frame_dependencies=current_dependencies,reference_provider=reference_provider)
                    inputs['_price_capture']=dict(path='complete',read_records=len(inputs['dependencies']),**capture_diagnostics)
                inputs['policy_identity']=policy
                inputs['reference_provider']=reference_provider
                from app.comparison.public_sportsbook_estimate import select as public_estimate
                capture_at = stamp(inputs['captured_at'])
                for row in inputs['quotes']:
                    if (row.get('sportsbook_baseline') or {}).get('indicative'):
                        row.pop('sportsbook_baseline')
                    if public_matches and (row.get('source') or {}).get('provider') in ('kalshi', 'polymarket_us'):
                        estimate = public_estimate(row, quote_authority(row, inputs), public_matches, at=capture_at)
                        if estimate:
                            row['sportsbook_baseline'] = estimate
                # Ingress can add a venue between planning and this capture.
                # Fee authority must cover the actual quotes in this member.
                captured_venues = {row['venue'] for row in inputs['quotes']}
                product_components[key].update(product_key for product_key, spec in product_schedules.PRODUCTS.items()
                                               if spec['venue'] in captured_venues)
                if 'prophetx' in captured_venues:
                    prophetx_components.add(key)
                inputs['fee_lifecycle']=fee_state if key in prophetx_components else None
                inputs['fee_products']={k:product_states[k] for k in product_components[key] if k in product_states}
                captured_dependencies={}
                for cid, value in inputs['dependencies'].items():
                    captured_dependencies.setdefault(membership.get(cid),{})[cid]=value
                identity=input_identity(key,captured_dependencies)
                facts=dict(input_identity=identity,finance='pending',visited_at=utc(),capture_seconds=inputs['capture_seconds'],
                    aggregate_receipts=captured_aggregate_receipts(inputs),
                    capture_binding_id=inputs['_price_basis']['binding'],governing_fields=governing,capture_structure_ids=structure_ids)
                facts['material_identity']=hashed([epoch,[(eid,{cid:v[:3] for cid,v in inputs['dependencies'].items()
                    if membership.get(cid)==eid}) for eid in sorted(scope[key])]])
                binding_start=monotonic();price_result=prices(inputs,settings)
                costs['price_binding_seconds']=round(monotonic()-binding_start,6)
                # Price-only members may outlive an optional-finance outage.
                # Their own expiry must still advance browser authority cursors
                # even if no provider update or further calculation occurs.
                boundaries=[v for row in price_result['rows'] for v in
                    (row['current_authority']['price'].get('current_until'),row['start_at'],
                     (row['current_authority'].get('sgo_native_contract') or {}).get('current_until'),
                     (row.get('sportsbook_baseline') or {}).get('current_until')) if v]
                fee_boundaries=[*schedule_boundaries, *(public_boundaries if key in prophetx_components or product_components[key] else ())]
                facts['next_fee_boundary']=min(fee_boundaries,key=stamp,default=None)
                boundaries.extend(fee_boundaries)
                facts['next_boundary']=min(boundaries,key=stamp) if boundaries else None
                seal(db,inputs,price_result,facts,insert_inputs=True,component=key,prior_parts=prior_parts,costs=costs)
                del prior_parts
                component_trace.append(dict(component=key,event_ids=sorted(scope[key])[:8],event_count=len(scope[key]),
                    queue_position=pending.index(key),selected_at=at.isoformat(),
                    aggregate_receipts=facts['aggregate_receipts'],
                    desired_identity=desired[key],captured_identity=identity,member=price_result['id'],
                    captured_at=inputs['captured_at'],capture_seconds=inputs['capture_seconds'],
                    member_costs=costs,rows=len(inputs['quotes']),price_capture=inputs.get('_price_capture'),previous_visit=(prior or {}).get('facts',{}).get('visited_at'),
                    receipts=[dict(venue=q['venue'],market_id=q['source']['native_market_id'],
                        received_at=q['times']['received_at'],source_at=q['times'].get('source_at'))
                        for q in (inputs['quotes'][:2]+inputs['quotes'][-2:])]))
                work.append((key,inputs['id'],facts));changed+=1
                # Indicative EV is already in the ordinary price member. Seal
                # a fresh first delivery before spending the turn on peers.
                if live_deliveries and key == live_deliveries[0]:
                    live_first_price_seal = any(row.get('sportsbook_baseline')
                        and row['current_authority']['price'].get('lifecycle', {}).get('state') == 'live'
                        and not row['current_authority']['price']['reasons'] for row in price_result['rows'])
                if native_slots:
                    # Give both dedicated feeds their reserved turn. Once
                    # captured, publish usable prices before more background
                    # rotation consumes their short source-clock lifetime.
                    native_deadlines.extend(stamp(price['current_until']) for row in price_result['rows']
                        if (price := row['current_authority']['price']).get('provider') in ('kalshi','polymarket_us')
                        and not price['reasons'] and price['current_until'])
                    native_slots.discard(key)
                    native_price_seal=not native_slots and any(deadline > stamp(utc()) for deadline in native_deadlines)
                del inputs,price_result
                if not native_slots and (live_first_price_seal or native_price_seal):
                    break
            timings['capture_seconds']=round(monotonic()-capture_started,6)
            price_seal_started=monotonic()
            # One atomic price replacement per bounded batch, before optional math.
            # Repeated whole-board packing per game otherwise dominated acquisition.
            if changed:
                gc.collect()
                price_generation=compose(db,settings,scope=scope,policy=policy,epoch=epoch,started=started)
                price_published_at=status(db)['facts']['published_at']
        timings['price_seal_seconds']=round(monotonic()-price_seal_started,6)
        # Yield at the committed source-only boundary, never while holding the
        # staged component/root transaction. Stop and the child deadline remain
        # binding throughout a cooperative pressure pause.
        checkpoint()
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            db.execute('SET LOCAL jit=off')
            finance_started=monotonic()
            # An unavailable reference owner cannot produce current finance.
            # Keep original evidence in leased members and publish source prices;
            # retry pending finance when actual reference authority returns.
            # No reference timestamp or accounting state is changed here.
            for key,input_id,facts in (work if finance_available else ()):
                checkpoint()
                # Finance shares the turn's wall-time budget with planning and
                # capture. Keep one oldest job progressing even on a costly turn.
                if computed and monotonic()-started>=turn_seconds:break
                inputs=snapshots.unpack(db.execute('SELECT inputs FROM comparison_snapshot WHERE id=%s',(input_id,)).fetchone()['inputs'])
                try:
                    result=bind(snapshots.calculate(inputs,settings),inputs,'ready')
                except Exception as exc:
                    from app.comparison.calculation_control import CalculationStopped
                    if isinstance(exc,CalculationStopped):raise
                    db.execute("UPDATE comparison_publication SET facts=facts || %s WHERE kind='component' AND id=%s",
                        (Jsonb(dict(finance='failed',error='ordinary_finance_failed',visited_at=utc())),key))
                    errors.append(dict(component=key,reason='ordinary_finance_failed'))
                    del inputs
                    continue
                now=stamp(utc())
                future=[v for v in [*schedule_boundaries, *(public_boundaries if key in prophetx_components or product_components[key] else ())]
                        if stamp(v)>now]
                for row in result['rows']:
                    a=row['current_authority']
                    future.extend(v for v in [a.get('fee_until'),a.get('conservative_fee_until'),
                        (row.get('trade_fee',{}).get('evidence') or {}).get('review_before'),
                        (a.get('sgo_native_contract') or {}).get('current_until'),
                        a['start_at'],a['price'].get('current_until'),
                        (row.get('sportsbook_baseline') or {}).get('current_until'),
                        *(w.get('current_until') for w in a['references'])] if v and stamp(v)>now)
                facts.update(finance='ready',next_boundary=min(future,key=stamp) if future else None,visited_at=utc())
                seal(db,inputs,result,facts,component=key)
                computed+=1
                del inputs,result
            timings['finance_seconds']=round(monotonic()-finance_started,6)
            finance_seal_started=monotonic()
            if computed or errors:
                gc.collect()
                generation=compose(db,settings,scope=scope,policy=policy,epoch=epoch,started=started)
            else:generation=status(db)['generation']
        timings['finance_seal_seconds']=round(monotonic()-finance_seal_started,6)
        snapshots.prune(db)
        # Exact identities at this turn's planning snapshot. This is a bounded
        # census, not an exhaustive arrival log: intervening updates can coalesce.
        import base64
        from .store import encoded
        queue=base64.b64encode(gzip.compress(encoded([[key,desired[key],key in pending,
            old.get(key,{}).get('facts',{}).get('visited_at')] for key in sorted(scope)]),mtime=0)).decode()
        queue_trace=dict(encoding='gzip-base64-json',at=at.isoformat(),count=len(scope),
            value=queue if len(queue)<=32768 else None,omitted=len(scope) if len(queue)>32768 else 0)
        if capture_cache is not None:
            capture_structure.save(capture_cache)
            capture_materialization.save(capture_cache.with_suffix('.material.json'))
        return dict(timings=timings,component_trace=component_trace[-8:],component_queue=queue_trace,
            capture_structure=capture_structure.metrics(),materialization=capture_materialization.metrics(),serviced_components=[key for key,_,_ in work],pending_components=len(pending),
            captured_components=len(work),finance_deferred_reason=None if finance_available else 'reference_source_unavailable',
            live_first_price_seal=live_first_price_seal,
            native_price_seal=native_price_seal,
            published=bool(changed or computed),unchanged=not pending and not removed,computed=computed,errors=errors,
            remaining_components=max(0,len(pending)-(computed if finance_available else len(work))),expected_components=len(scope),
            generation=generation,price_generation=price_generation,price_published_at=price_published_at,
            turn_seconds=round(monotonic()-started,3))
    finally:db.execute('SELECT pg_advisory_unlock(901153)')


def retain(db, result_id, lease_id=None):
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(901154)')
        db.execute("DELETE FROM comparison_result_reference WHERE kind='lease' AND expires_at<now()")
        if not db.execute('SELECT 1 FROM comparison_snapshot_result WHERE id=%s FOR KEY SHARE',(result_id,)).fetchone():
            raise snapshots.SnapshotOperationError('Selected evidence expired')
        if lease_id:
            row=db.execute("""UPDATE comparison_result_reference SET expires_at=now()+interval '2 hours'
                WHERE kind='lease' AND holder=%s AND result_id=%s RETURNING holder""",(lease_id,result_id)).fetchone()
            if not row:raise snapshots.SnapshotOperationError('Evidence lease expired or does not match')
        else:
            if db.execute("SELECT count(*) n FROM comparison_result_reference WHERE kind='lease'").fetchone()['n']>=MAX_RETAINED:
                raise snapshots.SnapshotOperationError('Selected evidence lease capacity reached')
            lease_id=uuid4().hex
            db.execute("""INSERT INTO comparison_result_reference (kind,holder,result_id,expires_at)
                VALUES('lease',%s,%s,now()+interval '2 hours')""",(lease_id,result_id))
    return dict(result_id=result_id,lease_id=lease_id,lease_seconds=7200,provider_requests=0)


def retire_legacy(db):
    """Retire replaced working projections; immutable evidence/leases stay owned.

    These are rebuildable outputs of LatestBoardOwner, whose loops this owner
    replaces. Keeping both sets silently spends the bounded publication budget
    twice. No source, settings, journal, snapshot review or accounting row changes.
    """
    # Kept for historical replay fixtures. Installed startup does not call it.
    from .latest_board import LOCK
    with db.transaction():
        for key in (LOCK,LOCK+1):
            if not db.execute('SELECT pg_try_advisory_xact_lock(%s) held',(key,)).fetchone()['held']:
                raise snapshots.SnapshotOperationError('Legacy board owner still running')
        if db.execute('SELECT EXISTS(SELECT 1 FROM latest_board) present').fetchone()['present']:
            db.execute('''TRUNCATE latest_board,latest_board_status,latest_dashboard,
                current_grid_projection,current_result_unit,current_result_parent_original,
                current_result_inventory,current_result_work''')
        # Existing packet-lifetime triggers and cleanup retain exact leased
        # Originals independently of the working rows, including the grace period.
