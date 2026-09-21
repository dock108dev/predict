"""File-only E5 preview. No controller, collection or database lifecycle imports."""
import argparse
import json
from decimal import Decimal, localcontext, Context
from hashlib import sha256
from pathlib import Path
import sys

from aiohttp import web
from app.opportunities.service import restore, rank
from app.pricing.baseline import restore as restore_price
from app.reference.records import import_records, as_of
from app.storage.store import exact_time

ROOT = Path(__file__).resolve().parents[2]
CASES = ('e3-unavailable-ev', 'invented-positive', 'invented-negative',
         'invented-missing-mass', 'unknown-quantity', 'unknown-fees', 'stale-book')
LABELS = ('E3 · expected value unavailable', 'Invented scenario · positive',
          'Invented scenario · negative', 'Invented scenario · missing mass',
          'Unknown quantity', 'Unknown fees', 'Stale book')


def fixed(value):
    if value is None: return None
    text = format(Decimal(value), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def percent(value):
    if value is None: return None
    with localcontext(Context(prec=110)):
        return fixed((Decimal(value) * 100).quantize(Decimal('0.0001')))


def project_estimate(estimate):
    d = estimate.data
    records = json.loads(d['dependencies'])['payload']['records']
    receipts = {r['data']['id']: r['data'] for r in records if r['type'] == 'Receipt'}
    rows = []
    for c in d['candidates']:
        receipt = receipts[c['receipt_id']]
        row = {**c, 'received_at': receipt['received_at'],
               'receipt_age_seconds': fixed(exact_time(d['as_of']) - exact_time(receipt['received_at'])),
               'read_age_seconds': None if c['provider_last_read'] is None else fixed(exact_time(d['as_of']) - exact_time(c['provider_last_read']))}
        rows.append(row)
    rows.sort(key=lambda r: (exact_time(r['received_at']), r['receipt_id']))
    previous = None
    previous_time = None
    for row in rows:
        odds = row['original_odds']
        row['observed_change'] = ('Same receipt timestamp; no temporal ordering established' if row['received_at'] == previous_time else 'No comparable preceding paired receipt' if odds is None or previous is None else
                                 'Same paired odds as preceding paired receipt' if odds == previous else
                                 'Different paired odds from preceding paired receipt')
        if odds is not None:
            previous = odds
            previous_time = row['received_at']
    return dict(id=estimate.id, cutoff=d['as_of'], status=d['status'], percent=percent(d['conditional_target_probability']),
                reasons=d['reasons'], references=rows, policy=d['policy'], target=d['target'], calculation=d['calculation'])


def load_package(root=ROOT):
    """Fail closed: every named export and dependency must validate before presentation."""
    e3 = root/'evidence/e3/durable'
    references = import_records((e3/'reference-bundle.json').read_text())
    estimates = [restore_price((e3/f'estimate-{n}.json').read_text()) for n in range(6)]
    by_id = {e.id:e for e in estimates}
    for e in estimates:
        if as_of(references, e.data['as_of']) != e.data['dependencies']:
            raise ValueError('saved reference history does not resolve estimate dependencies')
    ledger=json.loads((root/'evidence/e4/durable/storage-verification.json').read_text())
    expected={r['name']:r for r in ledger['replays']}
    if set(expected)!=set(CASES): raise ValueError('E4 verification ledger case set mismatch')
    audits=[]; cases=[]
    for key, label in zip(CASES, LABELS):
        path=root/f'evidence/e4/durable/{key}.json'
        original=path.read_text(); audit=restore(original); d=audit.data
        saved=expected[key]
        if (audit.id!=saved['audit_id'] or sha256(original.encode()).hexdigest()!=saved['export_sha256']
            or d['estimate_id']!=saved['estimate_id'] or d['book_ids']!=saved['book_ids']):
            raise ValueError('saved audit differs from E4 verification ledger')
        if audit.export() != original: raise ValueError('noncanonical saved audit')
        if d['estimate_id'] not in by_id or d['inputs']['estimate'] != by_id[d['estimate_id']].export():
            raise ValueError('saved E3 dependency missing or changed')
        audits.append(audit)
        allocation=d['signals'][0]['conditional_calculation']
        books=[]
        for b in d['inputs']['market']['books']:
            q=b['observation']['quote']; ref=q['raw']['ref']
            leg=next((l for l in (allocation or {}).get('legs',[]) if l['identity']['observation']['venue']==ref['venue']),None)
            age=exact_time(d['inputs']['as_of'])-exact_time(q['raw']['received_at'])
            books.append(dict(id=b['id'], selection_key=ref['venue']+':'+ref['market_id']+':'+q['outcome_id'],
                venue=ref['venue'], outcome=q['outcome_id'], bid=q['bid'], ask=q['ask'], levels=b['levels'],
                received_at=q['raw']['received_at'], source_at=q['raw']['exchange_at'], age_seconds=fixed(age),
                stale=age>30, depth=b['observation']['depth'], leg=leg, details=b))
        signals=[]
        for s in d['signals']:
            signals.append({**s, 'display':dict(net=fixed(s['net_total_usd']), per_contract=None if s['net_per_contract_usd'] is None else fixed(Decimal(s['net_per_contract_usd']).quantize(Decimal('0.000001'))),
                return_percent=percent(s['return_fraction']), capital=fixed(s['denominator_usd']))})
        cases.append(dict(key=key,label=label,id=audit.id,export_sha256=sha256(original.encode()).hexdigest(),
            estimate_id=d['estimate_id'],cutoff=d['inputs']['as_of'],invented=d['inputs']['model'] is not None,
            model=d['inputs']['model'],books=books,signals=signals,assumptions=d['assumptions'],
            dependencies=d['dependency_hashes'],liquidity_families=d['liquidity_families'],replay='Verified · byte-exact restore and recomputation'))
    return dict(mode='Synthetic',cases=cases,estimates=[project_estimate(e) for e in estimates],ranking=rank(audits))


def isolate_process():
    import psycopg
    def no_database(*args, **kwargs):
        raise PermissionError('E5 file-only preview forbids database connections')
    psycopg.connect = no_database
    psycopg.Connection.connect = no_database
    psycopg.AsyncConnection.connect = no_database
    # Audit events are denied before the OS operation, including dependencies.
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0])
            if (any(part in {'.ssh', '.aws', '.codex', 'Keychains'} for part in path.parts)
                or path.name.startswith('.env') or path.name in {'auth.json', 'credentials', 'credentials.json'}
                or path.suffix in {'.pem', '.key'}):
                raise PermissionError('E5 preview forbids credential-file reads')
        if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('E5 file-only preview forbids outbound connections and child processes')
    sys.addaudithook(guard)


def create_app(root=ROOT):
    app=web.Application()
    async def data(request):
        try: return web.json_response(load_package(root))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            return web.json_response({'error':'Saved evidence validation failed', 'reason':str(exc)},status=422)
    async def page(request): return web.FileResponse(ROOT/'app/dashboard/e5_static/index.html')
    async def style(request): return web.FileResponse(ROOT/'app/dashboard/static/style.css')
    @web.middleware
    async def headers(request, handler):
        response=await handler(request)
        response.headers.update({'Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",'X-Content-Type-Options':'nosniff'})
        return response
    app.middlewares.append(headers)
    app.router.add_get('/',page); app.router.add_get('/api/package',data)
    app.router.add_get('/assets/style.css',style)
    app.router.add_static('/e5/',ROOT/'app/dashboard/e5_static',show_index=False)
    return app


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8775)
    args=parser.parse_args()
    isolate_process()
    web.run_app(create_app(),host='127.0.0.1',port=args.port,print=print)

if __name__=='__main__': main()
