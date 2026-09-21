"""Capture-owned state and database; detached view computation in refresh.py."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from contextlib import contextmanager
from time import monotonic
from pathlib import Path

from app.storage import Store,connect,CapturePolicy
from app.dashboard.bounds import DeadlineConnection
from app.storage.store import ROOT,encoded
from app.storage.workflow import packet
from app.storage.replay import detector_audit
from app.normalization.observations import enrich_event
from app.matching import Matcher,observation
from app.moneyline import MoneylineMatcher,observe
from app.moneyline_captures import listing_profile
from app.arbitrage import book_observations,wire,Policy
from app.depth import book_ladders,size_depth,Search
from app.dashboard.views import candidate_view,depth_view,VENUES,side_labels


def instant(): return datetime.now(timezone.utc)
def serial(x): return json.loads(json.dumps(x,default=lambda v:str(v) if not isinstance(v,datetime) else v.isoformat()))


class Pipeline:
    def __init__(self, mode, limits, database='prediction_arb'):
        self.mode=mode;self.limits=limits;self.database=database
        self.db=None;self.sid=None;self.seq=0;self.receipts=0;self.raw_bytes=0
        self.parents=Matcher();self.matcher=MoneylineMatcher();self.rows=[];self.observations={};self.books={};self.contexts={};self.titles={};self.event_titles={};self.current_receipts={}
        self.stopping=False;self.defer_views=False;self.dirty=0;self.refreshes=[];self.last_refresh=monotonic();self.shutdown={}
        self.snapshot_sequence=0;self.snapshot_bytes_high=0
        from app.fees.engine import load_registry
        self.registry=load_registry()
        self.finalized=False;self.deadline=None;self.capture_item_id=None;self.item_receipts={}

    def set_deadline(self,deadline):
        self.deadline=deadline
        db=self.db
        while db is not None:
            if isinstance(db,DeadlineConnection):db.deadline=deadline;break
            db=getattr(db,'db',None)

    def close_resources(self):
        if self.db:self.db.close()

    def start(self):
        self.db=connect(self.database)
        self.db.execute('SET statement_timeout=3000');self.db.execute('SET lock_timeout=1000')
        self.db=DeadlineConnection(self.db)
        self.store=Store(self.db)
        self.sid=self.store.start('production' if self.mode=='live' else 'synthetic','current' if self.mode=='live' else 'synthetic',
            'Slice 13 supervised '+self.mode+' dashboard scan',CapturePolicy(max_seconds=self.limits['seconds'],max_receipts=self.limits['receipts']))
        self.store.event(self.sid,'coverage',dict(mode=self.mode,limits=self.limits,continuous_survival=False,stream_reconstruction=False))
        return self.sid

    def bootstrap(self, discovery):
        all_events=[e for d in discovery for e in d['events']]
        if any(e.raw.kind.value!='observation' for e in all_events):raise ValueError('Live discovery requires actual venue observations')
        normalized=[observation(enrich_event(e,environment='production'),artifact='current dashboard discovery') for e in all_events]
        self.parents.ingest(normalized)
        parents={(r['venue'],r['native_event_id']):r for r in normalized}
        for d in discovery:
            venue=d['venue']
            for e in d['events']: self.event_titles[(venue,e.raw.ref.event_id)]=e.title
            for market,native,context in d['markets']:
                raw=market.raw;src=dict(url=raw.source,artifact='live dashboard metadata',sha256=sha256(raw.json_text.encode()).hexdigest(),captured_at=raw.received_at.isoformat())
                rules=listing_profile(native,venue,src)
                row=observe(market,parents[(venue,raw.ref.event_id)],rules,native=native,context=context,artifact='live dashboard metadata')
                self.rows.append(row);self.titles[row['key']]=market.title
                if venue=='polymarket_us':
                    c=dict(venue=venue,environment='production',market_id=raw.ref.market_id,product='event_contract',settlement_status='UNKNOWN')
                else:
                    meta=d.get('fees',{}).get(raw.ref.event_id)
                    c=dict(venue=venue,environment='production',market_id=raw.ref.market_id,product='event_contract',settlement_status='UNKNOWN',series_id='KXNFLGAME',event_id=raw.ref.event_id)
                    if meta: c['kalshi_metadata']=meta
                    # No account precision, settlement-fee waiver or applicability assertion.
                for side in row['sides']: self.contexts[(row['key'],side['native_id'])]=c
        self.matcher.update(self.parents,self.rows)
        with self.db.transaction():
            for d in discovery:
                self.store.event(self.sid,'coverage',d.get('coverage',dict(venue=d['venue'],note='Bounded metadata refresh')))
                for i,r in enumerate(d['responses']):
                    body=r.body.encode();self.raw_bytes+=len(body)
                    if len(body)>16*1024*1024 or self.raw_bytes>self.limits['storage_bytes']: raise ValueError('metadata storage bound')
                    self.store.metadata(self.sid,'live-discovery',d['venue']+':'+str(i),dict(raw_hash=self.store.raw(body),source=r.source,received_at=r.received_at.isoformat()))
            for r in self.rows:
                self.store.metadata(self.sid,'native-market',r['key'],r)
                self.store.metadata(self.sid,'rule-profile',r['key'],r['profile'])
        return self.evaluate()

    def synthetic_bootstrap(self):
        from app.depth_example import fixture
        data,self.synthetic_ladders=fixture();self.parents,self.matcher,obs,self.contexts,self.rows=data
        self.titles={r['key']:r['native']['title'] for r in self.rows}
        for r in self.rows:self.event_titles[(r['venue'],r['native_event_id'])]='Atlanta vs Pittsburgh · invented example'
        view=self.synthetic_tick(0)
        return view if view is not None else self.evaluate()

    def synthetic_tick(self,n):
        from app.models.core import QuoteSide,Probability,Quantity
        from decimal import Decimal
        t=instant()
        with self.observation_transaction():
            for ladder in self.synthetic_ladders:
                o=ladder.observation;p='0.40' if n%3!=2 else '0.55'
                o=replace(o,quote=replace(o.quote,raw=replace(o.quote.raw,received_at=t,exchange_at=t),ask=QuoteSide(price=Probability(value=Decimal(p)),quantity=Quantity(value=Decimal('3'),unit='contracts'))))
                self._save_observation(o,levels=[dict(price=p,quantity='3',provenance='invented dashboard example')])
                self.books[(o.quote.raw.ref.venue.value,o.quote.raw.ref.market_id)]=replace(ladder,observation=o,levels=((p,'3','invented dashboard example'),))
        self.dirty+=1
        return None if self.defer_views else self.evaluate()

    def _save_observation(self,o,levels=None):
        if self.stopping: return
        key=(o.quote.raw.ref.venue.value,o.quote.raw.ref.market_id,o.quote.outcome_id)
        pkt=packet(o,levels)
        if self.receipts>=self.limits['receipts'] or self.raw_bytes+len(pkt['raw'])>self.limits['storage_bytes']: raise OverflowError('receipt/storage bound')
        rid='observation:'+str(self.receipts)
        self.store.receipt(self.sid,rid,pkt)
        self.receipts+=1;self.raw_bytes+=len(pkt['raw']);self.observations[key]=o;self.current_receipts[key]=rid

    @contextmanager
    def observation_transaction(self):
        # Publish mutable bindings only with the outer commit; restore on rollback.
        old=(self.receipts,self.raw_bytes,dict(self.observations),dict(self.current_receipts),dict(self.books))
        try:
            with self.db.transaction():yield
        except BaseException:
            self.receipts,self.raw_bytes,self.observations,self.current_receipts,self.books=old
            raise

    def refresh(self,force=False):
        if self.dirty and (force or monotonic()-self.last_refresh>=.25):return self.evaluate()

    def book(self,book):
        venue=book.raw.ref.venue.value;mid=book.raw.ref.market_id
        row=next(r for r in self.rows if r['venue']==venue and r['native_market_id']==mid)
        start=next(r['start'] for r in self.parents.snapshot['observations'].values() if r['venue']==venue and r['native_event_id']==row['native_event_id'])
        if start and datetime.fromisoformat(start)<=instant():
            from app.models.core import MarketState
            book=replace(book,state=MarketState.CLOSED)
        context=dict(environment='production',evidence_class='current',source_time_semantics='last_change' if venue=='polymarket_us' else 'unknown',locks_clear=None,units_verified=False)
        image=asdict(book);image.pop('raw');image=serial(image)
        prior=self.receipts
        with self.observation_transaction():
            for o in book_observations(book,**context):self._save_observation(o,image)
            self.books[(venue,mid)]=book
            if self.capture_item_id is not None:
                self.store.event(self.sid,'coverage',dict(capture_item=self.capture_item_id,receipts=['observation:'+str(n) for n in range(prior,self.receipts)]))
        if self.capture_item_id is not None:self.item_receipts[self.capture_item_id]=['observation:'+str(n) for n in range(prior,self.receipts)]
        self.dirty+=1
        return None if self.defer_views else self.evaluate()

    def disconnect(self,venue,reason):
        self.store.event(self.sid,'disconnect',dict(venue=venue,reason=reason,censored=True))
        for key,o in list(self.observations.items()):
            if key[0]==venue:self.observations[key]=replace(o,sync='unsynchronized')
        self.dirty+=1
        return None if self.defer_views else self.evaluate()

    def refresh_config(self):
        return dict(connector=getattr(self,'connector',connect),database=self.database,sid=self.sid,
            mode=self.mode,limits=dict(self.limits),metrics=getattr(self,'metrics',None))

    def snapshot(self,force=False):
        from app.dashboard.refresh import freeze
        if not self.dirty and not (force and self.seq==0):return None
        started=monotonic()
        # One capture-worker operation: only committed receipt bindings enter bytes.
        seq=max(self.snapshot_sequence,self.seq)+1
        state={k:getattr(self,k) for k in ('sid','mode','parents','matcher','observations',
            'contexts','rows','titles','event_titles','current_receipts','receipts','raw_bytes','registry')}
        state.update(sequence=seq,evaluation_time=instant(),depth_available=bool(self.books),
            inputs=self.dirty,start=started,previous_start=self.last_refresh)
        snapshot=freeze(state)
        self.snapshot_bytes_high=max(self.snapshot_bytes_high,len(snapshot))
        self.snapshot_sequence=seq;self.dirty=0;self.last_refresh=started
        return snapshot

    def persist_refresh(self,result):
        from app.dashboard.refresh import thaw_result
        data=thaw_result(result);view=data['view']
        if data['sid']!=self.sid or view['sequence']<=self.seq:return None
        started=monotonic()
        self.store.precompiled=data['artifacts'];self.store.precompiled_written=set()
        try:
            with self.db.transaction():
                self.store.calculation(self.sid,'dashboard:'+str(view['sequence']),data['audit'],data['receipt_ids'])
                self.store.metadata(self.sid,'dashboard-view',f"{view['sequence']:08}",view)
        finally:self.store.precompiled={};self.store.precompiled_written=None
        self.seq=view['sequence']
        sample=data['sample'];sample['sequence']=view['sequence'];sample['persistence_seconds']=monotonic()-started
        sample['latency']=monotonic()-sample['start'];sample['age']=monotonic()-sample.pop('previous_start')
        sample['input_to_persistence_seconds']=(instant()-datetime.fromisoformat(data['latest_input_at'])).total_seconds() if data['latest_input_at'] else None
        sample['oldest_input_to_persistence_seconds']=(instant()-datetime.fromisoformat(data['oldest_input_at'])).total_seconds() if data['oldest_input_at'] else None
        self.refreshes.append(sample)
        return dict(view=view,sample=dict(sample),sid=self.sid)

    def record_publication(self,seq,submitted,computed,published,accepted):
        from app.dashboard.refresh import complete_sample
        index=next(i for i in range(len(self.refreshes)-1,-1,-1) if self.refreshes[i]['sequence']==seq)
        self.refreshes[index]=complete_sample(self.refreshes[index],submitted,computed,published,accepted)

    def evaluate(self):
        # Synchronous bootstrap/direct callers use the same immutable boundary.
        from app.dashboard.refresh import compute
        dirty=self.dirty;last=self.last_refresh;issued=self.snapshot_sequence
        try:
            snapshot=self.snapshot(True)
            if snapshot is None:return None
            result=self.persist_refresh(compute(snapshot))
            return result['view'] if result else None
        except BaseException:
            self.dirty=dirty;self.last_refresh=last;self.snapshot_sequence=issued
            raise

    def depth(self,cid):
        ladders=[]
        for (venue,mid),book in self.books.items():
            if self.mode=='synthetic': ladders.append(book)
            else:ladders.extend(book_ladders(book,environment='production',evidence_class='current',source_time_semantics='last_change' if venue=='polymarket_us' else 'unknown',locks_clear=None,units_verified=False))
        # On-demand only: at most the configured small universe, 64 allocations per pair.
        report=size_depth(self.parents,self.matcher,ladders,self.contexts,evaluation_time=instant(),search=Search(max_evaluations=64),policy=Policy(max_receipt_age_seconds='10'))
        audit=next((c for c in report['candidates'] if c['id']==cid),None)
        if not audit: raise LookupError('Candidate no longer exists')
        from uuid import uuid4
        self.store.calculation(self.sid,'depth:'+str(uuid4()),audit,list(self.current_receipts.values()))
        return depth_view(audit)

    def finish(self,reason,queued,failed=False):
        if self.finalized:return
        self.finalized=True;self.stopping=True
        try:
            connector=getattr(self,'connector',connect)
            with connector(self.database) as readback:
                rows=readback.execute('SELECT r.id,octet_length(a.content) bytes FROM receipt r JOIN artifact a ON a.hash=r.raw_hash WHERE r.session_id=%s',(self.sid,)).fetchall()
                self.receipts=len(rows)
                self.shutdown['readback_receipts']=[r['id'] for r in rows]
                bindings=readback.execute("SELECT detail FROM coverage_event WHERE session_id=%s AND detail ? 'capture_item'",(self.sid,)).fetchall()
                self.item_receipts={r['detail']['capture_item']:r['detail']['receipts'] for r in bindings}
                self.shutdown['item_receipts']=self.item_receipts
                self.shutdown['readback_raw_receipt_bytes']=sum(r['bytes'] for r in rows)
                durable={r['id'] for r in rows}
                for key,rid in list(self.current_receipts.items()):
                    if rid not in durable:
                        self.current_receipts.pop(key);self.observations.pop(key,None)
                if failed:self.books.clear()

            state='failed' if failed else 'interrupted' if queued or self.shutdown.get('rejected') else 'complete'
            with self.db.transaction():
                self.store.event(self.sid,'shutdown',dict(reason=reason,queued_unprocessed=queued,**self.shutdown))
                self.store.finish(self.sid,state,reason)
        finally:
            if self.db:self.db.close()

    def failure_journal(self,error_type):
        from uuid import uuid4
        path=ROOT/'.local/failures';path.mkdir(parents=True,exist_ok=True)
        (path/(str(uuid4())+'.json')).write_text(json.dumps(dict(session_id=self.sid,at=instant().isoformat(),error_type=error_type,count=self.receipts,shutdown=self.shutdown)))
