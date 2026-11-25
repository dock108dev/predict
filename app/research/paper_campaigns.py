"""UI-authored daily paper schedules and exact daily/weekly comparisons."""
from bisect import bisect_right
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from fractions import Fraction as F
import re
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from app.storage import paper_result_queue as queue
from app.storage.store import encoded, hashed
from . import mens_d1, paper, paper_evidence, paper_results, records, workspace

VERSION = 'ncaab-paper-campaign-1'
SIZING_VERSION = 'ncaab-paper-campaign-2'
QUALITY_VERSION = 'paper-quote-age-at-receipt-1'
REPLAY_FAILED = 'paper_campaign_replay_failed'
WIN_10_CAMPAIGN = '521543a8363cd0a945e792726e387a23b2003e743fe7364945cd2ebfb5d65864'
EASTERN = ZoneInfo('America/New_York')
VARIANTS = paper_results.VARIANTS
MODES = ('fixed_profit', 'kelly')
AGE_BUCKETS = ('up_to_60', 'over_60_to_300', 'over_300', 'unknown', 'future')
DEFAULT_ODDS_EDGES = ('200', '300', '500', '1000')


def _odds_edges(value):
    invalid = 'Use one to twelve increasing whole-number odds boundaries above +100.'
    if not isinstance(value, list) or not 1 <= len(value) <= 12 or any(
        not isinstance(edge, str) or not re.fullmatch(r'\+?[0-9]{1,9}', edge) for edge in value
    ):
        raise workspace.SelectionError(invalid)
    edges = list(map(int, value))
    if edges[0] <= 100 or edges != sorted(set(edges)):
        raise workspace.SelectionError(invalid)
    return tuple(map(str, edges))


def configuration(body):
    if not isinstance(body, dict):
        raise workspace.SelectionError('Provide an experiment configuration.')
    fields = {'name', 'start_date', 'end_date', 'minimum_ev', 'bucket_edges'}
    kelly_fields = {'kelly_multiplier', 'reference_bankroll_usd'}
    legacy = set(body) == fields | kelly_fields
    sizing = {}
    portfolios = list(VARIANTS)
    if not legacy:
        mode = body.get('sizing_mode')
        if mode not in MODES or body.get('scope') != mens_d1.SCOPE:
            raise workspace.SelectionError('Choose a supported experiment scope and sizing mode.')
        fields |= {'sizing_mode', 'scope', 'portfolios'}
        selected = body.get('portfolios')
        if (not isinstance(selected, list) or not selected or any(v not in VARIANTS for v in selected)
                or len(selected) != len(set(selected))):
            raise workspace.SelectionError('Choose one or both supported venue portfolios.')
        portfolios = [v for v in VARIANTS if v in selected]
        sizing['sizing_mode'] = mode
        if 'portfolio_rule' in body:
            fields.add('portfolio_rule')
            if body['portfolio_rule'] != paper.MAIN_FIRST_ONE_PER_GAME or portfolios != ['best_venue']:
                raise workspace.SelectionError('Choose Best venue for the one-bet-per-game rule.')
            sizing['portfolio_rule'] = body['portfolio_rule']
        if mode == 'fixed_profit':
            fields |= {'target_profit_usd', 'kelly_comparison'}
            comparison = body.get('kelly_comparison')
            if not isinstance(comparison, bool):
                raise workspace.SelectionError('Choose whether to include a Kelly comparison.')
            try:
                target = workspace.assumptions({'reference_bankroll_usd': body.get('target_profit_usd')})
            except workspace.SelectionError:
                raise workspace.SelectionError('Enter a positive fixed profit target in dollars.') from None
            sizing.update(kelly_comparison=comparison, target_profit_usd=target['reference_bankroll_usd'],
                          sizing_rule=paper.FIXED_PROFIT_RULE)
        if mode == 'kelly' or sizing.get('kelly_comparison'):
            fields |= kelly_fields
            sizing['kelly_rule'] = paper.KELLY_RULE
        if 'minimum_stake_usd' in body:
            fields.add('minimum_stake_usd')
            try:
                minimum = workspace.assumptions({'reference_bankroll_usd': body['minimum_stake_usd']})
            except workspace.SelectionError:
                raise workspace.SelectionError('Enter a positive minimum stake in dollars.') from None
            sizing['minimum_stake_usd'] = minimum['reference_bankroll_usd']
        if 'odds_bucket_edges' in body:
            fields.add('odds_bucket_edges')
            odds_edges = _odds_edges(body['odds_bucket_edges'])
            if odds_edges != DEFAULT_ODDS_EDGES:
                sizing['odds_bucket_edges'] = list(odds_edges)
        if set(body) != fields:
            raise workspace.SelectionError('Provide the dates, EV rules and inputs for the selected sizing modes.')
    start, end = map(date.fromisoformat, (workspace.game_day(body['start_date']), workspace.game_day(body['end_date'])))
    if end < start:
        raise workspace.SelectionError('End date must be on or after start date.')
    if (end-start).days >= 366:
        raise workspace.SelectionError('Choose an experiment period of up to one year.')
    if not isinstance(body['name'], str) or not 1 <= len(body['name'].strip()) <= 120:
        raise workspace.SelectionError('Use an experiment name of 1–120 characters.')
    values = workspace.assumptions({k: body[k] for k in workspace.ASSUMPTIONS if k in body})
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
    return dict(version=VERSION if legacy else SIZING_VERSION, name=body['name'].strip(),
                start_date=str(start), end_date=str(end), **values, **sizing,
                bucket_edges=[str(v) for v in boundaries], timezone='America/New_York',
                scope=mens_d1.SCOPE, portfolios=portfolios, execution='paper_only')


