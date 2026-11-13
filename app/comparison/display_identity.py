"""Canonical outcome grouping for displayed prices."""
from fractions import Fraction


def canonical_key(row):
    """Identify the displayed occurrence, selection and exact signed line."""
    selection, market = row.get('selection', {}), row.get('market', {})
    predicate = selection.get('predicate')
    participant = selection.get('participant')
    game = row.get('game_key')
    family, period = market.get('market'), market.get('period')
    if not predicate or not game or not family or not period:
        return None
    total_side = predicate in ('over', 'under')
    if not total_side and not participant:
        return None
    line = selection.get('signed_line', market.get('line'))
    if family in ('spread', 'total') and line is None:
        return None
    if line is not None:
        try:
            line = str(Fraction(line))
        except (ValueError, ZeroDivisionError):
            line = str(line)
    return (game, family, period, None if total_side else participant,
            predicate, line, selection.get('result_interpretation'))


def published_key(row):
    """Use the sealed display key, deriving it for earlier retained rows."""
    if 'display_outcome_key' not in row:
        return canonical_key(row)
    key = row['display_outcome_key']
    return tuple(key) if key is not None else None


def outcome_key(row):
    """Preserve a separate browsing group for each unresolved observation."""
    return published_key(row) or ('unresolved', row['id'])
