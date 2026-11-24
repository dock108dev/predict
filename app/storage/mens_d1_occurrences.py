"""Reconcile dated occurrences without changing source, task or checkpoint records."""
from collections import Counter, defaultdict
from datetime import timedelta, timezone

from app.normalization.mens_d1_membership import load_membership
from app.research import experiment
from . import mens_d1_coverage as coverage
from .store import hashed, stamp

VERSION = 'mens-d1-occurrence-ledger-1'


def _day(value):
    return stamp(value).astimezone(coverage.EASTERN).date()


def _normalized_clock(value):
    return coverage.clock(stamp(value).astimezone(timezone.utc)) if value else None


def _team_identity(team):
    membership = team.get('membership') or {}
    if membership.get('division') == 'non_d1':
        return membership.get('membership_record_id')
    return team.get('canonical_id') or membership.get('canonical_id')


def _pair(teams):
    identities = {_team_identity(team) for team in teams}
    return frozenset(identities) if len(identities) == 2 and None not in identities else None


def _sources(db, day, at):
    # Neighbor evidence is needed only for a proven Eastern-date disagreement.
    # All of the selected day's source records stay in the ledger.
    revisions = db.execute("""SELECT * FROM public.mens_d1_revision WHERE source=ANY(%s)
        AND game_date BETWEEN %s AND %s AND observed_at<=%s AND recorded_at<=%s
        ORDER BY observed_at DESC,immutable_sequence DESC""",
        ([coverage.SOURCE, coverage.PUBLIC_SOURCE], day - timedelta(days=1), day + timedelta(days=1),
         at, at)).fetchall()
    official = coverage._official_corroborations(db, [row for row in revisions if row['kind'] == 'schedule'], at)
    groups, schedules = defaultdict(list), defaultdict(list)
    for revision in revisions:
        publisher, kind, date = revision['source'], revision['kind'], revision['game_date']
        if kind == 'schedule':
            schedules[publisher, date].append(revision)
        for row in revision['facts']:
            groups[publisher, row['source_game_id']].append((revision, row))
    return groups, schedules, official


def _official_for(records, official):
    # The original import binds a source ID to a schedule receipt. Reuse the
    # citation only while the latest retained participants still corroborate it.
    source, row = records[0]
    related_revisions = {record[0]['id'] for record in records}
    original_teams = {_team_identity(team) for team in row['teams']} - {None}
    return [item for item in official.get(row['source_game_id'], [])
            if item['schedule_revision_id'] in related_revisions and original_teams
            and original_teams <= {_team_identity(team) for team in item['teams']}
            and source['source'] == coverage.PUBLIC_SOURCE]


def _provider_schedule_history(db, provider_ids, at):
    rows = list(db.execute("""SELECT r.id,r.recorded_at,g.source_event_id FROM public.ev_experiment_game g
        JOIN public.ev_experiment_record r ON r.game_id=g.id AND r.kind='schedule'
        WHERE g.provider='sportsgameodds' AND g.source_event_id=ANY(%s) AND r.recorded_at<=%s
        ORDER BY r.recorded_at,r.id""", (list(provider_ids), at)))
    index = experiment._closure(db, [row['id'] for row in rows])
    history = defaultdict(list)
    for row in rows:
        value = experiment._value(index[row['id']], index)
        event = value.get('event') or {}
        if not event.get('starts_at'):
            continue
        revised = coverage.clock(row['recorded_at'])
        observed = event.get('source_metadata_received_at') or value.get('observed_at')
        series = history[row['source_event_id']]
        starts_at = event['starts_at']
        status = event.get('status') or {}
        previous = series[-1] if series else None
        change = ('added' if previous is None else
                  'rescheduled' if stamp(previous['starts_at']) != stamp(starts_at) else
                  'cancelled' if status.get('cancelled') and not previous['status'].get('cancelled') else
                  'status_changed' if previous['status'] != status else 'metadata_revised')
        series.append(dict(id=row['id'], starts_at=starts_at, eastern_game_date=str(_day(starts_at)), change=change,
            recorded_at=revised, observed_at=observed, home=event.get('home'), away=event.get('away'),
            status=status, receipt_sha256=event.get('source_metadata_receipt_sha256'),
            original_starts_at=event.get('source_start') or starts_at))
    return history