def modes(config):
    primary = config.get('sizing_mode', 'kelly')
    return [primary, 'kelly'] if config.get('kelly_comparison') else [primary]


def _initial_check(day, now):
    return max(now, datetime.combine(day, time.min, EASTERN))


def create(db, body, *, discoverable=True):
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
            prior = {k: v for k, v in prior_config.items() if k not in ('supersedes', 'discoverable')}
            if (config == prior or prior['version'] == VERSION
                    and config == dict(prior, version=SIZING_VERSION, sizing_mode='kelly', kelly_rule=paper.KELLY_RULE)):
                return dict(id=ancestor, **prior_config)
            config['supersedes'] = ancestor
        if discoverable:
            config['discoverable'] = True
        identity = hashed(config)
        if db.execute('SELECT 1 FROM public.paper_campaign WHERE id=%s', (identity,)).fetchone():
            return dict(id=identity, **config)
        workspace._admit(db, len(encoded(config)))
        db.execute('INSERT INTO public.paper_campaign VALUES (%s,DEFAULT,%s,%s) ON CONFLICT DO NOTHING',
                   (identity, Jsonb(config), len(encoded(config))))
        day, end = date.fromisoformat(config['start_date']), date.fromisoformat(config['end_date'])
        now = queue.utc()
        while day <= end:
            db.execute('''INSERT INTO public.paper_campaign_day(campaign_id,game_date,next_check_at)
                VALUES (%s,%s,%s) ON CONFLICT DO NOTHING''', (identity, day, _initial_check(day, now)))
            day += timedelta(days=1)
    return dict(id=identity, **config)


