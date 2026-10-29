"""Ordered bounded CPU reconstruction; transport, credentials and SQL stay parent-owned."""
import asyncio
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from multiprocessing import get_context
from types import SimpleNamespace
from .bulk_checkpoint import owned_thread

_ENGINE=None
_MARKETS=None
_VENUE=None
_GENERATION=None
_REQUEST=None
_CATALOG_REVISION=0


def initialize(venue,markets,connection,request,highwater,market_requests=None):
    global _ENGINE,_MARKETS,_VENUE,_GENERATION,_REQUEST,_CATALOG_REVISION
    _CATALOG_REVISION=0
    _VENUE=venue;_MARKETS={m.raw.ref.market_id:m for m in markets};_REQUEST=request
    if venue=='kalshi':
        from app.adapters.kalshi_stream import BookReconstructor
        _ENGINE=BookReconstructor(markets,maximum_markets=None)
        _ENGINE.source_highwater=highwater
        _ENGINE.begin(connection);_GENERATION=_ENGINE.generation
    else:
        from app.adapters.polymarket_us_stream import MarketStream
        _ENGINE=MarketStream(markets,None,maximum_markets=None)
        _ENGINE.source_time_high_water=highwater;_ENGINE.isolate_market_errors=True
        _GENERATION=_ENGINE.begin_subscription(request)
        _ENGINE.market_requests=market_requests


def reconfigure(markets, market_requests, retired):
    """Ordered with reconstruction jobs; old request IDs never acquire new meaning."""
    global _MARKETS,_CATALOG_REVISION
    from app.adapters.polymarket_us import next_market_data
    _MARKETS={m.raw.ref.market_id:m for m in markets}
    if _VENUE=='kalshi':
        _ENGINE.reconfigure(markets,retired.get('request_id') if retired else None)
        _CATALOG_REVISION+=1
        return _CATALOG_REVISION
    _ENGINE.markets={next_market_data(m)['slug']:m for m in markets}
    previous=_ENGINE.market_requests or {}
    _ENGINE.last={slug:book for slug,book in _ENGINE.last.items()
                  if slug in market_requests and previous.get(slug)==market_requests[slug]}
    _ENGINE.market_requests=market_requests
    _ENGINE.retired_requests=set(retired)
    _ENGINE.source_time_high_water={k:v for k,v in _ENGINE.source_time_high_water.items() if k in market_requests}
    _CATALOG_REVISION+=1
    return _CATALOG_REVISION