def _source_record(revision, row):
    record = coverage._schedule_game(revision, row)
    schedule = record['schedule']
    start = schedule['starts_at']
    return dict(record, **coverage._reference(revision, row), gender_evidence=row.get('gender_evidence'),
                starts_at=_normalized_clock(start), source_date=schedule['source_date'],
                source_time=schedule['source_time'], source_timezone=schedule['source_timezone'],
                eastern_game_date=str(_day(start)) if start else None, status=schedule['status'],
                revision_eastern_date=str(revision['game_date']), detail_reason=row.get('detail_reason'),
                overtime_periods=row.get('overtime_periods'))


def _source_occurrences(db, day, at, providers):
    groups, schedules, official = _sources(db, day, at)
    changes = {key: coverage._schedule_changes(series) for key, series in schedules.items()}
    candidates_by_pair = defaultdict(list)
    for key, provider in providers.items():
        pair = _pair(provider['teams'])
        if pair:
            candidates_by_pair[pair].append(key)
    games = []
    for (source, identity), records in groups.items():
        revisions_today = [item for item in records if item[0]['game_date'] == day]
        citations = _official_for(records, official)
        neighbor_link = any(item.get('scheduled_start') and _day(item['scheduled_start']) == day and
                            any(stamp(providers[key]['starts_at']) == stamp(item['scheduled_start'])
                                for key in candidates_by_pair[_pair(item['teams'])]) for item in citations)
        if not revisions_today and not neighbor_link:
            continue
        relevant = revisions_today or records
        newest, source_row = next((item for item in relevant if item[0]['kind'] == 'schedule'), relevant[0])
        key = source, newest['game_date']
        series = schedules[key]
        # A newer revision of this publisher can remove a row without erasing its clocks.
        removed = bool(revisions_today and newest['kind'] == 'schedule' and newest['id'] != series[0]['id'])
        game = coverage._schedule_game(newest, source_row, removed=removed)
        records = [_source_record(revision, row) for revision, row in records]
        game.update(occurrence_id=f'source:{identity}', source_records=records,
                    official_source_evidence=citations, source_day_observed=bool(revisions_today),
                    schedule_changes=changes.get(key, {}).get(identity, []),
                    result_only=newest['kind'] != 'schedule')
        if game['scope_state'] == 'unresolved' and game['gender'] == 'men':
            witnesses = {_pair(item['teams']) for item in citations
                         if all(team['membership']['division'] == 'd1' for team in item['teams'])}
            if len(witnesses) == 1 and None not in witnesses:
                proof = next(item for item in reversed(citations) if _pair(item['teams']) in witnesses)
                game.update(teams=proof['teams'], scope_state='eligible',
                            scope_reason='both_participants_verified_by_official_occurrence_evidence')
        pair = _pair(game['teams'])
        game['candidate_provider_ids'] = _candidates(game, candidates_by_pair[pair] if pair else [],
                                                      providers, day, source_row['membership_status'])
        games.append(game)
    return _merge_placeholders(games)


def _candidates(game, identities, providers, day, original_scope):
    schedule = game['schedule']
    start = schedule['starts_at']
    if game['gender'] != 'men' or game['scope_reason'] == 'superseded_source_placeholder':
        return []
    official_starts = {stamp(item['scheduled_start']) for item in game['official_source_evidence']
                       if item.get('scheduled_start')}
    exact = set(official_starts)
    if start:
        exact.add(stamp(start))
    matches = [key for key in identities if stamp(providers[key]['starts_at']) in exact]
    if len(matches) == 1:
        return matches
    # A unique same-date eligible pair can identify the occurrence while its
    # clocks disagree. We do not use this rule to pair excluded or TBD rows.
    if matches or game['scope_state'] != 'eligible' or original_scope == 'unresolved':
        return matches
    return [key for key in identities if _day(providers[key]['starts_at']) == day]


