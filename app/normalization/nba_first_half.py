"""NBA H1 scope; no football, full-game or ACHIEVEMENTS tie-rule inheritance."""
from app.normalization.nba import event_key, EVENT_FIELDS
from app.normalization.first_half import COMPLETION, PERIOD, validate_payout
SERIES={'moneyline':'KXNBA1HWINNER','spread':'KXNBA1HSPREAD','total':'KXNBA1HTOTAL'}
TERM_FIELDS={'completion','cancellation','suspension','postponement','void','corrections','settlement_fee','abandonment','shortened_game','refund','forfeit','venue_change'}

def scope(identity):
    return identity.get('competition')=='NBA' and identity.get('period')==PERIOD and identity.get('family') in SERIES

def validate_descriptor(event,d):
    expected=dict(offered='pregame',regulation='first_two_12_minute_quarters',overtime='excluded',
        overtime_format='not_applicable',normal_completion=COMPLETION,
        settlement_score='first_half_only',tied_score='evaluate_actual_score_predicate')
    for field,value in expected.items():
        if d.get(field)!=value:raise ValueError('NBA First half '+field+' missing or conflicting; completed second quarter required')
    validate_payout(d)

def score_value(identity,observation):
    from app.normalization.first_half import score_value as shared_score
    if not scope(identity):raise ValueError('Explicit completed NBA first-half score required')
    return shared_score(identity,observation)