def _definition(parent, job, population, recovery, fingerprint, mode):
    config = job['config']
    values = {key: config[key] for key in workspace.ASSUMPTIONS if key in config}
    proposed = workspace._changed_definition(parent, values)
    definition = mens_d1.definition(proposed, population, 'scheduled_paper_campaign', recovery=recovery)
    definition.update(id=job['campaign_id'], title=config['name'], campaign_id=job['campaign_id'],
                      supersedes=parent['version'], template_version=parent['version'])
    threshold = F(config['minimum_ev']) * 100
    if mode == 'kelly':
        sizing = f"using {F(config['kelly_multiplier'])*100}% of full Kelly"
    else:
        sizing = f"targeting {paper.money(F(config['target_profit_usd']))} USD net win profit"
    definition['question'] = f'Which men’s D1 T−10 paper opportunities qualify at {threshold}% minimum EV {sizing}?'
    if config['version'] == VERSION:
        definition['version'] = hashed([definition['version'], job['campaign_id']])
        return definition
    policy = definition['policy']
    policy.update(sizing_mode=mode, portfolios=config['portfolios'])
    policy.update({key: config[key] for key in ('minimum_stake_usd', 'portfolio_rule') if key in config})
    if config.get('portfolio_rule') == paper.MAIN_FIRST_ONE_PER_GAME:
        policy['duplicates'] = 'One trade per game; retain the best qualifying venue for the ranked bet.'
    if mode == 'fixed_profit':
        for key in ('reference_bankroll_usd', 'kelly_multiplier', 'sizing_scale_usd'):
            policy.pop(key, None)
        policy.update(target_profit_usd=config['target_profit_usd'], sizing_rule=config['sizing_rule'],
                      baseline=None)
    else:
        policy['sizing_rule'] = config['kelly_rule']
    definition.update(sizing_mode=mode, campaign_snapshot=fingerprint,
                      kelly_comparison=config.get('kelly_comparison', False))
    definition['version'] = hashed([definition['version'], job['campaign_id'], fingerprint, policy])
    return definition


def tick(db):
    """Publish one due dated snapshot; no network and no rewritten historical runs."""
    now = queue.utc()
    if queue._late_capture_due(db, now):
        return
    today = now.astimezone(EASTERN).date()
    lease_until = now + timedelta(minutes=15)
    with db.transaction():
        active_ids = [campaign['id'] for campaign in index(db, active_only=True)]
        if not active_ids:
            return
        job = db.execute('''SELECT d.*,c.payload config FROM public.paper_campaign_day d
            JOIN public.paper_campaign c ON c.id=d.campaign_id
            WHERE next_check_at<=%s AND (lease_until IS NULL OR lease_until<=%s) AND game_date<=%s
              AND d.campaign_id=ANY(%s)
            ORDER BY (game_date >= %s) DESC,next_check_at,game_date
            FOR UPDATE OF d SKIP LOCKED LIMIT 1''', (now, now, today, active_ids, today-timedelta(days=2))).fetchone()
        if job is None:
            return
        key = job['campaign_id'], job['game_date']
        db.execute('UPDATE public.paper_campaign_day SET lease_until=%s WHERE campaign_id=%s AND game_date=%s',
                   (lease_until, *key))
    state, error, run_id, fingerprint = 'waiting_for_evidence', None, job['run_id'], job['fingerprint']
    replays = []
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
                    definitions = [_definition(parent, job, population, recovery, fingerprint, mode)
                                   for mode in modes(job['config'])]
                    reports = paper.scoped_reports(db, day, [definition['policy'] for definition in definitions],
                                                  population=deepcopy(population), as_of=now.isoformat(), evidence=True)
                    replays = list(zip(definitions, reports, strict=True))
                state = 'published'
        with db.transaction():
            if replays:
                records._writer_lock(db)
            owned = db.execute('''SELECT 1 FROM public.paper_campaign_day WHERE campaign_id=%s
                AND game_date=%s AND lease_until=%s AND lease_until>%s FOR UPDATE''',
                (*key, lease_until, queue.utc())).fetchone()
            if not owned:
                return None
            if replays and queue._late_capture_due(db, queue.utc()):
                state, fingerprint = 'deferred_for_capture', job['fingerprint']
            elif replays:
                run_ids = [workspace._publish(db, day, parent, definition, report, details=False)
                           for definition, report in replays]
                run_id = run_ids[0]
            _finish(db, job, lease_until, state, run_id, fingerprint, error)
    except Exception as exc:
        from app.diagnostics import failure
        failure(__name__, 'paper_campaign_day_failed', exc)
        _finish(db, job, lease_until, 'failed', job['run_id'], job['fingerprint'], REPLAY_FAILED)
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


