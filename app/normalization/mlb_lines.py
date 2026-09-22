"""MLB line-only review bounds. Winner rules are never inherited."""
from app.normalization.mlb import event_key, EVENT_FIELDS as WINNER_EVENT_FIELDS

EVENT_FIELDS=('competition','sport',*WINNER_EVENT_FIELDS)
TERM_FIELDS={'completion','cancellation','suspension','postponement','void','corrections',
             'settlement_fee','shortened_game','abandonment','forfeit','venue_change',
             'resumed_game','tie','refund','pitcher_changes','format_changes'}
SEMANTICS={
    'extra_innings':'all_runs_including_automatic_runners',
    'pitcher_conditions':'action',
    'normal_completion':'nine_inning_format_completed_with_applicable_extra_innings',
    'tied_score':'evaluate_actual_score_predicate',
}


def validate_descriptor(event,d):
    for field,expected in SEMANTICS.items():
        if d.get(field)!=expected:
            raise ValueError('MLB '+field+' unknown or unsupported; explicit '+expected+' required')
    # A shortened official result is a separately retained exceptional outcome,
    # not an assertion that winner-market completion rules apply to lines.
    if d.get('completion_scope')!='normal_completed_game_only':
        raise ValueError('MLB shortened / incomplete game contract scope unsupported')
