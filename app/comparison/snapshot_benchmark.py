"""Exact retained Pinnacle pairs for snapshot math, never admission or execution.

Full Original records are required. Older display-only references cannot establish
receipt ownership, scoring scope or coherent frames and are not reconstructed.
"""
from collections import Counter, defaultdict
from fractions import Fraction as F

from app.comparison.snapshot_identity import project
from app.collection.current_benchmark import proportional_probability
from app.dashboard.current_contract import stamp
from app.storage.store import hashed


def reference_row(ref):
    r = ref['original_record']; m = r['market_identity']
    return dict(ref, league=r['event']['competition'], original_record=r,
        market=dict(market=m['family'],period=m['period'],line=m.get('line')),
        game_key=ref.get('game_key', 'reference:'+hashed(r['quote']['source'])))


def market_key(row):
    facts=(row.get('native_contract') or {}).get('same_outcome') or {}
    p=facts.get('predicate')
    if not row.get('snapshot_supported') or not p:return None
    scope=row['snapshot_identity']['scoring']
    if scope.get('overtime')!='included' or scope.get('score_domain','integer')!='integer':return None
    return (row['game_key'],row['market']['market'].replace('winner','moneyline'),
        row['market']['period'],p['domain'],p.get('subject_id'),str(F(p['threshold'])),scope['overtime'],scope.get('score_domain','integer'))