def _merge_placeholders(games):
    concrete = defaultdict(list)
    for game in games:
        if game['scope_state'] == 'eligible' and game['schedule']['starts_at'] and _pair(game['teams']):
            concrete[game['schedule']['source'], _pair(game['teams'])].append(game)
    retained = []
    for game in games:
        confirmed = concrete[game['schedule']['source'], _pair(game['teams'])]
        if game['scope_reason'] == 'superseded_source_placeholder' and len(confirmed) == 1:
            confirmed[0]['source_records'].extend(game['source_records'])
            confirmed[0]['schedule_changes'].extend(game['schedule_changes'])
        else:
            retained.append(game)
    return retained


def _deduplicate_source_groups(games):
    """Allow independently named publishers to corroborate one exact retained occurrence."""
    by_provider = defaultdict(list)
    for game in games:
        ids = game['candidate_provider_ids']
        if len(ids) == 1:
            by_provider[ids[0]].append(game)
    merged = set()
    for rows in by_provider.values():
        if len(rows) != 2:
            continue
        primary, other = sorted(rows, key=lambda row: row['schedule']['recorded_at'], reverse=True)
        schedule = primary['schedule']
        if (schedule['source'] != other['schedule']['source'] and schedule['starts_at']
                and other['schedule']['starts_at'] and stamp(schedule['starts_at']) == stamp(other['schedule']['starts_at'])):
            primary['source_records'].extend(other['source_records'])
            primary['official_source_evidence'].extend(other['official_source_evidence'])
            primary['schedule_changes'].extend(other['schedule_changes'])
            merged.add(other['occurrence_id'])
    return [row for row in games if row['occurrence_id'] not in merged]


def _clock_evidence(game, provider):
    source = game.get('schedule') or {}
    clocks = []
    if source:
        clocks.append(dict(origin='source', id=source['id'], source=source['source'], observed_at=source['observed_at'],
            recorded_at=source['recorded_at'], starts_at=source['starts_at'], original_time=source['source_time'],
            original_timezone=source['source_timezone'], source_date=source['source_date'],
            eastern_game_date=str(_day(source['starts_at'])) if source['starts_at'] else None))
    if provider:
        start = provider['starts_at']
        clocks.append(dict(origin='provider', id=provider.get('schedule_id'), source='sportsgameodds',
            observed_at=provider.get('observed_at'), starts_at=start, original_time=start,
            original_timezone='offset carried by retained provider clock', eastern_game_date=str(_day(start))))
    for item in game.get('official_source_evidence', []):
        if start := item.get('scheduled_start'):
            clocks.append(dict(origin='official', id=item['id'], source=item['publisher'], source_url=item['source_url'],
                observed_at=item['observed_at'], recorded_at=item['recorded_at'], starts_at=start,
                original_time=start, original_timezone='offset carried by official clock', eastern_game_date=str(_day(start))))
    return clocks


def _schedule(game, provider, day):
    evidence = _clock_evidence(game, provider)
    starts = {stamp(item['starts_at']) for item in evidence if item['starts_at']}
    official_starts = {stamp(item['starts_at']) for item in evidence if item['origin'] == 'official'}
    dates = {_day(start) for start in starts}
    start = None
    if len(starts) == 1:
        start, = starts
        state = 'agrees' if sum(bool(item['starts_at']) for item in evidence) > 1 else 'observed'
    elif len(official_starts) == 1 and provider and stamp(provider['starts_at']) in official_starts:
        start, = official_starts
        state = 'official_provider_clock_corroborated'
    elif starts:
        state = 'date_disputed' if len(dates) > 1 else 'start_disputed'
    else:
        state = 'start_unverified'
    source = game.get('schedule') or {}
    eastern_day = (_day(start) if start else next(iter(dates)) if len(dates) == 1 else
                   coverage.source_date(source['source_date']) if not dates and source.get('source_date') else None)
    status = 'source_removed_provider_retained' if provider and game.get('removed') else source.get('status')
    if provider and (provider.get('status') or {}).get('cancelled'):
        status = 'cancelled'
    return dict(state=state, starts_at=_normalized_clock(start), eastern_game_date=str(eastern_day) if eastern_day else None,
                evidence=evidence, day_applicability=('disputed' if eastern_day is None else
                    'on_date' if eastern_day == day else 'other_date'), status=status)


