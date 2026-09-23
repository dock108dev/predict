"""Frozen, prediction-only two-source qualification scope; pure validation."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID
from .venue_access import REFERENCES

POLICY = dict(version='two-source-nfl-2', discovery_seconds=30, event_pages=2,
              page_size=5, market_pages=2, events_selected=1, markets_per_venue=2,
              kickoff_margin_seconds=300, target_stop_seconds=60,
              cleanup_start_seconds=89, hard_deadline_seconds=90,
              refresh=False, imports=False,
              us_event_filter='football_team_full_game_winner', future_start_filter=True,
              rest_attempts={'kalshi':12,'polymarket_us':8})


def specification(start_after, start_before, attempt_id, mode='real'):
    return dict(mode=mode, start_after=start_after, start_before=start_before,
        duration=90, discovery_cadence=300, stale_seconds=15, reference_enabled=False,
        mapping_revision='native-occurrence-NFL-bounded-1',
        assessment_revisions={k:None for k in ('pairing','lineage','fees','settlement')},
        capture_authorization='Pending explicit approval: one two-source NFL observation attempt; no reference acquisition or trading',
        cleanup='Stop new work at 89 seconds; close sources; external supervisor terminates unclosed collection at 90 seconds; retain incomplete prefix on failure',
        sources={v:dict(credential_reference=ref,entitlement_reference='existing dedicated project read-only access; availability checked only at approved Start') for v,ref in REFERENCES.items()},
        prediction=dict(messages=600,connections=2,frame_bytes=1048576,session_bytes=16777216,
            discovery_requests=100,dollar_cap_per_source='0',dollars_per_discovery_request='0',
            dollars_per_connection='0',plan_evidence='Existing read-only API access; zero additional spend permitted; no quota/account changes'),
        native_sources={**{v:dict(state='enabled',environment='production',poll_seconds=30,event_cap=1,market_cap=2,
            **({'series':['KXNFLGAME']} if v=='kalshi' else {'tags':['nfl']})) for v in REFERENCES},
            'novig':dict(state='not_configured',selected=True),'prophetx':dict(state='not_configured',selected=True)},
        two_source_qualification=dict(POLICY,attempt_id=attempt_id))


def validate(spec):
    q=spec['two_source_qualification'];UUID(q['attempt_id'])
    if spec!=specification(spec['start_after'],spec['start_before'],q['attempt_id'],spec['mode']):
        raise ValueError('two-source scope differs from frozen policy')
    after=datetime.fromisoformat(spec['start_after']);before=datetime.fromisoformat(spec['start_before'])
    if after.utcoffset() is None or before.utcoffset() is None or before-after!=timedelta(minutes=15):
        raise ValueError('exact aware fifteen-minute start window required')
    if spec['mode'] not in ('real','mock'):raise ValueError('invalid mode')


def preflight(spec, now=None):
    from .run_spec import preflight as base
    try:
        validate(spec)
        # Reuse existing transport bounds without persisting invented event IDs.
        # These local validator sentinels are never journaled or used for matching.
        legacy=deepcopy(spec);legacy.pop('two_source_qualification')
        legacy.update(event='pending-bounded-discovery',participants=['pending-a','pending-b'],
            scheduled_start=(datetime.fromisoformat(spec['start_before'])+timedelta(hours=1)).isoformat())
        for source in legacy['sources'].values():source.update(event_id='pending',market_id='pending',participant_mapping={'a':'pending-a','b':'pending-b'})
        result=base(legacy,now=now)
        result['selection']='No event prequalified; same-attempt bounded native discovery required'
        return result
    except (ValueError,KeyError,TypeError,AttributeError) as exc:
        return dict(valid=False,activation_enabled=False,errors=['two-source policy: '+str(exc)],economics='unavailable')
