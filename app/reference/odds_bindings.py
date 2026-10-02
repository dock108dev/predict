"""Public-catalog mappings only; no book availability or settlement inference.

Evidence: evidence/source-bindings-20260929/public/manifest.json.
Network/credentials are deliberately absent from this module.
"""
from app.reference.product import SPORT_KEYS, time

PERIOD_VERSION = 'odds-aggregate-period-1'
BOOKS = ('novig', 'prophetx', 'pinnacle', 'draftkings', 'betmgm')
CHAMPIONSHIPS = dict(NFL='americanfootball_nfl_super_bowl_winner',
    NBA='basketball_nba_championship_winner', MLB='baseball_mlb_world_series_winner',
    NHL='icehockey_nhl_championship_winner', NCAAF='americanfootball_ncaaf_championship_winner',
    NCAAB='basketball_ncaab_championship_winner')


def period_binding(sport, key):
    suffixes = ({'h1': 'first_half'} if sport in ('NFL', 'NBA', 'NCAAF', 'NCAAB') else
                {'1st_3_innings': 'first_3', '1st_5_innings': 'first_5'} if sport == 'MLB' else
                {'p1': 'period_1', 'p2': 'period_2', 'p3': 'period_3'} if sport == 'NHL' else {})
    for suffix, period in suffixes.items():
        for base in ('h2h', 'h2h_3_way', 'spreads', 'totals'):
            if key == base + '_' + suffix:
                return dict(base=base, period=period, settlement='unverified',
                            outcome_form='three_way' if base == 'h2h_3_way' else 'two_way')
    return None


def normalize_event(body, sport, received_at):
    """Single-event odds response, retaining the ORIGINAL body hash and all fields."""
    from app.reference.odds_sample import normalize
    return normalize(body, sport, received_at, _event_object=True)


def select_event(events, as_of):
    """One NFL event, next seven days, stable tie-break; no fallback or polling."""
    now = time(as_of)
    eligible = []
    seen = set()
    for event in events:
        if event.get('sport_key') != SPORT_KEYS['NFL']:
            raise ValueError('Unexpected sport in discovery')
        if not all(isinstance(event.get(k), str) and event[k] for k in ('id','home_team','away_team')):
            raise ValueError('Incomplete event identity')
        if event['home_team'] == event['away_team']:
            raise ValueError('Participants are not distinct')
        if event['id'] in seen:
            raise ValueError('Duplicate discovery event identity')
        seen.add(event['id'])
        delta = (time(event['commence_time']) - now).total_seconds()
        if 0 < delta <= 7 * 86400:
            eligible.append(event)
    return min(eligible, key=lambda e:(time(e['commence_time']), e['id'])) if eligible else None


def acquisition_plan(event_id):
    """Reviewable, inert specification. No key, transport, activation or attempt ID."""
    if not isinstance(event_id, str) or not event_id or not event_id.isalnum():
        raise ValueError('Invalid event ID')
    return dict(endpoint=f'/v4/sports/americanfootball_nfl/events/{event_id}/odds',
                params=dict(bookmakers=','.join(BOOKS), markets='h2h_h1,spreads_h1,totals_h1',
                            oddsFormat='decimal', dateFormat='iso', includeLinks='true',
                            includeSids='true', includeBetLimits='true'), maximum_credits=3,
                maximum_requests_including_discovery=2, authorized=False)
