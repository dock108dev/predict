"""Default finite workflow imports preserved snapshots; never connects to venues."""
from dataclasses import asdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from app.arbitrage_example import historical, synthetic_inputs, NOW
from app.depth_example import historical_depth, fixture, run
from app.arbitrage import wire, book_observations
from .replay import detector_audit, observation_dump
from .store import ROOT, CapturePolicy


def packet(o, levels=None):
    w=wire(o); q=o.quote
    def val(side,attr):
        x=getattr(q,side)
        return None if x is None or getattr(x,attr) is None else str(getattr(x,attr).value)
    normalized={k:v for k,v in w.items() if k not in ('received_at','exchange_at','source','source_sha256')}
    normalized['quotes']=[dict(side=q.outcome_id,ask=val('ask','price'),ask_size=val('ask','quantity'),
        bid=val('bid','price'),bid_size=val('bid','quantity'),unit=w['unit'])]
    if levels is not None: normalized['levels']=levels
    return dict(environment=o.environment,evidence_class=o.evidence_class,raw=q.raw.json_text.encode(),
        received_at=w['received_at'],source_time=w['exchange_at'],venue=w['venue'],event_id=w['event_id'],
        market_id=w['market_id'],source=w['source'],normalized=normalized)


def import_default(store):
    sessions=[]; audits=[]
    # Existing loader supplies original retained image bodies and explicit historical scope.
    captured={}; images={}
    def observe_book(book,**context):
        observations=book_observations(book,**context)
        # Normalized native full supplied image, in addition to exact raw content.
        image=asdict(book); image.pop('raw')
        image=json.loads(json.dumps(image,default=str))
        for o in observations: images[(o.quote.raw.ref.venue.value,o.quote.raw.ref.market_id,o.quote.outcome_id)]=image
        return observations
    def builder(p,m,obs,c,**opts):
        captured.update(parents=p,matcher=m,observations=obs,audit=detector_audit(p,m,obs,c,**opts))
        return deepcopy(captured['audit']['result'])
    old_report=historical(observation_factory=observe_book,report_builder=builder)
    expected=json.loads((ROOT/'evidence/slice-10/detector-example.json').read_text())['historical_production']
    assert old_report==expected, 'preserved detector report changed'
    depth=json.loads(json.dumps(historical_depth()))
    preserved=json.loads((ROOT/'evidence/slice-11/depth-example.json').read_text())
    assert depth==preserved['historical_production'], 'preserved depth report changed'
    # The saved depth report is also imported byte-exact below with its original provenance.
    inputs=[('production','historical',captured['parents'],captured['matcher'],captured['observations'],captured['audit'],depth,None)]
    data,ladders=fixture(); p,m,obs,contexts,_=data
    synthetic=detector_audit(p,m,obs,contexts,evaluation_time=NOW,fill_grouping='single_fill_per_leg')
    inputs.append(('synthetic','synthetic',p,m,obs,synthetic,run(data,ladders),ladders))
    for env,kind,p,m,obs,det,d,ls in inputs:
        sid=store.start(env,kind,'Slice 12 finite preserved-image import' if kind=='historical' else 'Slice 11 invented-depth fixture',CapturePolicy(max_seconds=300))
        sessions.append(sid)
        try:
            with store.db.transaction():
                store.metadata(sid,'event-mapping','snapshot',det['input']['parents'])
                store.metadata(sid,'market-mapping','snapshot',det['input']['markets'])
                store.metadata(sid,'fee-registry','snapshot',det['input']['options']['registry'])
                for h,row in p.snapshot['observations'].items():
                    store.metadata(sid,'native-event',row['key'],row)
                for h,row in m.snapshot['observations'].items():
                    store.metadata(sid,'native-market',row['key'],row)
                    store.metadata(sid,'rule-profile',row['key'],row['profile'])
                if kind=='historical':
                    for name in ('evidence/slice-10/detector-example.json','evidence/slice-11/depth-example.json'):
                        body=(ROOT/name).read_bytes()
                        store.metadata(sid,'preserved-audit-file',name,dict(raw_hash=store.raw(body),source=name,sha256=sha256(body).hexdigest()))
                    # Imports exact files referenced by historical loader, never entire catalogs per receipt.
                    for name,h in old_report['artifacts'].items():
                        body=(ROOT/name).read_bytes(); assert sha256(body).hexdigest()==h
                        store.metadata(sid,'preserved-capture',name,dict(raw_hash=store.raw(body),source=name,sha256=h))
            packets=[('image:'+str(i),packet(o,images.get((o.quote.raw.ref.venue.value,o.quote.raw.ref.market_id,o.quote.outcome_id)) if ls is None else [list(v) for v in ls[i].levels])) for i,o in enumerate(obs)]
            store.ingest(sid,iter(packets))
            rids=[rid for rid,_ in packets]
            store.event(sid,'coverage',dict(mode='discrete retained images',continuous=False,raw_stream_reconstruction=False,
                every_exchange_event=False,note=old_report['coverage_note'] if kind=='historical' else 'invented synthetic books'),at=NOW.isoformat())
            store.event(sid,'gap',dict(reason='intervals between retained images were not observed; source clocks/venue skew retained',censored=True),at=NOW.isoformat())
            store.calculation(sid,'detector:0',det,rids); audits.append(det)
            for i,audit in enumerate(d['candidates']):
                store.calculation(sid,'depth:'+str(i),audit,rids); audits.append(audit)
            store.finish(sid)
        except BaseException:
            store.finish(sid,'failed','default import failed'); raise
    return dict(sessions=sessions,round_trip_audits=store.replay_all(),summary=store.summary())
