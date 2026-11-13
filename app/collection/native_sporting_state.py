"""Small identity-bound US sporting observations, independent of book material."""
from datetime import datetime, timezone, timedelta
from uuid import UUID
from app.storage.store import stamp

PAGE_SIZE = 20
POLL_SECONDS = 15


def _provider_ids(row):
    ids = {}
    number = row.get('gameId')
    if number is not None and type(number) not in (int, str):
        raise ValueError('invalid Polymarket US game ID')
    if number not in (None, '', 0, '0'):
        number = str(number)
        if not (number.isascii() and number.isdecimal() and 0 < len(number) <= 20):
            raise ValueError('invalid Polymarket US game ID')
        ids['game_id'] = number
    sportradar = row.get('sportradarGameId')
    if sportradar not in (None, ''):
        parsed = UUID(sportradar)
        if not parsed.int or str(parsed) != sportradar:
            raise ValueError('invalid Sportradar game ID')
        ids['sportradar_game_id'] = sportradar
    return ids


def _shared_ids(first, second):
    overlap = first.keys() & second.keys()
    if any(first[key] != second[key] for key in overlap):
        return {}
    return {key:first[key] for key in sorted(overlap)}


def observations(rows, *, league, receipt):
    result=[]
    for row in rows:
        if not isinstance(row, dict) or not row.get('id'):
            continue
        state=row.get('eventState') or {}
        if (not isinstance(state,dict) or str(state.get('eventId'))!=str(row.get('id'))
                or any(type(state.get(k)) is not bool for k in ('live','ended'))):continue
        try:
            event_ids, state_ids = _provider_ids(row), _provider_ids(state)
            ids = _shared_ids(event_ids, state_ids)
            if not ids:continue
            if stamp(state['updatedAt'])>stamp(receipt['received_at']):continue
            stamp(row['startTime'])
        except (KeyError,ValueError,TypeError,AttributeError):continue
        other_ids = {key:value for key,value in (event_ids | state_ids).items() if key not in ids}
        result.append(dict(event_id=str(row['id']),league=league,**ids,
            **({'other_game_ids':other_ids} if other_ids else {}),
            start_at=row['startTime'],source_at=state['updatedAt'],received_at=receipt['received_at'],
            body_sha256=receipt['body_sha256'],path=receipt['path'],
            state={**{k:row[k] for k in ('active','closed') if type(row.get(k)) is bool},
                   **{k:state[k] for k in ('live','ended')}}))
    return result


def matches_event(event, value):
    """Both the polling watermark and admission require the same exact identity."""
    raw = event.get('_native') or {}
    try:
        witnessed = {key:value[key] for key in ('game_id', 'sportradar_game_id') if key in value}
        raw_ids = _provider_ids(raw)
        other = value.get('other_game_ids') or {}
        return (event['id'] == value['event_id'] and event['competition'] == value['league']
                and bool(_shared_ids(raw_ids, witnessed))
                and all(raw_ids[key] == other[key] for key in raw_ids.keys() & other.keys())
                and stamp(event['scheduled_start']) == stamp(value['start_at']))
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def newest_observations(events, values, seen):
    """Keep the newest observation per bound game; bad rows cannot advance its clock."""
    by_id = {event['id']: event for event in events}
    latest = {}
    for value in values:
        event_id = value['event_id']
        if event_id not in by_id or not matches_event(by_id[event_id], value):
            continue
        prior = latest.get(event_id, seen.get(event_id))
        try:
            observed_at = stamp(value['source_at'])
            if prior and matches_event(by_id[event_id], prior) and observed_at <= stamp(prior['source_at']):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        latest[event_id] = value
    return latest


def current_observation(event, value):
    """Reject an observation older than the catalog's provider clocks."""
    prior = event.get('sporting_state_evidence')
    native_at = ((event.get('_native') or {}).get('eventState') or {}).get('updatedAt')
    try:
        source_at = stamp(value['source_at'])
        return ((not prior or source_at >= stamp(prior['source_at']))
                and (not native_at or source_at >= stamp(native_at)))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def apply(inventory, values, *, retain_evidence=False):
    """Replace only sporting state after exact event/game/schedule validation.

    Native terms, participants, lines, sides and book clocks remain untouched.
    The caller atomically withdraws affected derived rows before recalculation.
    """
    source='polymarket_us';cat=inventory.get(source)
    if not cat:return inventory,set()
    incoming=newest_observations(cat['events'], values, {});events=[];changed=set()
    copied_gate={m['event_id'] for m in cat['markets'] if m.get('exclusion')=='event_excluded:kickoff_reached'}
    for event in cat['events']:
        value=incoming.get(event['id'])
        if (value and current_observation(event,value)
                and (any((event.get('status') or {}).get(k)!=v for k,v in value['state'].items())
                     or retain_evidence and event.get('sporting_state_evidence')!=value
                     or event['id'] in copied_gate and value['state']['live'] and not value['state']['ended'])):
            event=dict(event,status=dict(value['state'],observed_at=value['source_at'],source_evidence=dict(value)),
                sporting_state_evidence=dict(value))
            if event.get('exclusion')=='kickoff_reached' and value['state']['live'] and not value['state']['ended']:
                event['exclusion']=None
            changed.add(event['id'])
        events.append(event)
    live={e['id'] for e in events if e['id'] in changed and not e.get('exclusion')
        and (e.get('status') or {}).get('live') is True and not (e.get('status') or {}).get('ended')}
    markets=[dict(m,exclusion=None,qualified_exclusion=m['exclusion'])
        if m['event_id'] in live and m.get('exclusion')=='event_excluded:kickoff_reached' else m for m in cat['markets']]
    return (dict(inventory,**{source:dict(cat,events=events,markets=markets)}) if changed else inventory),changed


def active_events(catalog, now=None):
    now=now or datetime.now(timezone.utc)
    events=[]
    for event in catalog.get('events',[]):
        try:
            if now-timedelta(hours=24)<=stamp(event['scheduled_start'])<=now+timedelta(minutes=15):
                events.append(event)
        except (KeyError,ValueError,TypeError):pass
    return events


def active_leagues(catalog, now=None):
    return sorted({e['competition'] for e in active_events(catalog,now)})


def handoff_leagues(catalog, now=None):
    """Prioritize head pages around kickoff while leaving deep scans intact."""
    from app.comparison.game_phase import sporting_phase

    now = now or datetime.now(timezone.utc)
    earliest, latest = now-timedelta(minutes=30), now+timedelta(minutes=15)
    return sorted({e['competition'] for e in active_events(catalog,now)
                   if earliest <= stamp(e['scheduled_start']) <= latest
                   and sporting_phase(e)['reason'] is None})


class SportingStatePages:
    """Interleave bounded head requests without moving the fair page cursor."""
    def __init__(self):
        self.offsets = {}
        self.fair_turn = 0
        self.head_turn = 0
        self.head_next = True

    def next_request(self, leagues, priority):
        fair_league = leagues[self.fair_turn % len(leagues)]
        fair_offset = self.offsets.get(fair_league, 0)
        if priority and self.head_next:
            head_league = priority[self.head_turn % len(priority)]
            self.head_turn += 1
            self.head_next = False
            if (head_league, 0) != (fair_league, fair_offset):
                return head_league, 0, 'priority_head'
        else:
            self.head_next = True
        self.fair_turn += 1
        return fair_league, fair_offset, 'round_robin'

    def record_page(self, league, offset, lane, rows):
        if lane == 'round_robin':
            self.offsets[league] = offset+rows if rows == PAGE_SIZE else 0
        return self.offsets.get(league, 0)
