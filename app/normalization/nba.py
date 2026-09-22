"""NBA single-game winner identity and explicit source/model review configuration."""
from datetime import timezone
import json
import re
from app.normalization.registry import Registry
from app.reference.product import time
LEAGUE='NBA'
KEY='nba'
SERIES='KXNBAGAME'
RULES='nba-full-game-two-way-including-overtime-v1'
FIELDS=('overtime','outcomes','tie','cancellation','postponement','suspension','abandonment',
        'shortened_game','void','refund','forfeit','venue_change','result_corrections')
EVENT_FIELDS=('competition','sport','game_id','original_start','scheduled_start','home','away','season','stage','schedule_status')
REQUIRED_TERMS={'overtime':'included','outcomes':'two_way'}

def event_key(event):
    """Reviewed shared game ID, never title or nearest-start matching."""
    if event.get('competition') != 'NBA' or event.get('sport') != 'basketball':
        raise ValueError('NBA competition / sport mismatch')
    season=event.get('season','')
    if not isinstance(season,str) or not re.fullmatch(r'20\d{2}-20\d{2}',season):
        raise ValueError('Explicit NBA season YYYY-YYYY required')
    start=time(event['scheduled_start']).astimezone(timezone.utc)
    original=time(event['original_start']).astimezone(timezone.utc)
    first,last=map(int,season.split('-'))
    if last!=first+1 or any(not ((t.year==first and t.month>=9) or (t.year==last and t.month<=7)) for t in (start,original)):
        raise ValueError('NBA start outside declared season')
    if event.get('stage') not in ('regular_season','play_in','playoffs','nba_cup'):
        raise ValueError('Explicit NBA regular season / play-in / playoffs / NBA Cup stage required')
    mapping=event.get('participants',{});registry=Registry.load()
    if len(mapping)!=2 or len(set(mapping.values()))!=2:
        raise ValueError('Two distinct NBA participants required')
    for name,cid in mapping.items():
        if registry.resolve('team',name,league='NBA').canonical_id!=cid:
            raise ValueError('Unknown, ambiguous or conflicting NBA participant')
    if event.get('home') not in mapping.values() or event.get('away') not in mapping.values() or event['home']==event['away']:
        raise ValueError('Explicit home and away NBA identities required')
    if not isinstance(event.get('game_id'),str) or not event['game_id'].strip():
        raise ValueError('Reviewed shared NBA game ID required; names alone are insufficient')
    if event.get('schedule_status') not in ('scheduled','rescheduled'):
        raise ValueError('Unknown or unsupported NBA game status')
    if (start!=original)!=(event['schedule_status']=='rescheduled'):
        raise ValueError('NBA original start / reschedule conflict')
    return ['NBA',season,event['stage'],start.isoformat(),event['home'],event['away'],
            event['game_id'],original.isoformat(),event['schedule_status']]


def inventory_gaps(inventory):
    from app.normalization import reviewed_winner
    import sys
    return reviewed_winner.inventory_gaps(sys.modules[__name__],inventory)


def winner_review(event,market,meta,source,mode):
    from app.normalization import reviewed_winner
    import sys
    return reviewed_winner.winner_review(sys.modules[__name__],event,market,meta,source,mode)

def model_reason(binding,body):
    from app.normalization import reviewed_winner
    import sys
    return reviewed_winner.model_reason(sys.modules[__name__],binding,body)


def assessment(rows,cutoff,game):
    from app.normalization import reviewed_winner
    import sys
    return reviewed_winner.assessment(sys.modules[__name__],rows,cutoff,game)
