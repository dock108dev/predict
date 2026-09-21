"""Invented NFL/provider payloads. No captured provider data or live access."""
from dataclasses import replace
from datetime import timedelta, datetime
from functools import lru_cache
import json

from .adapter import Response
from .enrichment import Assessment
from .records import EVENT, SourceRevision


@lru_cache(maxsize=1)
def terms():
    from app.arbitrage_example import synthetic_inputs
    from app.edge_contracts import MarketTerms
    from app.models.core import MarketType
    parents, matcher, _, _, rows = synthetic_inputs()
    return MarketTerms(canonical_event_id=next(iter(parents.envelope()['data']['canonicals'])),
        canonical_market_id=next(iter(matcher.envelope()['data']['decisions'].values()))['canonical_market_id'],
        league='NFL', scheduled_start=datetime.fromisoformat(next(iter(parents.envelope()['data']['observations'].values()))['start']),
        market_type=MarketType.MONEYLINE, period='full_game', phase='pregame', outcomes=('NFL:ATL', 'NFL:PIT'),
        line=None, rules_profile_json=json.dumps(rows[0]['profile'], sort_keys=True))


def before(seconds=60): return (terms().scheduled_start - timedelta(seconds=seconds)).isoformat()


def source(known_at=None, assessed=True, identity='source-synthetic-1'):
    return SourceRevision(id=identity, effective_at=before(120), known_at=known_at or before(120),
        origin='pinnacle' if assessed else None, family='pinnacle' if assessed else None,
        copied_from=() if assessed else None,
        evidence=('synthetic:invented external-only lineage assumption; not provider qualification',) if assessed else ())


def assessment(known_at=None, pairing=True, rules=True):
    return Assessment(known_at=known_at or before(120), effective_at=before(120), target=terms(),
        rules_json=terms().rules_profile_json if rules else None, pairing_verified=pairing,
        phase='pregame', period='full_game',
        evidence=('synthetic:invented pairing, event mapping and rules test assumptions',))


def payload():
    # Prices are numeric tokens with intentionally exact spelling and precision.
    return ('{"id":"' + EVENT + '","sport_key":"americanfootball_nfl",'
        '"home_team":"Atlanta Falcons","away_team":"Pittsburgh Steelers",'
        '"commence_time":"' + terms().scheduled_start.isoformat() + '",'
        '"bookmakers":[{"key":"pinnacle","sid":"book-event-0001","markets":[{"key":"h2h",'
        '"sid":"market-01","last_update":"' + before(65) + '","outcomes":['
        '{"name":"Atlanta Falcons","price":1.90000000000000000001,"sid":"01"},'
        '{"name":"Pittsburgh Steelers","price":2.1000,"sid":"02"}]}]}]}').encode()


class FixtureClock:
    def __init__(self, at=None): self.at = datetime.fromisoformat(at or before())
    def now(self): return self.at.isoformat()
    async def sleep(self, seconds):
        import asyncio
        self.at += timedelta(seconds=seconds)
        await asyncio.sleep(0)


class FixtureTransport:
    def __init__(self, responses): self.responses = iter(responses); self.calls = 0; self.closed = False
    async def request(self, request):
        self.calls += 1
        result = next(self.responses)
        if isinstance(result, BaseException): raise result
        return result
    async def aclose(self): self.closed = True
