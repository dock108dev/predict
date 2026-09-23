"""Bounded college-football winner review; membership is season-specific."""
from datetime import timezone
import re
import json
import sys
from app.normalization.registry import Registry
from app.normalization import reviewed_winner
from app.reference.product import time
LEAGUE='NCAAF'
KEY='ncaaf'
SERIES='KXNCAAFGAME'
NATIVE_SERIES=('KXNCAAFGAME','KXNCAAFCSGAME')
RULES='ncaaf-full-game-two-way-including-overtime-v1'
FIELDS=('overtime','outcomes','tie','cancellation','postponement','suspension','abandonment',
        'shortened_game','void','refund','forfeit','venue_change','result_corrections')
EVENT_FIELDS=('competition','sport','game_id','original_start','scheduled_start','home','away',
              'season','stage','schedule_status','subdivisions','neutral_site')
REQUIRED_TERMS={'overtime':'included','outcomes':'two_way'}


def event_key(event):
    if event.get('competition')!='NCAAF' or event.get('sport') not in ('football','american_football'):
        raise ValueError('NCAAF competition / sport mismatch')
    season=event.get('season','')
    if not isinstance(season,str) or not re.fullmatch(r'20\d{2}',season):
        raise ValueError('Explicit NCAAF season YYYY required')
    start=time(event['scheduled_start']).astimezone(timezone.utc)
    original=time(event['original_start']).astimezone(timezone.utc)
    if any(not ((t.year==int(season) and t.month>=8) or (t.year==int(season)+1 and t.month==1)) for t in (start,original)):
        raise ValueError('NCAAF start outside declared fall / January season')
    if event.get('stage') not in ('regular_season','conference_championship','bowl','playoffs'):
        raise ValueError('Explicit NCAAF single-game stage required')
    from app.normalization.college_registry import for_event
    registry=for_event(event);mapping=event.get('participants',{})
    if len(mapping)!=2 or len(set(mapping.values()))!=2:
        raise ValueError('Two distinct reviewed NCAAF schools required')
    for name,cid in mapping.items():
        if registry.resolve('team',name,league=LEAGUE).canonical_id!=cid:
            raise ValueError('Unknown, ambiguous or conflicting NCAAF school; coverage review required')
    if event.get('home') not in mapping.values() or event.get('away') not in mapping.values() or event['home']==event['away']:
        raise ValueError('Explicit designated NCAAF home and away identities required')
    subdivisions=event.get('subdivisions',{})
    if not isinstance(subdivisions,dict) or set(subdivisions)!=set(mapping.values()):
        raise ValueError('NCAAF subdivision required for each participant')
    for cid,value in subdivisions.items():
        review=registry.entities[cid].get('football_subdivisions',{}).get(season)
        if value not in ('FBS','FCS') or not review or value!=review['value']:
            raise ValueError('Unknown or conflicting season-specific NCAAF subdivision; coverage review required')
    if event.get('neutral_site') not in ('neutral','home','unknown'):
        raise ValueError('NCAAF site status must be explicit neutral / home / unknown')
    if not isinstance(event.get('game_id'),str) or not event['game_id'].strip():
        raise ValueError('Reviewed shared NCAAF game ID required; names alone are insufficient')
    if event.get('schedule_status') not in ('scheduled','rescheduled'):
        raise ValueError('Unknown or unsupported NCAAF game status')
    if (start!=original)!=(event['schedule_status']=='rescheduled'):
        raise ValueError('NCAAF original start / reschedule conflict')
    return [LEAGUE,season,event['stage'],start.isoformat(),event['home'],event['away'],
            event['game_id'],original.isoformat(),event['schedule_status'],
            [[cid,subdivisions[cid]] for cid in sorted(subdivisions)],event['neutral_site']]


def inventory_gaps(inventory):
    return reviewed_winner.inventory_gaps(sys.modules[__name__],inventory)


def winner_review(event,market,meta,source,mode):
    review=reviewed_winner.winner_review(sys.modules[__name__],event,market,meta,source,mode)
    if source=='kalshi':
        native=json.loads(meta['market']['raw']['json_text'])
        listings=native.get('markets',[])+[m for e in native.get('events',[]) for m in e.get('markets',[])]
        series=next(m['series_ticker'] for m in listings if m.get('ticker')==market['id'])
        if series=='KXNCAAFCSGAME' and set(event['subdivisions'].values())!={'FCS'}:
            raise ValueError('FCS-only native series conflicts with participant subdivisions')
        basis=review.get('fee_basis')
        if basis and basis.get('series_id')!=series:
            raise ValueError('NCAAF fee basis conflicts with native series')
    return review


def model_reason(binding,body):
    reason=reviewed_winner.model_reason(sys.modules[__name__],binding,body)
    if reason:return reason
    r=binding['ncaaf_model_review'];e=r['event']
    # Home/away here are designations, not evidence of home-field advantage.
    for field in ('neutral_site','subdivisions'):
        if r.get(field)!=e[field] or not r.get(field+'_literal') or r[field+'_literal'] not in body:
            return 'Model NCAAF site / subdivision evidence missing or conflicting'
    return None


def assessment(rows,cutoff,game):
    return reviewed_winner.assessment(sys.modules[__name__],rows,cutoff,game)
