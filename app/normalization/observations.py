"""Separate, immutable event enrichment. Never assigns canonical event identity."""
from dataclasses import dataclass
import re
from app.models.core import Event, Venue
from .registry import Registry, Resolution


@dataclass(frozen=True)
class ParticipantResolution:
    position: int
    name: str | None
    native_id: str | None
    role: str | None
    resolution: Resolution
    extraction: str


@dataclass(frozen=True)
class NormalizedEvent:
    observation: Event
    environment: str | None
    league: Resolution
    participants: tuple[ParticipantResolution, ...]
    extraction_status: str
    extraction_provenance: tuple[str, ...]
    # Unassociated native home/away IDs stay separate from title-order identities.
    native_roles: tuple[tuple[str, str], ...] = ()


def enrich_event(event: Event, *, environment=None, registry=None) -> NormalizedEvent:
    registry = registry or Registry.load()
    venue = event.raw.ref.venue
    payload = event.raw.decode()
    provenance = []
    roles = []
    inputs = []
    league_name = event.league
    league_id = None
    row = None
    if venue == Venue.POLYMARKET_US:
        rows = payload.get('events', [])
        matches = [x for x in rows if str(x.get('id')) == event.raw.ref.event_id]
        if len(matches) == 1:
            row = matches[0]
            lg = payload.get('league', {})
            league_name = lg.get('name', league_name)
            league_id = lg.get('id')
            for i, team in enumerate(row.get('teams', [])):
                inputs.append((team.get('name'), team.get('id'), team.get('ordering'),
                               f'events[id={event.raw.ref.event_id}].teams[{i}]', team.get('league')))
            provenance.append('pmus-event-teams:v1; array order; no home/away inference')
    elif venue == Venue.PROPHETX:
        matches = [x for x in payload.get('data', {}).get('sport_events', [])
                   if str(x.get('event_id')) == event.raw.ref.event_id]
        if len(matches) == 1:
            row = matches[0]
            league_name = row.get('tournament_name', league_name)
            league_id = row.get('tournament_id')
            for i, team in enumerate(row.get('competitors', [])):
                inputs.append((team.get('name'), team.get('id'), team.get('side'),
                               f'data.sport_events[event_id={event.raw.ref.event_id}].competitors[{i}]', None))
            provenance.append('prophetx-competitors:v1; array order and explicit side')
    elif venue == Venue.KALSHI:
        rows = payload.get('events', [])
        if isinstance(payload.get('event'), dict):
            rows = [payload['event']]
        matches = [x for x in rows if x.get('event_ticker') == event.raw.ref.event_id]
        if len(matches) == 1:
            row = matches[0]
            series_league = {'KXNFLGAME':'NFL', 'KXMLBGAME':'MLB', 'KXNBAGAME':'NBA', 'KXNCAAFGAME':'NCAAF', 'KXNCAAFCSGAME':'NCAAF', 'KXNCAAMBGAME':'NCAAB'}.get(row.get('series_ticker'))
            if series_league:
                league_name = series_league
                # Bounded observed format; deliberately no ticker substring decoding.
                pair = re.fullmatch(r'([\w .\'-]+) vs\.? ([\w .\'-]+)', row.get('title', ''))
                if pair and len(re.findall(r' vs\.? ', row.get('title', ''))) == 1:
                    inputs = [(n, None, None, 'event.title:kalshi-game-vs:v1', None) for n in pair.groups()]
                    provenance.append('kalshi-game-vs:v1; series gated; title order; roles unknown')
            for milestone in payload.get('milestones', []):
                details = milestone.get('details', {})
                if details.get('main_game_event_ticker') == event.raw.ref.event_id:
                    for role in ('home', 'away'):
                        if details.get(role + '_team_id'):
                            roles.append((role, str(details[role + '_team_id'])))
            if roles:
                provenance.append('milestone.details native role IDs retained; identity relationship unestablished')
    # Shared participants are a supported explicit input for any adapter. Unknown
    # title-only Novig formats are never converted into invented team evidence.
    if not inputs and event.participants:
        inputs = [(n, None, None, f'Event.participants[{i}]', None) for i, n in enumerate(event.participants)]
        provenance.append('shared-participants:v1')
    league = registry.resolve('league', league_name, venue=venue, environment=environment, native_id=league_id)
    if event.league and league.status == 'resolved':
        supplied = registry.resolve('league', event.league)
        if supplied.canonical_id != league.canonical_id:
            league = registry.result('conflicting', (*league.candidates, *supplied.candidates),
                                     (*league.provenance, 'observation-native-league-disagreement'), event.league)
    participants = []
    for i, (name, native, role, extraction, team_league) in enumerate(inputs):
        native = None if native is None else str(native)
        if league.status != 'resolved':
            result = registry.result('unknown', provenance=('unresolved-event-league',), name=name, native_id=native)
        else:
            result = registry.resolve('team', name, league=league.canonical_id, venue=venue,
                                      environment=environment, native_id=native)
            if team_league and registry.resolve('league', team_league).canonical_id != league.canonical_id:
                result = registry.result('conflicting', result.candidates,
                                         (*result.provenance, 'team-event-league-disagreement'), name, native)
        if event.participants and len(event.participants) != len(inputs):
            result = registry.result('conflicting', result.candidates,
                                     (*result.provenance, 'shared-native-participant-count-disagreement'), name, native)
        if event.participants and extraction != f'Event.participants[{i}]' and i < len(event.participants):
            supplied = registry.resolve('team', event.participants[i], league=league.canonical_id) if league.status == 'resolved' else None
            if supplied and supplied.canonical_id != result.canonical_id:
                result = registry.result('conflicting', (*result.candidates, *supplied.candidates),
                                         (*result.provenance, 'shared-native-participant-disagreement'), name, native)
        participants.append(ParticipantResolution(i, name, native, role, result, extraction))
    return NormalizedEvent(event, environment, league, tuple(participants),
                           'extracted' if inputs else 'unknown', tuple(provenance or ['unsupported-native-format:v1']), tuple(roles))
