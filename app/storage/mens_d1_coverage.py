"""Append-only source evidence and passive men's D1 coverage reads."""
from collections import Counter
from base64 import b64encode
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from app.normalization.college_registry import occurrence_registry
from app.normalization.mens_d1_membership import membership_for_provider_team
from .store import ROOT, encoded, hashed, stamp

SOURCE = 'sports_reference'
EASTERN = ZoneInfo('America/New_York')
SCOPE = 'mens-d1'
RECONCILIATION_VERSION = 'sports-reference-sgo-canonical-binding-1'
MAX_ROWS = 1024
MAX_PARSED_BYTES = 1024 * 1024


def utc():
    return datetime.now(timezone.utc)


def clock(value):
    return stamp(value).isoformat() if value is not None else None


def source_date(value):
    return value if type(value) is date else date.fromisoformat(value)


def eastern_time(day, hour=0, minute=0):
    return datetime.combine(day, time(hour, minute), tzinfo=EASTERN)


def retain(db, job, attempt, receipt, *, rows, parser_version, membership_version, error=None):
    """Retain transport evidence even when source or parser validation failed."""
    from app.collection.mens_d1_source import MAX_FIRECRAWL_RESPONSE_BYTES

    body = receipt.raw_body
    if (receipt.requested_url != attempt['request_url']
            or not attempt['admitted_at'] <= receipt.requested_at <= receipt.received_at
            or len(body) > MAX_FIRECRAWL_RESPONSE_BYTES):
        raise ValueError('mens_d1_invalid_receipt')
    metadata = dict(requested_url=receipt.requested_url, final_url=receipt.final_url,
                    requested_at=clock(receipt.requested_at), status_code=receipt.status_code,
                    transport_status=receipt.transport_status, parser_version=parser_version,
                    credits_used=receipt.credits_used, request_reason=attempt['request_reason'],
                    error=error or receipt.error)
    digest = sha256(body).hexdigest()
    identity = hashed(dict(attempt=attempt['id'], metadata=metadata, sha256=digest))
    db.execute("""INSERT INTO public.mens_d1_receipt(id,attempt_id,observed_at,body_sha256,body,metadata)
        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
        (identity, attempt['id'], receipt.received_at, digest, body, Jsonb(metadata)))
    if error or receipt.error:
        return identity
    if (rows is None or len(rows) > MAX_ROWS or len(encoded(rows)) > MAX_PARSED_BYTES
            or any(row['date'] != str(job['game_date']) for row in rows)
            or len({row['source_game_id'] for row in rows}) != len(rows)):
        raise ValueError('mens_d1_invalid_revision')
    rows = sorted(rows, key=lambda row: row['source_game_id'])
    revision = hashed(dict(source=job['source'], date=str(job['game_date']), kind=job['kind'],
                           parser=parser_version, membership=membership_version, rows=rows))
    row_id = hashed([identity, revision])
    db.execute("""INSERT INTO public.mens_d1_revision
        (id,source,game_date,kind,revision,receipt_id,observed_at,parser_version,membership_version,facts)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
        (row_id, job['source'], job['game_date'], job['kind'], revision, identity, receipt.received_at,
         parser_version, membership_version, Jsonb(rows)))
    return identity


def read_receipt(db, identity):
    row = db.execute("""SELECT r.*,a.game_date,a.purpose,a.source
        FROM public.mens_d1_receipt r JOIN public.mens_d1_attempt a ON a.id=r.attempt_id
        WHERE r.id=%s""", (identity,)).fetchone()
    if not row:
        raise ValueError('mens_d1_receipt_unknown')
    body = bytes(row['body'])
    if sha256(body).hexdigest() != row['body_sha256']:
        raise ValueError('mens_d1_receipt_integrity')
    try:
        response = json.loads(body)
        data = response.get('data') if isinstance(response, dict) else None
    except (UnicodeError, ValueError, RecursionError):
        data = None
    data = data if isinstance(data, dict) else {}
    try:
        original = dict(raw_body=body.decode('utf-8'))
    except UnicodeError:
        original = dict(raw_body_base64=b64encode(body).decode('ascii'))
    return dict(row['metadata'], id=row['id'], date=str(row['game_date']), source=row['source'],
        purpose=row['purpose'], observed_at=clock(row['observed_at']), recorded_at=clock(row['recorded_at']),
        body_sha256=row['body_sha256'], raw_html=data.get('rawHtml'), links=data.get('links') or [],
        **original)


