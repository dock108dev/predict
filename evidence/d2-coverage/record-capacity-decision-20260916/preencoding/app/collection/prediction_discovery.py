"""NFL event discovery via bounded generic catalog, excluding embedded league panels."""
from app.adapters.polymarket_us import PolymarketUSAdapter

class NFLPolymarketAdapter(PolymarketUSAdapter):
    async def _get(self,path,params=None):
        if path=='/v2/leagues/nfl/events':
            # Official generic event listing avoids the league page's large nested panels.
            path='/v1/events'
            params={**(params or {}),'tagSlug':'nfl','active':'true','closed':'false',
                    'orderBy':'startTime','orderDirection':'asc',
                    'sportsMarketTypes':'football_team_full_game_winner'}
        return await super()._get(path,params)


def participant_mapping(event):
    from app.normalization.observations import enrich_event
    from app.normalization.registry import Registry
    normalized=enrich_event(event,environment='production');registry=Registry.load();mapping={}
    for p in normalized.participants:
        value=p.resolution.canonical_id
        if value is None and isinstance(p.name,str) and ' ' in p.name:
            abbreviation,nickname=p.name.split(' ',1)
            a=registry.resolve('team',abbreviation,league='NFL');b=registry.resolve('team',nickname,league='NFL')
            if a.status==b.status=='resolved' and a.canonical_id==b.canonical_id:value=a.canonical_id
        mapping[p.name]=value
    return normalized,mapping


def validate_pregame(event, market=None):
    from datetime import datetime,timezone
    from .run_spec import time_value
    if event.scheduled_start is None or event.scheduled_start<=datetime.now(timezone.utc):
        raise ValueError('kickoff or unknown schedule')
    if event.raw.ref.venue.value=='polymarket_us':
        rows=[r for r in event.raw.decode().get('events',[]) if str(r.get('id'))==event.raw.ref.event_id]
        if len(rows)!=1:raise ValueError('ambiguous event identity')
        row=rows[0]
        if row.get('live') is True or row.get('ended') is True or row.get('closed') is True or row.get('period') not in (None,'NS') or row.get('rescheduledFromGameId') not in (None,0,'0'):
            raise ValueError('event phase or rescheduling changed')
        if market is not None:
            from app.adapters.polymarket_us import next_market_data
            native=next_market_data(market)
            if native.get('gameStartTime') and time_value(native['gameStartTime'])!=event.scheduled_start:
                raise ValueError('market and event schedule conflict')
