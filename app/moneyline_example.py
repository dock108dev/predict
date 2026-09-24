"""Offline moneyline matching demonstration from preserved captures; no prices or ROI."""
import argparse
from collections import Counter
import json
from app.moneyline import MoneylineMatcher
from app.moneyline_captures import captured_inputs


def report(store=None):
    parents,rows,excluded,coverage=captured_inputs()
    matcher=MoneylineMatcher(); result=matcher.update(parents,rows)
    if store:
        matcher.save(store)
        assert MoneylineMatcher.load(store).report(parents)==result
    pairs=list(result['pairs'].values())
    return {'scope':'Historical production capture replay; no live liquidity or tradability claim',
            'coverage':coverage,'excluded_captured_markets':excluded,
            'summary':{'confirmed_event_pairs':len({c['canonical_event_id'] for c in coverage}),
                'events_with_both_venues_covered':sum(all(x['captured_full_game_moneylines'] for x in coverage if x['canonical_event_id']==cid)
                    for cid in {x['canonical_event_id'] for x in coverage}),
                'native_moneyline_markets':len(rows),'structurally_matched_pairs':sum(p['structural_match'] for p in pairs),
                'same_exposure_relationships':sum(r['same_exposure'] for p in pairs for r in p['relationships']),
                'opposing_sporting_relationships':sum(r['opposing_sporting_outcomes'] for p in pairs for r in p['relationships']),
                'settlement_statuses':dict(Counter(p['settlement']['status'] for p in pairs)),
                'qualified_pairs':sum(p['qualification']['eligible_for_fee_arb_evaluation'] for p in pairs)},
            'results':result,'market_evidence':rows,
            'synthetic_results':synthetic_reports(),
            'separate_dependencies':['ProphetX sizing/clock/live-selection limitations unchanged',
                                     'Novig issued credentials and live qualification unchanged'],
            'next_project_action':'Fee evaluation is separate; see app.fees for the implemented engine'}


def synthetic_reports():
    from app.settlement import fact, profile, compare_profiles, relationships, DIMENSIONS, SCENARIOS
    from hashlib import sha256
    text='Wholly invented settlement fixtures; no venue rule or approval evidence.'
    h=sha256(text.encode()).hexdigest()
    source={'url':'synthetic:slice-8','sha256':h,'text':text}
    dims={k:fact('synthetic-common',evidence=h) for k in DIMENSIONS}
    payouts={k:{'kind':'fraction','value':'0.50','evidence':h} for k in SCENARIOS}
    def make(d=None,p=None):
        return profile(sources=[source],dimensions=d or dims,payouts=p or payouts,actor='synthetic-test')
    base=make(); refund={**payouts,'tie':{'kind':'refund','evidence':h}}
    postponed={**dims,'postponement':fact('synthetic-24h-vs-48h',evidence=h)}
    missing={**dims,'resumption':fact(reason='synthetic missing resumption window')}
    cases={'identical-complete':base,'tie-refund-vs-fraction':make(p=refund),
           'postponement-conflict':make(d=postponed),'missing-resumption':make(d=missing),
           'discretionary':make(p={**payouts,'canceled':{'kind':'discretionary','evidence':h}})}
    sides=[{'native_id':'A','participant':'team-a','predicate':'win'}]
    other=[{'native_id':'B','participant':'team-b','predicate':'win'}]
    return {name:{'evidence_kind':'synthetic','settlement':(c:=compare_profiles(base,p)),
                  'relationships':relationships(sides,other,base,p,['team-a','team-b'],c)} for name,p in cases.items()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--store')
    args=parser.parse_args()
    print(json.dumps(report(args.store),indent=2))
