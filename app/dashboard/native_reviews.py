"""Content-addressed native judgments. Explicit records never imply acquisition authority."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from app.dashboard.session_projection import stable, stamp

DIRECTORY=Path(__file__).resolve().parents[1]/'reviews/native'
STATES={'UNKNOWN','CONDITIONAL','INCOMPATIBLE','SUPPORTED'}


def validate(record):
    r=deepcopy(record);digest=r.pop('sha256',None)
    if digest!=stable(r):raise ValueError('Native review content hash mismatch')
    if r.get('schema')!='native-review-1' or not r.get('review_id') or not isinstance(r.get('revision'),int) or r['revision']<1:raise ValueError('Unsupported native review version')
    if r.get('evidence_mode') not in ('observation','synthetic'):raise ValueError('Review evidence class missing')
    for judgment in (r['applicability'],r['settlement_assessment']):
        if judgment.get('status') not in STATES:raise ValueError('Unknown review judgment state')
    settlement=r['settlement_assessment']
    if (settlement['status']!='UNKNOWN' and not settlement.get('evidence')) or not isinstance(settlement.get('qualified'),bool):raise ValueError('Settlement evidence/qualification missing')
    if settlement['qualified'] and settlement['status']!='SUPPORTED':raise ValueError('Unresolved settlement cannot be qualified')
    if any(not isinstance(x,dict) or not x.get('condition') for x in settlement.get('unknown',[])+settlement.get('conflicts',[])):raise ValueError('Settlement conditions must be explicit')
    a=r['applicability']
    if not a.get('basis') or stamp(a['start'])>stamp(a['end']):raise ValueError('Invalid review applicability interval')
    if len(json.dumps(r))>262144:raise ValueError('Review record byte bound')
    ident=r['identity']
    if not all(ident.get(k) for k in ('sport','competition','family','period')):raise ValueError('Review market identity incomplete')
    if ident['competition'] not in ('NFL','NBA','MLB','NHL','NCAAF','NCAAB'):raise ValueError('Unsupported native sport competition')
    if ident['family'] not in ('moneyline','spread','total','futures'):raise ValueError('Unsupported native market family')
    if ident['family']=='moneyline' and ident['period']=='full_game':
        if ident.get('line') is not None or len(r['participants'])!=2:raise ValueError('Unsupported full-game winner structure')
        names=set(r['participants'].values())
        for source in r['sources'].values():
            winners=[]
            for outcome in source['outcomes'].values():
                if outcome.get('participant') not in names or outcome.get('predicate') not in ('win','not_win'):raise ValueError('Unsupported native winner predicate')
                winner=outcome['participant'] if outcome['predicate']=='win' else next(n for n in names if n!=outcome['participant'])
                if any(outcome.get(k,winner)!=winner for k in ('normal_winner','comparison_outcome')):raise ValueError('Conflicting reviewed winner correspondence')
                winners.append(winner)
            if len(winners)!=2 or set(winners)!=names:raise ValueError('Native outcomes do not cover both reviewed winners')
    else:
        from app.normalization.score_lines import orient_descriptor
        canonical=None
        for source in r['sources'].values():
            d=source['descriptor'];normalized,oriented=orient_descriptor(r['normalized_event'],d)
            if d['family']!=ident['family'] or d['period']!=ident['period'] or (None if d['family']=='moneyline' else normalized['threshold'])!=ident.get('line'):raise ValueError('Native descriptor scope differs from review')
            if canonical is not None and canonical!=normalized:raise ValueError('Native scoring domains do not correspond')
            canonical=normalized
            for side in oriented:
                mapped=source['outcomes'].get(side['native_id'],{})
                if mapped.get('operator')!=side.get('operator') or mapped.get('payouts')!=side.get('payouts'):raise ValueError('Native outcome differs from validated descriptor')
                expected=stable(dict(normalized,operator=side.get('operator'),role=side.get('role'),participant=d.get('participant') if d['family']=='futures' else None))
                if mapped.get('comparison_outcome')!=expected:raise ValueError('Explicit validated score/state correspondence missing')
    if set(r['sources'])!={'kalshi','polymarket_us'}:raise ValueError('Unsupported native comparison source set')
    for s in r['sources'].values():
        if not s.get('provenance') or not s.get('orientation_evidence') or not s.get('outcomes'):raise ValueError('Native orientation/provenance evidence missing')
        if not all(s.get(k) for k in ('event_id','market_id','native_metadata_sha256','event_metadata_sha256')):raise ValueError('Exact native identity missing')
        catalog=s.get('catalog_evidence')
        if catalog:
            e,m=catalog['event'],catalog['market']
            if e['id']!=s['event_id'] or m['id']!=s['market_id'] or m['event_id']!=e['id'] or e['canonical_key']!=r['event'] or stable(e['native_metadata'])!=s['event_metadata_sha256'] or stable(m['native_metadata'])!=s['native_metadata_sha256']:raise ValueError('Reviewed derived catalog identity/hash differs')
        if 'semantic_review_contract' in s:
            from app.collection.native_review_contract import validate as validate_contract
            if catalog:validate_contract(next(v for v,x in r['sources'].items() if x is s),s['semantic_review_contract'],catalog['event']['native_metadata'],s['metadata'])
            else:
                from app.collection.native_review_contract import POLICIES,project
                semantic=s['semantic_review_contract']
                if semantic.get('policy') not in POLICIES or semantic.get('market')!=project(next(v for v,x in r['sources'].items() if x is s),s['metadata'],policy=semantic['policy']):raise ValueError('Invalid semantic review terms')
        fee=s.get('fee_review',{'status':'UNKNOWN'})
        if fee.get('status') not in STATES or (fee['status']!='UNKNOWN' and not fee.get('evidence')):raise ValueError('Fee evidence/state missing')
    r['sha256']=digest
    return r


def records(projection):
    # Journal-owned records override the packaged historical interpretation.
    explicit=getattr(projection,'native_reviews',None)
    cache_key=(str(DIRECTORY),projection.sid)
    if not explicit and 'native_review_records' not in projection.spec and getattr(projection,'packaged_review_cache_key',None)==cache_key:return projection.packaged_review_cache
    values=list(explicit.values())
    if not explicit and 'native_review_records' not in projection.spec:
        index=json.loads((DIRECTORY/'index-v4.json').read_text())
        for name in index['historical_sessions'].get(projection.sid,[]):
            digest=index['records'][name]
            if Path(name).name!=name:raise ValueError('Unsafe native review filename')
            value=json.loads((DIRECTORY/name).read_text())
            if value.get('sha256')!=digest:raise ValueError('Packaged native review differs from sealed index')
            values.append(value)
    accepted=[];errors={};seen=set()
    # Only this new ordinary-session policy explicitly replaces its own pinned
    # template. Unmarked historic/overlapping revisions retain the legacy rules.
    superseded=set();invalid_successors=set()
    from app.collection.native_review_binding import CURRENT_POLICIES,verify_successor,revalidated_sources,enabled as current_binding_enabled
    for i,value in enumerate(values):
        if value.get('current_session_revalidation',{}).get('policy') not in CURRENT_POLICIES:continue
        key=str(value.get('review_id','missing'))+':'+str(value.get('revision','missing'))
        try:
            if not current_binding_enabled(projection.spec):raise ValueError('Current review policy was not selected by this session')
            current=validate(value)
            parents=[(j,v) for j,v in enumerate(values) if v.get('sha256')==current['current_session_revalidation'].get('template_sha256')]
            if len(parents)!=1:raise ValueError('Current review requires one exact selected template')
            j,parent=parents[0];verify_successor(current,validate(parent),projection.sid)
            if j>=i or j in invalid_successors:raise ValueError('Current review predecessor is missing or unsupported')
            if (stamp(current['applicability']['start'])<stamp(projection.started)
                or stamp(current['applicability']['start'])<stamp(parent['applicability']['start'])
                or stamp(current['applicability']['end'])>stamp(projection.started)+timedelta(seconds=projection.spec['duration'])):
                raise ValueError('Current review interval extends beyond its originating session')
            for venue,source in current['sources'].items():
                if venue not in revalidated_sources(current):continue
                if not source['provenance'] or any((venue,p['body_sha256']) not in projection.native_receipts
                    or not stamp(projection.started)<=stamp(projection.native_receipts[venue,p['body_sha256']])<=stamp(current['applicability']['start']) for p in source['provenance']):
                    raise ValueError('Current review lacks complete originating-session receipts')
            superseded.add(j)
        except (ValueError,KeyError,TypeError) as exc:
            invalid_successors.add(i);errors[key]=str(exc)
    from collections import Counter
    identities=Counter((v.get('review_id'),v.get('revision')) for v in values)
    targets={}
    overlapping=set()
    for i,v in enumerate(values):
        if i in superseded or i in invalid_successors:continue
        target=tuple(sorted((venue,x.get('event_id'),x.get('market_id')) for venue,x in v.get('sources',{}).items()))
        for j,other in targets.get(target,[]):
            try:
                if max(stamp(v['applicability']['start']),stamp(other['applicability']['start']))<=min(stamp(v['applicability']['end']),stamp(other['applicability']['end'])):overlapping.update((i,j))
            except (KeyError,ValueError,TypeError):overlapping.update((i,j))
        targets.setdefault(target,[]).append((i,v))
    for i,value in enumerate(values):
        if i in superseded or i in invalid_successors:continue
        key=str(value.get('review_id','missing'))+':'+str(value.get('revision','missing'))
        try:
            r=validate(value)
            target=tuple(sorted((venue,x['event_id'],x['market_id']) for venue,x in r['sources'].items()))
            if identities[(r['review_id'],r['revision'])]>1 or i in overlapping:raise ValueError('Conflicting reviews for the same native selection; select one explicit revision')
            if key in seen:raise ValueError('Conflicting duplicate review ID/revision')
            seen.add(key)
            if r['evidence_mode']=='synthetic' and projection.spec.get('mode')!='mock':raise ValueError('Synthetic review excluded from real observations')
            accepted.append(r)
        except (ValueError,KeyError,TypeError) as exc:errors[key]=str(exc)
    if not explicit and 'native_review_records' not in projection.spec:
        projection.packaged_review_cache_key=cache_key;projection.packaged_review_cache=(accepted,errors)
    return accepted,errors


def historical_paths():
    """Only explicitly indexed retained packages; no recursive discovery or acquisition."""
    index=json.loads((DIRECTORY/'index-v4.json').read_text());root=Path(__file__).resolve().parents[2]
    result={}
    for sid,binding in sorted(index.get('historical_paths',{}).items(),key=lambda item:(item[1].get('started_at',''),item[0])):
        path=Path(binding['folder'])
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='evidence':raise ValueError('Unsafe retained native history path')
        folder=root/path
        if folder.is_dir():result[sid]=folder
    return result
