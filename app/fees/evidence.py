"""Effective terms and periodic source checks are different clocks."""
from app.comparison.current_dependencies import instant


def applies(evidence, at):
    """Check a captured fee's prospective authority, including provider cutovers."""
    if not evidence or at < instant(evidence['reviewed_at']):
        return False
    until = evidence.get('review_before')
    return at < instant(until) if until else evidence.get('standing_public_terms') is True


def earliest_end(*values):
    return min((value for value in values if value), key=instant, default=None)