def select(tickets, minimum, variant, portfolio_rule=None):
    eligible = [t for t in tickets if F(t['screen_ev']) >= minimum and F(t['ev']) >= minimum]
    if variant == 'all_venues' and portfolio_rule is None:
        return eligible
    return paper.best_tickets(eligible, portfolio_rule)


def _expected_roi(profit, stake):
    roi = profit / stake if stake else None
    return dict(expected_roi=str(roi) if roi is not None else None,
                expected_roi_percent=paper.money(roi * 100) if roi is not None else None)


def _selection_rows(tickets, report, variant):
    grades = {t['id']: t for t in report['portfolios'][variant]['tickets']} if report else {}
    for ticket in tickets:
        if ticket['id'] in grades:
            yield grades[ticket['id']]
            continue
        committed = F(ticket.get('cash_commitment_usd', ticket['stake_usd']))
        profit = ticket.get('expected_profit_exact_usd')
        yield dict(game_id=ticket['game_id'], posted_odds=ticket.get('posted_odds'),
                   grade=dict(state='pending'), stake_exact_usd=str(committed),
                   expected_profit_exact_usd=str(F(profit) if profit is not None else committed * F(ticket['ev'])))


def _selection_summary(tickets, odds_edges):
    stake = sum((F(t['stake_exact_usd']) for t in tickets), F())
    profit = sum((F(t['expected_profit_exact_usd']) for t in tickets), F())
    return paper_results._money(dict(tickets=len(tickets), odds_buckets=odds_buckets(tickets, odds_edges),
                                    **_expected_roi(profit, stake)), stake=stake, expected_profit=profit)


def _analysis_summary(tickets):
    summary = paper_results._summary(tickets)
    summary.update(_expected_roi(F(summary['expected_profit_exact_usd']), F(summary['stake_exact_usd'])))
    gap = (F(summary['pnl_exact_usd']) - F(summary['resolved_expected_profit_exact_usd'])
           if summary['resolved'] else None)
    return paper_results._money(summary, pnl_vs_expected=gap)


def _odds_bucket(value, boundaries):
    try:
        odds = F(str(value))
    except (ValueError, ZeroDivisionError):
        return -1
    if abs(odds) < 100:
        return -1
    if abs(odds) == 100:
        return 1
    if odds < 0:
        return 0
    return 2 + bisect_right(boundaries, odds)


def odds_buckets(tickets, edges=DEFAULT_ODDS_EDGES):
    """Partition the selected portfolio by the saved target quote's American odds."""
    boundaries = tuple(map(int, edges))
    bands = [('favorites', 'Favorites (below −100)'), ('even_money', 'Even money (±100)')]
    for low, high in zip((100, *boundaries), boundaries):
        label = 'Over +100' if low == 100 else f'+{low}'
        bands.append((f'plus_{low}_to_{high}', f'{label} to under +{high}'))
    bands.extend([(f'plus_{boundaries[-1]}_and_up', f'+{boundaries[-1]} or longer'),
                  ('unavailable', 'Unavailable odds')])
    groups = [[] for _ in bands]
    for ticket in tickets:
        groups[_odds_bucket(ticket.get('posted_odds'), boundaries)].append(ticket)
    buckets = [dict(id=key, label=label, summary=_analysis_summary(group))
               for (key, label), group in zip(bands, groups) if key != 'unavailable' or group]
    stakes = [F(bucket['summary']['stake_exact_usd']) for bucket in buckets]
    total_stake = sum(stakes, F())
    for bucket, stake in zip(buckets, stakes):
        share = stake / total_stake if total_stake else None
        bucket.update(stake_share=str(share) if share is not None else None,
                      stake_share_percent=paper.money(share * 100) if share is not None else None)
    return buckets


