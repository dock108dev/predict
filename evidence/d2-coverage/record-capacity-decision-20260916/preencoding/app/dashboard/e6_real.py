"""File-only historical watch. Fixed saved session; no collection entry points."""
import argparse
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from aiohttp import web
from app.dashboard.e5_preview import fixed, isolate_process
from app.storage.store import exact_time as _exact_time

def exact_time(value):
    return _exact_time(value.replace(" ","T",1))
from app.collection.transport_session import reopen
from app.collection.native_replay import verify_native

ROOT=Path(__file__).resolve().parents[2]
SID='75ec21c1-5962-48e1-96e2-5f6b5ef07150'
CHAIN='4a954b03a0e1146104a4ae6c319b3201e721a45eff356ec35fe506dbfb36c29a'
BASE='evidence/e6/prediction-only/'
RUN=BASE+'real-20260915-discovery6/'
JOURNAL=RUN+'session/'+SID+'.jsonl'
VENUES=('kalshi','polymarket_us')
LABELS={'kalshi':'Kalshi','polymarket_us':'Polymarket US'}
SIDES={'kalshi':{'yes':('Buffalo Bills','YES'),'no':('Detroit Lions','NO')},
       'polymarket_us':{'1315440':('Detroit Lions','Long'),'1315441':('Buffalo Bills','Short')}}


def validate_mapping(rows,spec):
    if spec['mode']!='real' or spec.get('reference_enabled') is not False or spec['scheduled_start']!='2026-09-18T00:15:00+00:00':
        raise ValueError('saved configuration identity mismatch')
    expected={'kalshi':('KXNFLGAME-26SEP17DETBUF','KXNFLGAME-26SEP17DETBUF-BUF'), 'polymarket_us':('101466','657964')}
    for venue in VENUES:
        row=spec['sources'][venue]
        if (row['event_id'],row['market_id'])!=expected[venue]:raise ValueError('native market identity mismatch')
        markets=[r['market'] for r in rows if r['type']=='market_selected' and r['source']==venue]
        if not markets:raise ValueError('saved market metadata missing')
        for market in markets:
            raw=market['raw'];native=json.loads(raw['json_text'])
            if (raw['ref']['event_id'],raw['ref']['market_id'])!=expected[venue]:raise ValueError('metadata identity mismatch')
            if venue=='kalshi':
                m=next(m for m in native['markets'] if m['ticker']==expected[venue][1])
                if m['yes_sub_title']!='Buffalo':raise ValueError('Kalshi YES mapping mismatch')
            else:
                e=next(e for e in native['events'] if str(e['id'])=='101466')
                m=next(m for m in e['markets'] if str(m['id'])=='657964')
                sides={str(s['id']):(s['long'],s['team']['name']) for s in m['marketSides']}
                if sides!={'1315440':(True,'Detroit Lions'),'1315441':(False,'Buffalo Bills')}:raise ValueError('US long/short mapping mismatch')
                if m['slug']!='aec-nfl-det-buf-2026-09-17':raise ValueError('US slug mismatch')


def level_map(book):
    return {(o['outcome_id'],side,Decimal(l['price']['value'])):Decimal(l['quantity']['value'])
            for o in book['outcomes'] for side in ('bids','asks') for l in (o[side] or {}).get('levels',[])}


def project_book(row, previous, sides=None):
    sides=SIDES if sides is None else sides
    venue=row['source'];book=row['book'];quotes={}
    for packet in row['packets']:
        n=packet['normalized']
        if n['raw_kind']!='observation':raise ValueError('non-real book')
        for quote in n['quotes']:
            if quote['side'] in quotes:raise ValueError('duplicate native side')
            quotes[quote['side']]=quote
    if set(quotes)!=set(sides[venue]):raise ValueError('unknown native outcome')
    outcomes=[]
    by_side={o['outcome_id']:o for o in book['outcomes']}
    for side,(team,native) in sides[venue].items():
        quote=quotes[side];o=by_side[side]
        outcomes.append(dict(side=side,team=team,native=native,quote=quote,depth={s:deepcopy(o[s]) for s in ('bids','asks')}))
    changed=None
    if previous:
        old=level_map(previous['book']);new=level_map(book)
        changed=sum(old.get(k)!=new.get(k) for k in old.keys()|new.keys())
    return dict(id=row['ingress_id'],known_at=row['observed_at'],received_at=book['raw']['received_at'],
                source_at=book['raw']['exchange_at'],source_progress=book['source_time_progress'],sync=book['sync'],
                receipt_state=book['receipt_freshness'],market_state=book['state'],outcomes=outcomes,changed_levels=changed)


