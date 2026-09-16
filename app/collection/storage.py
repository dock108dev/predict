"""Explicit-connection durable owner. Reuses capture/reference/E3/E4 stores."""
import json
from pathlib import Path
from hashlib import sha256
from app.storage.store import Store, CapturePolicy, now
from app.storage.workflow import packet
from app.storage.replay import observation_load
from app.reference.storage import ReferenceStore
from app.reference.records import unwire, packed, SourceRevision
from app.pricing.storage import FairPriceStore
from app.opportunities.storage import OpportunityStore

PROVENANCE='E6 bounded injected synthetic collection'


class Repository:
    def __init__(self, connection, output, limits):
        self.db=connection; self.output=Path(output); self.limits=limits
        self.store=Store(connection); self.refs=ReferenceStore(connection)
        self.fair=FairPriceStore(connection); self.opps=OpportunityStore(connection)
        self.used=0; self.high_db_bytes=0; self.sid=None

    def reserve(self, value):
        # Charge canonical payloads before each atomic write; no evidence deletion.
        n=len(packed(value).encode())
        if n>self.limits['item_bytes'] or self.used+n>self.limits['storage_bytes']:
            raise OverflowError('logical_storage_capacity')
        size=self.db.execute('SELECT pg_database_size(current_database()) AS n').fetchone()['n']
        self.high_db_bytes=max(self.high_db_bytes,size)
        if size+128*1024*1024>self.limits['database_bytes']:
            raise OverflowError('database_capacity_reserve')
        self.used+=n

    def recover(self):
        result=[]
        for row in self.db.execute('SELECT id FROM capture_session WHERE provenance=%s AND state=%s',(PROVENANCE,'running')).fetchall():
            sid=row['id']
            counts=self.counts(sid)
            journal=self.output/(sid+'.journal.jsonl')
            deliveries=[];torn=False
            if journal.exists():
                if journal.stat().st_size>32*1024*1024:raise ValueError('recovery journal exceeds finite bound')
                for line in journal.read_text().splitlines():
                    try:entry=json.loads(line)
                    except ValueError:torn=True;break
                    if entry.get('type')=='delivered':deliveries.append(entry['item']['id'])
            persisted=self.db.execute("SELECT count(*) AS n FROM coverage_event WHERE session_id=%s AND detail ? 'e6_ingress'",(sid,)).fetchone()['n']
            detail=dict(state='interrupted',detected_at=now(),crash_at=None,
                        delivered_journal_records=len(deliveries),persisted_ingress= persisted,
                        journal_only=max(0,len(deliveries)-persisted),journal_tail_incomplete=torn,
                        reason='unfinished prior process; exact crash and unseen interval unknown',counts=counts)
            self.store.event(sid,'restart',detail)
            self.store.finish(sid,'interrupted',detail['reason'])
            result.append(dict(id=sid,**detail,exported=self.export(sid)))
        return result

    def start(self,sid,source,limits):
        self.sid=sid
        self.store.start('synthetic','synthetic',PROVENANCE,CapturePolicy(max_receipts=limits['receipts'],
            max_seconds=max(1,int(limits['seconds'])),max_total_bytes=limits['storage_bytes']),session_id=sid)
        self.refs.save(source)
        self.store.event(sid,'coverage',dict(state='running',limits=limits,synthetic=True,
            event='synthetic-atl-pit-e2',wall_started_at=now(),coverage='delivered snapshots only; unseen changes unknown'))

    def persist(self,item):
        self.reserve(item)
        kind=item['kind']; value=item['value']
        with self.db.transaction():
            if kind=='reference': self.refs.save(unwire(value))
            elif kind=='prediction':
                o=observation_load(value['observation'])
                levels=[dict(price=p,quantity=q,provenance=e) for p,q,e in value['levels']]
                self.store.receipt(self.sid,item['id'],packet(o,levels))
            self.store.event(self.sid,'coverage',dict(e6_ingress=item),event_id=item['id'])
        return item

    def save_calculation(self, result, context=None):
        estimate,audit=result
        from .context import validate_context
        validate_context(context,estimate.data['as_of'])
        self.reserve(dict(estimate=estimate.export(),audit=None if audit is None else audit.export()))
        with self.db.transaction():
            self.fair.save(estimate)
            if audit: self.opps.save(audit)
            self.store.event(self.sid,'coverage',dict(e6_calculation=dict(estimate=estimate.id,
                audit=audit.id if audit else None,cutoff=estimate.data['as_of'],session_context=context)))
        return result

    def lifecycle(self,state,detail):
        self.store.event(self.sid,'coverage',dict(state=state,**detail))
        if state in ('completed','failed'):
            self.store.finish(self.sid,'complete' if state=='completed' else state,detail['reason'])

    def counts(self,sid):
        def count(table):return self.db.execute(f'SELECT count(*) AS n FROM {table} WHERE session_id=%s',(sid,)).fetchone()['n']
        return dict(prediction=count('receipt'),reference=count('reference_receipt'),
                    reference_gaps=count('reference_gap'),events=count('coverage_event'))

    def export(self,sid):
        directory=self.output/sid; directory.mkdir(exist_ok=True)
        self.refs.export(directory/'references.json')
        events=self.db.execute('SELECT id,original_time,kind,detail FROM coverage_event WHERE session_id=%s ORDER BY observed_at,id',(sid,)).fetchall()
        calculations=[r['detail']['e6_calculation'] for r in events if 'e6_calculation' in r['detail']]
        for row in calculations:
            self.fair.export(row['estimate'],directory/(row['estimate']+'.estimate.json'))
            if row['audit']:self.opps.export(row['audit'],directory/(row['audit']+'.audit.json'))
        session=self.db.execute('SELECT * FROM capture_session WHERE id=%s',(sid,)).fetchone()
        text=json.dumps(dict(format='e6-saved-1',session=session,events=events,counts=self.counts(sid),calculations=calculations),default=str,sort_keys=True)
        (directory/'session.json').write_text(text)
        files={p.name:sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.json')}
        (directory/'manifest.json').write_text(packed(files))
        return dict(directory=str(directory),counts=self.counts(sid),calculations=len(calculations),bytes=sum(p.stat().st_size for p in directory.iterdir()))