def _revisions(db, day, kind, at):
    return db.execute("""SELECT * FROM public.mens_d1_revision WHERE source=%s AND game_date=%s
        AND kind=%s AND observed_at<=%s AND recorded_at<=%s
        ORDER BY observed_at DESC,immutable_sequence DESC""", (SOURCE, day, kind, at, at)).fetchall()


def schedule_revisions(db, day, *, at):
    return _revisions(db, day, 'schedule', at)


def _reference(revision, game):
    return dict(id=revision['id'], revision=revision['revision'], receipt_id=revision['receipt_id'],
                kind=revision['kind'],
                parser_version=revision['parser_version'], observed_at=clock(revision['observed_at']),
                recorded_at=clock(revision['recorded_at']), source_url=game.get('source_url'),
                published_at=game.get('published_at'))


def _team(team):
    registry = occurrence_registry()
    identity = team['source_team_id']
    membership = team.get('membership') or {}
    reviewed = membership.get('canonical_id')
    resolution = (registry.resolve('team', team['name'], league='NCAAB', venue=SOURCE,
                                   environment='public', native_id=identity)
                  if identity and membership.get('division') == 'd1' else None)
    registered = resolution.canonical_id if resolution else None
    conflicting = bool(reviewed and registered and reviewed != registered)
    identity_evidence = dict(
        reviewed_membership_id=reviewed, registered_id=registered,
        conflict='exact_alias_disagreement' if conflicting else None,
        version=resolution.registry_version if resolution else None,
        sha256=resolution.registry_sha256 if resolution else None,
        details=list(resolution.provenance) if resolution else [])
    return dict(team, id=identity, canonical_id=None if conflicting else reviewed or registered,
        identity_evidence=identity_evidence, membership_evidence=membership)


