"""UI-authored daily paper schedules and exact daily/weekly EV comparisons."""
from collections import Counter
from datetime import date, timedelta
from fractions import Fraction as F
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from app.storage import paper_result_queue as queue
from app.storage.store import encoded, hashed
from . import mens_d1, paper, paper_results, records, workspace

VERSION = 'ncaab-paper-campaign-1'
VARIANTS = paper_results.VARIANTS


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
    config = configuration(body)
    identity = hashed(config)
    with db.transaction():
        records._writer_lock(db)
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
    with db.transaction():
        job = db.execute('''SELECT d.*,c.payload config FROM public.paper_campaign_day d
            JOIN public.paper_campaign c ON c.id=d.campaign_id
            WHERE next_check_at<=%s AND (lease_until IS NULL OR lease_until<%s)
            AND game_date<= (%s AT TIME ZONE 'America/New_York')::date
            AND game_date>= (%s AT TIME ZONE 'America/New_York')::date-2
            ORDER BY next_check_at,game_date FOR UPDATE OF d SKIP LOCKED LIMIT 1''', (now,now,now,now)).fetchone()
        # Older backfills are also eligible until their first snapshot exists.
        if job is None:
            job = db.execute('''SELECT d.*,c.payload config FROM public.paper_campaign_day d
                JOIN public.paper_campaign c ON c.id=d.campaign_id WHERE run_id IS NULL
                AND next_check_at<=%s AND (lease_until IS NULL OR lease_until<%s)
                AND game_date<= (%s AT TIME ZONE 'America/New_York')::date
                ORDER BY game_date FOR UPDATE OF d SKIP LOCKED LIMIT 1''', (now,now,now)).fetchone()
        if job is None:
            return
        db.execute('UPDATE public.paper_campaign_day SET lease_until=%s WHERE campaign_id=%s AND game_date=%s',
                   (now+timedelta(minutes=15),job['campaign_id'],job['game_date']))
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
                fingerprint = hashed([population['revision'], sorted(tasks,key=lambda t:t['id']),
                    # A pending task can expire without a write.
                    str(now.astimezone(ZoneInfo('America/New_York')).date() > job['game_date'])])
                if fingerprint != job['fingerprint'] or not run_id:
                    parent = workspace._definition(db, workspace.PILOT_VERSION)
                    proposed = workspace._changed_definition(parent, {k:job['config'][k] for k in workspace.ASSUMPTIONS})
                    recovery = mens_d1.daily_recovery(db, day, population)
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
        if report is not None and queue._late_capture_due(db, queue.utc()):
            state, fingerprint = 'deferred_for_capture', job['fingerprint']
        elif report is not None:
            run_id = workspace._publish(db, day, parent, definition, report)['run']['id']
    except Exception as exc:
        from app.diagnostics import failure
        failure(__name__, 'paper_campaign_day_failed', exc)
        state, error = 'failed', type(exc).__name__ + ': ' + str(exc)[:160]
        fingerprint = job['fingerprint']
    with db.transaction():
        db.execute('''UPDATE public.paper_campaign_day SET lease_until=NULL,next_check_at=%s,
            state=%s,last_error=%s,run_id=%s,fingerprint=%s,updated_at=%s
            WHERE campaign_id=%s AND game_date=%s''',
            (queue.utc()+timedelta(minutes=15),state,error,run_id,fingerprint,queue.utc(),job['campaign_id'],job['game_date']))
    return run_id


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


def view(db, identity, variant):
    if variant not in VARIANTS:
        raise workspace.SelectionError('Select Best venue or All qualifying venues.')
    row = db.execute('SELECT * FROM public.paper_campaign WHERE id=%s',(identity,)).fetchone()
    if not row:
        raise workspace.UnknownSelection('Unknown scheduled experiment.')
    config, days, all_tickets = row['payload'], [], []
    for day in db.execute('SELECT * FROM public.paper_campaign_day WHERE campaign_id=%s ORDER BY game_date',(identity,)):
        entry = dict(date=str(day['game_date']),run_id=day['run_id'],state=day['state'],error=day['last_error'],
                     retrospective=day['game_date'] <= row['created_at'].astimezone(ZoneInfo('America/New_York')).date())
        if day['run_id']:
            state = queue.read(db,day['run_id'])
            report = (state or {}).get('report')
            entry.update(result_state=(state or {}).get('state','collecting'), result_pending=(state or {}).get('pending',True))
            source = workspace._run(db,day['run_id'])['payload']['report']
            entry['captures'] = dict(Counter(g['status'] for g in source['games']))
            if report:
                screen = {t['id']:t['screen_ev'] for t in source['portfolios']['all_venues']['tickets']}
                tickets = [dict(t,screen_ev=screen[t['id']]) for t in report['portfolios']['all_venues']['tickets']]
                all_tickets.extend(tickets)
                entry.update(analysis=analysis(tickets,config['bucket_edges'],variant), result_id=state['version']['id'])
        days.append(entry)
    return dict(id=identity,config=config,variant=variant,days=days,
                weekly=analysis(all_tickets,config['bucket_edges'],variant),
                reported_days=sum('analysis' in d for d in days),provider_requests=0,orders_submitted=0)


def index(db):
    return [dict(id=r['id'],**r['payload']) for r in db.execute('SELECT id,payload FROM public.paper_campaign ORDER BY created_at DESC,id')]
