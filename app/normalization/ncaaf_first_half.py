"""Bounded 2026 college H1 review, with no FBS-to-FCS contract inheritance."""
from app.normalization.ncaaf import event_key,EVENT_FIELDS
from app.normalization.ncaaf_lines import TERM_FIELDS
from app.normalization.first_half import COMPLETION,PERIOD,validate_payout,score_value
SERIES={'moneyline':'KXNCAAF1H','spread':'KXNCAAF1HSPREAD','total':'KXNCAAF1HTOTAL'}

def scope(identity):
    return identity.get('competition')=='NCAAF' and identity.get('period')==PERIOD and identity.get('family') in SERIES

def validate_descriptor(event,d):
    if event['season']!='2026':raise ValueError('NCAAF H1 rules reviewed for 2026 only')
    expected=dict(offered='pregame',regulation='first_two_15_minute_quarters',overtime='excluded',
        overtime_format='not_applicable',overtime_scoring='excluded_from_first_half',
        normal_completion=COMPLETION,settlement_score='first_half_only',tied_score='evaluate_actual_score_predicate')
    for field,value in expected.items():
        if d.get(field)!=value:raise ValueError('NCAAF First half '+field+' missing or conflicting; later scoring excluded')
    divisions=sorted(set(event['subdivisions'].values()))
    if d.get('subdivision_scope')!=divisions:raise ValueError('NCAAF first-half contract subdivision scope missing or conflicting')
    if divisions==['FCS']:raise ValueError('FCS-only first-half contract not reviewed; no FBS or NFL inheritance')
    validate_payout(d)