def _providers(db, day, at):
    """Use dated retained experiment events and latest pregame provider frames."""
    from app.collection.experiment_acquisition import event_metadata

    lower, upper = eastern_time(day), eastern_time(day + timedelta(days=1))
    rows = db.execute("""SELECT source_event_id,event,outcome_id,first_observed_at,
        EXISTS (SELECT 1 FROM public.ev_experiment_record checkpoint
          WHERE checkpoint.id IN (early_id,late_id) AND checkpoint.recorded_at<=%s
            AND COALESCE((checkpoint.payload#>>'{summary,coverage,received,quotes}')::int,0)>0) observed
        FROM public.ev_experiment_game WHERE provider='sportsgameodds' AND event->>'league'='NCAAB'
          AND (event->>'starts_at')::timestamptz >= %s AND (event->>'starts_at')::timestamptz < %s
          AND first_observed_at <= %s
          AND COALESCE((event->>'source_metadata_received_at')::timestamptz,first_observed_at)<=%s""",
        (at, lower, upper, at, at)).fetchall()
    providers = {}
    for row in rows:
        event = row['event']
        providers[row['source_event_id']] = dict(event, provider_event_id=row['source_event_id'],
            market_observed=row['observed'], outcome_id=row['outcome_id'],
            observed_at=event.get('source_metadata_received_at') or clock(row['first_observed_at']))
    frames = db.execute("""SELECT event_id,facts FROM public.current_sgo_event_frame
        WHERE facts#>>'{event_context,league}'='NCAAB' AND (facts->>'starts_at')::timestamptz >= %s
          AND (facts->>'starts_at')::timestamptz < %s AND (facts->>'received_at')::timestamptz<=%s""",
        (lower, upper, at)).fetchall()
    names = occurrence_registry().entities
    for row in frames:
        raw = row['facts']
        context = raw['event_context']
        event = dict(event_id=row['event_id'], starts_at=raw['starts_at'],
                     received_at=raw['received_at'], aliases=[], **context)
        if not all(context.get(key) is not None for key in ('league', 'phase', 'teams', 'status')):
            continue
        try:
            native = event_metadata(event, raw['receipt_sha256'])
        except (ValueError, KeyError):
            continue
        prior = providers.get(row['event_id'], {})
        market = bool(raw.get('members')) or bool(prior.get('market_observed'))
        if not prior or stamp(raw['received_at']) >= stamp(prior['observed_at']):
            providers[row['event_id']] = dict(native, provider_event_id=row['event_id'],
                market_observed=market, outcome_id=prior.get('outcome_id'), observed_at=raw['received_at'],
                receipt_sha256=raw['receipt_sha256'],
                teams=[dict(role=role, name=context['teams'][role]['name'],
                            id=context['teams'][role]['id'], canonical_id=native[role])
                       for role in ('away', 'home')])
    for event in providers.values():
        away, separator, home = (event.get('title') or '').partition(' at ')
        labels = {'away': away, 'home': home} if separator else {}
        event.setdefault('teams', [dict(role=role, canonical_id=event[role],
                                       name=labels.get(role) or (names.get(event[role]) or {}).get('name') or event[role])
                                  for role in ('away', 'home')])
        event['native_role_witness'] = {role: event[role] for role in ('away', 'home')}
        for team in event['teams']:
            membership = membership_for_provider_team(team['canonical_id'], day=day, label=team['name'])
            canonical = membership.get('canonical_id')
            if membership.get('reason') == 'participant_identity_disagreement':
                event[team['role']] = None
            elif canonical:
                event[team['role']] = canonical
            team.update(membership=membership, original_canonical_id=team['canonical_id'],
                        canonical_id=event[team['role']])
        divisions = {team['membership']['division'] for team in event['teams']}
        event['retained_scope'] = dict(
            state='excluded' if 'non_d1' in divisions else 'eligible' if divisions == {'d1'} else 'unresolved',
            reason=('participant_not_ncaa_division_i' if 'non_d1' in divisions else
                    'both_participants_have_season_membership' if divisions == {'d1'} else
                    'provider_participant_membership_unverified'),
            membership_version=event['teams'][0]['membership']['membership_version'])
    return providers


def _pair(teams, field):
    ids = {team.get(field) for team in teams}
    return frozenset(ids) if len(ids) == 2 and None not in ids else None


def _match(game, providers):
    if game['scope_state'] != 'eligible':
        return game['scope_state'], game['scope_reason'], []
    pair = _pair(game['teams'], 'canonical_id')
    if not pair:
        return 'identity_conflict', 'source_team_alias_not_resolved', []
    candidates = [p for p in providers.values() if pair == {p['home'], p['away']}]
    if not candidates:
        return 'source_only', 'expected_game_missing_from_retained_provider_slate', []
    start = game['schedule']['starts_at']
    exact = [p for p in candidates if start and stamp(p['starts_at']) == stamp(start)]
    if len(exact) != 1:
        state = 'identity_conflict' if len(exact) > 1 else 'schedule_conflict'
        return state, 'multiple_provider_occurrences' if len(exact) > 1 else (
            'source_start_unverified' if not start else 'provider_start_disagrees'), candidates
    provider = exact[0]
    source_home = next((team['canonical_id'] for team in game['teams'] if team.get('display_role') == 'home'), None)
    source_neutral, provider_neutral = game['schedule']['neutral_site'], provider.get('neutral_site')
    reversed_display = bool(source_home and source_home != provider['home'])
    if (source_neutral is not None and provider_neutral is not None and source_neutral != provider_neutral
            or reversed_display and source_neutral is False and provider_neutral is not True):
        return 'site_conflict', 'source_provider_home_or_neutral_site_disagrees', exact
    if game['schedule']['status'] in ('postponed', 'cancelled'):
        return 'schedule_conflict', 'source_schedule_' + game['schedule']['status'], exact
    match_reason = ('canonical_participants_and_start_agree_display_order_differs' if reversed_display else
                    'canonical_participants_and_start_agree')
    return ('matched', match_reason, exact) if provider['market_observed'] else (
        'no_market', 'provider_identity_matched_but_no_retained_market_observed', exact)


