"""Reviewed NFL pregame H1 scope; source annotations remain bound to receipts."""
from app.normalization.nfl_lines import event_key, EVENT_FIELDS, TERM_FIELDS
PERIOD='first_half'
SERIES={'moneyline':'KXNFL1H','spread':'KXNFL1HSPREAD','total':'KXNFL1HTOTAL'}
COMPLETION='first_two_quarters_definitively_completed'

def scope(identity):
    return identity.get('competition')=='NFL' and identity.get('period')==PERIOD and identity.get('family') in SERIES

def validate_descriptor(event,d):
    expected=dict(offered='pregame',regulation='first_two_15_minute_quarters',overtime='excluded',
                  overtime_format='not_applicable',normal_completion=COMPLETION,
                  settlement_score='first_half_only',tied_score='evaluate_actual_score_predicate')
    for field,value in expected.items():
        if d.get(field)!=value:raise ValueError('NFL First half '+field+' missing or conflicting; second-half / overtime scoring excluded')
    from app.normalization.first_half import validate_payout
    validate_payout(d)


def score_value(identity,observation):
    from app.normalization.first_half import score_value as shared_score
    if not scope(identity):raise ValueError('Explicit completed first-half score required')
    return shared_score(identity,observation)
