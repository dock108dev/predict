"""UI-authored daily paper schedules and exact daily/weekly EV comparisons."""
from collections import Counter
from datetime import date, timedelta
from fractions import Fraction as F
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from app.storage import paper_result_queue as queue
from app.storage.store import encoded, hashed
from . import mens_d1, paper, paper_evidence, paper_results, records, workspace

VERSION = 'ncaab-paper-campaign-1'
QUALITY_VERSION = 'paper-quote-age-at-receipt-1'
EASTERN = ZoneInfo('America/New_York')
VARIANTS = paper_results.VARIANTS
AGE_BUCKETS = ('up_to_60', 'over_60_to_300', 'over_300', 'unknown', 'future')


def configuration(body):
    fields = {'name', 'start_date', 'end_date', 'minimum_ev', 'kelly_multiplier',
              'reference_bankroll_usd', 'bucket_edges'}
    if not isinstance(body, dict) or set(body) != fields:
        raise workspace.SelectionError('Provide dates, name, EV minimum, bankroll, Kelly fraction and bucket boundaries.')
    start, end = map(date.fromisoformat, (workspace.game_day(body['start_date']), workspace.game_day(body['end_date'])))
    if end < start:
        raise workspace.SelectionError('End date must be on or after start date.')
    if (end-start).days >= 366:
        raise workspace.SelectionError('Choose an experiment period of up to one year.')
    if not isinstance(body['name'], str) or not 1 <= len(body['name'].strip()) <= 120:
        raise workspace.SelectionError('Use an experiment name of 1–120 characters.')
    values = workspace.assumptions({k: body[k] for k in workspace.ASSUMPTIONS})
    edges = body['bucket_edges']
    if not isinstance(edges, list) or not edges or len(edges) > 12:
        raise workspace.SelectionError('Provide between one and twelve ascending EV boundaries.')
    try:
        boundaries = [F(v) for v in edges if isinstance(v, str) and len(v) <= 32]
    except (ValueError, ZeroDivisionError):
        raise workspace.SelectionError('Use numeric EV boundaries.') from None
    if (len(boundaries) != len(edges) or boundaries != sorted(set(boundaries))
            or boundaries[0] != F(values['minimum_ev']) or boundaries[-1] > 100):
        raise workspace.SelectionError('EV boundaries must increase from the selected minimum, with no gaps.')
    return dict(version=VERSION, name=body['name'].strip(), start_date=str(start), end_date=str(end),
                **values, bucket_edges=[str(v) for v in boundaries], timezone='America/New_York',
                scope=mens_d1.SCOPE, portfolios=list(VARIANTS), execution='paper_only')