def _schedule_game(revision, row, *, removed=False):
    return dict(source_game_id=row['source_game_id'], gender=row['gender'],
        teams=[_team(team) for team in row['teams']], membership_version=row.get('membership_version'),
        scope_state='excluded' if removed else row['membership_status'],
        scope_reason='removed_from_latest_source_slate' if removed else row['membership_reason'],
        removed=removed, receipt_id=revision['receipt_id'], native_game_id=row.get('native_game_id'),
        schedule=dict(_reference(revision, row), starts_at=row.get('scheduled_start'),
            source_date=row.get('source_date'), source_time=row.get('source_time'),
            source_timezone=row.get('source_timezone'), site=row.get('site'), neutral_site=row.get('neutral_site'),
            status='removed' if removed else row['status']))


def _bindings(slate, history, providers):
    games = [_schedule_game(slate, row) for row in slate['facts']]
    known = {row['source_game_id'] for row in games}
    for revision in history:
        for row in revision['facts']:
            if row['source_game_id'] not in known:
                games.append(_schedule_game(revision, row, removed=True))
                known.add(row['source_game_id'])
    for game in games:
        state, reason, related = _match(game, providers)
        related_ids = [provider['provider_event_id'] for provider in related]
        provider_id = related_ids[0] if state in ('matched', 'no_market') else None
        game.update(match_state=state, match_reason=reason, provider_event_id=provider_id,
                    provider_candidate_ids=related_ids)
    bound = Counter(row['provider_event_id'] for row in games if row['provider_event_id'])
    for game in games:
        if bound[game['provider_event_id']] > 1:
            game.update(provider_event_id=None, match_state='identity_conflict',
                        match_reason='multiple_source_occurrences_match_same_provider_event')
    return games


def _binding_projection(games, providers):
    return [dict(source_game_id=g['source_game_id'], scope_state=g['scope_state'], scope_reason=g['scope_reason'],
        membership_version=g['membership_version'], provider_event_id=g['provider_event_id'],
        candidate_ids=sorted(g['provider_candidate_ids']),
        match_state='matched' if g['match_state'] == 'no_market' else g['match_state'],
        starts_at=g['schedule']['starts_at'], native_game_id=g['native_game_id'],
        teams=[{key: team[key] for key in ('id','name','canonical_id','membership_evidence')} for team in g['teams']],
        registry=[team['identity_evidence'] for team in g['teams']],
        provider_witness={identity: {key: providers[identity].get(key) for key in
            ('starts_at', 'home', 'away', 'neutral_site')}
            for identity in g['provider_candidate_ids']}) for g in games]


def retain_bindings(db, game_date, *, at):
    slates = schedule_revisions(db, game_date, at=at)
    if not slates:
        return None
    providers = _providers(db, game_date, at)
    facts = dict(version=RECONCILIATION_VERSION,
        games=_binding_projection(_bindings(slates[0], slates[1:], providers), providers))
    if len(encoded(facts)) > MAX_PARSED_BYTES:
        raise ValueError('mens_d1_binding_revision_too_large')
    identity = hashed([slates[0]['id'], facts])
    db.execute("""INSERT INTO public.mens_d1_binding(id,schedule_revision_id,facts)
        VALUES (%s,%s,%s) ON CONFLICT (id) DO NOTHING""", (identity, slates[0]['id'], Jsonb(facts)))
    return identity


