"""Explicit bounded current subscriptions; complete catalog discovery is unchanged."""
from collections import defaultdict,deque,Counter
from datetime import datetime
from decimal import Decimal

from app.comparison.game_phase import sporting_phase
from .native_sporting_state import current_observation, matches_event

# The 512-market live population consumed nearly the entire 15-second price
# window before capture (derived p95 12–14 seconds). Keep discovery complete,
# but bound each active cohort; the other instruments remain explicitly deferred.
MAX_ACTIVE=256
ROTATE_SECONDS=20


def sportsbook_main_markets(catalog):
    """Use retained sportsbook lines as scheduling hints for exact native instruments."""
    from app.comparison.sgo_reference import BEST_BOOKS
    from app.storage.store import connect, stamp

    with connect() as db:
        rows = db.execute("""SELECT DISTINCT ON (e.id,r.bookmaker_id,r.facts->>'market')
            e.competition,e.scheduled_start,e.facts->>'home' home,e.facts->>'away' away,
            r.facts->>'market' family,(r.facts->>'line')::numeric line
            FROM current_event e JOIN current_sgo_reference r ON r.event_id=e.native_event_id
            WHERE e.provider='sportsgameodds' AND r.bookmaker_id=ANY(%s)
              AND e.scheduled_start::timestamptz BETWEEN now() AND now()+interval '72 hours'
              AND r.expires_at>now() AND r.facts->>'phase'='pregame'
              AND r.facts->>'period'='game' AND r.facts->>'available'='true'
              AND coalesce(r.facts->>'alternate','false')='false' AND r.facts->>'line' IS NOT NULL
              AND ((r.facts->>'market',r.facts->>'side') IN (('spread','home'),('total','over')))
            ORDER BY e.id,r.bookmaker_id,r.facts->>'market',r.received_order DESC,r.source_order DESC,r.id""",
            (list(BEST_BOOKS),)).fetchall()
    lines = defaultdict(Counter)
    for row in rows:
        key = (row['competition'], stamp(row['scheduled_start']), row['home'], row['away'], row['family'])
        lines[key][row['line']] += 1
    main = {key: min(counts, key=lambda line: (-counts[line], line)) for key, counts in lines.items()}
    return matching_main_markets(catalog, main)


def matching_main_markets(catalog, main):
    from .current_sink import source_local_display_binding
    from app.storage.store import stamp

    if not main:
        return set()
    scheduled = {key[:4] for key in main}
    occurrences = {}
    for event in catalog['events']:
        roles = event.get('source_participant_roles') or event
        start, home, away = event.get('scheduled_start'), roles.get('home'), roles.get('away')
        if (start and home and away and home != away and not event.get('exclusion')
                and not event.get('conflicting_duplicate') and not event.get('occurrence_conflict')):
            try:
                key = (event.get('competition'), stamp(start), home, away)
            except (AttributeError, TypeError, ValueError):
                continue
            if key in scheduled:
                occurrences[event['id']] = (event, key)
    chosen = set()
    for market in catalog['markets']:
        occurrence = occurrences.get(market['event_id'])
        if not occurrence or market.get('exclusion') or market.get('conflicting_duplicate'):
            continue
        event, key = occurrence
        binding = market.get('v1_raw_binding') or {}
        fact = binding.get('source_predicate') or {}
        identity = binding.get('identity') or {}
        if identity.get('period') != 'full_game':
            continue
        family = identity.get('family')
        if family == 'moneyline':
            matches = any(isinstance(side, dict) and side.get('predicate') == 'win'
                          and side.get('participant') in key[2:] for side in binding.get('predicate') or ())
        elif family in ('spread', 'total') and fact.get('period') == 'full_game' and fact.get('family') == family:
            line = main.get((*key, family))
            if line is None:
                continue
            participant, native_line = fact['participant'], Decimal(fact['line'])
            if family == 'total':
                matches = participant == 'combined' and native_line == line
            else:
                matches = participant == key[2] and native_line == line or participant == key[3] and native_line == -line
        else:
            continue
        # A source-local exact side can be scheduled even when season/stage
        # is unavailable. The subscription confers no comparison authority.
        if matches and (binding.get('status') == 'BOUND_RAW_PREDICATE'
                        or source_local_display_binding(event, market, binding, binding.get('source'))):
            chosen.add(market['id'])
    return chosen


