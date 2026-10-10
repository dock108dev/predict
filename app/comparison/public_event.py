"""Versioned exact event facts, separate from quote/rule/cross-provider authority."""
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
import json
from pathlib import Path

from .current_dependencies import digest, encoded, instant, profile, public_tree

VERSION = 'comparison-public-event-binding-1'
PATH = Path(__file__).resolve().parents[1] / 'fixtures/comparison-public-event-v1.json'
SIDES = {'2165646': ('Long', '73', 'away', 'NFL:PHI', 'Philadelphia Eagles'),
         '2165647': ('Short', '62', 'home', 'NFL:JAX', 'Jacksonville Jaguars')}


def extract(graph, receipt):
    """Reduce one authentic complete graph; no whole-graph copy or quote refresh."""
    if not all(receipt.get(k) is True for k in ('eof', 'transport_complete', 'json_complete')) or receipt.get('status') != 200:
        raise ValueError('public_event_incomplete_response')
    events = graph.get('events') if isinstance(graph, dict) else None
    if not isinstance(events, list) or len(events) != 1 or str(events[0].get('id')) != '129629':
        raise ValueError('public_event_exact_result_conflict')
    event = events[0]
    matches = [(i, m) for i, m in enumerate(event.get('markets', [])) if str(m.get('id')) == '1083081']
    if len(matches) != 1:
        raise ValueError('public_event_market_membership_conflict')
    index, market = matches[0]
    prefix = '/events/0/markets/' + str(index)
    sides = market.get('marketSides')
    if not isinstance(sides, list) or len(sides) != 2 or {str(s.get('id')) for s in sides} != set(SIDES):
        raise ValueError('public_event_side_membership_conflict')
    members = []
    roles = {}
    for i, side in enumerate(sides):
        sid = str(side['id'])
        word, team_id, role, participant, name = SIDES[sid]
        team = side.get('team') or {}
        if (str(side.get('marketId')) != '1083081' or side.get('long') is not (word == 'Long') or
                str(side.get('teamId')) != team_id or str(team.get('id')) != team_id or
                team.get('name') != name or team.get('league') != 'nfl'):
            raise ValueError('public_event_side_attachment_conflict')
        event_teams = [t for t in event.get('teams', []) if str(t.get('id')) == team_id]
        if len(event_teams) != 1 or event_teams[0].get('name') != name or event_teams[0].get('league') != 'nfl':
            raise ValueError('public_event_participant_conflict')
        actual_role = team.get('ordering')
        if actual_role not in (None, '', role):
            raise ValueError('public_event_role_conflict')
        if actual_role == role:
            roles[role] = participant
        members.append(dict(native_key=['polymarket_us', '129629', '1083081', sid, word],
            team_id=team_id, participant_id=participant, name=name, role=actual_role or None,
            provider_ids=deepcopy(team.get('providerIds', [])), pointer=prefix + '/marketSides/' + str(i)))
    start = event.get('startTime')
    if start is not None:
        instant(start)
        if event.get('startDate') is not None and instant(event['startDate']) != instant(start):
            raise ValueError('public_event_schedule_conflict')
        if market.get('gameStartTime') is not None and instant(market['gameStartTime']) != instant(start):
            raise ValueError('public_event_schedule_conflict')
    game = event.get('gameId')
    provider_game = event.get('sportradarGameId')
    replacement = event.get('rescheduledFromGameId')
    role_complete = set(roles) == {'away', 'home'}
    scope_complete = (market.get('sportsMarketType') == 'football_team_full_game_winner' and
        market.get('marketType') == 'moneyline' and market.get('sportsMarketTypeV2') == 'SPORTS_MARKET_TYPE_MONEYLINE')
    occurrence_complete = role_complete and bool(game) and bool(provider_game) and bool(start) and replacement in (None, 0, '0')
    result = dict(version=VERSION, event_id='129629', market_id='1083081', membership=True,
        market_pointer=prefix, members=members, participant_roles=roles,
        occurrence=dict(game_id=str(game) if game else None, provider='sportradar', provider_game_id=provider_game,
            scheduled_start=start, rescheduled_from_game_id=str(replacement) if replacement is not None else None,
            replacement_field_present='rescheduledFromGameId' in event,
            original_start_time=event.get('originalStartTime'), period=event.get('period'),
            active=event.get('active'), closed=event.get('closed'), source_local_qualified=occurrence_complete,
            cross_source_qualified=False,
            reason='public_event_source_local_occurrence_observed' if occurrence_complete else
                'public_event_roles_or_occurrence_or_replacement_unqualified'),
        scope=dict(family='moneyline' if scope_complete else None, period='full_game' if scope_complete else None,
            line=None, sports_market_type=market.get('sportsMarketType'),
            overtime='included' if 'Overtime is included if played.' in market.get('description', '') else 'unknown',
            selection_meaning='selected_team_win' if scope_complete else None, description=market.get('description')),
        provenance=dict(response_sha256=receipt['wire_sha256'], decoded_sha256=receipt['decoded_sha256'],
            url=receipt['url'], request_started_at=receipt['started_at'], headers_at=receipt['headers_at'],
            response_finished_at=receipt['finished_at'], wire_bytes=receipt['wire_bytes'],
            decoded_bytes=receipt['decoded_bytes'], event_pointer='/events/0',
            game_pointer='/events/0/gameId', provider_game_pointer='/events/0/sportradarGameId',
            schedule_pointer='/events/0/startTime'),
        effective_from=receipt['finished_at'],
        effective_until=(instant(receipt['finished_at']) + timedelta(seconds=900)).isoformat(),
        interval_policy='New evidence-only 900-second local metadata reuse interval; no old facet/crosswalk renewal',
        historical_quote_applicability=False)
    result['binding_version'] = digest(result)
    validate(result)
    return result