def _durable_clock(item):
    clocks = [stamp(value) for name in ('observed_at', 'recorded_at') if (value := item.get(name))]
    return max(clocks, default=None)


def _known_at(start, evidence):
    if start is None:
        return None
    ready_since = None
    for entry in evidence:
        if not entry.get('starts_at') or stamp(entry['starts_at']) != stamp(start):
            ready_since = None
        else:
            observed = _durable_clock(entry)
            if observed is not None and (ready_since is None or observed < ready_since):
                ready_since = observed
    return ready_since


def _observation(game, provider, schedule, provider_history):
    records = [row for row in game.get('source_records', []) if row['scope_reason'] != 'superseded_source_placeholder']
    source_schedules = [row['schedule'] for row in reversed(records)
                        if row['kind'] == 'schedule' and row['source_game_id'] == game['source_game_id']]
    source_start = (game.get('schedule') or {}).get('starts_at')
    first_source = min((stamp(row['observed_at']) for row in records), default=None)
    source_known = _known_at(source_start, source_schedules)
    pair = _pair(game['teams'])
    verified_schedules = [dict(row['schedule'], starts_at=row['schedule']['starts_at'] if _pair(row['teams']) == pair else None)
                          for row in reversed(records) if row['kind'] == 'schedule'
                          and row['source_game_id'] == game['source_game_id']]
    source_identity_known = _known_at(source_start, verified_schedules) if pair else None
    provider_start = provider['starts_at'] if provider else None
    provider_first = (provider.get('first_observed_at') or provider.get('observed_at')) if provider else None
    provider_known = _known_at(provider_start, provider_history)
    if provider and provider_known is None:
        provider_known = stamp(provider['observed_at']) if provider.get('observed_at') else None
    official = []
    for item in game.get('official_source_evidence', []):
        if item.get('scheduled_start') and schedule['starts_at'] and stamp(item['scheduled_start']) == stamp(schedule['starts_at']):
            official.append(_durable_clock(item))
    official_known = min((value for value in official if value is not None), default=None)

    def in_time(known, start):
        return known < stamp(start) - timedelta(minutes=10) if known and start else None

    source_in_time = in_time(source_known, source_start)
    verified_source_in_time = in_time(source_identity_known, source_start)
    provider_in_time = in_time(provider_known, provider_start)
    official_in_time = in_time(official_known, schedule['starts_at'])
    observed = [value for value in (verified_source_in_time, provider_in_time, official_in_time) if value is not None]
    known = any(observed) if observed and (provider_start or schedule['starts_at']) else None
    return dict(first_source_observed_at=coverage.clock(first_source), first_provider_observed_at=provider_first,
                first_observed_at=coverage.clock(min((stamp(value) for value in (first_source, provider_first)
                    if value), default=None)), source_clock_known_at=coverage.clock(source_known),
                source_identity_known_at=coverage.clock(source_identity_known),
                provider_clock_known_at=coverage.clock(provider_known), official_clock_known_at=coverage.clock(official_known),
                known_before_tminus10=known, source_known_before_tminus10=source_in_time,
                source_identity_known_before_tminus10=verified_source_in_time,
                provider_known_before_tminus10=provider_in_time, official_known_before_tminus10=official_in_time)


