"""Four-school men's Division I result scope atop the shared resolution engine."""
from app.resolution.core import (NCAAB_VERSIONS as VERSIONS, record, validate,
    emit_records, target, resolve, revision_error)
from app.normalization.ncaab_first_half import COMPLETION
SCHOOLS={'NCAAB:M:D1:'+name for name in ('ALA','AAMU','MIAFL','MIAOH')}
OVERTIME='repeated_5_minutes'
SCORING='official_final_points_including_all_overtime'


def scope_error(event):
    # The normalizer validates explicit season-specific membership.
    return None


def sporting_error(p):
    if p.get('status') not in ('pending','final','cancelled','suspended','abandoned','postponed','shortened','forfeit','administrative_change','unknown'):
        return 'Unsupported NCAAB sporting status'
    reason=revision_error(p,'NCAAB')
    if reason:return reason
    if p['status']!='final':return None
    half=p.get('period')=='first_half'
    expected=dict(score_scope='first_20_minute_half' if half else 'full_game_including_overtime',
        score_representation='official_period_points' if half else SCORING,
        period_format='first_20_minute_half' if half else 'two_20_minute_halves',
        completion=COMPLETION if half else 'all_regulation_and_applicable_overtime',
        result_basis='on_field_period_score')
    for key,value in expected.items():
        if p.get(key)!=value:return 'Missing or conflicting NCAAB '+key+'; no quarter inheritance, score reconstruction or overtime addition'
    if type(p.get('regulation_periods_completed')) is not int or p['regulation_periods_completed']!=(1 if half else 2):
        return 'Missing or conflicting completed college basketball half evidence'
    if not half:
        if p.get('overtime_format')!=OVERTIME or p.get('extra_periods_complete') is not True or type(p.get('extra_periods_completed')) is not int or not 0<=p['extra_periods_completed']<=100:
            return 'Missing or ambiguous college basketball overtime representation/completion'
    if any(type(p.get(k)) is not int or not 0<=p[k]<=1000 for k in ('home_score','away_score')):
        return 'Unsupported or missing explicit NCAAB period scores'
    if not half and p['home_score']==p['away_score']:
        return 'Tied college full-game result is exceptional, not normal completed overtime'
    return None
