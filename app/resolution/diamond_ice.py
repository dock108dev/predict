"""Explicit baseball/hockey result evidence; shared payouts and corrections."""
from app.resolution.core import revision_error
from app.normalization.nhl_lines import settlement_score, OT, SCORE
from app.reference.product import time


def hockey_score(p):
    e=p['target']['event']
    d=dict(overtime_format=OT[e['stage']],settlement_score=SCORE[e['stage']],input_score_basis=p['score_basis'],normal_completion='three_periods_and_applicable_overtime_shootout',tied_score='evaluate_score_predicate_exceptions_separate')
    return settlement_score(e,d,dict(home=p['home_score'],away=p['away_score'],decision=p['decision'],winner=p['winner'],score_basis=p['score_basis']))['settlement']


def sporting_error(p):
    sport=p['target']['event']['competition']
    if p.get('status') not in ('pending','final','cancelled','suspended','postponed','abandoned','shortened','forfeit','administrative_change','unknown'):
        return 'Unsupported '+sport+' sporting status'
    reason=revision_error(p,sport)
    if reason:return reason
    if sport=='MLB' and p['status']=='shortened':
        if p.get('period')!='full_game' or p.get('league_declared_final') is not True or p.get('score_representation')!='official_cumulative_runs' or any(type(p.get(k)) is not int or p[k]<0 for k in ('home_score','away_score')) or p['home_score']==p['away_score']:return 'Shortened MLB result needs explicit league-declared final runs; no inferred official-game rule'
        return None
    if p['status']!='final':return None
    if p.get('result_basis')!='on_field_period_score':return 'Missing sporting score basis'
    if any(type(p.get(k)) is not int or not 0<=p[k]<=1000 for k in ('home_score','away_score')):return 'Missing explicit nonnegative integer score'
    from app.normalization import score_periods
    if score_periods.scope(p['target']['market_identity']):return score_periods.validate_result(p)
    if p.get('period')!='full_game':return 'Unsupported result period'
    if sport=='NHL':
        if p.get('completion')!='three_periods_and_applicable_overtime_shootout' or p.get('score_scope')!='full_game' or p.get('regulation_periods_completed')!=3 or type(p.get('regulation_periods_completed')) is not int:
            return 'Missing NHL full-game completion; regulation-only cannot settle an OT-inclusive market'
        try:hockey_score(p)
        except (KeyError,ValueError,TypeError):return 'Unknown or conflicting NHL score basis, stage or shootout winner; no inferred adjustment'
    else:
        required=dict(score_scope='full_game_including_extra_innings',score_representation='official_cumulative_runs',completion='nine_inning_format_completed_with_applicable_extra_innings',pitcher_conditions='action',scheduled_innings=9)
        if any(p.get(k)!=v for k,v in required.items()):return 'Missing MLB completion, cumulative extra-inning score or action terms; listed-pitcher/shortened settlement unsupported'
        n=p.get('final_inning');half=p.get('final_half')
        if type(n) is not int or n<9 or n>100 or half not in ('top','bottom') or p.get('game_ended') not in ('completed_half','home_lead_bottom_unneeded','walkoff'):
            return 'Missing explicit completed MLB game/inning evidence'
        h,a=p['home_score'],p['away_score'];ended=p['game_ended']
        if h==a or (half=='top' and (ended!='home_lead_bottom_unneeded' or h<=a)) or (half=='bottom' and (ended=='home_lead_bottom_unneeded' or (ended=='walkoff' and h<=a))):
            return 'Conflicting MLB final half, winner or completion'
        if p.get('resume_status') not in ('not_suspended','resumed_completed'):return 'Unknown suspension/resumption evidence'
        if p['resume_status']=='resumed_completed':
            try:
                if p.get('resumed_game_id')!=p['target']['event']['game_id'] or not time(p['target']['event']['scheduled_start'])<=time(p['resumed_at'])<=time(p['source_at']):return 'Conflicting resumed MLB game or clock'
            except (KeyError,ValueError,TypeError):return 'Missing resumed MLB identity/time'
    return None