def analysis(tickets, edges, variant, portfolio_rule=None):
    edges = list(map(F,edges))
    selected = select(tickets, edges[0], variant, portfolio_rule)
    buckets = []
    for i, lower in enumerate(edges):
        upper = edges[i+1] if i+1<len(edges) else None
        group = [t for t in selected if F(t['screen_ev'])>=lower and (upper is None or F(t['screen_ev'])<upper)]
        buckets.append(dict(minimum=str(lower),maximum=str(upper) if upper else None,
                            summary=_analysis_summary(group)))
    thresholds = [dict(minimum=str(edge), summary=_analysis_summary(select(tickets, edge, variant, portfolio_rule)))
                  for edge in edges]
    return dict(summary=_analysis_summary(selected), buckets=buckets, thresholds=thresholds)


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
        reference_age_bucket = original.get('reference_age_bucket')
        if reference_age_bucket is None:
            witness = witnesses.get(ticket['id'])
            calculation = workspace._sized_calculation(witness) if witness else {}
            reference_age_bucket = _age_bucket(paper_evidence.reference_age(calculation))
        tickets.append(dict(ticket, screen_ev=original['screen_ev'],
            target_age_bucket=_age_bucket(paper_evidence.age_at_receipt(original.get('times') or {})),
            reference_age_bucket=reference_age_bucket))
    return tickets


def quality(tickets, edges, variant, *, inputs, portfolio_rule=None):
    selected = select(tickets, F(edges[0]), variant, portfolio_rule)
    fresh = [t for t in tickets if t['target_age_bucket'] == 'up_to_60']
    version_inputs = [QUALITY_VERSION, inputs, edges, variant]
    if portfolio_rule is not None:
        version_inputs.append(portfolio_rule)
    return dict(rule=QUALITY_VERSION, version=hashed(version_inputs),
        target_age_boundary_seconds=60,
        target_age_clock='Original target quote receipt minus provider book update time, inclusive from 0 to 60 seconds.',
        reference_age_clock='Oldest age across the required exact reference inputs, using each original receipt and book update time.',
        provenance={origin: analysis([t for t in tickets if t['capture_origin'] == origin], edges, variant, portfolio_rule)
                    for origin in ('frozen', 'reconstructed')},
        target_quote_age=paper_results._breakdown(selected, 'target_age_bucket', AGE_BUCKETS),
        reference_quote_age=paper_results._breakdown(selected, 'reference_age_bucket', AGE_BUCKETS),
        fresh_target_only=analysis(fresh, edges, variant, portfolio_rule))


def _window_analysis(tickets, edges, variant, *, inputs, portfolio_rule=None):
    result = analysis(tickets, edges, variant, portfolio_rule)
    return dict(result, quality=quality(tickets, edges, variant, inputs=inputs, portfolio_rule=portfolio_rule))


def _history(db, identity, game_date=None):
    history = {}
    for run in db.execute('''SELECT r.id,r.game_date,r.recorded_at,d.payload->>'campaign_snapshot' snapshot,
        COALESCE(d.payload->>'sizing_mode','kelly') mode FROM public.research_workspace_run r
        JOIN public.research_workspace_definition d ON r.definition_version=d.version
        WHERE d.payload->>'campaign_id'=%s AND (%s::date IS NULL OR r.game_date=%s)
        ORDER BY r.recorded_at DESC,r.id''', (identity, game_date, game_date)):
        history.setdefault(run['game_date'], []).append(run)
    return history


def _mode_runs(rows, primary_run, primary_mode):
    if not primary_run:
        return {}
    primary = next((row for row in rows if row['id'] == primary_run), None)
    if not primary or not primary['snapshot']:
        return {primary_mode: primary_run}
    return {row['mode']: row['id'] for row in rows if row['snapshot'] == primary['snapshot']}


def _snapshot_reports(db, run_ids):
    if not run_ids:
        return {}
    rows = db.execute('''SELECT r.id,r.payload#>'{report,portfolios,all_venues,tickets}' tickets,
        (SELECT jsonb_agg(jsonb_build_object('status',game->'status',
            'coverage',jsonb_build_object('incomplete',game#>'{coverage,incomplete}'),
            'sizing_exclusions',game->'sizing_exclusions')) FROM
            jsonb_array_elements(r.payload#>'{report,games}') game) games
        FROM public.research_workspace_run r WHERE r.id=ANY(%s)''', (list(run_ids),))
    return {row['id']: dict(games=row['games'] or [], portfolios=dict(all_venues=dict(tickets=row['tickets'])))
            for row in rows}


