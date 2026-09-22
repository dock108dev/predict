"""NFL score-line identity. Does not change the retained legacy winner path."""
from datetime import timezone
from app.normalization.registry import Registry
from app.reference.product import time
LEAGUE='NFL'
EVENT_FIELDS=('competition','sport','game_id','original_start','scheduled_start','home','away','season','stage','schedule_status')
OVERTIME={'regular_season':'2026_regular_max_one_10_minute_period',
          'postseason':'2026_postseason_15_minute_periods_until_winner'}
TERM_FIELDS={'completion','cancellation','suspension','postponement','void','corrections',
             'settlement_fee','shortened_game','abandonment','forfeit','venue_change'}

def validate_descriptor(event,d):
    if d.get('overtime_format')!=OVERTIME[event['stage']]:
        raise ValueError('NFL overtime format unknown or conflicts with season / stage')
    if d.get('tied_score')!='evaluate_actual_score_predicate':
        raise ValueError('NFL tied final score treatment unknown or unsupported')
    if d.get('normal_completion')!='all_regulation_and_applicable_overtime':
        raise ValueError('NFL normal completed-game score scope unknown')


def event_key(event):
    """Reviewed shared game ID, never title or nearest-start matching."""
    if event.get('competition') != 'NFL' or event.get('sport') != 'american_football':
        raise ValueError('NFL competition / sport mismatch')
    season=event.get('season','')
    if season!='2026':
        raise ValueError('NFL score-line rules reviewed for 2026 season only')
    start=time(event['scheduled_start']).astimezone(timezone.utc)
    original=time(event['original_start']).astimezone(timezone.utc)
    if any(not ((t.year==2026 and t.month>=9) or (t.year==2027 and t.month<=2)) for t in (start,original)):
        raise ValueError('NFL start outside declared season')
    if event.get('stage') not in OVERTIME:
        raise ValueError('Explicit NFL regular_season / postseason stage required')
    if event['stage']=='postseason' and any(t.year!=2027 for t in (start,original)):
        raise ValueError('NFL postseason start conflicts with season')
    if event['stage']=='regular_season' and any(t.year==2027 and t.month>1 for t in (start,original)):
        raise ValueError('NFL regular season start conflicts with season')
    mapping=event.get('participants',{});registry=Registry.load()
    if len(mapping)!=2 or len(set(mapping.values()))!=2:
        raise ValueError('Two distinct NFL participants required')
    for name,cid in mapping.items():
        if registry.resolve('team',name,league='NFL').canonical_id!=cid:
            raise ValueError('Unknown, ambiguous or conflicting NFL participant')
    if event.get('home') not in mapping.values() or event.get('away') not in mapping.values() or event['home']==event['away']:
        raise ValueError('Explicit home and away NFL identities required')
    if not isinstance(event.get('game_id'),str) or not event['game_id'].strip():
        raise ValueError('Reviewed shared NFL game ID required; names alone are insufficient')
    if event.get('schedule_status') not in ('scheduled','rescheduled'):
        raise ValueError('Unknown or unsupported NFL game status')
    if (start!=original)!=(event['schedule_status']=='rescheduled'):
        raise ValueError('NFL original start / reschedule conflict')
    return ['NFL',season,event['stage'],start.isoformat(),event['home'],event['away'],
            event['game_id'],original.isoformat(),event['schedule_status']]



def inventory_gaps(inventory):
    from app.normalization import reviewed_winner
    import sys
    # Legacy winner records remain governed by their original path.
    selected={}
    for source,cat in inventory.items():
        ids={m['event_id'] for m in cat.get('markets',[]) if m.get('market_type') in ('spread','total')}
        selected[source]=dict(events=[e for e in cat.get('events',[]) if e['id'] in ids])
    return reviewed_winner.inventory_gaps(sys.modules[__name__],selected)
