"""Bounded public identity diagnostics at the native normalization boundary.

No exception payloads or wire bodies leave this module. Unknown exceptions keep
an explicit type and stage instead of being mistaken for a financial refusal.
"""
VERSION = 'native-normalization-trace-1'
REASONS = {
    'Conflicting source-local identity': 'source_identity_conflict',
    'Native identity or predicate incomplete': 'native_binding_incomplete',
    'Outside common sporting scope': 'outside_sporting_scope',
    'Book identity conflict': 'book_identity_conflict',
    'Exact score outcome requires supported orientation': 'score_operator_unsupported',
    'Partial winner requires a named team predicate': 'winner_participant_missing',
    'Invalid bounded book depth': 'invalid_book_depth',
}


def refusal(exc, event, market, binding, exclusion, source):
    reason = REASONS.get(str(exc), 'normalization_exception_'+type(exc).__name__)
    return dict(version=VERSION, source=source, event_id=market['event_id'],
        market_id=market['id'], stage='normalized', disposition='rejected',
        reason=reason, reason_code=reason, exception_type=type(exc).__name__,
        sport=(event or {}).get('competition'), family=market.get('market_type'),
        binding_revision=(binding or {}).get('sha256'),
        binding_status=(binding or {}).get('status'),
        binding_blockers=(binding or {}).get('blockers', [])[:16],
        catalog_exclusion=exclusion,
        expected=dict(distinct_participants=2, roles=['home','away'], binding='typed_native_predicate_or_display'),
        observed=dict(identity=(event or {}).get('identity'),
            participants=(event or {}).get('participants'),
            roles=(event or {}).get('source_participant_roles'),
            season=(event or {}).get('season'), stage=(event or {}).get('stage'),
            scheduled_start=(event or {}).get('scheduled_start')),
        owner='app.collection.current_sink.normalized_records',
        next_action='Inspect retained event/market facts and binding blockers; repair normalization before financial evaluation')