def _population(slate, games, providers):
    bindings = _binding_projection(games, providers)
    evidence_id = hashed([slate['id'], dict(version=RECONCILIATION_VERSION, games=bindings)])
    return dict(revision=hashed([RECONCILIATION_VERSION, slate['revision'], bindings]),
        source=SOURCE, membership_version=slate['membership_version'], observed_at=clock(slate['observed_at']),
        recorded_at=clock(slate['recorded_at']), parser_version=slate['parser_version'],
        schedule_revision_id=slate['id'], schedule_receipt_id=slate['receipt_id'], evidence_id=evidence_id,
        games=bindings)


def read_population(db, game_date, *, at=None):
    day, at = source_date(game_date), at or utc()
    slates = schedule_revisions(db, day, at=at)
    if not slates:
        return None
    providers = _providers(db, day, at)
    games = _bindings(slates[0], slates[1:], providers)
    return _population(slates[0], games, providers)


def _provider_results(db, providers, *, at):
    from app.research.experiment import _closure, _value

    ids = [p['outcome_id'] for p in providers.values() if p.get('outcome_id')]
    index = _closure(db, ids)
    for provider in providers.values():
        identity = provider.pop('outcome_id', None)
        roots = []
        while identity and identity in index and len(roots) < 8:
            row = index[identity]
            item = _value(row, index)
            if row['recorded_at'] <= at:
                result = item['data']
                source = result.get('source_result', {})
                roles = {}
                for role in ('home', 'away'):
                    observed_role = source.get(role)
                    roles[role] = (provider[role] if not observed_role or
                                   observed_role == provider['native_role_witness'][role] else observed_role)
                scores = [dict(role=role, canonical_id=roles[role], score=result.get(role + '_score'))
                          for role in roles]
                roots.append(dict(id=identity, source=result['source'], status='final' if result['final'] else 'unresolved',
                    published_at=result.get('published_at'), observed_at=result.get('observed_at'),
                    recorded_at=clock(row['recorded_at']), receipt_sha256=result.get('receipt_sha256'),
                    starts_at=source.get('starts_at'), teams=scores, reason=source.get('reason')))
            identity = item.get('supersedes_id')
            if identity and identity not in index:
                index.update(_closure(db, [identity]))
        provider['provider_results'] = roots


def _result_rows(db, day, at):
    result_rows = [(revision, row) for kind in ('results', 'detail')
                   for revision in _revisions(db, day, kind, at) for row in revision['facts']]
    result_rows.sort(key=lambda item: (item[0]['observed_at'], item[0]['immutable_sequence']), reverse=True)
    seen, distinct = set(), []
    for revision, row in result_rows:
        # Retain index and detail observations independently. Older source
        # revisions remain available through the day's evidence list.
        key = revision['kind'], row['source_game_id']
        if key not in seen:
            distinct.append((revision, row))
            seen.add(key)
    return distinct


def _result_history(db, day, at):
    revisions = db.execute("""SELECT id,revision,receipt_id,kind,parser_version,observed_at,recorded_at
        FROM public.mens_d1_revision WHERE source=%s AND game_date=%s AND kind IN ('results','detail')
        AND observed_at<=%s AND recorded_at<=%s ORDER BY observed_at DESC,immutable_sequence DESC""",
        (SOURCE, day, at, at))
    return [_reference(revision, {}) for revision in revisions]


def _result(revision, row):
    return dict(_reference(revision, row), source=SOURCE, kind=revision['kind'], status=row['status'],
        source_game_id=row['source_game_id'], native_game_id=row.get('native_game_id'),
        starts_at=row.get('scheduled_start'),
        source_date=row.get('source_date'), source_time=row.get('source_time'),
        source_timezone=row.get('source_timezone'), site=row.get('site'), neutral_site=row.get('neutral_site'),
        teams=[_team(team) for team in row['teams']], overtime_periods=row.get('overtime_periods'),
        detail_url=row.get('detail_url'), detail_reason=row.get('detail_reason'))


