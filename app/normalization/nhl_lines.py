"""NHL line-specific identity and score review; no winner-rule inheritance."""
from datetime import timezone
from copy import deepcopy
from app.normalization import nhl
from app.reference.product import time

LEAGUE='NHL'
EVENT_FIELDS=('competition','sport','game_id','original_start','scheduled_start','home','away','season','stage','schedule_status')
TERM_FIELDS={'completion','cancellation','suspension','postponement','void','corrections','settlement_fee',
             'shortened_game','abandonment','forfeit','venue_change','resumed_game','tie','refund'}
OT={'regular_season':'five_minute_three_on_three_then_shootout','playoffs':'successive_twenty_minute_sudden_death_no_shootout'}
SCORE={'regular_season':'regulation_ot_plus_one_goal_to_shootout_winner','playoffs':'regulation_and_all_overtime_goals_no_shootout'}
BASES={'on_ice_regulation_and_overtime','official_final_including_shootout_award'}


def event_key(event):
    key=nhl.event_key(event)
    if event['season']!='2026-2027':raise ValueError('NHL line scoring reviewed for 2026-2027 only')
    original=time(event['original_start']).astimezone(timezone.utc);start=time(event['scheduled_start']).astimezone(timezone.utc)
    nhl.event_key(dict(event,scheduled_start=event['original_start']))
    if event['stage']=='playoffs' and any(t.year!=2027 or t.month<4 for t in (original,start)):
        raise ValueError('NHL playoff date conflicts with reviewed season')
    if not isinstance(event.get('game_id'),str) or not event['game_id'].strip():raise ValueError('Reviewed NHL game ID required; team names alone are insufficient')
    if event.get('schedule_status') not in ('scheduled','rescheduled') or (start!=original)!=(event['schedule_status']=='rescheduled'):
        raise ValueError('NHL original start / reschedule status missing or conflicting')
    return key+[event['game_id'],original.isoformat(),event['schedule_status']]


def inventory_gaps(inventory):
    from app.normalization import reviewed_winner
    import sys
    selected={}
    for source,cat in inventory.items():
        ids={m['event_id'] for m in cat.get('markets',[]) if m.get('market_type') in ('spread','total')}
        selected[source]=dict(events=[e for e in cat.get('events',[]) if e['id'] in ids])
    return reviewed_winner.inventory_gaps(sys.modules[__name__],selected)


def validate_descriptor(event,d):
    if d.get('overtime_format')!=OT[event['stage']] or d.get('settlement_score')!=SCORE[event['stage']]:
        raise ValueError('NHL overtime / shootout settlement-score convention unknown or conflicts with stage')
    if d.get('input_score_basis') not in BASES:raise ValueError('NHL native score basis unknown; shootout adjustment cannot be inferred')
    if d.get('normal_completion')!='three_periods_and_applicable_overtime_shootout':raise ValueError('NHL shortened / incomplete normal score scope unsupported')
    if d.get('tied_score')!='evaluate_score_predicate_exceptions_separate':raise ValueError('NHL tied-score settlement scope unknown')


def settlement_score(event,d,observed):
    """Pure reviewed numeric mapping, not a result feed or payout declaration.

    Keep the input score and award separate. Official final scores already carry
    the single shootout award; shootout attempt totals are never accepted.
    """
    event_key(event);validate_descriptor(event,d)
    if set(observed)!={'home','away','decision','winner','score_basis'}:raise ValueError('Explicit original numeric score and basis required')
    if observed['score_basis']!=d['input_score_basis']:raise ValueError('Native score basis conflicts with reviewed input convention')
    h,a=observed['home'],observed['away'];decision=observed['decision'];winner=observed['winner']
    if any(type(v) is not int or v<0 for v in (h,a)):raise ValueError('Nonnegative integer goals required')
    if decision not in ('regulation','overtime','shootout') or winner not in ('home','away'):raise ValueError('Completed scoring decision / winner unknown')
    adjustment={'home':0,'away':0}
    if decision=='shootout':
        if event['stage']!='regular_season':raise ValueError('Shootout incompatible with NHL playoffs')
        if observed['score_basis']=='on_ice_regulation_and_overtime':
            if h!=a:raise ValueError('Pre-award shootout score must be tied; possible double counting')
            adjustment[winner]=1
        elif (h-a if winner=='home' else a-h)!=1:
            raise ValueError('Official shootout score must include exactly one winner goal')
    elif (h-a if winner=='home' else a-h)<=0:raise ValueError('Completed on-ice score conflicts with winner')
    return dict(observed=deepcopy(observed),adjustment=adjustment,
                settlement={'home':h+adjustment['home'],'away':a+adjustment['away']},
                convention=d['settlement_score'])
