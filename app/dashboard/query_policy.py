"""Shared dashboard selection policy; numerical calculation engines stay separate."""
from app.fees.engine import number
from app.dashboard.local_security import PublicRequestError

CHOICES = {
    'period': ('', 'full_game', 'first_half', 'second_half', 'quarter_1', 'quarter_2',
               'quarter_3', 'quarter_4', 'first_3', 'first_5', 'first_6', 'regulation_9',
               'period_1', 'period_2', 'period_3', 'season'),
    'family': ('', 'moneyline', 'spread', 'total', 'futures'),
    'view': ('feed', 'arb', 'ev', 'research'),
    'sort': ('roi', 'dollars'),
    'scenario': ('cent', 'direct', 'unknown'),
    'freshness': ('', 'usable', 'unavailable'),
    'positive': ('true', 'false'),
}


def validate_choice(key, value):
    if value not in CHOICES[key]:
        raise PublicRequestError('Unknown ' + key + ' selection')


def validate_unique_query(query):
    # HTTP MultiDicts must not collapse duplicate choices before validation.
    if hasattr(query, 'getall') and any(len(query.getall(k)) != 1 for k in query):
        raise PublicRequestError('Duplicate selection')


def validate_choices(query):
    validate_unique_query(query)
    for key in CHOICES:
        if key in query:
            validate_choice(key, query[key])


def decimal_input(value, label):
    # Reuse the existing exact numeric policy before loading saved datasets.
    if type(value) not in (str, int, float) or len(str(value)) > 128:
        raise PublicRequestError('Invalid ' + label)
    try:
        return number(value)
    except (ValueError, ArithmeticError):
        raise PublicRequestError('Invalid ' + label + '; use a finite number within supported precision') from None


def validate_http_query(query):
    validate_choices(query)
    decimal_input(query.get('quantity', '100'), 'quantity')
    if query.get('probability'):
        decimal_input(query['probability'], 'probability')


def validate_assumptions(value):
    if not isinstance(value, dict) or len(value) > 256:
        raise PublicRequestError('Invalid assumptions object')
    for key, entry in value.items():
        if not isinstance(key, str) or not isinstance(entry, dict) or set(entry) - {'probability', 'basis'}:
            raise PublicRequestError('Invalid assumption')
        if not isinstance(entry.get('basis', ''), str) or len(entry.get('basis', '')) > 2000:
            raise PublicRequestError('Invalid assumption basis')
        if entry.get('probability') not in (None, ''):
            decimal_input(entry['probability'], 'probability')
            if not entry.get('basis', '').strip():
                raise PublicRequestError('Probability needs an explicit source or basis')
    return value