def reconstruct(batch):
    import json,os,resource,sys,time
    from . import native_payload
    from .native_semantics import current_purchase_book
    from .native_book_value import book_value
    from app.adapters.polymarket_us_stream import MalformedMarketFrame
    # Decode once and coalesce repeated market images inside an already-received
    # contiguous delta run. Every delta still passes the ordered reconstructor;
    # only redundant intermediate complete-book allocations are avoided.
    decoded=[]
    for body,_ in batch:
        try:decoded.append(native_payload.parse(body.encode() if isinstance(body,str) else body))
        except (ValueError,TypeError):decoded.append(None)
    emit=[True]*len(batch);later=set();following=None
    if _VENUE=='kalshi':
        for index in range(len(batch)-1,-1,-1):
            data=decoded[index]
            if not isinstance(data,dict) or data.get('type')!='orderbook_delta':
                later.clear();following=None;continue
            if following is None or data.get('sid')!=following.get('sid') or type(data.get('seq')) is not int or following.get('seq')!=data['seq']+1:
                later.clear()
            mid=data.get('msg',{}).get('market_ticker')
            if isinstance(mid,str):
                emit[index]=mid not in later;later.add(mid)
            following=data
    result=[]
    for index,(body,received) in enumerate(batch):
        raw=body.encode() if isinstance(body,str) else body
        entry=dict(body=body,received=received,stage='decode',catalog_revision=_CATALOG_REVISION)
        start=time.monotonic()
        try:
            data=decoded[index]
            if not isinstance(data,dict):raise ValueError('malformed_native_frame')
            entry['decode_ms']=(time.monotonic()-start)*1000
            entry['stage']='reconstruct'
            materialize=emit[index]
            book=(_ENGINE.feed(raw,_GENERATION,received,materialize=materialize) if _VENUE=='kalshi' else
                  _ENGINE.parse(raw.decode('utf-8'),_REQUEST,generation=_GENERATION,received_at=received))
            entry['book']=None
            if _VENUE=='polymarket_us' and book is not None:
                from app.models.core import SourceTimeProgress
                if book.source_time_progress==SourceTimeProgress.REGRESSED:
                    entry['isolated_reason']='regressed_native_source_clock'
                    raise MalformedMarketFrame(data['marketData']['marketSlug'])
            if book is not None:
                if _VENUE=='kalshi':book=replace(book,state=_MARKETS[book.raw.ref.market_id].state)
                entry['book']=SimpleNamespace(raw=book.raw,state=book.state,sync=book.sync,source_time_progress=book.source_time_progress)
                entry['value']=book_value(current_purchase_book(book))
                entry['encoded_bytes']=len(json.dumps(entry['value']).encode())
                if entry['encoded_bytes']>256*1024:raise ValueError('native_image_size')
                from .current_confirmation import content
                entry['content_sha256']=content(entry['value'])
                if _VENUE=='kalshi':
                    key=book.raw.ref.market_id;clock=_ENGINE.source_highwater.get(key)
                    entry['data']={k:data[k] for k in ('type','sid','seq','sending_ts_ms') if k in data}
                    entry['data']['msg']={'market_ticker':data.get('msg',{}).get('market_ticker')}
                else:
                    md=data['marketData'];key=md['marketSlug'];clock=_ENGINE.source_time_high_water.get(key)
                    entry['data']={k:data[k] for k in ('requestId','subscriptionType') if k in data}
                    entry['data']['marketData']={k:md[k] for k in ('marketSlug','transactTime') if k in md}
                    for side in ('bids','offers'):
                        if isinstance(md.get(side),list):entry['data']['marketData'][side]=[]
                entry['clock']=(key,clock)
            else:
                entry['data']={k:data[k] for k in ('type','sid','seq') if k in data}
                if _VENUE=='kalshi' and not materialize:
                    mid=data['msg']['market_ticker']
                    entry['clock']=(mid,_ENGINE.source_highwater.get(mid))
                    entry['coalesced']=True
        except MalformedMarketFrame as exc:
            entry['malformed_slug']=exc.slug
        except (ValueError,KeyError,TypeError):
            entry['error']='native_reconstruction_failure'
        finally:
            # This worker returns complete images to the parent. Adapter `last`
            # exists for their standalone disconnect/stale-image API, which is
            # not used here. Keep only ladders, identity and clock high-water;
            # retaining another decoded full roster wastes memory and GC work.
            _ENGINE.last.clear()
            if _VENUE=='kalshi':
                entry.update(sid=_ENGINE.sid,seq=_ENGINE.seq)
                _ENGINE.frames.clear()
            else:
                _ENGINE.responses.clear();_ENGINE.events.clear();_ENGINE.diagnostics.clear()
            entry['processing_ms']=(time.monotonic()-start)*1000
        result.append(entry)
        # Stream-wide continuity failures terminate this batch at the exact frame.
        if entry.get('error'):break
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return result,dict(pid=os.getpid(),peak_rss_bytes=rss if sys.platform=='darwin' else rss*1024)


