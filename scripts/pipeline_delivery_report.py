"""Summarize measured delivery with sample bounds, never invented exact latency."""
import gzip
import json
from collections import Counter
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import stamp
from scripts.pipeline_convergence_report import publication_current
from scripts.pipeline_changing_report import distribution


def load_samples(folder):
    paths=sorted(Path(folder).glob('sample-*.json*'))
    return [json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes()) for p in paths]


def build(folder):
    folder=Path(folder);samples=load_samples(folder)
    if not samples:raise ValueError('delivery_samples_required')
    first,last=samples[0],samples[-1];initial={e['id']:e for e in first['events']}
    ledger={g['id']:g for s in samples for g in s['generations'] if g['engine']==first['engine']}
    histories={};current_generations={};changed=set();materiality=Counter()
    for sample in samples:
        current={e['id']:e for e in sample['events']}
        changed.update(sample['summary']['changed_events'])
        for change in sample['field_observation']['changes']:
            fields=set(change['fields'])
            category=('price_or_depth' if fields & {'price_value','depth_revision'} else
                'contract_or_rules' if fields & {'contract_dependency','metric_dependency'} else
                'state_or_sync' if fields & {'state','sync'} else
                'receipt_only' if fields <= {'received_at','book_received_at'} else 'source_clock_or_revision')
            materiality[category]+=1
        valid=[p for p in sample['publications'] if publication_current(p,sample)]
        for p in valid:
            if p['generation']:current_generations.setdefault(p['generation'],sample['at'])
        valid_events={eid for p in valid for eid in p['publication_events'] or []}
        for eid,e in current.items():
            h=histories.setdefault(eid,dict(source_event_id=eid,source=e['provider'],native_event_id=e['native_event_id'],
                first_offered=sample['at'],offered_samples=0,current_samples=0,first_current=None,last_current=None))
            h['offered_samples']+=1
            if eid in valid_events:
                h['current_samples']+=1;h['first_current']=h['first_current'] or sample['at'];h['last_current']=sample['at']
    final_events={e['id'] for e in last['events']};historical=set(json.loads((folder/'historical-identities.json').read_text()))
    receipt_to_marker=[];receipt_to_sample=[];capture_to_marker=[];admission_to_completion=[];lock_wait=[];new_receipt_marker=[];new_receipt_sample=[]
    for gid,g in ledger.items():
        trace=g.get('trace',{});receipt=trace.get('receipt_newest_at')
        if g['published_at'] and g['disposition']=='published' and not g['facts'].get('retained_financial_only'):
            if receipt:
                latency=(stamp(g['published_at'])-stamp(receipt)).total_seconds();receipt_to_marker.append(latency)
                if stamp(receipt)>=stamp(first['at']):new_receipt_marker.append(latency)
            if trace.get('captured_at'):capture_to_marker.append((stamp(g['published_at'])-stamp(trace['captured_at'])).total_seconds())
        if gid in current_generations and receipt:
            latency=(stamp(current_generations[gid])-stamp(receipt)).total_seconds();receipt_to_sample.append(latency)
            if stamp(receipt)>=stamp(first['at']):new_receipt_sample.append(latency)
        if g['completed_at']:admission_to_completion.append((stamp(g['completed_at'])-stamp(g['admitted_at'])).total_seconds())
        if g['facts'].get('ingress_lock_wait_ms') is not None:lock_wait.append(g['facts']['ingress_lock_wait_ms'])
    attempts={a['event_id']:a for a in last['attempts'] if a['branch']=='metrics' and a['engine']==last['engine']}
    for eid,h in histories.items():
        generations=[g for g in ledger.values() if eid in g.get('events',[])]
        attempt=attempts.get(eid)
        h.update(unique_generations=len(generations),committed_generations=sum(bool(g['published_at']) for g in generations),
            current_attempt=attempt,
            oldest_attempt_age_seconds=(stamp(last['at'])-stamp(attempt['first_attempt'])).total_seconds() if attempt else None)
        h.update(changed_observed=eid in changed,still_offered=eid in final_events,historical_unresolved=eid in historical,
            temporary_membership_gaps=sum(not any(e['id']==eid for e in s['events']) for s in samples
                if stamp(h['first_offered'])<=stamp(s['at']) and eid in final_events))
    def group(ids):
        rows=[histories[eid] for eid in ids if eid in histories]
        return dict(identities=len(ids),observed=len(rows),ever_current=sum(r['current_samples']>0 for r in rows),
            still_offered=sum(r['still_offered'] for r in rows),
            never_current_still_offered=[r for r in rows if r['still_offered'] and not r['current_samples']])
    sizes=[s['summary']['database_bytes'] for s in samples]
    return dict(interval=[first['at'],last['at']],seconds=(stamp(last['at'])-stamp(first['at'])).total_seconds(),samples=len(samples),
        engines=sorted({s['engine'] for s in samples}),runtimes=sorted({s['runtime']['runtime_id'] for s in samples}),
        healthy_samples=sum(s['runtime']['healthy'] for s in samples),
        storage=dict(first=sizes[0],last=sizes[-1],minimum=min(sizes),maximum=max(sizes),net_growth=sizes[-1]-sizes[0],headroom=2147483648-sizes[-1]),
        initial=group(set(initial)),historical=group(historical),historical_not_observed=sorted(historical-set(histories)),
        arrivals=group(set(histories)-set(initial)),changing=group(changed),
        generations_admitted_during_observation=sum(stamp(g['admitted_at'])>=stamp(first['at']) for g in ledger.values()),
        unique_generations=len(ledger),unique_completed=sum(bool(g['completed_at']) for g in ledger.values()),
        unique_reused=sum(bool(g['reuses']) for g in ledger.values()),unique_dispositions=dict(Counter(g['disposition'] for g in ledger.values())),
        unique_sampled_current_generations=len(current_generations),bounded_field_witness_categories=dict(materiality),
        newest_dependency_receipt_to_publication_marker_seconds=distribution(receipt_to_marker),
        in_run_newest_receipt_to_publication_marker_seconds=distribution(new_receipt_marker),
        in_run_newest_receipt_to_first_sampled_current_seconds=distribution(new_receipt_sample),
        newest_dependency_receipt_to_first_sampled_current_seconds=distribution(receipt_to_sample),
        capture_to_publication_marker_seconds=distribution(capture_to_marker),admission_to_completion_seconds=distribution(admission_to_completion),
        ingress_lock_wait_ms=distribution(lock_wait),
        oldest_current_engine_pending=min((a['first_attempt'] for a in last['attempts'] if a['branch']=='metrics'
            and a['engine']==last['engine'] and a['event_id'] in final_events and a['disposition']!='passed'),default=None),
        rows=list(histories.values()),
        limitations=['published_at is written inside the commit transaction; exact commit visibility is bounded by the first observing sample.',
            'Receipt latency is from the newest captured dependency receipt, not latency of every changed field.',
            'Field witnesses are capped at 32 changed offers per sample and eight dependencies per generation; unsampled materiality is unknown.',
            'Raw field snapshots follow publication snapshots; clocks are separate. Retired means absent from observed eligible window, not authoritative source withdrawal.',
            'Generation totals cover the fixed engine including bootstrap before the first sample; in-run admissions are counted separately.',
            'Attempt first_attempt may predate this admission; its age is an observed pending-age bound, not an exact per-generation queue wait.',
            'Current publication is not proof of supported EV or financial pairs.'])

if __name__=='__main__':
    result=build(sys.argv[1]);Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('rows','initial','historical','arrivals','changing')},indent=2))
