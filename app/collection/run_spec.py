"""Pure preflight: no networking, credential lookup, fixtures or database access."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import math
import json
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
    if 'two_source_qualification' in spec:
        from .two_source_policy import preflight as bounded_preflight
        return bounded_preflight(spec,now)
    now = now or datetime.now(timezone.utc)
    from .acquisition_policy import dynamic
    from .us_metadata_diagnostic import enabled as us_diagnostic
    metadata_diagnostic=us_diagnostic(spec)
    discovery_only=dynamic(spec) or bool(spec.get('native_discovery'))
    errors = []
    required = ('mode', 'event', 'participants', 'scheduled_start', 'start_after', 'start_before',
                'duration', 'discovery_cadence', 'stale_seconds', 'sources',
                'mapping_revision', 'assessment_revisions', 'prediction', 'cleanup', 'capture_authorization')
    if discovery_only:required=tuple(k for k in required if k not in ('event','participants','scheduled_start'))
    for key in required:
        if key not in spec or spec[key] is None or spec[key] == '':
            errors.append(key+': missing')
    if errors:
        return dict(valid=False, activation_enabled=False, errors=errors, economics='unavailable')
    optional={'v1_comparison_policy','native_review_records','reference_enabled','reference_cadence','http','supervised_profile','native_sources','source_session','native_discovery','native_transport','us_metadata_diagnostic'}
    if spec.get('v1_comparison_policy') not in (None,'manual-comparison-1','manual-comparison-2'):
        errors.append('Unknown V1 comparison policy')
    if 'us_metadata_diagnostic' in spec and not metadata_diagnostic:
        errors.append('us_metadata_diagnostic: exact metadata-only slice required')
    if 'native_transport' in spec:
        try:
            from .native_payload import validate_transport
            validate_transport(spec)
        except (ValueError, TypeError, KeyError):
            errors.append('native_transport: exact finite delivery contract required')
    policy=None
    if 'native_review_records' in spec:
        try:
            from app.dashboard.native_reviews import validate
            values=spec['native_review_records']
            if not isinstance(values,list) or len(values)>128 or len(json.dumps(values).encode())>4*1024*1024:raise ValueError('Review bound')
            keys=set()
            for value in values:
                record=validate(value);key=(record['review_id'],record['revision'])
                if key in keys:raise ValueError('Duplicate review revision')
                keys.add(key)
                if record['evidence_mode']=='synthetic' and spec['mode']!='mock':raise ValueError('Synthetic review in real session')
        except (ValueError,KeyError,TypeError):errors.append('native_review_records: invalid evidence-bound records')
    if 'native_discovery' in spec:
        from .native_selectors import validate_probe
        try:
            from .native_books import enabled as book_slice, validate as validate_books
            if metadata_diagnostic:
                from .us_metadata_diagnostic import validate_spec
                validate_spec(spec)
                expected_prediction=dict(messages=0,connections=0,frame_bytes=0,session_bytes=8388608,
                    discovery_requests=1,dollar_cap_per_source='0',dollars_per_discovery_request='0',
                    dollars_per_connection='0',plan_evidence='docs/us-metadata-delivery-repair.md')
                expected_source=dict(credential_reference='none:public-metadata-no-credential-access',
                    entitlement_reference='docs/us-metadata-delivery-repair.md; retained official event-by-ID documentation')
                expected_native={v:dict(state='disabled',selected=False) for v in ('kalshi','polymarket_us','novig','prophetx')}
                expected_native['polymarket_us']=dict(state='enabled',environment='production',poll_seconds=60,event_cap=1,market_cap=1)
                from .native_payload import TRANSPORT_CONTRACT
                diagnostic_window=spec['us_metadata_diagnostic']['validity_window']
                if (spec['duration']!=15 or type(spec['duration']) is not int or spec['discovery_cadence']!=60
                    or type(spec['discovery_cadence']) is not int or spec['stale_seconds']!=10 or type(spec['stale_seconds']) is not int
                    or spec['prediction']!=expected_prediction or spec.get('native_transport')!=TRANSPORT_CONTRACT
                    or spec['sources']!={'polymarket_us':expected_source} or spec.get('native_sources')!=expected_native
                    or spec.get('reference_enabled') is not False or any(k in spec for k in ('source_session','native_review_records','supervised_profile','http'))
                    or spec['assessment_revisions']!=dict(pairing=None,lineage=None,fees=None,settlement=None)
                    or spec['start_after']!=diagnostic_window['start']
                    or time_value(spec['start_before'])!=time_value(diagnostic_window['expires'])-timedelta(seconds=32)):
                    raise ValueError('Exact single-request public metadata diagnostic limits required')
            elif book_slice(spec): validate_books(spec)
            else: validate_probe(spec['native_discovery'],transport=spec.get('native_transport'))
            if spec.get('source_session') or reference_enabled(spec):raise ValueError()
            if {v for v,c in spec.get('native_sources',{}).items() if c.get('state')=='enabled'}!=({'polymarket_us'} if metadata_diagnostic else {'kalshi','polymarket_us'}):raise ValueError()
        except (ValueError,TypeError,KeyError):errors.append('invalid native discovery probe')
    if 'source_session' in spec:
        from .source_session import validate
        try:
            validate(spec['source_session'])
            if spec['mode'] not in ('mock','real') or reference_enabled(spec):raise ValueError()
            if spec['mode']=='real' and not spec.get('native_sources'):raise ValueError()
            if any(spec.get('native_sources',{}).get(v,{}).get('state')=='enabled' for v in ('novig','prophetx')):raise ValueError()
        except (ValueError,TypeError,KeyError,ArithmeticError):errors.append('source_session: invalid roles, limits or source activation configuration')
    if 'supervised_profile' in spec:
        from .supervised import profile
        try: policy=profile(spec['supervised_profile'])
        except ValueError: errors.append('unknown supervised profile')
        if supervised_live:
            if spec.get('mode')!='real' or spec.get('reference_enabled',False): errors.append('supervised live requires prediction-only real mode')
        elif spec.get('mode')!='mock' or spec.get('reference_enabled',False): errors.append('supervised profile is isolated mock only')
    if 'native_sources' in spec:
        from .native_product import validate_sources
        try: validate_sources(spec)
        except (ValueError, TypeError, KeyError): errors.append('native_sources: invalid bounded source configuration')
    if reference_enabled(spec):
        for key in ('reference_cadence','http'):
            if key not in spec:errors.append(key+': missing')
    if type(spec.get('reference_enabled',False)) is not bool:errors.append('reference_enabled: boolean required')
    for key in set(spec)-set(required)-optional:errors.append(str(key)+': unsupported field')
    if spec['mode'] not in ('real', 'mock'):
        errors.append('mode: expected real or mock')
    for key in (('mapping_revision','capture_authorization','cleanup') if discovery_only else ('event','mapping_revision','capture_authorization','cleanup')):
        if not isinstance(spec[key], str) or not spec[key].strip():
            errors.append(key+': nonempty reference required')
    people = spec.get('participants')
    if not discovery_only and (not isinstance(people, list) or len(people) != 2 or any(not isinstance(x,str) or not x for x in people) or len(set(people)) != 2):
        errors.append('participants: exactly two distinct canonical identities required')
        people=[]
    times = {}
    for key in (('start_after','start_before') if discovery_only else ('scheduled_start','start_after','start_before')):
        try: times[key] = time_value(spec[key])
        except (ValueError, TypeError, AttributeError): errors.append(key+': aware ISO timestamp required')
    for key, ceiling in (('duration',300), ('reference_cadence',300), ('discovery_cadence',300), ('stale_seconds',60)):
        v = spec.get(key)
        if key=='reference_cadence' and not reference_enabled(spec):continue
        if type(v) not in (int,float) or not math.isfinite(v) or not 0 < v <= ceiling:
            errors.append(key+': positive finite value <= '+str(ceiling)+' required')
    if discovery_only and len(times)==2 and (times['start_after']>times['start_before'] or now>times['start_before']):
        errors.append('start window invalid or expired')
    if len(times)==3:
        if not times['start_after'] <= times['start_before'] < times['scheduled_start']:
            errors.append('start window: must be ordered and before kickoff')
        if now >= times['scheduled_start'] or now > times['start_before']:
            errors.append('start window: expired or kickoff reached')
        if type(spec['duration']) in (int,float) and math.isfinite(spec['duration']) and 0 < spec['duration'] <= 300:
            if times['start_before']+timedelta(seconds=spec['duration']) >= times['scheduled_start']:
                errors.append('duration: latest permitted start must end before kickoff')
    sources = spec['sources']
    for source in (*(('polymarket_us',) if metadata_diagnostic else SOURCES), *(('the_odds_api',) if reference_enabled(spec) else ())):
        row = sources.get(source, {}) if isinstance(sources,dict) else {}
        if not isinstance(row,dict):row={}
        for key in set(row)-{'event_id','market_id','participant_mapping','credential_reference','entitlement_reference'}:
            errors.append('sources.'+source+'.'+key+': unsupported field; credential values prohibited')
        for key in (('credential_reference','entitlement_reference') if discovery_only else ('event_id','market_id','participant_mapping','credential_reference','entitlement_reference')):
            value = row.get(key)
            if not value:
                errors.append('sources.'+source+'.'+key+': missing')
        if discovery_only:
            if set(row)!={'credential_reference','entitlement_reference'}:errors.append('discovery scope prohibits bootstrap identities')
            continue
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
        if 'synthetic' in json.dumps([spec.get('event'),sources,spec['mapping_revision'],revisions]).lower():
            errors.append('real scope: synthetic identity or assessment prohibited')
    if reference_enabled(spec):
        from dataclasses import fields
        if isinstance(spec.get('http'),dict):
            for f in fields(HTTPPolicy):
                if f.name not in spec.get('http'):errors.append('http.'+f.name+': missing')
        try:
            http = dict(spec.get('http'))
            for key in ('dollars','dollars_per_credit'): http[key]=Decimal(http[key])
            http_policy=HTTPPolicy(**http)
            if spec['mode']=='real' and (http_policy.credits>5 or http_policy.dollars!=0 or http_policy.dollars_per_credit!=0):
                errors.append('http: optional reference requires at most five free credits')
        except (ValueError, TypeError, KeyError, ArithmeticError):
            errors.append('http: complete explicit HTTPPolicy bounds, quota baseline and plan/cost assumptions required')
    prediction=spec['prediction']
    for key, cap in (('messages',1000),('connections',5),('frame_bytes',1048576),('session_bytes',16777216),('discovery_requests',100)):
        from .acquisition_policy import isolated_native, native_caps
        if key=='discovery_requests' and isolated_native(spec):cap=max(native_caps(spec).values())
        if policy: cap={'messages':policy['group_messages'],'session_bytes':policy['body_bytes'],'discovery_requests':policy['requests']}.get(key,cap)
        v=prediction.get(key) if isinstance(prediction,dict) else None
        if metadata_diagnostic and key in ('messages','connections','frame_bytes'):
            if type(v) is not int or v!=0:errors.append('prediction.'+key+': metadata diagnostic requires zero')
        elif type(v) is not int or not 0 < v <= cap:
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
                activation_reason='explicit separately approved Start required; public discovery probe never loads credentials' if spec.get('native_discovery',{}).get('discovery_only') else 'explicit Start required; credentials resolved only for selected subscriptions')


def main():
    import argparse,json
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spec',type=Path)
    args=parser.parse_args()
    print(json.dumps(preflight(json.loads(args.spec.read_text())),indent=2))

if __name__=='__main__': main()