class Reconstruction:
    def __init__(self,venue,markets,connection,request,highwater,metrics,market_requests=None):
        self.pool=ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn'),
            initializer=initialize,initargs=(venue,markets,connection,request,dict(highwater),market_requests))
        self.ready=deque();self.metrics=metrics;self.highwater=highwater;self.pending=None
        self.catalog_revision=0
        self.market_revisions={m.raw.ref.market_id:0 for m in markets}

    async def reconfigure(self,markets,market_requests,retired):
        future=asyncio.wrap_future(self.pool.submit(reconfigure,markets,market_requests,retired))
        try:revision=await asyncio.shield(future)
        except asyncio.CancelledError:
            await asyncio.gather(future,return_exceptions=True)
            raise
        self.market_revisions={m.raw.ref.market_id:self.market_revisions.get(m.raw.ref.market_id,revision) for m in markets}
        self.catalog_revision=revision

    def obsolete_book(self,frame):
        """Retire delayed old-catalog images, never forgive an unknown current image.

        Ready/prefetched results may outlive multiple membership transitions.
        Re-added markets require their new image even when the identifier repeats.
        The map contains current members only; no retired-ID history accumulates.
        Sequence and decode errors are checked by the caller before this predicate.
        """
        book=frame.get('book')
        if book is None:return False
        revision=frame['catalog_revision'];mid=book.raw.ref.market_id
        return revision<self.catalog_revision and (mid not in self.market_revisions or revision<self.market_revisions[mid])

    def accept(self,batch,rows,metrics):
        self.metrics['reconstruction_coalesced_frames']=self.metrics.get('reconstruction_coalesced_frames',0)+sum(bool(row.get('coalesced')) for row in rows)
        self.metrics['reconstruction_worker']=metrics
        self.metrics['reconstruction_frames_discarded_on_resync']=self.metrics.get('reconstruction_frames_discarded_on_resync',0)+len(batch)-len(rows)
        for row in rows:
            if row.get('clock'):
                key,value=row['clock']
                if value is not None and (key not in self.highwater or value>self.highwater[key]):self.highwater[key]=value
        self.ready.extend(rows)

    async def load(self,receiver,timeout=None):
        # At most one bounded batch may run ahead of the consumed result batch.
        # Keep the same 1 MiB wire bound; a wider small-delta run permits more
        # redundant images to coalesce while every sequence is still validated.
        async with asyncio.timeout(timeout):batch=await receiver.recv_batch(2048,1024*1024)
        started=time.monotonic()
        future=asyncio.wrap_future(self.pool.submit(reconstruct,batch))
        self.metrics['reconstruction_inflight_frames']=len(batch)
        self.metrics['reconstruction_oldest_received_at']=batch[0][1].isoformat()
        try:rows,metrics=await asyncio.shield(future)
        except asyncio.CancelledError:
            await asyncio.gather(future,return_exceptions=True)
            raise
        finally:self.metrics['reconstruction_inflight_frames']=0
        self.metrics['reconstruction_batch_ms']=(time.monotonic()-started)*1000
        self.metrics['reconstruction_batch_frames']=len(rows)
        self.metrics['reconstruction_batch_cpu_ms']=sum(row['processing_ms'] for row in rows)
        return batch,rows,metrics

    async def recv(self,receiver,timeout=None):
        if getattr(receiver,'capacity_failed',False):raise receiver.error
        if not self.ready:
            task=self.pending
            if task is None:task=asyncio.create_task(self.load(receiver,timeout))
            self.pending=task
            try:
                batch,rows,metrics=await asyncio.shield(task)
                self.accept(batch,rows,metrics)
            except asyncio.CancelledError:
                completed=(await asyncio.gather(task,return_exceptions=True))[0]
                if not isinstance(completed,BaseException):self.accept(*completed)
                raise
            finally:self.pending=None
        # Only prefetch bytes already received. A quiet socket cannot hold up a
        # catalog transition or Stop. The child still validates every delta in
        # order; the parent publishes each result in that same order.
        if (self.pending is None and getattr(receiver,'queue',None) is not None
                and not receiver.queue.empty() and not any(r.get('error') for r in self.ready)):
            self.pending=asyncio.create_task(self.load(receiver),name='predict-native-reconstruct-next')
        self.metrics['reconstruction_ready_frames']=len(self.ready)-1
        row=self.ready.popleft()
        if self.pending is None:
            self.metrics['reconstruction_oldest_received_at']=self.ready[0]['received'].isoformat() if self.ready else None
        return row

    async def close(self):
        if self.pending is not None:
            completed=(await asyncio.gather(self.pending,return_exceptions=True))[0]
            if not isinstance(completed,BaseException):self.accept(*completed)
            self.pending=None
        self.metrics['reconstruction_frames_discarded_on_resync']=self.metrics.get('reconstruction_frames_discarded_on_resync',0)+len(self.ready)
        self.ready.clear()
        self.metrics['reconstruction_ready_frames']=0
        self.metrics['reconstruction_oldest_received_at']=None
        await owned_thread(self.pool.shutdown,wait=True,cancel_futures=True)
        self.metrics['reconstruction_worker_stopped']=True