def snapshot_document(db, run_id):
    return dict(report=_snapshot_reports(db, [run_id])[run_id])


def sizing_comparison(reports, minimum, variant, *, details=False, portfolio_rule=None):
    if not all(mode in reports and any(g['status'] in paper_results.CAPTURED for g in reports[mode]['games'])
               for mode in MODES):
        return None
    pools = {mode: reports[mode]['portfolios']['all_venues']['tickets'] for mode in MODES}
    qualified = {mode: {ticket['frozen_quote_id']: ticket for ticket in pools[mode]} for mode in MODES}
    selected = {mode: {ticket['frozen_quote_id']: ticket for ticket in select(pools[mode], minimum, variant, portfolio_rule)}
                for mode in MODES}
    fixed, kelly = (qualified[mode].keys() for mode in MODES)
    fixed_selected, kelly_selected = (selected[mode].keys() for mode in MODES)
    by_bet = {mode: {ticket['equivalent_bet_id']: ticket['venue'] for ticket in selected[mode].values()}
              for mode in MODES}
    fixed_bets, kelly_bets = (by_bet[mode] for mode in MODES)
    counts = dict(jointly_qualifying_quotes=len(fixed & kelly),
        fixed_profit_only_qualifying_quotes=len(fixed - kelly), kelly_only_qualifying_quotes=len(kelly - fixed),
        jointly_selected_quotes=len(fixed_selected & kelly_selected),
        fixed_profit_only_selected_quotes=len(fixed_selected - kelly_selected),
        kelly_only_selected_quotes=len(kelly_selected - fixed_selected),
        venue_changes=sum(fixed_bets[bet] != kelly_bets[bet] for bet in fixed_bets.keys() & kelly_bets.keys())
            if variant == 'best_venue' else 0)
    if not details:
        return counts
    exclusions = {mode: {row['frozen_quote_id']: row for game in reports[mode]['games']
                         for row in (game.get('sizing_exclusions') or [])} for mode in MODES}
    changes = []
    for quote in sorted(fixed | kelly):
        across = {mode: qualified[mode].get(quote) for mode in MODES}
        if (all(across.values()) and across['fixed_profit']['ev'] == across['kelly']['ev']
                and (quote in fixed_selected) == (quote in kelly_selected)):
            continue
        original = across['fixed_profit'] or across['kelly']
        row = {key: original[key] for key in ('frozen_quote_id', 'equivalent_bet_id', 'game_id',
                                              'family', 'line', 'label', 'venue')}
        for mode, ticket in across.items():
            unavailable = exclusions[mode].get(quote, {})
            row[mode] = (dict(qualifies=True, selected=quote in selected[mode], ev=ticket['ev'],
                              venue=ticket['venue'], ticket_id=ticket['id']) if ticket
                         else dict(qualifies=False, selected=False, venue=original['venue'],
                                   ev=unavailable.get('sized_ev'),
                                   reason=unavailable.get('reason', 'not_in_qualifying_pool')))
        changes.append(row)
    return dict(counts=counts, changes=changes)


def sizing_run_detail(db, run, definition, report):
    if not definition['kelly_comparison']:
        return dict(sizing_runs={definition['sizing_mode']: run['id']})
    related = {row['mode']: row['id'] for row in db.execute('''SELECT r.id,d.payload->>'sizing_mode' mode
        FROM public.research_workspace_run r JOIN public.research_workspace_definition d
          ON r.definition_version=d.version
        WHERE r.game_date=%s AND d.payload->>'campaign_id'=%s
          AND d.payload->>'campaign_snapshot'=%s''',
        (run['game_date'], definition['campaign_id'], definition['campaign_snapshot']))}
    other_reports = _snapshot_reports(db, [identity for identity in related.values() if identity != run['id']])
    reports = {mode: report if identity == run['id'] else other_reports[identity]
               for mode, identity in related.items()}
    minimum = F(report['policy']['minimum_ev'])
    portfolio_rule = report['policy'].get('portfolio_rule')
    return dict(sizing_runs=related, sizing_comparison={v: sizing_comparison(reports, minimum, v, details=True,
                                                                            portfolio_rule=portfolio_rule)
                                                     for v in report['policy']['portfolios']})


