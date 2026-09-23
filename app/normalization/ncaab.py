"""Bounded men's Division I basketball identity and source review configuration."""
from datetime import timezone
import re
import sys
from app.normalization.registry import Registry
from app.normalization import reviewed_winner
from app.reference.product import time

LEAGUE='NCAAB'
KEY='ncaab'
SERIES='KXNCAAMBGAME'
RULES='ncaab-men-d1-full-game-two-way-including-overtime-v1'
FIELDS=('overtime','outcomes','tie','cancellation','postponement','suspension','abandonment',
        'shortened_game','void','refund','forfeit','venue_change','result_corrections',
        'regulation_format','overtime_format')
CONTEXT_FIELDS=('gender','division','competition_id','neutral_site','tournament_id','round','period_structure','schools')
EVENT_FIELDS=('competition','sport','game_id','original_start','scheduled_start','home','away',
              'season','stage','schedule_status',*CONTEXT_FIELDS)
REQUIRED_TERMS={'overtime':'included','outcomes':'two_way',
                'regulation_format':'two_20_minute_halves','overtime_format':'repeated_5_minutes'}


def event_key(event):
    if event.get('competition')!=LEAGUE or event.get('sport')!='basketball':
        raise ValueError('NCAAB competition / sport mismatch')
    if (event.get('gender'),event.get('division'),event.get('competition_id'))!=('men','I','NCAA:M:D1'):
        raise ValueError('NCAAB scope requires explicit men Division I competition; women / other divisions unsupported')
    season=event.get('season','')
    if not isinstance(season,str) or not re.fullmatch(r'20\d{2}-20\d{2}',season):
        raise ValueError('Explicit NCAAB season YYYY-YYYY required')
    first,last=map(int,season.split('-'))
    start=time(event['scheduled_start']).astimezone(timezone.utc)
    original=time(event['original_start']).astimezone(timezone.utc)
    if last!=first+1 or any(not ((t.year==first and t.month>=11) or (t.year==last and t.month<=4)) for t in (start,original)):
        raise ValueError('NCAAB start outside reviewed November / April season')
    stage=event.get('stage')
    if stage not in ('regular_season','in_season_tournament','conference_tournament','ncaa_tournament','other_postseason_tournament'):
        raise ValueError('Explicit NCAAB single-game stage required')
    tournament,round_name=event.get('tournament_id'),event.get('round')
    if stage=='regular_season':
        if (tournament,round_name)!=('not_applicable','not_applicable'):
            raise ValueError('Regular-season game has conflicting tournament identity')
    elif any(not isinstance(v,str) or v.strip().lower() in ('','unknown','not_applicable') for v in (tournament,round_name)):
        raise ValueError('Tournament game requires reviewed tournament ID and round')
    if event.get('period_structure')!='two_20_minute_halves':
        raise ValueError('NCAAB men period structure must be two 20-minute halves')
    from app.normalization.college_registry import for_event
    registry=for_event(event);mapping=event.get('participants',{})
    if not isinstance(mapping,dict) or len(mapping)!=2 or len(set(mapping.values()))!=2:
        raise ValueError('Two distinct reviewed NCAAB school teams required')
    schools=event.get('schools',{})
    if not isinstance(schools,dict) or set(schools)!=set(mapping.values()):
        raise ValueError('Explicit NCAAB school identity required for each team')
    for name,cid in mapping.items():
        if registry.resolve('team',name,league=LEAGUE).canonical_id!=cid:
            raise ValueError('Unknown, ambiguous or conflicting NCAAB school; coverage review required')
        team=registry.entities[cid];membership=team.get('basketball_memberships',{}).get(season,{})
        if team.get('gender')!=event['gender'] or membership.get('division')!=event['division'] or membership.get('competition_id')!=event['competition_id']:
            raise ValueError('Unreviewed season or conflicting NCAAB gender / division membership')
        if team.get('school_id')!=schools[cid]:
            raise ValueError('NCAAB campus / school identity conflicts with reviewed team')
    if event.get('home') not in mapping.values() or event.get('away') not in mapping.values() or event['home']==event['away']:
        raise ValueError('Explicit designated NCAAB home and away identities required')
    if event.get('neutral_site') not in ('neutral','home','unknown'):
        raise ValueError('NCAAB site status must be explicit neutral / home / unknown')
    if not isinstance(event.get('game_id'),str) or not event['game_id'].strip():
        raise ValueError('Reviewed shared NCAAB game ID required; names alone are insufficient')
    if event.get('schedule_status') not in ('scheduled','rescheduled'):
        raise ValueError('Unknown or unsupported NCAAB game status')
    if (start!=original)!=(event['schedule_status']=='rescheduled'):
        raise ValueError('NCAAB original start / reschedule conflict')
    return [LEAGUE,season,stage,start.isoformat(),event['home'],event['away'],event['game_id'],
            original.isoformat(),event['schedule_status'],event['gender'],event['division'],event['competition_id'],
            event['neutral_site'],tournament,round_name,event['period_structure'],
            [[cid,schools[cid]] for cid in sorted(schools)]]


def inventory_gaps(inventory):
    return reviewed_winner.inventory_gaps(sys.modules[__name__],inventory)


def winner_review(event,market,meta,source,mode):
    return reviewed_winner.winner_review(sys.modules[__name__],event,market,meta,source,mode)


def model_reason(binding,body):
    reason=reviewed_winner.model_reason(sys.modules[__name__],binding,body)
    if reason:return reason
    r=binding['ncaab_model_review'];event=r['event']
    for field in CONTEXT_FIELDS:
        if r.get(field)!=event[field] or not isinstance(r.get(field+'_literal'),str) or not r[field+'_literal'] or r[field+'_literal'] not in body:
            return 'Model NCAAB competition / school / site / tournament evidence missing or conflicting'
    return None


def assessment(rows,cutoff,game):
    return reviewed_winner.assessment(sys.modules[__name__],rows,cutoff,game)


def settlement_terms(terms):
    """Carry the reviewed sporting format in the existing overtime dimension."""
    result={k:v for k,v in terms.items() if k not in ('regulation_format','overtime_format')}
    result['overtime']='; '.join(terms[k] for k in ('overtime','regulation_format','overtime_format'))
    return result
