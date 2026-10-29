"""Exact native score references using the shared typed two-way owner.

No nearest-line substitution. Equality is excluded from this conditional metric;
this is neither a settlement equivalence nor a complete probability model.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from .benchmark import TwoWayBenchmark
from .domain import CanonicalSelection, Scope
from .current_dependencies import digest, profile, references
from .source_inputs import produce_two_way_benchmark

RULE_PATH='app/fixtures/pinnacle-rules-20261028.html'
RULE_URL='https://www.pinnacle.com/en/future/betting-rules?aup=True&page=1'


def scoring(league):
    if league not in ('NFL','NCAAF','NBA','NCAAB','MLB','NHL'):
        raise ValueError('reference_scoring_scope_unreviewed')
    return dict(overtime='included',extra_innings='included' if league=='MLB' else 'not_applicable',
        shootout='official_final_score' if league=='NHL' else 'not_applicable',score_domain='integer')


def pairs(rows,event,venue):
    from app.collection.current_comparison_inputs import selection
    groups=defaultdict(list)
    for r in rows:
        q=r['quote'];m=r['market_identity']
        if q['venue']!=venue or m['family'] not in ('spread','total') or m['period']!='full_game':continue
        # Independent routes/receipts cannot provide opposite halves of a pair.
        groups[digest([m,q['provenance']['sha256'],q['times']['received_at'],
            q['source']['native_market_id'].startswith('alternate:')])].append(r)
    found=defaultdict(list)
    for group in groups.values():
        if len(group)!=2:continue
        first=group[0]['quote'];family=group[0]['market_identity']['family']
        typed=[]
        grouped='declared-aggregate-score:'+digest([r['quote']['source'] for r in group])
        try:
            for r in group:
                q=r['quote'];m=r['market_identity']
                g=dict(market=family,period='full_game',line=m['line'])
                s=CanonicalSelection.from_dict(selection(event,g,r['selection'],q))
                s=replace(s,scope=Scope('full_game','included','conditional_decisive_win_loss'),native=replace(s.native,market_id=grouped))
                clocks=q['provider_clocks']
                typed.append(dict(selection=s.to_dict(),decimal_odds=q['original']['value'],book_at=clocks['book'],
                    market_at=clocks['market'],received_at=q['times']['received_at'],revision=digest(r)))
            value=produce_two_way_benchmark(typed,venue=venue,receipt_sha256=first['provenance']['sha256'],source_revision=digest(group))
            ref=TwoWayBenchmark.from_dict(value);s=ref.outcomes[0].selection
            found[(family,s.predicate.domain,s.predicate.threshold.value)].append(dict(reference=value,original_sources=[deepcopy(r['quote']['source']) for r in group]))
        except (ValueError,KeyError,TypeError,ArithmeticError):continue
    return found


def attach(rows,state,pool,venue):
    from app.dashboard.current_contract import quotes_of
    evidence=dict(url=RULE_URL,path=RULE_PATH,sha256=sha256((Path(__file__).resolve().parents[2]/RULE_PATH).read_bytes()).hexdigest(),
        reviewed_at='2026-10-28T19:59:00Z',scope='Full-game completed ordinary scoring only; general rule 22 preserves market exceptions; exceptional settlement excluded')
    for event in state['events']:
        candidates=pairs(rows,event,venue) if venue=='pinnacle' else {}
        for group in event['groups']:
            if group['market'] not in ('spread','total'):continue
            for outcome in group['outcomes']:
                for q in quotes_of(outcome):
                    if q['source']['provider'] not in ('kalshi','polymarket_us'):continue
                    try:
                        identity=references(q,state['comparison_profiles'])['identity']['payload']
                        s=CanonicalSelection.from_dict(identity['selection'])
                        native=q['native_contract']['same_outcome']
                        if native.get('reason'):raise ValueError(native['reason'])
                        if native.get('predicate')!=s.predicate.to_dict():raise ValueError('reference_native_predicate_conflict')
                        actual=native['scoring'];expected=scoring(event['league'])
                        if any(actual.get(k)!=v for k,v in expected.items()):raise ValueError('reference_scoring_scope_conflict')
                        if not q['binding']['verified'] or q.get('occurrence_match',{}).get('status')!='matched':
                            raise ValueError('reference_occurrence_unqualified')
                        refs=candidates.get((group['market'],s.predicate.domain,s.predicate.threshold.value),[])
                        if not refs:raise ValueError('exact_native_reference_pair_absent')
                        # Select a complete most-recent original pair, never splice.
                        chosen=max(refs,key=lambda r:(min(x['received_at'] for x in r['reference']['outcomes']),r['reference']['revision']))
                        value=chosen['reference']
                        ref=TwoWayBenchmark.from_dict(value)
                        if any(x.selection.event.key!=s.event.key for x in ref.outcomes):raise ValueError('reference_occurrence_conflict')
                        key,item=profile('reference',value)
                        if not pool.add(key,item):raise ValueError('combined_benchmark_profile_capacity')
                        q['comparison_input_refs']['refs']['reference']=key
                        q['comparison_input_status']['reference']=dict(status='available_and_bound',reason='exact_native_score_reference_bound',
                            scoring_evidence=evidence,source_originals=chosen['original_sources'],scoring=expected,selected_predicate=s.predicate.to_dict(),
                            selected_equality=s.equality.to_dict(),conditioning='score_unequal_to_exact_threshold',
                            excluded=['equality','push','void','cancellation','exceptional settlement'])
                    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                        q['comparison_input_refs']['refs']['reference']=None
                        q['comparison_input_status']['reference']=dict(status='applicability_unresolved',reason=str(exc))
