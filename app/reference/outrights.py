"""Award observations: no game teams, inferred seasons or exhaustive field claims."""
from copy import deepcopy
from hashlib import sha256
import json
from app.reference.odds_bindings import BOOKS, CHAMPIONSHIPS
from app.reference.product import probability, time
from app.normalization.college_registry import aggregate_registry
from app.dashboard.session_projection import stable

VERSION='odds-award-observation-1'
AWARDS=dict(NFL='Super Bowl',NBA='NBA Championship',MLB='World Series',NHL='Stanley Cup',NCAAF='CFP National Championship',NCAAB='NCAA Men Division I Championship')

def normalize(body,sport,received_at):
    from app.reference.odds_acquire import strict_json
    time(received_at);events=strict_json(body)
    if not isinstance(events,list) or len(events)>32:raise ValueError('Award response bound/shape')
    rows=[];seen=set()
    for event in events:
        eid=event.get('id')
        if not isinstance(eid,str) or not eid or eid in seen or event.get('sport_key')!=CHAMPIONSHIPS[sport]:raise ValueError('Award identity conflict')
        seen.add(eid)
        # An outright commence time is retained as provider timing, never a game
        # kickoff or evidence of a season. Exact explicit associations are needed.
        season=event.get('season');award=event.get('award')
        association=dict(season=season,award=award,category='league_champion',conference_id=None)
        books=set()
        for book in event['bookmakers']:
            if book['key'] not in BOOKS or book['key'] in books:raise ValueError('Award bookmaker conflict')
            books.add(book['key']);markets=set()
            for market in book['markets']:
                if market['key']!='outrights' or market['key'] in markets:raise ValueError('Award market conflict')
                markets.add(market['key']);names=set()
                for outcome in market['outcomes']:
                    name=outcome.get('name')
                    if not isinstance(name,str) or not name or name in names:raise ValueError('Award entrant conflict')
                    names.add(name)
                    try:implied=probability(outcome['price'],'decimal_odds');issue=None
                    except (ValueError,ArithmeticError):implied=None;issue='Invalid decimal odds'
                    rows.append(dict(provider='the_odds_api',evidence_mode='observation',sport=sport,source_event_id=eid,
                        scheduled_start=event.get('commence_time'),home_team=None,away_team=None,bookmaker=book['key'],
                        role='aggregated_venue_observation' if book['key'] in ('novig','prophetx') else 'bookmaker_reference',
                        market='outrights',period='season',outcome=name,point=None,decimal_odds=str(outcome['price']),
                        raw_implied_probability=implied,price_issue=issue,source_at=market.get('last_update') or book.get('last_update'),
                        received_at=received_at,award_association=association,source_fields=dict(event={k:v for k,v in event.items() if k!='bookmakers'},
                        book={k:v for k,v in book.items() if k!='markets'},market={k:v for k,v in market.items() if k!='outcomes'},outcome=deepcopy(outcome)),
                        receipt_sha256=sha256(body).hexdigest(),executable=False,settlement=None,fees=None,purchasable_depth=None,
                        source_delay_seconds=None,fair_probability=None,ev=None))
    return rows

def bind(raw,registry=None):
    registry=registry or aggregate_registry();r=deepcopy(raw);a=r['award_association'];reasons=[]
    from app.normalization.futures import SEASONS
    if a['season']!=SEASONS[r['sport']] or a['award']!=AWARDS[r['sport']]:reasons.append('Exact current season/award association unavailable or conflicting')
    entrant=registry.resolve('team',r['outcome'],league=r['sport'],venue='the_odds_api')
    if entrant.status!='resolved':reasons.append('Exact canonical award entrant unavailable')
    timing=None
    try:
        if time(r['source_at'])>time(r['received_at']):timing='Source timestamp after receipt'
    except (TypeError,ValueError,AttributeError):timing='Source timestamp unavailable'
    ident=dict(competition=r['sport'],season=a['season'],stage='championship',period='season',family='futures',
        category='league_champion',conference_id=None,award=a['award'],line=None,subject=None,
        event=['the_odds_api',r['sport'],r['source_event_id'],a['season'],a['award']],
        scheduled_start=None,rules_revision='aggregate-settlement-unverified')
    return dict(id=stable(r),version=VERSION,registry_version=registry.version,registry_sha256=registry.fingerprint,
        original=r,role=r['role'],identity=ident,participant=entrant.canonical_id,predicate='wins_award',reasons=reasons,
        mapping_notes=['Observed entrant only; complete field required only for dependent calculations'],timing_issue=timing,
        price_issue=r['price_issue'],implied=r['raw_implied_probability'],response=r['receipt_sha256'])