def _score_key(teams, identity_key):
    if not _pair(teams, identity_key) or any(team.get('score') is None for team in teams):
        return None
    return {team[identity_key]: str(team['score']) for team in teams}


def _with_result(game, source_rows, providers, at):
    pair = _pair(game['teams'], 'source_team_id')
    eligible = [pairing for pairing in source_rows if pairing[1]['gender'] == game['gender']
                and (pairing[1]['source_game_id'] == game['source_game_id'] or
                     pair and pair == _pair(pairing[1]['teams'], 'source_team_id'))]
    exact = [item for item in eligible if item[1]['source_game_id'] == game['source_game_id']]
    rows = exact or eligible
    provider = providers.get(game['provider_event_id']) or {}
    provider_results = provider.get('provider_results', [])
    game.update(result=None, result_state='pending', result_reason='source_final_not_retained',
                provider_results=provider_results, result_revisions=[])
    if not rows:
        start = game['schedule']['starts_at']
        if game['schedule']['status'] in ('removed', 'postponed', 'cancelled'):
            game.update(result_state=game['schedule']['status'], result_reason='source_schedule_' + game['schedule']['status'])
        elif not start or stamp(start) <= at:
            game.update(result_state='unresolved', result_reason='source_final_not_retained')
        if provider_results:
            game['provider_sporting_evidence_retained'] = True
        return
    game['result_revisions'] = [_result(revision, row) for revision, row in rows]
    result = game['result_revisions'][0]
    game['result'] = result
    open_results = [item for item in game['result_revisions'] if item['kind'] != result['kind']]
    canonical_scores = _score_key(result['teams'], 'canonical_id')
    source_scores = _score_key(result['teams'], 'source_team_id')

    def disagree(other):
        if other['status'] != 'final':
            return False
        canonical_other = _score_key(other['teams'], 'canonical_id')
        if canonical_scores is not None and canonical_other is not None:
            return canonical_scores != canonical_other
        native_other = _score_key(other['teams'], 'source_team_id')
        return source_scores is not None and native_other is not None and source_scores != native_other

    conflicting = ((not exact and len({row['source_game_id'] for _, row in eligible}) > 1)
                   or result.get('detail_reason') == 'index_detail_score_conflict'
                   or any(disagree(other) for other in open_results))
    for other in provider_results[:1]:
        if other['status'] == 'final':
            provider_scores = _score_key(other['teams'], 'canonical_id')
            conflicting |= (
                (other['starts_at'] and game['schedule']['starts_at']
                    and stamp(other['starts_at']) != stamp(game['schedule']['starts_at']))
                or (provider_scores is not None and canonical_scores is not None
                    and provider_scores != canonical_scores))
    if conflicting:
        game.update(result_state='conflicting', result_reason='retained_sporting_evidence_disagrees')
    elif result['status'] == 'final' and (source_scores or canonical_scores):
        game.update(result_state='final', result_reason='source_final_score_retained')
    else:
        state = result['status'] if result['status'] in ('postponed', 'cancelled', 'incomplete') else 'unresolved'
        game.update(result_state=state, result_reason=result.get('detail_reason') or 'source_result_not_final')


def _source_state(db):
    return db.execute("SELECT * FROM public.mens_d1_source_state WHERE source=%s", (SOURCE,)).fetchone() or dict(
        state='disabled', reason='sports_reference_private_hosted_use_and_firecrawl_account_unverified',
        checked_at=None, budget={})