def _result(game, provider, schedule, at):
    head = {}
    for row in game.get('source_records', []):
        if row['source_game_id'] == game['source_game_id']:
            head.setdefault((row['source'], row['kind']), row)
    source_finals = []
    for (source, kind), row in head.items():
        if kind == 'schedule' and (source, 'results') in head:
            continue
        entry = dict(row['schedule'], source_game_id=row['source_game_id'], teams=row['teams'],
                     overtime_periods=row['overtime_periods'])
        if entry['status'] == 'final':
            source_finals.append(entry)
    official_finals = [item for item in game.get('official_source_evidence', []) if item['status'] == 'final']
    provider_results = provider.get('provider_results', []) if provider else []
    comparisons = []
    for item in [*official_finals, *source_finals, *provider_results[:1]]:
        scores = {_team_identity(team): str(team['score']) for team in item['teams'] if team.get('score') is not None}
        if item['status'] == 'final' and len(scores) == 2 and None not in scores:
            comparisons.append((item, scores))
    revisions = dict(result_revisions=source_finals, provider_results=provider_results)
    if comparisons:
        picked, scores = comparisons[0]
        disputed = any(other != scores for _, other in comparisons[1:])
        publishers = {item.get('publisher') or item['source'] for item, _ in comparisons}
        return dict(revisions, result=picked, result_state='conflicting' if disputed else 'final',
            result_reason='retained_scores_disagree' if disputed else 'independent_final_scores_agree'
                if len(publishers) > 1 else 'one_final_score_witness_retained')
    status = schedule['status']
    if status in ('removed', 'cancelled', 'postponed'):
        state, reason = status, 'retained_schedule_' + status
    elif any(stamp(item['starts_at']) > at for item in schedule['evidence'] if item.get('starts_at')) or (
            schedule['eastern_game_date'] is not None and schedule['eastern_game_date'] >= str(_day(at))):
        state, reason = 'pending', 'final_not_yet_observed'
    else:
        state, reason = 'unresolved', 'confirmed_final_score_missing'
    return dict(revisions, result=None, result_state=state, result_reason=reason)


def _apply_evidence(game, provider, day, at, history):
    row = dict(game)
    schedule = _schedule(row, provider, day)
    observation = _observation(row, provider, schedule, history)
    source, candidate_ids = row.get('schedule'), row.pop('candidate_provider_ids', [])
    if source and provider:
        source_start = source['starts_at']
        market = provider['market_observed']
        if schedule['state'] == 'official_provider_clock_corroborated':
            state, reason = 'schedule_conflict', 'official_provider_scheduled_start_agrees_source_clock_differs'
        elif schedule['state'] in ('date_disputed', 'start_disputed'):
            state, reason = 'schedule_conflict', 'same_occurrence_retained_clocks_disagree'
        elif (source_start and stamp(source_start) == stamp(provider['starts_at'])
              and row['scope_state'] == 'eligible'):
            state, reason, _ = coverage._match(row, {provider['provider_event_id']: provider})
        elif source_start or schedule['starts_at']:
            state, reason = ('matched' if market else 'no_market'), (
                'retained_provider_and_official_start_agree' if not source_start else
                'retained_participants_and_start_agree')
        else:
            state, reason = 'schedule_conflict', 'source_start_unverified'
        if row['removed']:
            state, reason = 'provider_only', 'source_removed_same_occurrence_provider_still_retained'
            row.update(scope_state=provider['retained_scope']['state'], scope_reason=provider['retained_scope']['reason'])
        elif row['scope_state'] == 'excluded':
            reason = 'excluded_occurrence_linked_by_verified_participants_and_start'
    elif source:
        if candidate_ids:
            state, reason = 'identity_conflict', 'multiple_retained_occurrence_candidates'
        elif row['scope_state'] != 'eligible':
            state, reason = row['scope_state'], row['scope_reason']
        else:
            state, reason = 'source_only', 'no_linked_retained_provider_occurrence'
    else:
        state, reason = 'provider_only', 'retained_provider_occurrence_missing_from_dated_source'
    if provider:
        row.update(provider_event_id=provider['provider_event_id'], retained_scope=provider['retained_scope'],
                   title=provider['title'], starts_at=_normalized_clock(provider['starts_at']),
                   provider_evidence=dict(provider, eastern_game_date=str(_day(provider['starts_at'])),
                                          schedule_revisions=history))
    else:
        row.update(provider_event_id=None, provider_evidence=None,
                   title=' · '.join(team['name'] for team in row['teams']), starts_at=schedule['starts_at'])
    row.update(match_state=state, match_reason=reason, occurrence_schedule=schedule,
        provider_candidate_ids=candidate_ids, observation=observation,
        day_applicability=schedule['day_applicability'], eastern_game_date=schedule['eastern_game_date'],
        known_before_tminus10=observation['source_known_before_tminus10'],
        first_source_observed_at=observation['first_source_observed_at'])
    row['paper_eligible'] = (row['scope_state'] == 'eligible' and row['day_applicability'] == 'on_date'
                             and schedule['status'] not in ('removed', 'cancelled', 'postponed'))
    row.update(_result(row, provider, schedule, at))
    return row


