"""Small identity-bound US sporting observations, independent of book material."""
from datetime import datetime, timezone, timedelta
from app.storage.store import stamp

PAGE_SIZE = 20
POLL_SECONDS = 15


def observations(rows, *, league, receipt):
    result=[]
    for row in rows:
        if not isinstance(row, dict) or not row.get('id'):
            continue
        state=row.get('eventState') or {}
        if (not isinstance(state,dict) or not row.get('gameId')
                or str(state.get('gameId'))!=str(row['gameId'])
                or str(state.get('eventId'))!=str(row.get('id'))
                or any(type(state.get(k)) is not bool for k in ('live','ended'))):continue
        try:
            if stamp(state['updatedAt'])>stamp(receipt['received_at']):continue
            stamp(row['startTime'])
        except (KeyError,ValueError,TypeError):continue
        result.append(dict(event_id=str(row['id']),game_id=str(row['gameId']),league=league,
            start_at=row['startTime'],source_at=state['updatedAt'],received_at=receipt['received_at'],
            body_sha256=receipt['body_sha256'],path=receipt['path'],
            state={**{k:row[k] for k in ('active','closed') if type(row.get(k)) is bool},
                   **{k:state[k] for k in ('live','ended')}}))
    return result


def matches_event(event, value):
    """Both the polling watermark and admission require the same exact identity."""
    raw = event.get('_native') or {}
    try:
        return (event['id'] == value['event_id'] and event['competition'] == value['league']
                and raw.get('gameId') is not None and str(raw['gameId']) == value['game_id']
                and stamp(event['scheduled_start']) == stamp(value['start_at']))
    except (KeyError, ValueError, TypeError):
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
            if prior and matches_event(by_id[event_id], prior) and observed_at < stamp(prior['source_at']):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        latest[event_id] = value
    return latest


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
        value=incoming.get(event['id']);raw=event.get('_native') or {}
        prior=event.get('sporting_state_evidence')
        native_at=(raw.get('eventState') or {}).get('updatedAt')
        if value:
            try:
                valid=((not prior or stamp(value['source_at'])>=stamp(prior['source_at']))
                    and (not native_at or stamp(value['source_at'])>=stamp(native_at)))
            except (ValueError,KeyError,TypeError):valid=False
            if valid and (any((event.get('status') or {}).get(k)!=v for k,v in value['state'].items())
                    or retain_evidence and prior!=value
                    or event['id'] in copied_gate and value['state']['live'] and not value['state']['ended']):
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