def read_coverage(db, game_date, *, at=None):
    day, at = source_date(game_date), at or utc()
    slates = schedule_revisions(db, day, at=at)
    source = _source_state(db)
    providers = _providers(db, day, at)
    _provider_results(db, providers, at=at)
    games = _bindings(slates[0], slates[1:], providers) if slates else []
    population = _population(slates[0], games, providers) if slates else None
    if population:
        saved = db.execute("SELECT id FROM public.mens_d1_binding WHERE id=%s AND recorded_at<=%s",
                           (population['evidence_id'], at)).fetchone()
        population['binding_revision_id'] = saved['id'] if saved else None
    result_rows = _result_rows(db, day, at)
    for row in games:
        _with_result(row, result_rows, providers, at)
    used = {game['provider_event_id'] for game in games if game['provider_event_id']}
    disputed = {identity for g in games for identity in g['provider_candidate_ids']} - used
    provider_only = []
    for identity, event in sorted(providers.items()):
        if identity in used:
            continue
        if identity in disputed:
            state, reason = 'provider_conflict', 'source_candidate_conflicts_with_provider_identity_or_schedule'
        elif slates:
            state, reason = 'provider_only', 'retained_provider_event_missing_from_source_slate'
        else:
            state, reason = 'provider_only', 'source_slate_unverified_provider_event_does_not_establish_eligibility'
        provider_only.append(dict(event, match_state=state, match_reason=reason,
            result_state='provider_final' if (event['provider_results'] or [{}])[0].get('status') == 'final' else 'unresolved'))
    attempt = db.execute("""SELECT r.id,r.observed_at,r.recorded_at,r.metadata FROM public.mens_d1_receipt r
        JOIN public.mens_d1_attempt a ON a.id=r.attempt_id
        WHERE a.source=%s AND a.game_date=%s AND a.purpose LIKE 'schedule_%%' AND r.recorded_at<=%s
        ORDER BY r.recorded_at DESC LIMIT 1""", (SOURCE, day, at)).fetchone()
    failed = attempt and attempt['metadata'].get('error')
    state = ('verified' if slates else 'failed' if failed else
             'disabled' if source['state'] in ('disabled', 'paused') else 'unverified')
    reason = failed or (None if slates else source['reason'] or 'valid_source_slate_not_retained')
    membership = Counter(row['scope_state'] for row in games)
    matches = Counter(row['match_state'] for row in games)
    results = Counter(row['result_state'] for row in games if row['scope_state'] == 'eligible')
    result_only = []
    used_source_result_ids = {r['source_game_id'] for g in games for r in g['result_revisions']}
    for revision, row in result_rows:
        identity = row['source_game_id']
        if identity not in used_source_result_ids:
            result_only.append(_result(revision, row))
            used_source_result_ids.add(identity)
    return dict(date=str(day), scope=SCOPE, timezone=EASTERN.key, as_of=clock(at.astimezone(EASTERN)),
        source=SOURCE, source_state=state, source_state_reason=reason, population=population,
        population_revision=population['revision'] if population else None,
        membership_version=population['membership_version'] if population else None,
        games=games, provider_only=provider_only, result_only=result_only,
        source_observed_at=population['observed_at'] if population else None,
        source_receipt_id=slates[0]['receipt_id'] if slates else None,
        source_revisions=[_reference(revision, {}) for revision in slates],
        result_source_revisions=_result_history(db, day, at),
        last_source_attempt=dict(attempt, observed_at=clock(attempt['observed_at']),
            recorded_at=clock(attempt['recorded_at'])) if attempt else None,
        counts=dict(source_rows=len(slates[0]['facts']) if slates else None,
            source_returned_mens_games=sum(row['gender'] in ('men', 'mens', 'male') for row in slates[0]['facts'])
                if slates else None,
            expected=membership['eligible'] if slates else None,
            excluded=membership['excluded'] if slates else None,
            unresolved_membership=membership['unresolved'] if slates else None,
            provider_matches=matches['matched'] + matches['no_market'] if slates else None,
            provider_only=len(provider_only), matches=dict(matches), results=dict(results)),
        provider_requests=0)


