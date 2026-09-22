"""College score-line review configuration; no implied FCS contract qualification."""
from app.normalization.ncaaf import event_key,EVENT_FIELDS

OVERTIME='ncaa_2026_possession_series_second_period_two_point_third_alternating_tries'
SCORING='official_final_points_including_all_extra_period_tries'
TERM_FIELDS={'completion','cancellation','suspension','postponement','void','corrections',
             'settlement_fee','shortened_game','abandonment','forfeit','venue_change'}


def validate_descriptor(event,d):
    if event['season']!='2026' or d.get('overtime_format')!=OVERTIME:
        raise ValueError('NCAAF reviewed 2026 college overtime format required')
    if d.get('overtime_scoring')!=SCORING:
        raise ValueError('NCAAF overtime points / try scoring unverified')
    if d.get('tied_score')!='exceptional_not_normal_completed_game':
        raise ValueError('NCAAF tied-score contract scope unknown or incompatible')
    if d.get('normal_completion')!='all_regulation_and_applicable_college_overtime':
        raise ValueError('NCAAF full completed-game score scope unknown')
    divisions=sorted(set(event['subdivisions'].values()))
    if d.get('subdivision_scope')!=divisions:
        raise ValueError('NCAAF source contract subdivision scope missing or conflicting')
    if d.get('source')=='kalshi' and divisions==['FCS']:
        raise ValueError('FCS-only native line contract not reviewed; no FBS contract inheritance')
