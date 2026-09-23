"""Shared dashboard selection policy; numerical calculation engines stay separate."""
from app.fees.engine import number

CHOICES = {
    'period': ('', 'full_game', 'first_half', 'second_half', 'quarter_1', 'quarter_2',
               'quarter_3', 'quarter_4', 'first_3', 'first_5', 'first_6', 'regulation_9',
               'period_1', 'period_2', 'period_3', 'season'),
    'family': ('', 'moneyline', 'spread', 'total', 'futures'),
    'view': ('arb', 'ev', 'research'),
    'sort': ('roi', 'dollars'),
    'scenario': ('cent', 'direct', 'unknown'),
    'freshness': ('', 'usable', 'unavailable'),
    'positive': ('true', 'false'),
}


def validate_choice(key, value):
    if value not in CHOICES[key]:
        raise ValueError('Unknown ' + key + ' selection')


def validate_choices(query):
    # HTTP MultiDicts must not collapse duplicate choices before validation.
    if hasattr(query, 'getall') and any(len(query.getall(k)) != 1 for k in query):
        raise ValueError('Duplicate selection')
    for key in CHOICES:
        if key in query:
            validate_choice(key, query[key])


def decimal_input(value, label):
    # Reuse the existing exact numeric policy before loading saved datasets.
    if type(value) not in (str, int, float) or len(str(value)) > 128:
        raise ValueError('Invalid ' + label)
    return number(value)


def validate_http_query(query):
    validate_choices(query)
    decimal_input(query.get('quantity', '100'), 'quantity')
    if query.get('probability'):
        decimal_input(query['probability'], 'probability')


def validate_assumptions(value):
    if not isinstance(value, dict) or len(value) > 256:
        raise ValueError('Invalid assumptions object')
    for key, entry in value.items():
        if not isinstance(key, str) or not isinstance(entry, dict) or set(entry) - {'probability', 'basis'}:
            raise ValueError('Invalid assumption')
        if not isinstance(entry.get('basis', ''), str) or len(entry.get('basis', '')) > 2000:
            raise ValueError('Invalid assumption basis')
        if entry.get('probability') not in (None, ''):
            decimal_input(entry['probability'], 'probability')
            if not entry.get('basis', '').strip():
                raise ValueError('Probability needs an explicit source or basis')
    return value
