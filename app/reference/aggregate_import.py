"""Offline-only retained response import. No provider access or credentials."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from app.reference.aggregate import VERSION, bind
from app.reference.odds_sample import normalize
from app.collection.transport_session import ObservationJournal

ROOT=Path(__file__).resolve().parents[2]
SAMPLE=ROOT/'evidence/odds-api-five-books-20260929'
OUTPUT=ROOT/'evidence/aggregate-ingestion-20260929/sessions'


def import_sample(sample=SAMPLE, output=OUTPUT):
    coverage=json.loads((sample/'coverage.json').read_text())
    normalized=json.loads((sample/'observations.json').read_text())
    batches=[]
    for item in coverage:
        path=ROOT/item['raw_path']
        body=path.read_bytes()
        if sha256(body).hexdigest()!=item['raw_sha256']:raise ValueError('Original response hash changed')
        receipt=json.loads((path.parent/'result.json').read_text())
        rows=normalize(body,item['sport'],receipt['received_at'])
        original=[r for r in normalized if r['sport']==item['sport']]
        if rows!=original:raise ValueError('Normalized observations differ from original response replay')
        batches.append(dict(sport=item['sport'],at=receipt['received_at'],records=bind(rows),response_sha256=item['raw_sha256']))
    return _write_batches(batches, output)


def import_event_response(response, receipt, sport, output):
    """Offline single-event import with an independently retained receipt/hash."""
    from app.reference.odds_bindings import normalize_event
    if Path(response).stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Event response exceeds retained body limit')
    body=Path(response).read_bytes()
    meta=json.loads(Path(receipt).read_text())
    digest=sha256(body).hexdigest()
    if digest != meta['raw_sha256']:raise ValueError('Original response hash changed')
    records=normalize_event(body,sport,meta['received_at'])
    mapped=bind(records)
    if len(mapped)>5000 or len(json.dumps(mapped).encode())>16*1024*1024:
        raise ValueError('Event import exceeds durable projection limit')
    return _write_batches([dict(sport=sport,at=meta['received_at'],records=mapped,response_sha256=digest)],Path(output))


def _write_batches(batches, output):
    batches.sort(key=lambda b:b['at'])
    sid='odds-aggregate-'+sha256(json.dumps(batches,sort_keys=True).encode()).hexdigest()[:20]
    folder=output/sid;folder.mkdir(parents=True,exist_ok=False)
    spec=dict(mode='observation',aggregate_version=VERSION,mapping_revision=VERSION,collection_authorized=False,
              scope=list(item['sport'] for item in batches),required_market_cells=63)
    def save(name,data): (folder/name).write_text(json.dumps(data,indent=2)+'\n')
    save('run-spec.json',spec)
    journal=ObservationJournal(folder/(sid+'.jsonl'))
    def emit(typ,at,**data):journal.save(dict(type=typ,session_id=sid,observed_at=at,**data))
    try:
        emit('session_started',batches[0]['at'],spec=spec)
        for batch in batches:
            emit('product_aggregate',batch['at'],version=VERSION,records=batch['records'],sport=batch['sport'],response_sha256=batch['response_sha256'])
        emit('session_finished',batches[-1]['at'],reason='Offline retained import complete; acquisition consumed')
    finally:journal.close()
    save('aggregate-limits.json',dict(records=5000,bytes=16*1024*1024))
    save('report.json',dict(cleanup_complete=True,outcome=dict(status='complete'),historical=True))
    save('replay.json',dict(verified=True,version=VERSION,original_responses=[b['response_sha256'] for b in batches],qualification='Offline exact original response replay only'))
    files={p.name:sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    save('manifest.json',dict(files=files,journal_chain=journal.previous))
    return folder


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--event-response',type=Path)
    parser.add_argument('--receipt',type=Path)
    parser.add_argument('--sport',choices=('NFL','NBA','MLB','NHL','NCAAF','NCAAB'))
    args=parser.parse_args()
    if args.event_response or args.receipt or args.sport:
        if not all((args.event_response,args.receipt,args.sport)):
            parser.error('--event-response, --receipt and --sport are required together')
        print(import_event_response(args.event_response,args.receipt,args.sport,args.output))
    else:
        print(import_sample(output=args.output))

if __name__=='__main__':main()
