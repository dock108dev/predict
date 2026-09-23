"""NBA score-scope validation atop the shared immutable resolution framework."""
from app.resolution.core import (NBA_VERSIONS as VERSIONS, record, validate,
    emit_records, target, resolve)


def sporting_error(p):
    if p.get('status') not in ('pending','final','cancelled','suspended','abandoned','postponed','shortened','unknown'):
        return 'Unsupported NBA sporting status'
    if p.get('status')!='final':return None
    half=p.get('period')=='first_half'
    scope='first_half_end_of_second_quarter' if half else 'full_game_including_overtime'
    if p.get('score_scope')!=scope:
        return 'Unsupported NBA score scope: explicit end-Q2 or overtime-inclusive final required; regulation-only and other period scores are separate'
    if p.get('completion')!=('first_two_quarters_definitively_completed' if half else 'all_regulation_and_applicable_overtime'):
        return 'Unsupported NBA completion evidence'
    if type(p.get('regulation_periods_completed')) is not int or p['regulation_periods_completed']!=(2 if half else 4):
        return 'Missing or conflicting completed NBA quarter evidence'
    if not half and (p.get('overtime_complete') is not True or type(p.get('overtime_periods_completed')) is not int or not 0<=p['overtime_periods_completed']<=100):
        return 'Missing or conflicting NBA overtime completion evidence'
    if any(type(p.get(k)) is not int or not 0<=p[k]<=1000 for k in ('home_score','away_score')):
        return 'Unsupported or missing explicit NBA period scores'
    if not half and p['home_score']==p['away_score']:
        return 'Unsupported tied overtime-inclusive NBA final'
    return None
