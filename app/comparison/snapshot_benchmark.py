"""Exact retained Pinnacle pairs for snapshot math, never admission or execution.

Full Original records are required. Older display-only references cannot establish
receipt ownership, scoring scope or coherent frames and are not reconstructed.
"""
from collections import Counter, defaultdict
from fractions import Fraction as F
from copy import deepcopy

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
        row['market']['period'],p['domain'],p.get('subject_id'),str(F(p['threshold'])),scope['overtime'],scope.get('score_domain','integer'),
        scope.get('extra_innings','not_applicable'),scope.get('shootout','not_applicable'))


def withhold_unqualified_sgo(row):
    """Keep an SGO observation visible without borrowing a legacy reference.

    The current SGO normalization does not yet carry verified settlement or a
    current contributor lifecycle. A captured arithmetic witness alone does not
    authorize publishing it as live EV. This is deliberately fail-closed until
    those owners are integrated into the ordinary snapshot dependency path.
    """
    if (row.get('source') or {}).get('provider') != 'sportsgameodds':
        return False
    row['snapshot_benchmark'] = None
    row['reference'] = None
    row['benchmark_quote'] = None
    row['snapshot_benchmark_reason'] = 'sgo_reference_qualification_unavailable'
    row['snapshot_benchmark_missing'] = 'SportsGameOdds reference awaits verified occurrence, settlement and current contributor evidence'
    return True


def bind(quotes, references, settings, at):
    """Project all witnesses together; bind only exact, coherent two-sided frames."""
    originals=list(references)
    venue=settings['benchmark_venue']
    refs=[reference_row(r) for r in originals if r.get('original_record') and r['venue']==venue]
    combined=project([*quotes,*refs],settings)
    # Apply the same exact-context rule to received native prices in the other
    # leagues. Known bindings and their gross benchmark semantics stay intact.
    combined=project(combined,settings,leagues=('NFL','NCAAF','NBA','MLB','NHL'),preserve_known=True)
    rows=combined[:len(quotes)]
    # Finance has its own explicitly decisive domain. It never changes the
    # full-state grouping predicate (not-win remains not-win) or Admin scenarios.
    finance = deepcopy([*quotes,*refs])
    from app.comparison.occurrence_matching import OccurrenceResolver
    records = [r['original_record'] for r in finance]
    for record in records:
        record.setdefault('verified', False)
        record.setdefault('orientation_evidence', [])
    resolvable = all(all(r['event'].get(k) for k in ('season','stage'))
        for r in records if r['quote']['source']['provider']=='the_odds_api')
    resolved = OccurrenceResolver().resolve(records, clock=at) if records and resolvable else records
    occurrences = {}
    for row, record in zip(finance, resolved):
        match = record['quote'].get('occurrence_match',{})
        # A source-only provider grouping is not a cross-provider match.
        # Preserve the exact schedule and roles fallback for those records.
        if (match.get('status')=='matched' and not match['conflicts']
                and len({member['provider'] for member in match['members']}) > 1):
            source=record['quote']['source']
            occurrences[(source['provider'],source['native_event_id'])]=match['occurrence_id']
        # Full-game aggregate reference scoring is a reviewed source rule,
        # never borrowed from the native instrument it is meant to price.
        if row['venue']==venue and venue=='pinnacle' and record['quote']['source']['provider']=='the_odds_api':
            from app.comparison.line_reference import scoring, RULE_PATH, RULE_URL
            if not record.get('comparison_scope') and not record.get('comparison_source_metadata',{}).get('scoring_scope'):
                record['comparison_scope']=scoring(record['event']['competition'])
        row['original_record']=record
    finance=project(finance,dict(settings,scenario='decisive_only'),
        leagues=('NFL','NCAAF','NBA','NCAAB','MLB','NHL'),occurrences=occurrences)
    projected=finance[len(quotes):]
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
    for row, financial in zip(rows,finance[:len(quotes)]):
        if withhold_unqualified_sgo(row):
            issues['sgo_reference_qualification_unavailable']+=1
            continue
        if row['league']!='NCAAB' and row['venue'] not in ('kalshi','polymarket_us') and row.get('source',{}).get('provider')!='novig':continue
        row['snapshot_benchmark']=None
        row['snapshot_benchmark_reason']='exact_reference_pair_unavailable'
        row['snapshot_benchmark_missing']='Exact two-sided '+venue.title()+' reference absent from captured inputs'
        key=market_key(financial)
        if key is None:
            row['snapshot_benchmark_reason']=financial.get('same_outcome',{}).get('reason') or 'reference_scoring_scope_incompatible'
        candidates=index.get(key,[])
        if not candidates:
            if originals:row['snapshot_benchmark_missing']='No exact coherent '+venue.title()+' pair for this occurrence, scope and threshold; see reference diagnostics'
            continue
        p=financial['native_contract']['same_outcome']['predicate'];op=p['operator']
        if op not in ('gt','lt','ge','le'):continue
        # Prefer latest complete frame, never splice sides. Tied frames must agree.
        latest=max(stamp(c['received_at']) for c in candidates)
        candidates=[c for c in candidates if stamp(c['received_at'])==latest]
        if len({tuple(c['odds']) for c in candidates})!=1:
            row['snapshot_benchmark_reason']='reference_frames_conflict'
            row['snapshot_benchmark_missing']='Conflicting complete '+venue.title()+' frames';issues['conflicting_frames']+=1;continue
        ref=dict(sorted(candidates,key=lambda c:c['ids'])[0],selected=0 if op in ('gt','ge') else 1)
        ref['probability']=str(proportional_probability(ref['odds'],ref['selected']))
        ref['selected_odds']=ref['odds'][ref['selected']]
        ref['selected_predicate']=p
        ref['selected_identity']=financial['snapshot_identity']
        ref['selected_equality']=(row.get('native_contract') or {}).get('same_outcome',{}).get('equality')
        ref['fair_decimal_odds']=str(1/F(ref['probability']))
        row['snapshot_benchmark']=ref;row['snapshot_benchmark_missing']=None;row['snapshot_benchmark_reason']=None
        row['reference']=ref
        issues['bound_observations']+=1
    return rows,dict(reference_observations=len(originals),**issues)
