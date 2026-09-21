"""Isolated read-only recovery view using the E6 saved-session routes/components."""
import argparse
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
from app.collection.recovery import reopen_index
from app.dashboard import e6_live,e6_real

ROOT=e6_live.ROOT
CATALOG=ROOT/'evidence/e6/interrupted-recovery/catalog'

def projection(report,saved):
    rows=saved['rows'];spec=rows[0]['spec'];metadata={};health={v:'idle' for v in e6_real.VENUES};latest={};previous={};timeline=[];known=0
    for r in rows:
        v=r.get('source');kind=r['type'];at=r['observed_at']
        if kind=='market_selected':metadata[v]=r['market']
        if kind=='source_health':health[v]=r['state']
        if kind=='prediction_book':
            b=r['book'];m=metadata[v];quotes={q['side']:q for p in r['packets'] for q in p['normalized']['quotes']};outcomes=[]
            labels={o['native_id']:o['label'] for o in m['outcomes']}
            for o in b['outcomes']:
                side=o['outcome_id'];label=labels[side];native=side
                if v=='kalshi':label=m['title'] if side=='yes' else 'Not: '+m['title'];native=side.upper()
                else:
                    payload=json.loads(m['raw']['json_text'])
                    market=next(x for e in payload['events'] for x in e['markets'] if str(x['id'])==spec['sources'][v]['market_id'])
                    entry=next(x for x in market['marketSides'] if str(x['id'])==side)
                    native='Long' if entry['long'] else 'Short'
                    label=entry.get('team',{}).get('name',label)
                outcomes.append(dict(side=side,team=label,native=native,quote=quotes[side],depth={k:deepcopy(o[k]) for k in ('bids','asks')}))
            old=previous.get(v);levels=e6_real.level_map(b);changed=None if old is None else sum(old.get(k)!=levels.get(k) for k in old.keys()|levels.keys());previous[v]=levels
            latest[v]=dict(id=r['ingress_id'],known_at=at,received_at=b['raw']['received_at'],source_at=b['raw']['exchange_at'],source_progress=b['source_time_progress'],sync=b['sync'],receipt_state=b['receipt_freshness'],market_state=b['state'],outcomes=outcomes,changed_levels=changed);known+=1
        if kind not in ('session_started','prediction_book','source_health','session_finished'):continue
        cards=[]
        for venue in e6_real.VENUES:
            book=deepcopy(latest.get(venue));age=None if book is None else e6_real.fixed(e6_real.exact_time(at)-e6_real.exact_time(book['received_at']))
            cards.append(dict(venue=venue,label=e6_real.LABELS[venue],market_id=spec['sources'][venue]['market_id'],connection=health[venue],book=book,age_seconds=age,receipt_stale=age is not None and Decimal(age)>Decimal(str(spec['stale_seconds']))))
        timeline.append(dict(id=r.get('ingress_id',report['session']+':terminal'),at=at,type=kind,label=('Terminal record retained · finalization incomplete' if kind=='session_finished' else kind.replace('_',' ')),known_books=known,cards=cards))
    limitation=f"Verified prefix only: {report['verified_offset']} bytes; {report['excluded_trailing_bytes']} trailing bytes excluded. No exact crash time or total lost/pending count is known."
    if report['terminal_record_present']:limitation+=' A terminal record is retained, but saved-session finalization was not committed.'
    return dict(session=report['session'],hash=report['recovery_identity'],live=False,recovery=report,event=spec['event'],kickoff=spec['scheduled_start'],capture_start=rows[0]['observed_at'],capture_end=rows[-1]['observed_at'],timeline=timeline,counts=report['counts'],replay=report['replay'],
        transitions=[dict(at=r['observed_at'],source=r['source'],state=r.get('state'),type=r['type']) for r in rows if r['type'] in ('source_health','controlled_interruption')],
        coverage=dict(limitation=limitation,completeness='Historical interrupted history. Recorded connected states are past observations, not current connections. No closing snapshot or successful shutdown is inferred. Hash-chain and native validation do not prove protection against every form of tampering.'),
        economics=dict(arb='Unavailable — fee and settlement inputs unqualified.',our_price='Unavailable — supporting inputs absent.',mispricing='Unavailable — no qualified fair price.'),provenance=spec['mode'])

def load_saved(folder,expected=None):
    if (folder/'manifest.json').exists():return e6_live.validate_saved(folder,expected)
    report,saved=reopen_index(folder/'recovery.json',expected)
    if folder.name!=report['session']:raise ValueError('catalog session identity mismatch')
    return projection(report,saved)

class Reader:
    def __init__(self,output):self.output=Path(output)
    def status(self):
        saved=sorted({p.parent.name for pattern in ('*/recovery.json','*/manifest.json') for p in self.output.glob(pattern)})[:8]
        statuses={s:('Interrupted' if (self.output/s/'recovery.json').exists() else 'Completed') for s in saved}
        return dict(state='idle',active=False,start_available=False,interrupted=False,saved=saved,saved_status=statuses,error=None,view=None)
    async def start(self):raise ValueError('read-only recovery cannot collect')
    async def interrupt(self):raise ValueError('read-only recovery cannot connect')
    async def stop(self):pass
    async def close(self):pass

def card_source():
    source=(ROOT/'app/dashboard/e6_real_static/watch.js').read_text()
    source=source.replace("${c.venue==='kalshi'?'KXNFLGAME-26SEP17DETBUF-BUF':'657964 · aec-nfl-det-buf-2026-09-17'}","${escape(c.market_id||'Saved native market')}")
    a=source.index("${c.venue==='kalshi'?'YES = Buffalo");b=source.index('</p>',a)
    source=source[:a]+"Native outcome identity and supported quote conversion are retained. No execution eligibility is implied."+source[b:]
    source=source.replace('This cutoff precedes this venue’s first retained book. No later price is shown.','No synchronized book is supported at this cutoff. It may be absent from the entire recovered prefix; no later image is invented.')
    return source

def main():
    p=argparse.ArgumentParser();p.add_argument('--catalog',type=Path,default=CATALOG);p.add_argument('--port',type=int,default=8780);a=p.parse_args()
    from app.dashboard.e5_preview import isolate_process
    from aiohttp import web
    isolate_process()
    web.run_app(e6_live.create_app(owner=Reader(a.catalog),saved_loader=load_saved,assets=ROOT/'app/dashboard/e6_recovery_static',card_source=card_source()),host='127.0.0.1',port=a.port,access_log=None)
if __name__=='__main__':main()
