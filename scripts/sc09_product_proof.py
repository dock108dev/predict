#!/usr/bin/env python3
"""Read-only, streamed common-snapshot raw/publication reconciliation.

No acquisition, normalization or production calculator is invoked. Results retain
revision distinctions: a current raw book need not equal an older result frame.
"""
import argparse
from collections import Counter,defaultdict
from fractions import Fraction
import json
from pathlib import Path
import sys
from time import monotonic
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,encoded,hashed
from sc09_independent_math import benchmark, conditional as verify_conditional
from app.storage import raw_prices
from app.collection.runtime_status import read_runtime
from app.dashboard.comparison_board import expand_price_fields,expand_odds


def ratio(v):
    return Fraction(int(v['numerator']),int(v['denominator'])) if isinstance(v,dict) else Fraction(v)


def run(destination):
    started=monotonic();counts=defaultdict(Counter);raw_index={};issues=Counter();examples=[];results=[];typed_results=[];conditional_results=[];receipts={};publications=[]
    with connect() as db:
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            at=db.execute('SELECT transaction_timestamp()::text at').fetchone()['at'];owner=read_runtime(db)
            with db.cursor(name='proof_raw') as cursor:
                cursor.itersize=100;cursor.execute('SELECT * FROM ('+raw_prices.HEADER+') h ORDER BY kind,venue,sport,event_id,market_id')
                for header in cursor:
                    b=raw_prices.book(db,header,owner);key='|'.join((b['venue'],b['sport'],b['family']));c=counts[key]
                    c['received_books']+=1;c['book_state:'+b['status']]+=1
                    if b['period']=='unknown':issues['unknown_period_books']+=1
                    # Independent source ladder/outcome lookup, no display helper.
                    if b['kind']=='native':
                        original=db.execute('SELECT image FROM current_acquisition_image WHERE source=%s AND event_id=%s AND market_id=%s',(b['venue'],b['event_id'],b['market_id'])).fetchone()['image']
                        originals={(o['outcome_id'],side):((o.get(side) or {}).get('levels') or [None])[0] for o in original['outcomes'] for side in ('asks','bids')}
                    else:
                        receipt_key=(b['kind'],b['sport'],b['event_id'] if b['kind']=='alternate' else None)
                        if receipt_key not in receipts:
                            if b['kind']=='featured':
                                payload=db.execute('SELECT payload FROM current_acquisition_aggregate WHERE sport=%s',(b['sport'],)).fetchone()['payload']['events']
                            else:
                                payload=[db.execute('SELECT payload FROM current_acquisition_alternate WHERE sport=%s AND event_id=%s',(b['sport'],b['event_id'])).fetchone()['payload']]
                            receipts[receipt_key]={(e['id'],book['key'],m['key']):m['outcomes'] for e in payload for book in e.get('bookmakers',[]) for m in book.get('markets',[])}
                        original=receipts[receipt_key][(b['event_id'],b['venue'],b['market_id'])]
                        originals={(str(o.get('name',i)),str(o.get('point'))):o for i,o in enumerate(original)}
                    for o in b['observations']:
                        c['received_slots']+=1;c['slot:'+o['disposition']]+=1
                        if b['kind']=='native':
                            native=originals[(o['outcome_id'],o['side'])];expected=(native or {}).get('price',{}).get('value')
                            quantity=(native or {}).get('quantity')
                            if quantity!=o['quantity']:issues['quantity_mismatch']+=1
                        else:expected=originals[(o['outcome_id'],str(o['line']))].get('price')
                        if o['price']!=expected:issues['original_value_mismatch']+=1
                        if o['price'] is not None and b['kind']!='native' and Fraction(str(o['price']))==1:issues['aggregate_decimal_one']+=1
                        if b['venue']=='polymarket_us' and str(o['label']).isdigit():issues['numeric_pm_labels']+=1
                        if o.get('representation')=='not_independently_supplied_short_bid':issues['pm_short_bid_not_separately_supplied']+=1
                        if o['price'] is not None:
                            raw_index[(b['venue'],b['event_id'],b['market_id'],o['outcome_id'],o['side'],str(o['line']))]=(str(o['price']),b['source_at'],b['received_at'],b['revision'])
                    if len(examples)<6 or (b['venue']=='polymarket_us' and not any(x['venue']=='polymarket_us' for x in examples)):examples.append(b)
            # Native admission and aggregate raw receipts are independent populations.
            admitted=db.execute("SELECT c.venue,e.competition league,c.facts#>>'{market_identity,family}' family,count(*) n FROM current_contract c JOIN current_event e ON e.id=c.event_id GROUP BY 1,2,3").fetchall()
            for r in admitted:counts['|'.join((r['venue'],r['league'],r['family']))]['admitted_contracts']=r['n']
            inventory=db.execute("""SELECT c.venue,e.competition league,
                c.facts#>>'{market_identity,family}' family,
                c.facts#>>'{market_identity,period}' period,
                COALESCE(c.facts#>>'{comparison_source_metadata,native_market_type}',c.facts#>>'{comparison_source_metadata,series_id}','aggregate_outcome') native_type,
                c.facts#>>'{comparison_source_metadata,comparison_admission,reason}' admission_reason,
                o.facts#>>'{original,units}' price_units,o.facts#>>'{original,quantity_units}' quantity_units,
                count(*) contracts,
                count(*) FILTER (WHERE e.facts->>'season' IS NULL OR e.facts->>'stage' IS NULL) missing_occurrence_context,
                count(*) FILTER (WHERE c.facts#>>'{comparison_source_metadata,source_predicate}' IS NOT NULL) explicit_score_predicates
                FROM current_contract c JOIN current_event e ON e.id=c.event_id JOIN current_offer o ON o.contract_id=c.id
                GROUP BY 1,2,3,4,5,6,7,8 ORDER BY 1,2,3,4,5,6,7,8""").fetchall()
            status=db.execute('SELECT facts FROM latest_board_status').fetchone()['facts']
            games={g['game_key']:g for g in status['games']}
            with db.cursor(name='proof_boards') as cursor:
                cursor.itersize=1;cursor.execute('SELECT game_key,facts FROM latest_board ORDER BY game_key')
                for saved in cursor:
                    publications.append(dict(game=saved['game_key'],has_completed_financial=bool(saved['facts'].get('context')),
                        availability=saved['facts'].get('estimate_availability'),context=saved['facts'].get('context')))
                    packed=saved['facts'].get('selected_frame')
                    if packed:
                        from app.storage.payload_codec import decode
                        from app.storage.shared_json import loads
                        from app.dashboard.comparison_board import entries
                        from app.comparison.current_dependencies import references
                        financial=loads(decode(packed)).get('financial')
                        if financial:
                            for event,group,q in entries(financial['state_inputs']):
                                family={'winner':'moneyline'}.get(group['market'],group['market'])
                                c=counts['|'.join((q['venue'],event['league'],family))]
                                status_ref=q.get('comparison_input_status',{}).get('reference',{})
                                c['reference_binding:'+status_ref.get('reason','absent')]+=1
                                payload=references(q,financial['state_inputs']['comparison_profiles']).get('reference',{}).get('payload',{})
                                if len(payload.get('outcomes',[]))==2:c['complete_bound_reference_pair']+=1
                    odds=expand_odds(expand_price_fields(saved['facts']['boards']['odds']))
                    for price in odds.get('prices',[]):
                        event=price.get('event',{});family=price.get('market',{}).get('market','unknown')
                        family={'winner':'moneyline'}.get(family,family)
                        c=counts['|'.join((price['venue'],event.get('league','unknown'),family))]
                        c['published_prices']+=1
                        c['financial_publication:'+('completed' if saved['facts'].get('context') else 'pending')]+=1
                        identity=price.get('same_outcome',{})
                        c['identity:'+('supported' if identity.get('supported') else str(identity.get('reason','unknown')))]+=1
                        comparison=price.get('gross_comparison',{})
                        c['equivalent_peer:'+('available' if comparison.get('available') else str(comparison.get('reason_code','absent')))]+=1
                        if comparison.get('available'):
                            inputs=comparison['inputs']
                            assert len(inputs)==2
                            assert inputs[0]['same_outcome']['key']==inputs[1]['same_outcome']['key']
                            c['equal_contract_key_verified']+=1
                    board=expand_odds(expand_price_fields(saved['facts']['boards']['ev']))
                    prices={p['quote_id']:p for p in board.get('prices',[])}
                    for r in board.get('rows',[]):
                        p=prices.get(r.get('price_ref') or r.get('quote_id'),r)
                        event=p.get('event') or games.get(saved['game_key'],{});market=p.get('market') or r.get('market') or {}
                        family=market.get('market') if isinstance(market,dict) else market
                        family={'winner':'moneyline'}.get(family,family) or ('total' if p.get('selection',{}).get('predicate') in ('over','under') else 'spread' if p.get('selection',{}).get('predicate')=='cover' else 'moneyline' if p.get('selection',{}).get('predicate') in ('win','not_win') else 'unknown')
                        key='|'.join((p.get('venue',r.get('venue','unknown')),event.get('league',board.get('league','unknown')),family));c=counts[key]
                        c['published_ev_rows']+=1;c['availability:'+r.get('availability',{}).get('state','unknown')]+=1
                        for reason in r.get('availability',{}).get('reason_codes',[]):c['reason:'+reason]+=1
                        conditional=r.get('conditional_trade_benchmark') or {}
                        c['conditional:'+str(conditional.get('state') if conditional.get('available') else conditional.get('reason') or 'not_supplied')]+=1
                        gross=r.get('gross_decisive_benchmark') or {}
                        if not gross.get('available'):
                            c['gross_unavailable:'+str(gross.get('reason','not_supplied'))]+=1;continue
                        c['gross_state:'+gross.get('state','unknown')]+=1
                        for why in gross.get('currentness_reasons',[]):c['gross_currentness:'+why]+=1
                        ref=gross.get('reference_binding')
                        probability,cost=benchmark(gross,p)
                        expected=100*(probability/cost-1);actual=ratio(gross['return_percent'])
                        if conditional.get('available'):
                            terminal_sum=verify_conditional(conditional,p,probability)
                            c['independently_verified_conditional']+=1
                            conditional_results.append(dict(game=saved['game_key'],quote=r['quote_id'],cohort=key,
                                expected=str(terminal_sum),original=p['original'],times=p['times'],reference=ref or gross['reference_originals'],metric=conditional))
                        if not ref:
                            c['independently_verified_typed_gross']+=1
                            typed_results.append(dict(game=saved['game_key'],quote=r['quote_id'],cohort=key,price=p,metric=gross,independently_verified_return_percent=str(expected)))
                            continue
                        c['independently_verified_gross']+=1;c['gross_sign:'+('positive' if actual>0 else 'negative' if actual<0 else 'zero')]+=1
                        source=p['source'];original=p['original'];native_market='h2h' if family=='moneyline' else 'spreads' if family=='spread' else 'totals'
                        if source['native_market_id'].startswith('alternate:'):native_market='alternate_'+native_market
                        raw_key=(p['venue'],source['native_event_id'],native_market,source['native_outcome_id'],'offer',str(source.get('native_line')))
                        current=raw_index.get(raw_key)
                        relation='same_source_value_and_clock' if current and current[:2]==(str(original['value']),p['times']['source_at']) else 'retained_result_revision_or_unmapped'
                        c['raw_link:'+relation]+=1
                        results.append(dict(game=saved['game_key'],title=event.get('title'),quote=r.get('quote_id'),cohort=key,
                            state=gross['state'],original=original,source=source,times=p['times'],reference=ref,
                            independently_verified_return_percent=str(expected),published=gross['return_percent'],raw_relation=relation))
            report=dict(schema='sc09-common-snapshot-proof-1',captured_at=at,provider_requests=0,
                raw_and_publications_same_mvcc=True,core_applicability_inventory=inventory,cohorts={k:dict(v) for k,v in sorted(counts.items())},raw_issues=dict(issues),
                numeric_gross=results,numeric_typed=typed_results,conditional_results=conditional_results,raw_examples=examples,publication_errors=status.get('observation_errors',[]),
                calculation_errors=status.get('errors',[]),scope_complete=status.get('scope_complete'),
                publications=publications,
                raw_identity_digest=hashed(sorted((list(k),v) for k,v in raw_index.items())),
                runtime=dict(active=owner.get('active'),healthy=owner.get('healthy'),runtime_id=owner.get('runtime_id')),
                elapsed_seconds=monotonic()-started)
    Path(destination).write_bytes(encoded(report));print(json.dumps(dict(output=destination,cohorts=len(counts),raw_issues=dict(issues),numeric_gross=len(results),conditional=len(conditional_results),elapsed_seconds=report['elapsed_seconds'])))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    run(parser.parse_args().output)