def validate(value):
    public_tree(value)
    if len(encoded(value)) > 16384 or value.get('version') != VERSION or value.get('binding_version') != digest({k: v for k, v in value.items() if k != 'binding_version'}):
        raise ValueError('public_event_binding_revision_conflict')
    if value.get('event_id') != '129629' or value.get('market_id') != '1083081' or value.get('membership') is not True:
        raise ValueError('public_event_binding_identity_conflict')
    if not instant(value['effective_from']) < instant(value['effective_until']) or value['effective_from'] != value['provenance']['response_finished_at']:
        raise ValueError('public_event_binding_interval_conflict')
    if value['historical_quote_applicability'] is not False or value['occurrence']['cross_source_qualified'] is not False:
        raise ValueError('public_event_unproved_authority')
    if len(value['members']) != 2 or {m['native_key'][3] for m in value['members']} != set(SIDES):
        raise ValueError('public_event_binding_side_conflict')
    for member in value['members']:
        key = member['native_key']; expected = SIDES[key[3]]
        if key != ['polymarket_us', '129629', '1083081', key[3], expected[0]] or member['team_id'] != expected[1] or member['participant_id'] != expected[3] or member['role'] not in (None, expected[2]):
            raise ValueError('public_event_binding_side_conflict')
    roles = {m['role']: m['participant_id'] for m in value['members'] if m['role']}
    if value['participant_roles'] != roles:
        raise ValueError('public_event_binding_role_conflict')
    occurrence = value['occurrence']
    expected = (set(roles) == {'away', 'home'} and bool(occurrence['game_id']) and
        bool(occurrence['provider_game_id']) and bool(occurrence['scheduled_start']) and
        occurrence['rescheduled_from_game_id'] in (None, '0'))
    if occurrence['source_local_qualified'] != expected:
        raise ValueError('public_event_binding_occurrence_conflict')
    return value


@lru_cache(maxsize=1)
def _retained():
    return validate(json.loads(PATH.read_text()))


def retained():
    return deepcopy(_retained())


def registry(base, value=None):
    result = deepcopy(base)
    value = retained() if value is None else validate(value)
    result.setdefault('event_records', []).append(deepcopy(value))
    return result


def audit(q, registry, at, *, roles=None, observed_occurrence=None):
    source = q['source']
    key = [q['venue'], source['native_event_id'], source['native_market_id'], source['native_outcome_id'], source['native_side']]
    rows = registry.get('event_records', []) if registry else []
    if not isinstance(rows, list) or len(rows) > 16 or len(encoded(rows)) > 256 * 1024:
        raise ValueError('public_event_registry_capacity')
    matches = []
    for row in rows:
        validate(row)
        member = next((m for m in row['members'] if m['native_key'] == key), None)
        if member is not None:
            matches.append((row, member))
    if not matches:
        return None
    active = [(r, m) for r, m in matches if instant(r['effective_from']) <= at < instant(r['effective_until'])]
    if len(active) > 1:
        raise ValueError('public_event_binding_not_unique')
    row, member = active[0] if active else matches[-1]
    selection = q['binding']['selection']
    conflict = selection['participant'] != member['participant_id'] or selection['predicate'] != 'win' or selection['signed_line'] is not None
    if roles is not None and row['participant_roles'] and roles != row['participant_roles']:
        conflict = True
    if observed_occurrence:
        for field in ('game_id', 'provider_game_id', 'rescheduled_from_game_id'):
            if observed_occurrence.get(field) is not None and observed_occurrence[field] != row['occurrence'][field]:
                conflict = True
        if observed_occurrence.get('event_id') not in (None, row['event_id']):
            conflict = True
    state = 'contradictory' if conflict else 'available_and_bound' if active else 'expired'
    reason = 'public_event_current_attachment_conflict' if conflict else 'public_event_exact_membership_observed' if active else 'public_event_metadata_expired_or_not_effective'
    return dict(version=VERSION, binding_version=row['binding_version'], status=state, reason=reason,
        event_id=row['event_id'], market_id=row['market_id'], selected=deepcopy(member),
        occurrence=deepcopy(row['occurrence']), scope=deepcopy(row['scope']),
        provenance=deepcopy(row['provenance']), effective_from=row['effective_from'], effective_until=row['effective_until'],
        historical_quote_applicability=False, cross_source_qualified=False,
        original_quote_source_at=q['times']['source_at'], original_quote_received_at=q['times']['received_at'])


def apply(result, record, context, at):
    """Publish metadata as an identity dependency without upgrading its other facets."""
    q = context['quote']; event = record['event']
    value = audit(q, context.get('selected_applicability'), at, roles={k: event[k] for k in ('home', 'away')},
        observed_occurrence=record.get('comparison_source_metadata', {}).get('public_event_occurrence'))
    if value is None:
        return
    result['gaps']['identity']['public_event'] = value
    key = result['comparison_input_refs']['refs']['identity']
    if key is not None:
        prior = result['profiles'].pop(key)
        payload = deepcopy(prior['payload']); payload['public_event'] = value
        new_key, item = profile('identity', payload, expires_at=prior['expires_at'])
        result['profiles'][new_key] = item
        result['comparison_input_refs']['refs']['identity'] = new_key