def occurrence_ledger(db, day, at, providers, *, include_history=True):
    source_games = _deduplicate_source_groups(_source_occurrences(db, day, at, providers))
    candidate_count = Counter(row['candidate_provider_ids'][0] for row in source_games
                              if len(row['candidate_provider_ids']) == 1)
    provider_history = _provider_schedule_history(db, providers, at) if include_history else {}
    used, ledger = set(), []
    for row in source_games:
        ids = row['candidate_provider_ids']
        row['provider_candidates'] = [dict(provider_event_id=key, starts_at=providers[key]['starts_at'],
            observed_at=providers[key]['observed_at'], home=providers[key]['home'], away=providers[key]['away'],
            receipt_sha256=providers[key].get('receipt_sha256')) for key in ids]
        identity = ids[0] if len(ids) == 1 and candidate_count[ids[0]] == 1 else None
        if identity:
            used.add(identity)
        ledger.append(_apply_evidence(row, providers.get(identity), day, at, provider_history.get(identity, [])))
    for identity, provider in providers.items():
        if identity in used or _day(provider['starts_at']) != day:
            continue
        scope = provider['retained_scope']
        ledger.append(_apply_evidence(dict(occurrence_id=f'provider:{identity}', teams=provider['teams'],
            scope_state=scope['state'], scope_reason=scope['reason'], gender='men',
            membership_version=scope['membership_version'], source_records=[], official_source_evidence=[],
            schedule_changes=[]), provider, day, at, provider_history.get(identity, [])))
    return sorted(ledger, key=lambda row: (row['starts_at'] or '~', row['occurrence_id']))


def reconciled_population(db, day, at, providers):
    rows = occurrence_ledger(db, day, at, providers, include_history=False)
    fields = ('occurrence_id', 'source_game_id', 'provider_event_id', 'title', 'starts_at', 'scope_state',
              'scope_reason', 'eastern_game_date', 'day_applicability', 'paper_eligible', 'match_state')
    games, observations = [], []
    for row in rows:
        game = {key: row.get(key) for key in fields}
        game['teams'] = [{key: val for key, val in team.items() if key in ('id', 'name', 'canonical_id', 'membership')}
                         for team in row['teams']]
        game['official_evidence_ids'] = sorted({item['id'] for item in row.get('official_source_evidence', [])})
        observations.extend(item['observed_at'] for item in row['official_source_evidence'])
        observations.extend(filter(None, (row['first_source_observed_at'],
            (row.get('provider_evidence') or {}).get('first_observed_at'))))
        starts = [(item['origin'], _normalized_clock(item['starts_at'])) for item in row['occurrence_schedule']['evidence']]
        game['schedule_clocks'] = sorted(set(starts), key=lambda item: (item[0], item[1] or ''))
        games.append(game)
    basis = dict(kind='reconciled_occurrence_ledger', source='retained_source_and_provider', date=str(day),
                 membership_version=load_membership(day).version, expected_games=None, games=games)
    observed_at = max(map(stamp, observations), default=coverage.eastern_time(day))
    return dict(basis, revision=hashed([VERSION, basis]), observed_at=coverage.clock(observed_at))