def view(db, identity, variant=None, mode=None, *, game_date=None, include_comparison=True):
    if variant is not None and variant not in VARIANTS:
        raise workspace.SelectionError('Select Best venue or All qualifying venues.')
    if mode is not None and mode not in MODES:
        raise workspace.SelectionError('Select fixed profit or Kelly sizing.')
    row = db.execute('SELECT * FROM public.paper_campaign WHERE id=%s',(identity,)).fetchone()
    if not row:
        raise workspace.UnknownSelection('Unknown scheduled experiment.')
    config, days, all_tickets, versions = row['payload'], [], [], []
    available_modes = modes(config)
    mode = mode if mode in available_modes else available_modes[0]
    variant = variant if variant in config['portfolios'] else config['portfolios'][0]
    now = queue.utc()
    today = now.astimezone(EASTERN).date()
    history = _history(db, identity, game_date)
    day_rows = list(db.execute('''SELECT * FROM public.paper_campaign_day WHERE campaign_id=%s
        AND (%s::date IS NULL OR game_date=%s) ORDER BY game_date''', (identity, game_date, game_date)))
    run_ids = {day['game_date']: _mode_runs(history.get(day['game_date'], []), day['run_id'], available_modes[0])
               for day in day_rows}
    compare = include_comparison and config.get('kelly_comparison')
    report_ids = {run for runs in run_ids.values() for key, run in runs.items() if key == mode or compare}
    latest_reports = _snapshot_reports(db, report_ids) if config['version'] == SIZING_VERSION else {}
    edges = config['bucket_edges']
    odds_edges = config.get('odds_bucket_edges', DEFAULT_ODDS_EDGES)
    portfolio_rule = config.get('portfolio_rule')
    comparison = Counter()
    selected_tickets, selected_days = [], 0
    for day in day_rows:
        current_day = day['game_date']
        in_window = current_day <= today or game_date is not None
        runs = run_ids[current_day]
        run_id = runs.get(mode)
        if not include_comparison:
            runs = {mode: run_id} if run_id else {}
        snapshots = [dict(id=r['id'], recorded_at=r['recorded_at'].isoformat())
                     for r in history.get(current_day, []) if r['mode'] == mode]
        replay_state = day['state']
        if day['lease_until'] and day['lease_until'] > now:
            replay_state = 'replaying'
        elif replay_state == 'scheduled' and current_day <= today:
            replay_state = 'replay_queued'
        entry = dict(date=str(current_day), run_id=run_id, run_ids=runs, state=day['state'],
                     replay_state=replay_state, error=REPLAY_FAILED if day['last_error'] else None,
                     next_check_at=max(day['next_check_at'], datetime.combine(current_day, time.min, EASTERN)).isoformat(),
                     checked_at=day['updated_at'].isoformat(), snapshots=snapshots,
                     retrospective=current_day <= row['created_at'].astimezone(EASTERN).date(),
                     capture_state='scheduled' if day['state'] == 'scheduled' else 'awaiting_evidence')
        if compare:
            entry['comparison'] = sizing_comparison({m: latest_reports[r] for m, r in runs.items()},
                                                    F(edges[0]), variant, portfolio_rule=portfolio_rule)
            if entry['comparison'] is not None:
                comparison.update(entry['comparison'])
        if run_id:
            state = queue.read(db, run_id, include_history=False)
            report = (state or {}).get('report')
            entry.update(result_state=(state or {}).get('state','collecting'),
                         result_pending=(state or {}).get('pending',True), result_error=bool((state or {}).get('error')))
            document = (dict(report=latest_reports[run_id]) if run_id in latest_reports else
                        workspace._run(db,run_id)['payload'])
            source = document['report']
            entry['captures'] = dict(Counter(g['status'] for g in source['games']))
            usable = sum(entry['captures'].get(s, 0) for s in paper_results.CAPTURED)
            pending = sum(entry['captures'].get(s, 0) for s in ('pending', 'claimed'))
            if usable:
                complete = usable == len(source['games']) and all(
                    (game.get('coverage') or {}).get('incomplete') is False for game in source['games'])
                entry['capture_state'] = 'retained' if complete else 'partial'
                selections = select(source['portfolios']['all_venues']['tickets'], F(edges[0]), variant, portfolio_rule)
                selected = list(_selection_rows(selections, report, variant))
                entry['selection'] = _selection_summary(selected, odds_edges)
                if in_window:
                    selected_tickets.extend(selected)
                    selected_days += 1
            else:
                entry['capture_state'] = 'pending' if pending else 'missing'
            if not usable and not pending:
                entry['result_state'] = 'no_usable_capture'
            if report:
                entry['result_id'] = state['version']['id']
                if usable and (not pending or report['portfolios']['all_venues']['tickets']):
                    tickets = analysis_tickets(document, report)
                    if in_window:
                        all_tickets.extend(tickets)
                        versions.append(entry['result_id'])
                    entry['analysis'] = _window_analysis(tickets, edges, variant, inputs=entry['result_id'],
                                                         portfolio_rule=portfolio_rule)
                    if config['version'] == SIZING_VERSION and not state['pending'] and not state['error']:
                        entry['result_state'] = paper_results.portfolio_status(report, variant)
        days.append(entry)
    return dict(id=identity,config=config,variant=variant,mode=mode,available_modes=available_modes,days=days,
                as_of=now.isoformat(),
                selection=_selection_summary(selected_tickets, odds_edges) if selected_days else None,
                weekly=_window_analysis(all_tickets, edges, variant, inputs=versions,
                                        portfolio_rule=portfolio_rule) if versions else None,
                comparison=dict(comparison) if comparison else None,
                reported_days=len(versions),provider_requests=0,orders_submitted=0)