def project(rows,spec):
    timeline=[];health={v:'idle' for v in VENUES};latest={};previous={};known_books=0
    for row in rows:
        kind=row['type'];venue=row.get('source');at=row['observed_at']
        if kind=='source_health':health[venue]=row['state']
        if kind=='prediction_book':
            if exact_time(row['book']['raw']['received_at'])>exact_time(at):raise ValueError('book known before receipt')
            latest[venue]=project_book(row,previous.get(venue));previous[venue]=row;known_books+=1
        if kind not in ('session_started','prediction_book','source_health','session_finished'):continue
        cards=[]
        for v in VENUES:
            b=deepcopy(latest.get(v));age=None if b is None else fixed(exact_time(at)-exact_time(b['received_at']))
            cards.append(dict(venue=v,label=LABELS[v],connection=health[v],book=b,age_seconds=age,
                              receipt_stale=age is not None and Decimal(age)>Decimal(str(spec['stale_seconds']))))
        timeline.append(dict(id=row.get('ingress_id',SID+':finished'),at=at,type=kind,source=venue,
                             label={'session_started':'Capture started','session_finished':'Capture stopped','source_health':LABELS.get(venue,'')+' · '+row.get('state',''),'prediction_book':LABELS.get(venue,'')+' · book observation'}[kind],
                             known_books=known_books,cards=cards))
    return timeline


def load_package(root=ROOT):
    identity=json.loads((ROOT/'app/dashboard/e6_real_identity.json').read_text())
    data={}
    for name,expected in identity.items():
        path=root/name
        if path.stat().st_size>32*1024*1024:raise ValueError('saved file exceeds bound')
        body=path.read_bytes()
        if sha256(body).hexdigest()!=expected:raise ValueError('saved evidence changed: '+Path(name).name)
        if name!=JOURNAL:data[name]=json.loads(body)
    saved=reopen(root/JOURNAL);rows=saved['rows'];spec=data[RUN+'run-spec.json'];summary=data[RUN+'capture-summary.json']
    if saved['sha256']!=CHAIN or saved['state']!='complete':raise ValueError('journal chain or completion mismatch')
    if rows[0]['spec']!=spec or any(r.get('session_id')!=SID for r in rows):raise ValueError('saved session/configuration mismatch')
    if data[RUN+'saved-observations.json']!=saved:raise ValueError('saved export mismatch')
    validate_mapping(rows,spec)
    counts=dict(frames=sum(r['type']=='prediction_frame' for r in rows),books=sum(r['type']=='prediction_book' for r in rows),
                packets=sum(len(r['packets']) for r in rows if r['type']=='prediction_book'),ingress=sum('ingress_id' in r for r in rows))
    if counts!=dict(frames=45,books=44,packets=88,ingress=139) or rows[-1]['persisted']!=139 or rows[-1]['delivered']!=139:raise ValueError('completion accounting mismatch')
    replay=verify_native(root/JOURNAL);independent=data[BASE+'independent-replay.json']
    if any(replay[k]!=independent[k] for k in replay) or replay['exact_native_books']!={'kalshi':16,'polymarket_us':28}:raise ValueError('native replay evidence mismatch')
    # Recheck hashes after replay so a concurrent edit cannot become a mixed package.
    if any(sha256((root/n).read_bytes()).hexdigest()!=h for n,h in identity.items()):raise ValueError('saved evidence changed during validation')
    timeline=project(rows,spec)
    return dict(session=SID,hash=CHAIN,mode='Historical — captured from real feeds',event='Detroit Lions at Buffalo Bills',
                kickoff=spec['scheduled_start'],capture_start=timeline[0]['at'],capture_end=timeline[-1]['at'],
                duration=str(summary['elapsed_seconds']),counts=counts,timeline=timeline,
                coverage=dict(native_replay=replay,metadata_validations={v:sum(r['type']=='discovery_validated' and r.get('source')==v for r in rows) for v in VENUES},
                limitation='The deadline interrupted the final Polymarket US metadata refresh between requests. Two US refreshes were validated; the third was incomplete. Dispatched HTTP bodies were complete.',
                completeness='No observed sequence gap in this window. This bounded capture is not complete upstream history or continuous reliability.'),
                economics=dict(arb='Unavailable — effective fees, account rounding and settlement compatibility were not qualified.',our_price='Unavailable — no supporting reference inputs or probability model.',mispricing='Unavailable — fair-price and other supporting inputs are absent. Optional sportsbook data is not needed to view books.'),
                collected_now=False,execution_eligible=False)


def create_app(root=ROOT):
    @web.middleware
    async def guard(request,handler):
        if request.host not in ('127.0.0.1:'+str(request.url.port),'localhost:'+str(request.url.port)):
            raise web.HTTPForbidden(text='Loopback host required')
        response=await handler(request)
        response.headers.update({'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",'X-Content-Type-Options':'nosniff'})
        return response
    app=web.Application(middlewares=[guard],client_max_size=2048)
    async def package(request):
        try:return web.json_response(load_package(root))
        except Exception:
            return web.json_response(dict(error='Saved evidence validation failed. A required file is missing, altered or invalid. No observations were displayed.'),status=422)
    async def page(request):return web.FileResponse(ROOT/'app/dashboard/e6_real_static/index.html')
    async def css(request):return web.FileResponse(ROOT/'app/dashboard/static/style.css')
    async def component(request):return web.FileResponse(ROOT/'app/dashboard/e5_static/state.js')
    app.router.add_get('/',page);app.router.add_get('/api/package',package)
    app.router.add_get('/style.css',css);app.router.add_get('/shared-state.js',component)
    app.router.add_static('/view/',ROOT/'app/dashboard/e6_real_static',show_index=False)
    return app


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8778);args=parser.parse_args()
    isolate_process()
    web.run_app(create_app(),host='127.0.0.1',port=args.port,access_log=None)

if __name__=='__main__':main()
