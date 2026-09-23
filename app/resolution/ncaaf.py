"""Six-school 2026 college score contracts; shared journal and payout dispatch."""
from app.resolution.core import (NCAAF_VERSIONS as VERSIONS, record, validate,
    emit_records, target, resolve, revision_error)
from app.normalization.ncaaf_lines import OVERTIME, SCORING

SCHOOLS={'NCAAF:ALA','NCAAF:AAMU','NCAAF:MIAFL','NCAAF:MIAOH','NCAAF:NDSU','NCAAF:SDAKST'}


def scope_error(event):
    if set(event['subdivisions'].values())=={'FCS'}:
        return 'Unsupported FCS-only resolution contract; no FBS or NFL rule inheritance'
    return None


def sporting_error(p):
    if p.get('status') not in ('pending','final','cancelled','suspended','abandoned','postponed','shortened','forfeit','administrative_change','unknown'):
        return 'Unsupported NCAAF sporting status'
    reason=revision_error(p,'NCAAF')
    if reason:return reason
    if p['status']!='final':return None
    half=p.get('period')=='first_half'
    expected=dict(score_scope='first_half_only' if half else 'full_game_including_college_overtime',
        score_representation='official_period_points' if half else SCORING,
        completion='first_two_quarters_definitively_completed' if half else 'all_regulation_and_applicable_college_overtime',
        result_basis='on_field_period_score')
    for key,value in expected.items():
        if p.get(key)!=value:return 'Missing or conflicting NCAAF '+key+'; no reconstruction or overtime addition'
    if type(p.get('regulation_periods_completed')) is not int or p['regulation_periods_completed']!=(2 if half else 4):
        return 'Missing or conflicting completed college period evidence'
    if not half:
        if p.get('overtime_format')!=OVERTIME or p.get('extra_periods_complete') is not True or type(p.get('extra_periods_completed')) is not int or not 0<=p['extra_periods_completed']<=100:
            return 'Missing or ambiguous college possession-series / later-try overtime evidence'
    if any(type(p.get(k)) is not int or not 0<=p[k]<=1000 for k in ('home_score','away_score')):
        return 'Unsupported or missing explicit NCAAF period scores'
    if not half and p['home_score']==p['away_score']:
        return 'Tied college full-game result is exceptional, not normal completed overtime'
    return None
