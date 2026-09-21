"""Read-only interpretation of saved lifecycle and capture evidence.

Events must include the whole session, ordered newest first. Counts are recorded
snapshots, not additive events: never sum duplicate shutdown/accounting rows.
"""


def interpret_session(session, events):
    def count(*keys):
        values = [e['detail'][k] for e in events for k in keys
                  if type(e['detail'].get(k)) is int and e['detail'][k] >= 0]
        return max(values) if values else None

    unprocessed = count('unprocessed', 'queued_unprocessed')
    rejected = count('rejected')
    messages = count('messages', 'stream_messages')
    shutdown = [e['detail'] for e in events if e['kind'] == 'shutdown']
    reason = next((d.get('first_stop', {}).get('reason') or d.get('reason')
                   for d in shutdown if d.get('first_stop', {}).get('reason') or d.get('reason')), None)
    # Older bounded collectors emitted a "gap" even for clean finite endings.
    # An explicit zero backlog + censored interval alone is not evidence of loss.
    def gap(e):
        d = e['detail']
        return e['kind'] == 'gap' and not (
            d.get('queued_unprocessed') == 0 and d.get('continuous_coverage') is False
            and d.get('censored') is True
            and d.get('reason') in ('Scan deadline reached', 'Time limit reached', 'Stopped by owner', 'Stopped by you'))

    gaps = bool(unprocessed or rejected) or any(gap(e) or e['kind'] in ('disconnect', 'restart') for e in events)
    failure = any(e['kind'] == 'failure' for e in events)
    lifecycle = session['state']
    coverage = 'gaps' if gaps else 'saved' if (
        lifecycle == 'complete' and shutdown and unprocessed == 0 and rejected == 0 and not failure
    ) else 'unknown'
    explanation = {
        'gaps': 'Saved observations are available, but capture has recorded gaps.',
        'saved': 'Observations were saved successfully within the bounded capture. Continuous coverage is not claimed.',
        'unknown': 'The saved evidence does not establish capture completeness.',
    }[coverage]
    label = {'gaps': 'Saved with capture gaps', 'saved': 'Saved successfully', 'unknown': 'Saved · coverage unknown'}[coverage]
    if lifecycle == 'running':
        label = 'Unfinished record' + (' · capture gaps' if gaps else ' · coverage unknown')
        explanation = 'No terminal outcome was saved. ' + explanation
    elif lifecycle in ('failed', 'interrupted'):
        label = lifecycle.capitalize() + (' · capture gaps' if gaps else ' · coverage unknown')
        explanation = 'The session ended ' + lifecycle + '. ' + explanation
    origin = {'current': 'Captured from a live feed', 'synthetic': 'Invented synthetic observations',
              'historical': 'Imported historical observations'}[session['evidence_class']]
    return dict(lifecycle=lifecycle, coverage=coverage, label=label, explanation=explanation,
                stop_reason=reason, unprocessed=unprocessed, rejected=rejected, messages=messages,
                origin=origin, current_status='Saved observations—not live')
