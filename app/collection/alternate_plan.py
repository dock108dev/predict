"""Pure complete-scope alternate request plan. No paid dispatch authority."""
from .current_aggregate_policy import POLICY
from app.reference.product import SPORT_KEYS


def plan(events_by_sport):
    requests = []
    counts = {}
    for sport, events in events_by_sport.items():
        ids = sorted({event['id'] for event in events})
        counts[sport] = len(ids)
        for eid in ids:
            requests.append(dict(sport=sport, event_id=eid,
                path='/v4/sports/' + SPORT_KEYS[sport] + '/events/' + eid + '/odds',
                params=dict(bookmakers=','.join(POLICY.bookmakers),
                    markets='alternate_spreads,alternate_totals', oddsFormat='decimal', dateFormat='iso'),
                maximum_credits=2))
    # Interleave leagues so a slow or interrupted cycle does not put all of
    # NCAAB/MLB/NHL behind the much larger football event rosters. Every event
    # remains in the same manifest and credit envelope.
    from collections import deque
    pools={sport:deque(r for r in requests if r['sport']==sport) for sport in events_by_sport}
    requests=[]
    while any(pools.values()):
        for pool in pools.values():
            if pool:requests.append(pool.popleft())
    extra = 2 * len(requests)
    return dict(schema='predict-alternate-plan-1', dispatch_enabled=False,
        reason='Additional paid routes require a larger cycle/day authority',
        events_by_sport=counts, event_requests=len(requests), requests=requests,
        interval_seconds=POLICY.interval_seconds, featured_credits_per_cycle=18,
        alternate_maximum_credits_per_cycle=extra, total_maximum_credits_per_cycle=18+extra,
        total_maximum_credits_per_operating_day=56*(18+extra),
        authorized_cycle=18, authorized_day=1008,
        credit_basis='Two unique alternate markets times one group of up to ten bookmakers; actual returned-market charges can be lower',
        freshness='900-second acquisition cadence plus provider quote age; no continuous fresh-coverage guarantee',
        denominator='Complete event route; price offerings and alternate availability remain unknown until event odds responses')
