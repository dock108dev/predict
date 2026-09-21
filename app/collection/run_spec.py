"""Pure preflight: no networking, credential lookup, fixtures or database access."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import math
import re
from .odds_http import HTTPPolicy

SOURCES = ('kalshi', 'polymarket_us')

def reference_enabled(spec):
    return spec.get('reference_enabled', False) is True



def time_value(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result


def preflight(spec, now=None, *, supervised_live=False):
    if not isinstance(spec,dict):
        return dict(valid=False,activation_enabled=False,errors=['spec: object required'],economics='unavailable')
    now = now or datetime.now(timezone.utc)
    errors = []
    required = ('mode', 'event', 'participants', 'scheduled_start', 'start_after', 'start_before',
                'duration', 'discovery_cadence', 'stale_seconds', 'sources',
                'mapping_revision', 'assessment_revisions', 'prediction', 'cleanup', 'capture_authorization')
    for key in required:
        if key not in spec or spec[key] is None or spec[key] == '':
            errors.append(key+': missing')
    if errors:
        return dict(valid=False, activation_enabled=False, errors=errors, economics='unavailable')
    optional={'reference_enabled','reference_cadence','http','supervised_profile'}
    policy=None
    if 'supervised_profile' in spec:
        from .supervised import profile
        try: policy=profile(spec['supervised_profile'])
        except ValueError: errors.append('unknown supervised profile')
        if supervised_live:
            if spec.get('mode')!='real' or spec.get('reference_enabled',False): errors.append('supervised live requires prediction-only real mode')
        elif spec.get('mode')!='mock' or spec.get('reference_enabled',False): errors.append('supervised profile is isolated mock only')
    if reference_enabled(spec):
        for key in ('reference_cadence','http'):
            if key not in spec:errors.append(key+': missing')
    if type(spec.get('reference_enabled',False)) is not bool:errors.append('reference_enabled: boolean required')
    for key in set(spec)-set(required)-optional:errors.append(str(key)+': unsupported field')
    if spec['mode'] not in ('real', 'mock'):
        errors.append('mode: expected real or mock')
    for key in ('event', 'mapping_revision', 'capture_authorization', 'cleanup'):
        if not isinstance(spec[key], str) or not spec[key].strip():
            errors.append(key+': nonempty reference required')
    people = spec['participants']
    if not isinstance(people, list) or len(people) != 2 or any(not isinstance(x,str) or not x for x in people) or len(set(people)) != 2:
        errors.append('participants: exactly two distinct canonical identities required')
        people=[]
    times = {}
    for key in ('scheduled_start', 'start_after', 'start_before'):
        try: times[key] = time_value(spec[key])
        except (ValueError, TypeError, AttributeError): errors.append(key+': aware ISO timestamp required')
    for key, ceiling in (('duration',300), ('reference_cadence',300), ('discovery_cadence',300), ('stale_seconds',60)):
        v = spec.get(key)
        if key=='reference_cadence' and not reference_enabled(spec):continue
        if type(v) not in (int,float) or not math.isfinite(v) or not 0 < v <= ceiling:
            errors.append(key+': positive finite value <= '+str(ceiling)+' required')
    if len(times)==3:
        if not times['start_after'] <= times['start_before'] < times['scheduled_start']:
            errors.append('start window: must be ordered and before kickoff')
        if now >= times['scheduled_start'] or now > times['start_before']:
            errors.append('start window: expired or kickoff reached')
        if type(spec['duration']) in (int,float) and math.isfinite(spec['duration']) and 0 < spec['duration'] <= 300:
            if times['start_before']+timedelta(seconds=spec['duration']) >= times['scheduled_start']:
                errors.append('duration: latest permitted start must end before kickoff')
    sources = spec['sources']
    for source in (*SOURCES, *(('the_odds_api',) if reference_enabled(spec) else ())):
        row = sources.get(source, {}) if isinstance(sources,dict) else {}
        if not isinstance(row,dict):row={}
        for key in set(row)-{'event_id','market_id','participant_mapping','credential_reference','entitlement_reference'}:
            errors.append('sources.'+source+'.'+key+': unsupported field; credential values prohibited')
        for key in ('event_id','market_id','participant_mapping','credential_reference','entitlement_reference'):
            value = row.get(key)
            if not value:
                errors.append('sources.'+source+'.'+key+': missing')
        for key in ('event_id','market_id'):
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', str(row.get(key,''))):
                errors.append('sources.'+source+'.'+key+': invalid native ID')
        mapping=row.get('participant_mapping')
        if not isinstance(mapping,dict) or len(mapping)!=2 or any(not isinstance(x,str) for x in mapping.values()) or set(mapping.values()) != set(people):
            errors.append('sources.'+source+'.participant_mapping: must map two native identities to participants')
    if reference_enabled(spec) and isinstance(sources,dict) and (not isinstance(sources.get('the_odds_api'),dict) or sources['the_odds_api'].get('market_id') != 'h2h'):
        errors.append('sources.the_odds_api.market_id: only h2h permitted')
    revisions=spec['assessment_revisions']
    for key in ('pairing','lineage','fees','settlement'):
        if not isinstance(revisions,dict) or key not in revisions:
            errors.append('assessment_revisions.'+key+': explicit null or evidence reference required')
    if spec['mode']=='real':
        # Reject fixture-derived positive knowledge; null economics are allowed.
        import json
        if 'synthetic' in json.dumps([spec['event'],sources,spec['mapping_revision'],revisions]).lower():
            errors.append('real scope: synthetic identity or assessment prohibited')
    if reference_enabled(spec):
        from dataclasses import fields
        if isinstance(spec.get('http'),dict):
            for f in fields(HTTPPolicy):
                if f.name not in spec.get('http'):errors.append('http.'+f.name+': missing')
        try:
            http = dict(spec.get('http'))
            for key in ('dollars','dollars_per_credit'): http[key]=Decimal(http[key])
            policy=HTTPPolicy(**http)
            if spec['mode']=='real' and (policy.credits>5 or policy.dollars!=0 or policy.dollars_per_credit!=0):
                errors.append('http: optional reference requires at most five free credits')
        except (ValueError, TypeError, KeyError, ArithmeticError):
            errors.append('http: complete explicit HTTPPolicy bounds, quota baseline and plan/cost assumptions required')
    prediction=spec['prediction']
    for key, cap in (('messages',1000),('connections',5),('frame_bytes',1048576),('session_bytes',16777216),('discovery_requests',100)):
        if policy: cap={'messages':policy['group_messages'],'session_bytes':policy['body_bytes'],'discovery_requests':policy['requests']}.get(key,cap)
        v=prediction.get(key) if isinstance(prediction,dict) else None
        if type(v) is not int or not 0 < v <= cap:
            errors.append('prediction.'+key+': positive integer <= '+str(cap)+' required')
    for key in ('dollar_cap_per_source','dollars_per_discovery_request','dollars_per_connection'):
        try:
            value=Decimal(prediction[key])
            if not value.is_finite() or value<0:raise ValueError()
        except (TypeError,KeyError,ValueError,ArithmeticError):errors.append('prediction.'+key+': explicit nonnegative decimal cost required')
    if not isinstance(prediction,dict) or not prediction.get('plan_evidence'):
        errors.append('prediction.plan_evidence: explicit applicable cost assumption required')
    if spec['mode']=='real':
        for key in ('dollar_cap_per_source','dollars_per_discovery_request','dollars_per_connection'):
            if not isinstance(prediction,dict) or prediction.get(key) != '0':errors.append('prediction.'+key+': this slice requires zero additional cost')
    return dict(valid=not errors, activation_enabled=not errors, errors=errors,
                economics='unavailable: observation-only transport package',
                activation_reason='explicit Start required; credentials resolved only at Start')


def main():
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec',type=Path)
    args=parser.parse_args()
    print(json.dumps(preflight(json.loads(args.spec.read_text())),indent=2))

if __name__=='__main__': main()
