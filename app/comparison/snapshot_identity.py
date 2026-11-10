"""Snapshot-only identity projection. Never changes source admission or Originals."""
from collections import defaultdict
from copy import deepcopy

from app.comparison.event_links import instant
from app.comparison.occurrence_matching import OccurrenceResolver, UNKNOWN
from app.comparison.same_outcome import descriptor, selection_identity
from app.storage.store import hashed

SCORING_ASSUMPTION = 'ncaab_full_game_overtime'
DECISIVE_EQUALITY_BASIS = 'assumed conditional domain excludes equal score/threshold'
SCORING_MEANING = ('NCAAB full-game comparison assumes both instruments use integer final points including '
    'all overtime. Only the stated normal scoring predicate is compared; cancellation, postponement, '
    'tie/refund, fees and execution equivalence are not asserted.')


def project(quotes, settings, *, leagues=('NCAAB',), preserve_known=False, occurrences=None):
    """Exact-time, mutually unique occurrence associations and literal predicates.

    Native IDs identify only source-local occurrences. Cross-provider joins require
    consistent roles, exact schedule and unique source-game membership. Neither
    unknown context nor a declared scoring assumption can repair a conflicting join.
    """
    def target(q):
        reason=q.get('same_outcome',{}).get('reason')
        return (not preserve_known or reason=='comparison_context_missing' or
            reason=='comparison_equality_missing' and settings.get('scenario')=='decisive_only')

    resolver = OccurrenceResolver()
    facts = {}; conflicts = set(); neighborhoods = defaultdict(set)
    known_games = defaultdict(set)
    for q in quotes:
        if q['league'] not in leagues or not q.get('original_record'):continue
        r = q['original_record']; f = resolver._facts(r); k = f['key']
        if not target(q) and q.get('binding',{}).get('verified'):
            known_games[k].add(q['game_key'])
        comparable = {n:v for n,v in f.items() if n not in ('event','evidence','version')}
        if k in facts and comparable != facts[k][1]:conflicts.add(k)
        facts[k] = (f, comparable)
        if f['conflict'] or f['replacement']:conflicts.add(k)
        occurrence = (occurrences or {}).get(k)
        neighborhood = ('resolved', occurrence) if occurrence else ('schedule', instant(f['start']))
        neighborhoods[(f['league'], tuple(sorted(f['roles'].values())), neighborhood)].add(k)
    associations = {}
    for keys in neighborhoods.values():
        members = sorted(keys)
        if any(k in conflicts for k in members):continue
        # Distinct games from one provider at the same time are ambiguous even
        # when a shared ID happens to agree. Explicit native family aliases count once.
        source_games = defaultdict(set)
        for k in members:source_games[k[0]].add(facts[k][0]['source_game'])
        if any(len(v)>1 for v in source_games.values()):continue
        if not all(resolver._consistent(facts[a][0],facts[b][0]) and
                   facts[a][0]['roles']==facts[b][0]['roles'] for a in members for b in members):continue
        # Same typed shared ID at a conflicting schedule/roles must not silently
        # become a second snapshot occurrence.
        if any(set(facts[k][0]['shared'].items()) & set(other['shared'].items())
               for k in members for p,(other,_) in facts.items() if p not in keys):continue
        oid = 'snapshot-game:' + hashed(members)
        existing={g for k in members for g in known_games[k]}
        if preserve_known and len(existing)==1:oid=next(iter(existing))
        for k in members:associations[k] = (oid, members)
    output = []
    for original in quotes:
        q = dict(original); output.append(q)
        if q['league'] not in leagues or not q.get('original_record') or not target(q):continue
        r = q['original_record']; k = (r['quote']['source']['provider'],r['quote']['source']['native_event_id'])
        meta = r.get('comparison_source_metadata',{}); admission = meta.get('comparison_admission',{})
        q['snapshot_supported']=False
        q['same_outcome']=dict(supported=False,key=None,reason='snapshot_identity_or_scope_conflict',missing_fields=['identity_or_scope'])
        if r['market_identity'].get('period')!='full_game':continue
        # Other admission failures retain their independent meaning.
        if admission.get('supported') is False and (admission.get('reason')!='comparison_context_missing'
                or not set(admission.get('missing_fields',[])) <= {'season','stage'}):continue
        if k not in associations:
            q['same_outcome'] = dict(supported=False,key=None,reason='snapshot_occurrence_ambiguous',missing_fields=['occurrence'])
            q['snapshot_supported'] = False
            continue
        oid,members = associations[k]
        scope = meta.get('scoring_scope',{})
        if scope.get('conflicts'):continue
        scoring = dict(scope.get('scoring') or r.get('comparison_scope') or {})
        evidence = {v['overtime'] for v in scope.get('evidence',[]) if v.get('overtime') in ('included','excluded')}
        if len(evidence)>1:continue
        assumed = False
        if evidence:
            observed = next(iter(evidence))
            if scoring.get('overtime') in ('included','excluded') and scoring['overtime']!=observed:continue
            scoring['overtime'] = observed
        if q['league']=='NCAAB' and scoring.get('overtime') not in ('included','excluded') and settings.get('scoring')==SCORING_ASSUMPTION:
            scoring['overtime']='included';assumed=True
        mapping={r['event'][role]:facts[k][0]['roles'][role] for role in ('home','away')}
        event=dict(r['event'],**facts[k][0]['roles'])
        selection=dict(r['selection'],participant=mapping.get(r['selection'].get('participant'),r['selection'].get('participant')))
        projected = dict(r,event=event,selection=selection,comparison_source_metadata=dict(meta))
        if meta.get('source_predicate'):
            pred=deepcopy(meta['source_predicate'])
            pred['participant']=mapping.get(pred.get('participant'),pred.get('participant'))
            projected['comparison_source_metadata']['source_predicate']=pred
        projected['comparison_source_metadata'].pop('comparison_admission',None)
        # Reparse retained native sides through the shared strict predicate owner.
        # A previous unavailable descriptor is not a source predicate.
        projected['comparison_source_metadata'].pop('same_outcome',None)
        d = descriptor(projected,scoring=scoring)
        market=r['market_identity']
        normal=d.get('normal_payout') or r['quote']['original']
        if r['quote']['original'].get('units') in ('decimal_odds','american_odds'):
            normal=dict(payout='1',payout_units='USD',quantity_units='contracts')
        elif (r['quote']['source']['provider']=='novig' and r['quote'].get('novig_v3_evidence')
                and r['quote']['original'].get('quantity_units')=='novig_v3_cent_contracts'
                and normal.get('payout')=='1' and normal.get('payout_units')=='USD'):
            # The stored acquired-side price is already per normalized $1
            # claim. Only the mathematical payout identity uses that unit.
            normal=dict(normal,quantity_units='contracts')
        conditional_equality = False
        if d.get('reason')=='comparison_equality_missing' and settings.get('scenario')=='decisive_only':
            # Equality is outside this explicitly selected conditional domain.
            d = dict(d,reason=None,equality=dict(treatment='predicate',payout=None,refund_fees='not_applicable',unknown_reason=None))
            conditional_equality = True
        ident = selection_identity(event,market['family'],market['period'],scoring,selection,
            predicate=d['predicate'],equality=d['equality'],normal_payout=normal,occurrence=oid)
        if d.get('reason') and d['reason']!='comparison_equality_missing':
            ident=dict(supported=False,key=None,reason=d['reason'],missing_fields=d.get('missing_fields',[]))
        q['same_outcome']=ident
        q['snapshot_supported']=ident['supported']
        q['snapshot_identity']=dict(occurrence=oid,members=[list(p) for p in members],
            method='validated_ordinary_occurrence' if (occurrences or {}).get(k) else 'exact_schedule_unique_roles' if len(members)>1 else 'native_event_only',
            observed_context={f:r['event'].get(f) for f in ('season','stage')},
            scoring=scoring,scoring_basis='declared assumption' if assumed else 'retained source scoring evidence',
            assumption=SCORING_MEANING if assumed else None,
            equality_basis=DECISIVE_EQUALITY_BASIS if conditional_equality else 'retained predicate/equality',
            strict_verified=False)
        if conditional_equality and ident['supported']:ident['key'].append('conditional_excludes_equality')
        q['game_key']=oid
        q['native_contract']=dict(q.get('native_contract') or {},same_outcome=d)
    if preserve_known:
        # An optional equality projection may fail to establish cross-instrument
        # scoring equivalence. Keep the already verified source-local price and
        # exact benchmark instead of withdrawing its unchanged decisive math.
        for i,(original,projected) in enumerate(zip(quotes,output)):
            if (original.get('same_outcome',{}).get('reason')=='comparison_equality_missing'
                    and original.get('binding',{}).get('verified')
                    and not projected.get('snapshot_supported')):
                output[i]=dict(original)
    return output


def games(inputs, projected):
    """Retain every source name when several captured catalogs share a game.

    A projection may also split a prior display bucket. Build from each quote's
    actual destination instead of letting the last old->new mapping win.
    """
    catalogs={g['game_key']:g for g in inputs['games']}
    output={}
    for old,new in zip(inputs['quotes'],projected):
        source=catalogs.get(old['game_key'])
        if source is None:continue
        key=new['game_key']
        game=output.setdefault(key,dict(source,game_key=key,participants=[]))
        for participant in source.get('participants',[]):
            if participant not in game['participants']:game['participants'].append(participant)
    for game in output.values():
        roles={role:[p.get('name','') for p in game['participants'] if p.get('role')==role] for role in ('home','away')}
        if all(roles.values()):
            game['title']=max(roles['away'],key=len)+' at '+max(roles['home'],key=len)
    return output