def bind(quotes, references, settings, at):
    """Project all witnesses together; bind only exact, coherent two-sided frames."""
    originals=[r for r in references if r.get('market',{}).get('competition')=='NCAAB']
    venue=settings['benchmark_venue']
    refs=[reference_row(r) for r in originals if r.get('original_record') and r['venue']==venue]
    combined=project([*quotes,*refs],settings)
    # Apply the same exact-context rule to received native prices in the other
    # leagues. Known bindings and their gross benchmark semantics stay intact.
    combined=project(combined,settings,leagues=('NFL','NCAAF','NBA','MLB','NHL'),preserve_known=True)
    rows=combined[:len(quotes)]
    # Reference weights are explicitly conditional on no equality. Execution
    # claims still use the user's actual scope/equality settings above.
    projected=project([*quotes,*refs],dict(settings,scenario='decisive_only'))[len(quotes):] if refs else []
    groups=defaultdict(list);issues=Counter();index=defaultdict(list)
    issues['missing_original_evidence']=len(originals)-len(refs)
    for ref in projected:
        key=market_key(ref)
        if key is None:
            issues['identity_or_scope_conflict']+=1;continue
        q=ref['original_record']['quote'];s=q['source'];t=q['times']
        # The aggregate adapter's alternate market IDs include each signed
        # source line, so opposite spread sides legitimately have different IDs.
        # As in current_benchmark.attach, exact semantic market + receipt + route
        # owns the pair; retain each original native ID without equating them.
        route=('alternate' if s['native_market_id'].startswith('alternate:') else 'standard') if s['provider']=='the_odds_api' else s['native_market_id']
        frame=(s['provider'],s['native_event_id'],route,
            q.get('provenance',{}).get('sha256'),t['received_at'],hashed(q.get('provider_clocks')))
        groups[(key,frame)].append(ref)
    for (key,frame),pair in groups.items():
        if len(pair)!=2:
            issues['incomplete_or_duplicate_pair']+=1;continue
        try:
            pair=sorted(pair,key=lambda r:r['native_contract']['same_outcome']['predicate']['operator'])
            preds=[r['native_contract']['same_outcome']['predicate'] for r in pair]
            if {p['operator'] for p in preds}!={'gt','lt'}:raise ValueError('crossed_pair')
            for ref in pair:
                record=ref['original_record'];market=record['market_identity'];selection=record['selection']
                if market.get('competition')!=record['event']['competition']:
                    raise ValueError('market_competition_conflict')
                if market.get('scheduled_start') and stamp(market['scheduled_start'])!=stamp(record['event']['scheduled_start']):
                    raise ValueError('market_schedule_conflict')
                if market['family'] in ('spread','total'):
                    line=F(market['line']);side=F(selection['signed_line'])
                    if (abs(line)!=abs(side) if market['family']=='spread' else line!=side):
                        raise ValueError('market_line_conflict')
            qs=[r['original_record']['quote'] for r in pair]
            if len({hashed(q['source']) for q in qs})!=2 or any(r['id']!=hashed(q['source']) for r,q in zip(pair,qs)):
                raise ValueError('original_identifier_conflict')
            if any(q['venue']!=venue or q['original']['units']!='decimal_odds' or q['original'].get('payout_units')!='USD' or F(q['original'].get('payout','0'))!=1 for q in qs):raise ValueError('original_odds_conflict')
            sha=frame[3]
            if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):raise ValueError('receipt_evidence_missing')
            odds=[q['original']['value'] for q in qs]
            proportional_probability(odds,0)
            clocks=[q['times']['source_at'] for q in qs]
            if None in clocks:raise ValueError('source_clock_unknown')
            if len(set(clocks))!=1:raise ValueError('incoherent_source_clocks')
            evaluation=stamp(at)
            for q in qs:
                t=q['times'];receipt=stamp(t['received_at']);source=stamp(t['source_at'])
                if receipt>evaluation or source>receipt or source>evaluation:raise ValueError('clock_future')
                pc=q.get('provider_clocks')
                if not pc or pc.get('selected_basis') not in ('book','market') or pc.get(pc['selected_basis'])!=t['source_at']:raise ValueError('provider_clock_evidence_missing')
                if any(stamp(pc[c])>receipt for c in ('book','market') if pc.get(c)):raise ValueError('clock_future')
            index[key].append(dict(bookmaker=venue,ids=[r['id'] for r in pair],odds=odds,source_at=clocks,
                method='proportional_no_vig',market_key=list(key),predicates=preds,
                reference_identities=[r['snapshot_identity'] for r in pair],
                received_at=frame[4],sha256=sha,provider_clocks=[q['provider_clocks'] for q in qs],
                age_seconds=(evaluation-stamp(clocks[0])).total_seconds(),
                conditioning='decisive win/loss; equality, ties, pushes and exceptional settlement excluded',
                role='reference_only',historical=True,strict_verified=False))
            issues['complete_pairs']+=1
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:issues[str(exc)]+=1
    for row in rows:
        if row['league']!='NCAAB':continue
        row['snapshot_benchmark']=None
        row['snapshot_benchmark_missing']='Exact two-sided '+venue.title()+' reference absent from captured inputs'
        key=market_key(row)
        candidates=index.get(key,[])
        if not candidates:
            if originals:row['snapshot_benchmark_missing']='No exact coherent '+venue.title()+' pair for this occurrence, scope and threshold; see reference diagnostics'
            continue
        p=row['native_contract']['same_outcome']['predicate'];op=p['operator']
        if op not in ('gt','lt','ge','le'):continue
        if op in ('ge','le') and F(p['threshold']).denominator==1 and settings['scenario']!='decisive_only':
            row['snapshot_benchmark_missing']='Inclusive equality requires explicit decisive-only domain';continue
        # Prefer latest complete frame, never splice sides. Tied frames must agree.
        latest=max(stamp(c['received_at']) for c in candidates)
        candidates=[c for c in candidates if stamp(c['received_at'])==latest]
        if len({tuple(c['odds']) for c in candidates})!=1:
            row['snapshot_benchmark_missing']='Conflicting complete '+venue.title()+' frames';issues['conflicting_frames']+=1;continue
        ref=dict(sorted(candidates,key=lambda c:c['ids'])[0],selected=0 if op in ('gt','ge') else 1)
        ref['probability']=str(proportional_probability(ref['odds'],ref['selected']))
        ref['selected_odds']=ref['odds'][ref['selected']]
        row['snapshot_benchmark']=ref;row['snapshot_benchmark_missing']=None
        row['reference']=ref
        issues['bound_observations']+=1
    return rows,dict(reference_observations=len(originals),**issues)