def select(markets,catalog,now,offset,*,limit=MAX_ACTIVE,phase_events=(),priority_pregame=False,preferred=()):
    events={e['id']:e for e in catalog.get('events',[])}
    committed={e['id']:e for e in phase_events}
    metadata={m['id']:m for m in catalog.get('markets',[])}
    cells=defaultdict(lambda:defaultdict(list))
    priorities={}
    def distance(eid):
        if eid in priorities:return priorities[eid]
        event=events.get(eid,{})
        try:
            value=event.get('scheduled_start')
            if not isinstance(value,str):raise ValueError()
            start=datetime.fromisoformat(value.replace('Z','+00:00'))
            if start.tzinfo is None:raise ValueError()
            elapsed=(now-start).total_seconds()
            phase=event
            updated=committed.get(eid,{})
            observation=updated.get('sporting_state_evidence')
            if observation and matches_event(event,observation) and current_observation(event,observation):
                phase=updated
            status = sporting_phase(phase)
            live=0<=elapsed<86400 and status['state']=='live'
            upcoming = priority_pregame and -7200 <= elapsed < 0 and not status['reason'] and status['state'] != 'live'
            rank=(0 if upcoming else 1 if live else 2,abs(elapsed),eid)
        except (TypeError,ValueError):rank=(2,float('inf'),eid)
        priorities[eid]=rank
        return rank
    for market in markets:
        mid=market.raw.ref.market_id;eid=market.raw.ref.event_id
        event=events.get(eid,{})
        cells[(event.get('competition','unknown'),metadata.get(mid,{}).get('market_type','unknown'))][eid].append(market)
    queues={}
    for cell,groups in sorted(cells.items()):
        groups={eid:deque(sorted(rows,key=lambda m:(m.raw.ref.market_id not in preferred,m.raw.ref.market_id)))
                for eid,rows in groups.items()}
        ordered=[]
        while groups:
            for eid in sorted(groups,key=distance):
                ordered.append(groups[eid].popleft())
                if not groups[eid]:del groups[eid]
        queues[cell]=deque(ordered)
    fair=[]
    while queues:
        for cell in list(queues):
            fair.append(queues[cell].popleft())
            if not queues[cell]:del queues[cell]
    if len(fair)<=limit:chosen=fair
    else:
        fixed=limit//2
        # Give each league/family a fixed slot before filling the remaining
        # fixed capacity with live lines. A sparse live slate can then retain
        # every line without cutting the rotating half or losing other cells.
        seed=fair[:min(fixed,len(cells))]
        pool=fair[len(seed):]
        hot=sorted((m for m in pool if distance(m.raw.ref.event_id)[0] < 2),
                    key=lambda m:distance(m.raw.ref.event_id)[:2])
        primary=seed+hot[:fixed-len(seed)]
        fixed_ids={m.raw.ref.market_id for m in primary}
        main_lines=sorted((m for m in pool if m.raw.ref.market_id in preferred and m.raw.ref.market_id not in fixed_ids),
                          key=lambda m:distance(m.raw.ref.event_id)[:2])
        primary.extend(main_lines[:fixed-len(primary)])
        fixed_ids.update(m.raw.ref.market_id for m in primary)
        primary.extend([m for m in pool if m.raw.ref.market_id not in fixed_ids][:fixed-len(primary)])
        fixed_ids.update(m.raw.ref.market_id for m in primary)
        remaining=[m for m in fair if m.raw.ref.market_id not in fixed_ids]
        width=limit-len(primary);start=(offset*width)%len(remaining)
        chosen=primary+[remaining[(start+i)%len(remaining)] for i in range(width)]
    detail = describe(markets,catalog,chosen,offset)
    if priority_pregame:
        detail.update(policy='fair-current-subscriptions-4',
                      meaning='Fixed slots cover each league and family, then favor near-kickoff pregame and observed live lines. Remaining slots rotate.')
    return chosen,detail


def describe(markets,catalog,chosen,offset):
    events={e['id']:e for e in catalog.get('events',[])}
    metadata={m['id']:m for m in catalog.get('markets',[])}
    selected={m.raw.ref.market_id for m in chosen};counts=Counter();cells=set()
    for m in markets:
        mid=m.raw.ref.market_id
        cell=(events.get(m.raw.ref.event_id,{}).get('competition','unknown'),metadata.get(mid,{}).get('market_type','unknown'))
        cells.add(cell);counts[cell,mid in selected]+=1
    detail=[dict(league=cell[0],family=cell[1],active=counts[cell,True],deferred=counts[cell,False]) for cell in sorted(cells)]
    return dict(policy='fair-current-subscriptions-3',eligible_markets=len(markets),active_markets=len(chosen),
        deferred_markets=len(markets)-len(chosen),rotation_seconds=ROTATE_SECONDS,rotation=offset,cells=detail,
        meaning='Fixed slots cover each league and family, then prioritize live lines nearest kickoff. The other half rotates deferred markets.')
