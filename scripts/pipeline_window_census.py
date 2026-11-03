"""One-snapshot received/normalized/published 72h reconciliation, no acquisition.

Native identity joins, not selected financial frames, define the observation
population. Source-offered inventory is separately unknown. Publication keys
are checked against each normalized native instrument, including missing rows.
"""
import json
from collections import Counter,defaultdict
from datetime import timedelta,timezone
from fractions import Fraction
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp
from app.storage.current_games import engine_binding,observation_binding
from app.storage.current_rows import contract_id
from app.dashboard.comparison_board import expand_price_fields,expand_odds,expand_financial,age_observation


def run(path, *, trace=False):
    publication_traces={};branch_rows=[];pair_rows=[]
    counts=defaultdict(Counter);normalized={};published={};groups=defaultdict(list);traces=[];game_counts=Counter();references=set();opposing=Counter();opposing_traces=[];trace_counts=Counter()
    with connect() as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        at=db.execute('select transaction_timestamp() at').fetchone()['at'].astimezone(timezone.utc);end=at+timedelta(hours=72)
        source_events=db.execute("select id,provider,native_event_id,facts->>'scheduled_start' start from current_event").fetchall()
        events={r['id']:r for r in source_events if r['start'] and at<=stamp(r['start'])<end}
        with db.cursor(name='normalized_population') as cursor:
            cursor.itersize=256;cursor.execute('''select c.venue,e.native_event_id,c.native_market_id,c.native_outcome_id,c.native_side,
                e.facts->>'competition' league,c.facts#>>'{market_identity,family}' family,
                c.facts#>>'{market_identity,period}' period,c.facts->'selection' selection,
                c.facts#>'{comparison_source_metadata,same_outcome}' descriptor,o.revision
                from current_offer o join current_contract c on c.id=o.contract_id join current_event e on e.id=c.event_id
                where c.event_id=ANY(%s)''',(list(events),))
            for r in cursor:
                key=tuple(r[k] for k in ('venue','native_event_id','native_market_id','native_outcome_id','native_side'))
                cohort='|'.join((r['venue'],r['league'],r['family'] or 'unknown'))
                counts[cohort]['normalized_offers']+=1;normalized[key]=dict(cohort=cohort,**r)
        status=db.execute('select facts from latest_board_status').fetchone()['facts'];engine=engine_binding();source_binding=observation_binding()
        from app.storage import observation_publication as publication
        from app.storage.latest_board import runtime,source_states
        owner=runtime(db)
        states=source_states({r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status')},owner)
        frame=publication.capture(db,states,compact='lazy',selector=dict(events=list(events),occurrences=[],shared=[]))
        catalog={g['game_key']:g for g in status['games'] if g.get('start_at') and at<=stamp(g['start_at'])<end}
        with db.cursor(name='publication_population') as cursor:
            cursor.itersize=1;cursor.execute("select game_key,facts->'boards'->'odds' odds,facts->'boards'->'ev' ev,facts->'boards'->'arbs' arbs,facts#>>'{context,engine_binding}' engine,facts->>'observation_binding' observation_binding,facts->'publication_dependencies' observation_dependencies,coalesce(facts->'financial_dependencies',facts->'publication_dependencies') dependencies,facts->>'retained_financial_only' retained_only,facts->>'valid_until' valid_until from latest_board where game_key=ANY(%s)",(list(catalog),))
            for r in cursor:
                observation_checks=publication.reasons(frame,r['observation_dependencies']) if r['observation_dependencies'] else dict(all=['missing_manifest'],observations={})
                checks=publication.reasons(frame,r['dependencies']) if r['dependencies'] else dict(all=['missing_manifest'],observations={},comparisons={})
                failures=sorted(set(checks['all']+[reason for section,values in checks.items() if section!='all' for reasons in values.values() for reason in reasons]))
                if r['retained_only']=='true':failures.append('retained_financial_only')
                if r['valid_until'] and stamp(r['valid_until'])<=at:failures.append('publication_expired')
                if not owner.get('healthy') or not owner.get('active') or owner.get('calculations',{}).get('board')!='running':
                    failures.append('runtime_authority_unavailable')
                game_counts['published_games']+=1;game_counts['engine_current_games']+=r['engine']==engine
                game_counts['financial_current_games']+=r['engine']==engine and not failures
                game_counts['financial_historical_games']+=r['engine']!=engine or bool(failures)
                b=expand_odds(expand_price_fields(r['odds']))
                for ref in b.get('reference_prices',[]):
                    src=ref['source'];references.add(('pinnacle',src['native_event_id'],src['native_market_id'],src['native_outcome_id'],src['native_side']))
                exact=[q for q in b['prices'] if q.get('same_outcome',{}).get('supported')]
                for i,a in enumerate(exact):
                    ak=a['same_outcome']['key']
                    for other in exact[i+1:]:
                        bk=other['same_outcome']['key']
                        if a['venue']==other['venue'] or ak[1:7]!=bk[1:7] or ak[10:]!=bk[10:] or ak[10]!=['predicate']:continue
                        ap,bp=ak[9],bk[9]
                        if ap[0]!=bp[0] or {ap[1],bp[1]}!={'ge','le'}:continue
                        low,high=(ap,bp) if ap[1]=='le' else (bp,ap)
                        if Fraction(*high[2])-Fraction(*low[2])!=1:continue
                        pair_key='|'.join((*sorted((a['venue'],other['venue'])),a['event']['league'],ak[5]))
                        opposing[pair_key]+=1
                        if len(opposing_traces)<30:opposing_traces.append(dict(game_key=r['game_key'],quote_ids=[a['quote_id'],other['quote_id']],classification='normal_score_complement_only_full_settlement_unproven'))
                ev=expand_price_fields(r['ev']);ev_index={q['quote_id']:q for q in ev['rows']}
                arbs=expand_financial(r['arbs']);pairs_by_quote=defaultdict(list)
                for pair in arbs['rows']:
                    item=dict(unit='published_pair_row',game_key=r['game_key'],pair_id=pair['pair_id'],
                        engine_current=r['engine']==engine,quote_ids=[leg['quote_id'] for leg in pair['legs']],
                        availability=pair.get('availability'),financial_metrics=pair.get('financial_metrics'))
                    pair_rows.append(item)
                    for qid in item['quote_ids']:pairs_by_quote[qid].append(pair['pair_id'])
                for q in b['prices']:
                    s=q['source'];key=(q['venue'],s['native_event_id'],s['native_market_id'],s['native_outcome_id'],s['native_side'])
                    cohort='|'.join((q['venue'],q['event']['league'],{'winner':'moneyline'}.get(q['market']['market'],q['market']['market'])))
                    c=counts[cohort];c['published_price_observations']+=1
                    raw_reasons=observation_checks['all']+observation_checks['observations'].get(contract_id(dict(quote=q)),['missing_observation_dependency'])
                    if r['observation_binding']!=source_binding:raw_reasons.append('matching_binding_changed')
                    age_observation(q,q['event'],at,source_states=states,publication_reasons=raw_reasons)
                    c['raw_display:'+q['observation_display']['state']]+=1
                    for code in q['freshness']['reasons']:c['raw_freshness_reason:'+code]+=1
                    c['financial_publication_current']+=r['engine']==engine and not failures
                    c['financial_publication_historical']+=r['engine']!=engine or bool(failures)
                    c['occurrence:'+q.get('occurrence_match',{}).get('status','absent')]+=1
                    ident=q.get('same_outcome',{});reason=ident.get('reason') or 'supported'
                    c['exact_outcome:'+reason]+=1
                    if key in published:c['duplicate_published_native_identity']+=1
                    published[key]=(r['game_key'],q['quote_id'],cohort)
                    if ident.get('supported'):groups[json.dumps(ident['key'])].append((cohort,q['venue'],q['quote_id']))
                    e=ev_index.get(q['quote_id']);c['ev_row_present']+=e is not None
                    if e:
                        c['full_ev_numeric_retained']+=e.get('financial_metrics',{}).get('buffered_ev_usd') is not None
                        for code in set(e.get('availability',{}).get('metrics',{}).get('buffered_ev_usd',{}).get('reason_codes',[])):
                            c['ev_refusal:'+code]+=1
                    publication_traces[key]=dict(game_key=r['game_key'],quote_id=q['quote_id'],
                        outcome=ident,occurrence=q.get('occurrence_match'),engine=r['engine'],dependency_failures=failures,raw_freshness=q['freshness'],raw_display=q['observation_display'],
                        pair_ids=pairs_by_quote.get(q['quote_id'],[]),pair_availability=arbs.get('availability'),
                        ev=None if e is None else dict(availability=e.get('availability'),
                            numeric=e.get('financial_metrics',{}).get('buffered_ev_usd') is not None))
                    if trace_counts[(cohort,reason)]<2:
                        traces.append(dict(native_key=key,game_key=r['game_key'],quote_id=q['quote_id'],outcome_reason=reason,occurrence=q.get('occurrence_match'),normalized_present=key in normalized,ev_row=e is not None))
                        trace_counts[(cohort,reason)]+=1
        for key,value in normalized.items():
            label=('reference_published' if key in references else 'reference_awaiting_publication') if key[0]=='pinnacle' else ('normalized_with_publication' if key in published else 'normalized_without_publication')
            counts[value['cohort']][label]+=1
        for key,value in normalized.items():
            p=publication_traces.get(key);is_reference=key[0]=='pinnacle'
            for branch in (('reference_grid',) if is_reference else ('raw_grid','ev','covered_pair')):
                disposition='waiting';stage='published';reason='normalized_identity_not_published'
                if is_reference and key in references:disposition='passed';reason='reference_publication_present'
                elif p:
                    if branch=='raw_grid':disposition='passed';reason='price_publication_present'
                    elif p['engine']!=engine:
                        disposition='waiting';stage='published';reason='old_engine_publication'
                    elif p['dependency_failures']:
                        disposition='waiting';stage='published';reason='stale_or_superseded_publication'
                    elif p['occurrence'] and p['occurrence'].get('status')!='matched':
                        disposition='rejected';stage='event_matched';reason='occurrence_unresolved_with_retained_candidates'
                    elif not p['outcome'].get('supported'):
                        disposition='rejected';stage='market_outcome_matched';reason=p['outcome'].get('reason') or 'outcome_diagnostic_absent'
                    elif branch=='covered_pair':
                        disposition='passed' if p['pair_ids'] else 'unknown';stage='comparison_assembled'
                        reason='published_pair_rows_linked' if p['pair_ids'] else 'no_published_pair_row_for_offer'
                    elif p['ev'] is None:reason='price_published_ev_row_absent'
                    elif p['ev']['numeric']:disposition='passed';stage='calculated';reason='numeric_retained_requires_currentness_validation'
                    else:
                        disposition='rejected';stage='metric_eligible'
                        codes=(p['ev'].get('availability') or {}).get('metrics',{}).get('buffered_ev_usd',{}).get('reason_codes',[])
                        reason=next(iter(sorted(codes)),'metric_diagnostic_absent')
                branch_rows.append(dict(unit='normalized_offer',native_key=list(key),revision=value['revision'],
                    cohort=value['cohort'],branch=branch,stage=stage,disposition=disposition,primary_reason=reason,
                    pair_ids=p.get('pair_ids',[]) if p and branch=='covered_pair' else None,
                    secondary_reasons=(p.get('pair_availability') or {}).get('causes',[]) if p and branch=='covered_pair' else [],
                    publication=p if branch=='raw_grid' else None,api_selected='unobserved',rendered='unobserved'))
        branch_counts=Counter('|'.join((r['cohort'],r['branch'],r['stage'],r['disposition'],r['primary_reason'])) for r in branch_rows)
        attempts=[dict(r) for r in db.execute('SELECT event_id,branch,first_attempt::text,last_attempt::text,attempts,disposition,reason,elapsed_ms,engine,facts FROM current_pipeline_attempt')]
        for key in published:
            if key not in normalized:
                # Schedule/source-frame transitions are distinct from dropped input.
                counts[published[key][2]]['publication_native_absent_current_window']+=1
        group_count=0;pair_count=0
        for rows in groups.values():
            venues={r[1] for r in rows if r[1]!='pinnacle'}
            if len(venues)>1:
                group_count+=1
                # Independent combinatorics, not the production comparison picker.
                pair_count+=sum(a[1]!=b[1] and 'pinnacle' not in (a[1],b[1]) for i,a in enumerate(rows) for b in rows[i+1:])
                for cohort,venue,qid in rows:counts[cohort]['comparable_cross_source_observations']+=1
        raw_dates={(r['provider'],r['native_event_id']):r['start'] for r in source_events}
        raw_events={}
        for header in db.execute('select source,header from current_native_catalog_recovery'):
            for event in header['header'].get('events',[]):
                raw_dates[(header['source'],event['id'])]=event.get('scheduled_start')
                raw_events[(header['source'],event['id'])]=event
        raw=db.execute("""select i.source venue,i.event_id,coalesce(m.sport,'unknown') league,
            coalesce(m.family,'unknown') family,i.disposition,i.market_id,count(*) books
            from current_acquisition_image i left join current_acquisition_market m using(source,event_id,market_id)
            group by i.source,i.event_id,m.sport,m.family,i.disposition,i.market_id""").fetchall()
        normalized_markets={(k[0],k[1],k[2]) for k in normalized}
        binding_rows=db.execute("select source,market_id,metadata->>'subscription_evidence_exclusion' exclusion,metadata#>>'{v1_raw_binding,status}' status,metadata#>'{v1_raw_binding,blockers}' blockers from current_native_market_recovery").fetchall()
        bindings={(r['source'],r['market_id']):r for r in binding_rows}
        raw_traces=[];raw_trace_counts=Counter()
        for r in raw:
            date=raw_dates.get((r['venue'],r['event_id']))
            within=None if not date else at<=stamp(date)<end
            label='raw_books_unknown_schedule' if within is None else 'raw_books_window' if within else 'raw_books_outside_window'
            c=counts['|'.join((r['venue'],r['league'],r['family']))];c[label]+=r['books']
            if within:
                c['raw_disposition:'+r['disposition']]+=r['books']
                present=(r['venue'],r['event_id'],r['market_id']) in normalized_markets
                c['raw_books_with_normalized_offer' if present else 'raw_books_without_normalized_offer']+=r['books']
                if not present:
                    binding=bindings.get((r['venue'],r['market_id']),{})
                    reason=binding.get('exclusion') or binding.get('status') or 'binding_unavailable'
                    c['raw_unpublished_binding:'+reason]+=r['books']
                    trace_key=(r['venue'],r['league'],r['family'],reason)
                    if raw_trace_counts[trace_key]<2:
                        raw_traces.append(dict(source=r['venue'],event_id=r['event_id'],market_id=r['market_id'],league=r['league'],family=r['family'],receipt_disposition=r['disposition'],binding=binding))
                        raw_trace_counts[trace_key]+=1
        from scripts.pipeline_result_unit_census import census as result_census
        result_units=result_census(db,frame,owner,at,events,engine)
        matching_trace=None
        receipt_trace=None
        if trace:
            from app.storage.pipeline_census import native_receipts
            receipt_trace=native_receipts(db,at,end,normalized)
            from app.storage.pipeline_matching_census import census as matching_census
            from app.storage.pipeline_matching_census import link_raw_peers
            matching_trace=link_raw_peers(db,matching_census(db),receipt_trace)
    result=dict(result_units=result_units,matching_lookup=matching_trace,branch_dispositions=dict(unit='normalized_offer_per_branch',total=len(branch_rows),counts=dict(branch_counts),reconciled=sum(branch_counts.values())==len(branch_rows),records=branch_rows),publication_attempts=attempts,native_receipt_trace=receipt_trace,captured_at=at.isoformat(),window_end=end.isoformat(),engine=engine,source_events=len(events),games=dict(game_counts),
        published_pair_rows=dict(unit='published_pair_row',total=len(pair_rows),records=pair_rows),
        offered_inventory=None,raw_unpublished_traces=raw_traces,cohorts={k:dict(v) for k,v in sorted(counts.items())},
        normal_score_opposing_pairs=dict(opposing),opposing_traces=opposing_traces,
        exact_cross_source_groups=group_count,same_outcome_cross_source_price_pairs=pair_count,traces=traces,
        notes=['One repeatable-read SQL snapshot; current means membership, not price freshness.',
               'Same-outcome price pairs are not opposing financial pairs.',
               'Raw native books use retained native catalog schedules independently of successful normalization; unknown schedule is explicit.',
               'Normal-score opposing pairs independently enumerate exact complementary integer score sets with predicate equality and identical scope/payout; they do not assert joint exceptional cashflows, allocations, fees, freshness or executable quantity.',
               'A linked pair row is provenance, not eligibility; an absent pair row does not prove the offer has no raw peer.',
               'EV refusal reasons overlap; normalized offers, books, price pairs and published EV rows are distinct units.'],provider_requests=0)
    Path(path).write_text(json.dumps(result,indent=2,default=str)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('cohorts','traces','opposing_traces','raw_unpublished_traces','native_receipt_trace','branch_dispositions','publication_attempts','matching_lookup','result_units')},default=str))

if __name__=='__main__':run(sys.argv[1],trace='--trace' in sys.argv[2:])