def create(db, body):
    if not isinstance(body, dict):
        raise workspace.SelectionError('Provide an experiment configuration.')
    ancestor = body.get('supersedes')
    if 'supersedes' in body and (not isinstance(ancestor, str) or not workspace.HASH.fullmatch(ancestor)):
        raise workspace.SelectionError('Select the experiment to revise.')
    config = configuration({k: v for k, v in body.items() if k != 'supersedes'})
    with db.transaction():
        records._writer_lock(db)
        if ancestor:
            previous = db.execute('SELECT payload FROM public.paper_campaign WHERE id=%s', (ancestor,)).fetchone()
            if previous is None:
                raise workspace.UnknownSelection('Unknown experiment to revise.')
            prior_config = previous['payload']
            if config == {k: v for k, v in prior_config.items() if k != 'supersedes'}:
                return dict(id=ancestor, **prior_config)
            config['supersedes'] = ancestor
        identity = hashed(config)
        if db.execute('SELECT 1 FROM public.paper_campaign WHERE id=%s', (identity,)).fetchone():
            return dict(id=identity, **config)
        workspace._admit(db, len(encoded(config)))
        db.execute('INSERT INTO public.paper_campaign VALUES (%s,DEFAULT,%s,%s) ON CONFLICT DO NOTHING',
                   (identity, Jsonb(config), len(encoded(config))))
        day, end = date.fromisoformat(config['start_date']), date.fromisoformat(config['end_date'])
        while day <= end:
            db.execute('INSERT INTO public.paper_campaign_day(campaign_id,game_date) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                       (identity, day))
            day += timedelta(days=1)
    return dict(id=identity, **config)


def tick(db):
    """Publish one due dated snapshot; no network and no rewritten historical runs."""
    now = queue.utc()
    if queue._late_capture_due(db, now):
        return
    today = now.astimezone(EASTERN).date()
    lease_until = now + timedelta(minutes=15)
    with db.transaction():
        job = db.execute('''SELECT d.*,c.payload config FROM public.paper_campaign_day d
            JOIN public.paper_campaign c ON c.id=d.campaign_id
            WHERE next_check_at<=%s AND (lease_until IS NULL OR lease_until<=%s) AND game_date<=%s
            ORDER BY (game_date >= %s) DESC,next_check_at,game_date
            FOR UPDATE OF d SKIP LOCKED LIMIT 1''', (now, now, today, today-timedelta(days=2))).fetchone()
        if job is None:
            return
        key = job['campaign_id'], job['game_date']
        db.execute('UPDATE public.paper_campaign_day SET lease_until=%s WHERE campaign_id=%s AND game_date=%s',
                   (lease_until, *key))
    state, error, run_id, fingerprint = 'waiting_for_evidence', None, job['run_id'], job['fingerprint']
    try:
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            day = str(job['game_date'])
            population = mens_d1.daily_population(db, day)
            if population is not None:
                tasks = list(db.execute('''SELECT g.id,g.schedule_id,g.late_id,t.state,t.last_reason,
                    (t.state IN ('pending','claimed') AND t.deadline_at<%s) AS window_closed
                    FROM public.ev_experiment_game g JOIN public.ev_experiment_task t ON t.game_id=g.id
                    WHERE t.checkpoint='late' AND g.event->>'league'='NCAAB'
                    AND ((g.event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date=%s''', (now,day)))
                recovery = mens_d1.daily_recovery(db, day, population)
                fingerprint = hashed([population['revision'], sorted(tasks,key=lambda t:t['id']), recovery,
                    # A pending task can expire without a write.
                    today > job['game_date']])
                if fingerprint != job['fingerprint'] or not run_id:
                    parent = workspace._definition(db, workspace.PILOT_VERSION)
                    proposed = workspace._changed_definition(parent, {k:job['config'][k] for k in workspace.ASSUMPTIONS})
                    definition = mens_d1.definition(proposed, population, 'scheduled_paper_campaign', recovery=recovery)
                    definition.update(id=job['campaign_id'], title=job['config']['name'], campaign_id=job['campaign_id'])
                    definition.update(supersedes=parent['version'], template_version=parent['version'])
                    definition['question'] = f"Which men’s D1 T−10 paper opportunities qualify at {F(job['config']['minimum_ev'])*100}% minimum EV using {F(job['config']['kelly_multiplier'])*100}% of full Kelly?"
                    definition['version'] = hashed([definition['version'],job['campaign_id']])
                    report = paper.report(db, day, evidence=True, policy=definition['policy'], population=population)
                else:
                    report = None
                state = 'published'
            else:
                report = None
        with db.transaction():
            if report is not None:
                records._writer_lock(db)
            owned = db.execute('''SELECT 1 FROM public.paper_campaign_day WHERE campaign_id=%s
                AND game_date=%s AND lease_until=%s AND lease_until>%s FOR UPDATE''',
                (*key, lease_until, queue.utc())).fetchone()
            if not owned:
                return None
            if report is not None and queue._late_capture_due(db, queue.utc()):
                state, fingerprint = 'deferred_for_capture', job['fingerprint']
            elif report is not None:
                run_id = workspace._publish(db, day, parent, definition, report)['run']['id']
            _finish(db, job, lease_until, state, run_id, fingerprint, error)
    except Exception as exc:
        from app.diagnostics import failure
        failure(__name__, 'paper_campaign_day_failed', exc)
        error = type(exc).__name__ + ': ' + str(exc)[:160]
        _finish(db, job, lease_until, 'failed', job['run_id'], job['fingerprint'], error)
        return None
    return run_id


def _finish(db, job, lease_until, state, run_id, fingerprint, error):
    now = queue.utc()
    # Continue checking older days for newly retained original evidence, at a lower cadence.
    recent = job['game_date'] >= now.astimezone(EASTERN).date() - timedelta(days=2)
    interval = timedelta(minutes=15) if recent or state in ('failed', 'deferred_for_capture') else timedelta(days=1)
    db.execute('''UPDATE public.paper_campaign_day SET lease_until=NULL,next_check_at=%s,
        state=%s,last_error=%s,run_id=%s,fingerprint=%s,updated_at=%s
        WHERE campaign_id=%s AND game_date=%s AND lease_until=%s''',
        (now+interval, state, error, run_id, fingerprint, now, job['campaign_id'], job['game_date'], lease_until))


def select(tickets, minimum, variant):
    eligible = [t for t in tickets if F(t['screen_ev']) >= minimum and F(t['ev']) >= minimum]
    if variant == 'all_venues':
        return eligible
    best = {}
    for ticket in eligible:
        key = ticket['equivalent_bet_id']
        if key not in best or (-F(ticket['ev']),ticket['venue'],ticket['id']) < (-F(best[key]['ev']),best[key]['venue'],best[key]['id']):
            best[key] = ticket
    return list(best.values())


def analysis(tickets, edges, variant):
    edges = list(map(F,edges))
    selected = select(tickets, edges[0], variant)
    buckets = []
    for i, lower in enumerate(edges):
        upper = edges[i+1] if i+1<len(edges) else None
        group = [t for t in selected if F(t['screen_ev'])>=lower and (upper is None or F(t['screen_ev'])<upper)]
        buckets.append(dict(minimum=str(lower),maximum=str(upper) if upper else None,
                            summary=paper_results._summary(group)))
    thresholds = [dict(minimum=str(edge), summary=paper_results._summary(select(tickets,edge,variant))) for edge in edges]
    return dict(summary=paper_results._summary(selected), buckets=buckets, thresholds=thresholds)


def _age_bucket(age):
    if age is None:
        return 'unknown'
    if age < 0:
        return 'future'
    if age <= 60:
        return 'up_to_60'
    if age <= 300:
        return 'over_60_to_300'
    return 'over_300'


def analysis_tickets(document, report):
    source = {t['id']: t for t in document['report']['portfolios']['all_venues']['tickets']}
    witnesses = document.get('witnesses') or {}
    tickets = []
    for ticket in report['portfolios']['all_venues']['tickets']:
        original = source[ticket['id']]
        witness = witnesses.get(ticket['id'])
        calculation = workspace._sized_calculation(witness) if witness else {}
        tickets.append(dict(ticket, screen_ev=original['screen_ev'],
            target_age_bucket=_age_bucket(paper_evidence.age_at_receipt(original.get('times') or {})),
            reference_age_bucket=_age_bucket(paper_evidence.reference_age(calculation))))
    return tickets


def quality(tickets, edges, variant, *, inputs):
    selected = select(tickets, F(edges[0]), variant)
    fresh = [t for t in tickets if t['target_age_bucket'] == 'up_to_60']
    return dict(rule=QUALITY_VERSION, version=hashed([QUALITY_VERSION, inputs, edges, variant]),
        target_age_boundary_seconds=60,
        target_age_clock='Original target quote receipt minus provider book update time, inclusive from 0 to 60 seconds.',
        reference_age_clock='Oldest age across the required exact reference inputs, using each original receipt and book update time.',
        provenance={origin: analysis([t for t in tickets if t['capture_origin'] == origin], edges, variant)
                    for origin in ('frozen', 'reconstructed')},
        target_quote_age=paper_results._breakdown(selected, 'target_age_bucket', AGE_BUCKETS),
        reference_quote_age=paper_results._breakdown(selected, 'reference_age_bucket', AGE_BUCKETS),
        fresh_target_only=analysis(fresh, edges, variant))


def _window_analysis(tickets, edges, variant, *, inputs):
    result = analysis(tickets, edges, variant)
    return dict(result, quality=quality(tickets, edges, variant, inputs=inputs))


def view(db, identity, variant):
    if variant not in VARIANTS:
        raise workspace.SelectionError('Select Best venue or All qualifying venues.')
    row = db.execute('SELECT * FROM public.paper_campaign WHERE id=%s',(identity,)).fetchone()
    if not row:
        raise workspace.UnknownSelection('Unknown scheduled experiment.')
    config, days, all_tickets, versions = row['payload'], [], [], []
    history = {}
    for run in db.execute('''SELECT r.id,r.game_date,r.recorded_at FROM public.research_workspace_run r
        JOIN public.research_workspace_definition d ON r.definition_version=d.version
        WHERE d.payload->>'campaign_id'=%s ORDER BY r.recorded_at DESC,r.id''', (identity,)):
        history.setdefault(run['game_date'], []).append(dict(id=run['id'], recorded_at=run['recorded_at'].isoformat()))
    edges = config['bucket_edges']
    for day in db.execute('SELECT * FROM public.paper_campaign_day WHERE campaign_id=%s ORDER BY game_date',(identity,)):
        entry = dict(date=str(day['game_date']),run_id=day['run_id'],state=day['state'],error=day['last_error'],
                     next_check_at=day['next_check_at'].isoformat(), checked_at=day['updated_at'].isoformat(),
                     snapshots=history.get(day['game_date'], []),
                     retrospective=day['game_date'] <= row['created_at'].astimezone(EASTERN).date())
        if day['run_id']:
            state = queue.read(db,day['run_id'])
            report = (state or {}).get('report')
            entry.update(result_state=(state or {}).get('state','collecting'), result_pending=(state or {}).get('pending',True))
            document = workspace._run(db,day['run_id'])['payload']
            source = document['report']
            entry['captures'] = dict(Counter(g['status'] for g in source['games']))
            if report:
                entry['result_id'] = state['version']['id']
                usable = any(entry['captures'].get(s) for s in paper_results.CAPTURED)
                if usable and (report['status'] not in ('collecting', 'awaiting_results')
                               or report['portfolios']['all_venues']['tickets']):
                    tickets = analysis_tickets(document, report)
                    all_tickets.extend(tickets)
                    versions.append(entry['result_id'])
                    entry['analysis'] = _window_analysis(tickets, edges, variant, inputs=entry['result_id'])
                elif not usable and report['status'] == 'no_selected_tickets':
                    entry['result_state'] = 'no_usable_capture'
        days.append(entry)
    return dict(id=identity,config=config,variant=variant,days=days,
                weekly=_window_analysis(all_tickets, edges, variant, inputs=versions) if versions else None,
                reported_days=sum('analysis' in d for d in days),provider_requests=0,orders_submitted=0)


def index(db):
    return [dict(id=r['id'],**r['payload']) for r in db.execute('SELECT id,payload FROM public.paper_campaign ORDER BY created_at DESC,id')]