def read_status(db, *, at=None):
    from app.collection.current_storage_policy import SQL_BYTE_CAP, disk_capacity, sql_usage
    from app.research.records import TOTAL_BYTE_CAP, retention_usage

    at = at or utc()
    day = at.astimezone(EASTERN).date()
    source = _source_state(db)
    jobs = list(db.execute("""SELECT source,game_date,purpose,kind,due_at,expires_at,next_attempt_at,state,
        attempts,last_attempt_at,last_success_at,last_reason FROM public.mens_d1_job
        WHERE source=%s AND game_date BETWEEN %s AND %s ORDER BY due_at,purpose""",
        (SOURCE, day - timedelta(days=2), day + timedelta(days=1))))
    usage = retention_usage(db)
    storage = dict(allocation_bytes=TOTAL_BYTE_CAP, retained_bytes=int(usage['total']),
        reserved_bytes=int(usage['reserved']), source_bytes=usage.get('daily_coverage_bytes', 0),
        source_reserved_bytes=usage.get('daily_coverage_reserved_bytes', 0),
        headroom_bytes=max(0, TOTAL_BYTE_CAP - usage['total'] - usage['reserved']),
        sql_bytes=sql_usage(db), sql_cap_bytes=SQL_BYTE_CAP, disk=disk_capacity(ROOT / '.local/postgres'))
    planned = sum(row['state'] == 'pending' and row['expires_at'] > at
                  and row['next_attempt_at'] <= at + timedelta(days=1) for row in jobs)
    from app.collection.mens_d1_source import DOCUMENTED_BASIC_SCRAPE_CREDITS, MAX_FIRECRAWL_RESPONSE_BYTES
    from app.collection.mens_d1_jobs import MAX_STORAGE_RESERVATION
    capture = db.execute("""SELECT count(*) AS all_sports,
        count(*) FILTER (WHERE game.event->>'league'='NCAAB') AS college_basketball
        FROM public.ev_experiment_task task JOIN public.ev_experiment_game game ON task.game_id=game.id
        WHERE task.checkpoint='late' AND task.state IN ('pending','claimed')
         AND task.deadline_at>=%s AND task.target_at<=%s""", (at, at + timedelta(days=1))).fetchone()
    forecast = dict(next_24h_pending_jobs=planned, planned_basic_credits=planned * DOCUMENTED_BASIC_SCRAPE_CREDITS,
                    maximum_response_bytes=planned * MAX_FIRECRAWL_RESPONSE_BYTES,
                    one_request_storage_reservation_bytes=MAX_STORAGE_RESERVATION,
                    next_24h_late_tasks=capture['all_sports'], next_24h_cbb_late_tasks=capture['college_basketball'],
                    excludes_additional_retries_and_future_detail_jobs=True)
    totals = db.execute("""SELECT count(*) FILTER(WHERE disposition='dispatched') AS requests,
        count(*) FILTER(WHERE disposition IN ('reserved','unknown')) AS unconfirmed_dispatches,
        COALESCE(sum(charged_credits),0) AS charged,
        COALESCE(sum(reserved_credits) FILTER(WHERE charged_credits IS NULL),0) AS held
        FROM public.mens_d1_attempt WHERE source=%s""", (SOURCE,)).fetchone()
    next_run = min((row['next_attempt_at'] for row in jobs if row['state'] == 'pending'
                    and row['expires_at'] > at), default=None)
    last_success = max((row['last_success_at'] for row in jobs if row['last_success_at']), default=None)
    return dict(source=SOURCE, state=source['state'], reason=source['reason'], checked_at=clock(source['checked_at']),
        next_run_at=clock(next_run), last_success_at=clock(last_success),
        jobs=[{k: str(v) if type(v) is date else clock(v) if isinstance(v, datetime) else v
               for k, v in job.items()} for job in jobs],
        credits=dict(confirmed=totals['charged'], held=totals['held'], requests=totals['requests'],
                     unconfirmed_dispatches=totals['unconfirmed_dispatches'], budget=source['budget'],
                     cost_usd=0 if not (totals['charged'] or totals['held']) else None),
        storage=storage, forecast=forecast, provider_requests=0)