def daily(db, identity, game_date, variant=None):
    game_date = workspace.game_day(game_date)
    primary = view(db, identity, variant, game_date=game_date)
    if not primary['days']:
        raise workspace.UnknownSelection('This game date is outside the saved experiment.')
    days = {primary['mode']: primary['days'][0]}
    for mode in primary['available_modes'][1:]:
        comparison = view(db, identity, primary['variant'], mode, game_date=game_date)
        days[mode] = comparison['days'][0]
    return dict(id=identity, config=primary['config'], variant=primary['variant'], date=game_date,
                modes=days, provider_requests=0, orders_submitted=0)


def index(db, *, active_only=False):
    campaigns = [dict(id=r['id'], **r['payload']) for r in db.execute(
        'SELECT id,payload FROM public.paper_campaign ORDER BY created_at DESC,id')]
    return _discovery(campaigns)['campaigns'] if active_only else campaigns


def discovery(db):
    return _discovery(index(db))


def _discovery(campaigns):
    parents = {campaign['id']: campaign.get('supersedes') for campaign in campaigns}
    visible = [campaign for campaign in campaigns
               if campaign['id'] == WIN_10_CAMPAIGN or campaign.get('discoverable') is True]
    replaced = set()
    for campaign in visible:
        ancestor = parents[campaign['id']]
        while ancestor and ancestor not in replaced:
            replaced.add(ancestor)
            ancestor = parents.get(ancestor)
    active = [campaign for campaign in visible if campaign['id'] not in replaced]
    successors = {}
    for campaign in active:
        ancestor = parents[campaign['id']]
        while ancestor and ancestor not in successors:
            successors[ancestor] = campaign['id']
            ancestor = parents.get(ancestor)
    preferred = successors.get(WIN_10_CAMPAIGN, WIN_10_CAMPAIGN)
    active.sort(key=lambda campaign: campaign['id'] != preferred)
    return dict(campaigns=active, successors=successors)
