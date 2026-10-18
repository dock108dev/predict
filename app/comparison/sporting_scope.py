"""Shared scopes supported by exact current native predicate representations."""


def supported(league, family, period):
    if family not in ('moneyline', 'spread', 'total'):
        return False
    if period == 'full_game':
        return league in ('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL')
    if period == 'first_half':
        return league in ('NFL', 'NCAAF', 'NBA', 'NCAAB')
    return league == 'MLB' and (period == 'first_5' or period == 'first_3' and family == 'moneyline')
