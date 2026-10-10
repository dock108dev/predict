"""Bounded immutable calculation dependencies for the existing current transport.

This module owns reference validation and invalidation, not acquisition or maths.
Profiles are content addressed and shared once per snapshot. Missing inputs are
local reasons; malformed inputs reject the proposed snapshot atomically.
"""
from datetime import datetime
from hashlib import sha256
import json

VERSION = 'comparison-current-dependencies-1'
KINDS = ('identity', 'payout', 'reference', 'fee', 'quantity', 'buffer', 'probability')
MAX_PROFILES = 128
MAX_PROFILE_BYTES = 32768
MAX_PROFILES_BYTES = 2 * 1024 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def digest(value):
    return sha256(encoded(value)).hexdigest()


def instant(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Dependency UTC timestamp required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError('Dependency UTC timestamp required')
    return parsed


def public_tree(value, depth=0):
    if depth > 24:
        raise ValueError('Dependency structure capacity')
    if isinstance(value, float):
        raise ValueError('Financial dependency floats forbidden')
    if isinstance(value, dict):
        if len(value) > 256 or any(not isinstance(k, str) for k in value):
            raise ValueError('Dependency field capacity')
        for k, v in value.items():
            if k in ('account_ref', 'account', 'positions', 'baseline_cashflows', 'net_before',
                     'net_before_usd', 'balance', 'balances', 'generic_context',
                     'credential', 'token', 'secret') and v is not None:
                raise ValueError('Private cost context cannot enter current profiles')
            public_tree(v, depth + 1)
    elif isinstance(value, list):
        if len(value) > 512:
            raise ValueError('Dependency list capacity')
        for v in value:
            public_tree(v, depth + 1)
    elif isinstance(value, str):
        if len(value) > 4096:
            raise ValueError('Dependency text capacity')
    elif value is not None and type(value) not in (int, bool):
        raise ValueError('Unsupported dependency value')


def profile(kind, payload, *, expires_at=None):
    """Create a new immutable version; callers retain predecessor evidence."""
    value = dict(version=VERSION, kind=kind, payload=payload, expires_at=expires_at)
    key = digest(value)
    validate_profiles({key: value})
    return key, value


def validate_profiles(profiles):
    if not isinstance(profiles, dict) or len(profiles) > MAX_PROFILES:
        raise ValueError('Shared comparison profile capacity')
    if len(encoded(profiles)) > MAX_PROFILES_BYTES:
        raise ValueError('Shared comparison profile byte capacity')
    for key, value in profiles.items():
        if not isinstance(value, dict) or set(value) != {'version', 'kind', 'payload', 'expires_at'}:
            raise ValueError('Exact immutable profile envelope required')
        if value['version'] != VERSION or value['kind'] not in KINDS or not isinstance(value['payload'], dict):
            raise ValueError('Unsupported comparison profile version/kind')
        if key != digest(value) or len(encoded(value)) > MAX_PROFILE_BYTES:
            raise ValueError('Comparison profile digest/byte mismatch')
        public_tree(value['payload'])
        if value['expires_at'] is not None:
            instant(value['expires_at'])
    return profiles


def references(q, profiles):
    inputs = q.get('comparison_input_refs')
    if inputs is None:
        return {}
    if not isinstance(inputs, dict) or set(inputs) != {'version', 'refs', 'phase'} or inputs['version'] != VERSION:
        raise ValueError('Exact comparison input references required')
    if inputs['phase'] not in ('pregame', 'live', 'unknown'):
        raise ValueError('Explicit comparison phase required')
    refs = inputs['refs']
    if not isinstance(refs, dict) or set(refs) != set(KINDS):
        raise ValueError('All comparison dependency kinds required; missing values use null')
    for kind, key in refs.items():
        if key is not None and (key not in profiles or profiles[key]['kind'] != kind):
            raise ValueError('Missing or mismatched shared comparison profile')
    return {kind: profiles[key] for kind, key in refs.items() if key is not None}


def link_reasons(q, at):
    link = q.get('occurrence_link')
    if link is None:
        return []
    if not isinstance(link, dict) or set(link) != {'version','edges','effective_from','effective_until'}:
        raise ValueError('Exact occurrence link interval required')
    if link['version'] != 'comparison-evidenced-overlap-2' or not isinstance(link['edges'], list) or len(link['edges']) != 2:
        raise ValueError('Bounded occurrence edge identities required')
    if any(not isinstance(e, str) or len(e) != 64 or any(c not in '0123456789abcdef' for c in e) for e in link['edges']):
        raise ValueError('Exact occurrence edge digests required')
    start = instant(link['effective_from'])
    end = None if link['effective_until'] is None else instant(link['effective_until'])
    if end is not None and end <= start:
        raise ValueError('Positive occurrence link interval required')
    return ['occurrence_link_expired_or_not_effective'] if at < start or end is not None and at >= end else []


def input_status(q):
    values=q.get('comparison_input_status',{})
    if not isinstance(values,dict) or len(values)>16:
        raise ValueError('Bounded comparison input status required')
    allowed={'available_and_bound','available_but_unbound','applicability_unresolved','absent','expired','contradictory'}
    for kind,item in values.items():
        if not isinstance(kind,str) or kind not in {*KINDS,'phase','clock','depth','source'} or not isinstance(item,dict):
            raise ValueError('Typed comparison input status required')
        if item.get('status') not in allowed or not isinstance(item.get('reason'),str) or len(item['reason'])>160:
            raise ValueError('Sanitized comparison input reason required')
        public_tree(item)
    return values


def input_reason(q,kind):
    status=input_status(q).get(kind)
    return status['reason'] if status and status['status']!='available_and_bound' else kind+'_inputs_unbound'


def eligibility(q, profiles, at, *, kinds=KINDS):
    values = references(q, profiles)
    links = link_reasons(q, at)
    if not values and not q.get('comparison_input_status'):
        return tuple(['comparison_inputs_unbound', *links])
    reasons = [*links, *[input_reason(q,kind) for kind in kinds if kind not in values]]
    # Binding a retained fact records availability, not applicability. A partial
    # identity/rule profile must not become calculation authority merely because
    # its content addressed reference now exists.
    reasons.extend(item['reason'] for kind,item in input_status(q).items()
        if kind in kinds and kind in values and item['status']!='available_and_bound')
    phase = q.get('comparison_input_refs',{}).get('phase','unknown')
    limit = {'pregame': 900, 'live': 15}.get(phase)
    if limit is None:
        reasons.append('source_phase_unknown')
    source = q['times']['source_at']
    if source is None:
        reasons.append('source_clock_unknown')
    else:
        source = instant(source)
        receipt=q['times']['received_at']
        if receipt is None:reasons.append('source_receipt_clock_unknown')
        # An input already future dated at receipt never ages into authority.
        if source > at or receipt is not None and source > instant(receipt):
            reasons.append('source_clock_future')
        elif limit is not None and (at - source).total_seconds() > limit:
            reasons.append('source_price_expired')
    for kind, value in values.items():
        if kind not in kinds:
            continue
        if value['expires_at'] is not None and at >= instant(value['expires_at']):
            reasons.append(kind + '_inputs_expired')
        payload = value['payload']
        if kind == 'fee' and payload.get('version') == 'comparison-direct-site-retail-case-1':
            reasons.append('direct_site_cost_case_modeled_total_charges_unverified')
        intervals=[payload]
        if kind=='fee' and isinstance(payload.get('rule'),dict):intervals.append(payload['rule'])
        if kind=='fee' and isinstance(payload.get('engine_registry'),dict):
            selected=payload.get('engine_context',{}).get('schedule_version')
            intervals.extend(s for s in payload['engine_registry'].get('schedules',[]) if s.get('version')==selected)
        for interval in intervals:
            for field in ('effective_to', 'effective_until', 'expires_at'):
                if interval.get(field) is not None and at >= instant(interval[field]):
                    reasons.append(kind + '_inputs_expired')
            if interval.get('effective_from') is not None and at < instant(interval['effective_from']):
                reasons.append(kind + '_not_effective')
        if kind == 'reference':
            clocks = payload.get('source_at', [])
            if not isinstance(clocks, list) or len(clocks) not in (2, 3):
                reasons.append('reference_source_clock_unknown')
            else:
                outcomes=payload.get('outcomes',[])
                for index,clock in enumerate(clocks):
                    if clock is None:
                        reasons.append('reference_source_clock_unknown')
                    elif index<len(outcomes) and outcomes[index].get('received_at') is None:
                        reasons.append('reference_receipt_clock_unknown')
                    elif instant(clock) > at or (index<len(outcomes) and
                            instant(clock)>instant(outcomes[index]['received_at'])):
                        reasons.append('reference_clock_future')
                    elif limit is not None and (at - instant(clock)).total_seconds() > limit:
                        reasons.append('reference_expired')
    return tuple(sorted(set(reasons)))


def group_dependencies(group, profiles):
    refs = set()
    for outcome in group['outcomes']:
        for q in [*outcome['quotes'].values(), *(q for qs in outcome.get('alternatives', {}).values() for q in qs)]:
            references(q, profiles)
            refs.update(k for k in q.get('comparison_input_refs', {}).get('refs', {}).values() if k is not None)
    return {key: profiles[key] for key in sorted(refs)}


def temporal_revision(q,profiles,at):
    """Selected authored/evidenced fee history activates without new packets."""
    fee=references(q,profiles).get('fee',{}).get('payload',{})
    metadata=fee.get('engine_context',{}).get('kalshi_metadata',{})
    active=[]
    for kind in ('series_changes','event_changes'):
        for change in metadata.get(kind,[]):
            if change.get('scheduled_ts') is not None and instant(change['scheduled_ts'])<=at:
                active.append(change['scheduled_ts'])
    event=q.get('comparison_input_status',{}).get('identity',{}).get('public_event')
    if event is not None:
        valid=instant(event['effective_from'])<=at<instant(event['effective_until'])
        return digest(dict(fee=sorted(active),public_event=[event['binding_version'],valid]))
    return digest(sorted(active)) if active else None


def refresh_metadata_status(q,at):
    """Expiry changes only the metadata facet; preserve held profiles and clocks."""
    states=q.get('comparison_input_status',{})
    identity=states.get('identity',{})
    event=identity.get('public_event')
    if event is None or event['status']=='contradictory':return
    valid=instant(event['effective_from'])<=at<instant(event['effective_until'])
    event=dict(event,status='available_and_bound' if valid else 'expired',
        reason='public_event_exact_membership_observed' if valid else 'public_event_metadata_expired_or_not_effective')
    q['comparison_input_status']=dict(states,identity=dict(identity,public_event=event))
