"""Exact images, independent transaction candidates, and bounded decode ownership."""
from copy import deepcopy
from unittest.mock import patch
from app.collection.current_book_images import CurrentBookImages
from app.collection.current_database import normalize_current
from tests.test_current_service import native_fixture


def test_child_packed_image_keeps_parent_clock_and_confirmation_without_reencoding():
    from app.collection.current_book_images import encode_container
    _,book=native_fixture();image=encode_container(book)
    images=CurrentBookImages();expected=deepcopy(book)
    expected['raw']['exchange_at']='2026-09-01T00:00:00Z'
    expected['book_confirmation']={'confirmed_at':'2026-11-07T23:00:00Z','proof':'owned'}
    with patch('app.collection.current_book_images.encode_container',side_effect=AssertionError('loop compression')):
        images.set_prepared('one',image,exchange_at=expected['raw']['exchange_at'],confirmation=expected['book_confirmation'])
        copied=images.copy();moved=copied.take(['one'])
    assert moved['one']==expected and images['one']==expected
    expected['book_confirmation']['proof']='outside mutation'
    assert moved['one']['book_confirmation']['proof']=='owned'
    assert images.encoded_bytes==len(images.encoded['one'])


def test_owned_images_are_exact_and_candidates_do_not_mutate_committed_books():
    _,book=native_fixture()
    book['inspection']={'unicode':'é 🎯','price':'0.12345678901234567890','missing':None}
    images=CurrentBookImages();images['one']=book
    original=deepcopy(book)
    book['inspection']['price']='changed outside'
    assert images['one']==original
    candidate=images.copy()
    assert candidate.encoded['one'] is images.encoded['one']
    decoded=candidate['one'];decoded['inspection']['price']='new'
    candidate['one']=decoded
    assert images['one']==original
    del candidate['one']
    candidate.retain_from(images,['one'])
    assert candidate['one']==original
    assert candidate.encoded_bytes==sum(map(len,candidate.encoded.values()))
    del candidate['one']
    assert candidate.encoded_bytes==0 and len(images)==1


def test_full_roster_decodes_only_current_normalization_batch():
    cat,book=native_fixture();market=cat['markets'][0]
    cat['markets']=[]
    images=CurrentBookImages()
    for index in range(1100):
        mid='bulk-'+str(index)
        cat['markets'].append(dict(deepcopy(market),id=mid))
        image=deepcopy(book);image['raw']['ref']['market_id']=mid
        obs=dict(type='prediction_book',source='kalshi',book=image,observed_at=image['raw']['received_at'],packets=[])
        images[('kalshi',image['raw']['ref']['event_id'],mid)]=obs
    catalog=dict(id='catalog',record=dict(source='kalshi',value=dict(inventory=cat)))
    seen=[];decoded=[]
    original=CurrentBookImages.__getitem__
    def decode(self,key):
        decoded.append(key)
        return original(self,key)
    def capture(part,books,**kwargs):
        batch=part['record']['value']['inventory']['markets']
        assert len(books)==len(batch)<=256
        assert len(decoded)==len(seen)+len(batch)
        seen.extend(m['id'] for m in batch)
        return [],[]
    with patch.object(CurrentBookImages,'__getitem__',decode),patch('app.comparison.combined_native.normalize',side_effect=capture):
        assert normalize_current(catalog,[],at=book['raw']['received_at'],current_images=images)==([],[])
    assert len(seen)==len(set(seen))==1100


def test_live_memory_observer_does_not_decode_or_walk_book_graphs():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.collection.retained_memory import watch
    images=CurrentBookImages();images['one']={'price':'0.123456789'}
    runtime=SimpleNamespace(service=SimpleNamespace(
        sink=SimpleNamespace(reducer=SimpleNamespace(books=images)),workers={}))
    async def run():
        with patch('app.collection.retained_memory.asyncio.sleep',AsyncMock(side_effect=[None,asyncio.CancelledError])), \
                patch('app.collection.retained_memory.measure',side_effect=AssertionError('recursive heap walk')), \
                patch.object(CurrentBookImages,'__getitem__',side_effect=AssertionError('decoded image')):
            try:await watch(runtime)
            except asyncio.CancelledError:pass
    asyncio.run(run())
    assert runtime.retained_memory['roots']['reducer_books']==dict(entries=1,encoded_bytes=images.encoded_bytes)


def test_clear_discards_encoded_queue_without_decoding():
    images=CurrentBookImages();images['one']={'price':'0.123400'}
    with patch.object(CurrentBookImages,'__getitem__',side_effect=AssertionError('discard decoded')):
        images.clear()
    assert len(images)==0 and images.encoded_bytes==0


def test_native_queues_share_exact_encoded_image_and_keep_independent_ownership():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.collection.current_native import NativeWorker
    from app.collection.current_policy import DEFAULT
    async def run():
        w=NativeWorker(SimpleNamespace(config=DEFAULT,dispatch=True,database_mode=True),'kalshi')
        w.persist_raw=AsyncMock()
        _,book=native_fixture();mid=book['raw']['ref']['market_id'];original=deepcopy(book)
        try:
            w.queue_book(book)
            assert w.pending_books.encoded[mid] is w.raw_pending.encoded[mid]
            book['raw']['exchange_at']='changed outside'
            assert w.raw_pending[mid]==original
            decoded=w.pending_books.pop(mid)
            assert decoded==original and w.raw_pending[mid]==original
            assert w.pending_books.encoded_bytes==0
        finally:
            if w.publication_handle:w.publication_handle.cancel()
            if w.raw_task:await w.raw_task
    asyncio.run(run())

def test_compressed_and_small_images_preserve_original_quote_text_and_container_ownership():
    from app.collection.current_book_images import decode_container, encode_container

    side = {"name": "Sí", "price": "0.6200", "depth": ["3.00", None, 0]}
    assert not encode_container(side).startswith(b'\0')
    event = {"markets": [side] * 90}
    encoded = encode_container(event)
    assert encoded.startswith(b'\0')
    assert decode_container(encoded) == event
    changed = decode_container(encoded)
    changed["markets"][0]["price"] = "1.00"
    assert decode_container(encoded) == event


def test_take_transfers_encoded_ownership_without_decoding():
    images=CurrentBookImages()
    images['one']={'original':'0.123400'};images['two']={'original':'0.5600'}
    encoded=images.encoded['one']
    with patch.object(CurrentBookImages,'__getitem__',side_effect=AssertionError('main-loop decode')):
        batch=images.take(['one'])
    assert batch.encoded['one'] is encoded and 'one' not in images
    assert images.encoded_bytes==len(images.encoded['two'])
    assert batch.encoded_bytes==len(encoded)
    images['one']={'original':'0.7800'}
    assert batch['one']=={'original':'0.123400'}


def test_raw_storage_decodes_in_owned_thread_and_reports_original_receipts():
    import asyncio,threading,time
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.collection.current_native import NativeWorker
    from app.collection.current_policy import DEFAULT
    async def run():
        w=NativeWorker(SimpleNamespace(config=DEFAULT,dispatch=True,database_mode=True,runtime_id='owner'),'kalshi')
        _,book=native_fixture();mid=book['raw']['ref']['market_id']
        w.raw_pending[mid]=book;w.raw_context[mid]=('owner',2,'census');w.raw_since[mid]=time.monotonic()
        w.synchronization=Mock();main=threading.get_ident();original=CurrentBookImages.__getitem__
        def decode(images,key):
            assert threading.get_ident()!=main
            return original(images,key)
        def save(venue,books,disposition,contexts):
            assert threading.get_ident()!=main
            assert venue=='kalshi' and disposition=='pending' and books==[book]
            assert contexts=={mid:('owner',2,'census')}
        with patch.object(CurrentBookImages,'__getitem__',decode),patch('app.collection.bulk_checkpoint.save_images',side_effect=save):
            await w.persist_raw()
        assert not w.raw_pending and not w.raw_inflight and not w.raw_context
        assert w.metrics['raw_images_persisted']==1
        w.synchronization.persist.assert_called_once_with(2,[mid])
        w.synchronization.delivered.assert_called_once_with('raw',[book['raw']['received_at']])
    asyncio.run(run())


def test_raw_storage_failure_restores_exact_images_without_overwriting_new_arrival():
    import asyncio,threading,time
    from types import SimpleNamespace
    from app.collection.current_native import NativeWorker
    from app.collection.current_policy import DEFAULT
    async def run():
        w=NativeWorker(SimpleNamespace(config=DEFAULT,dispatch=True,database_mode=True,runtime_id='owner'),'kalshi')
        _,book=native_fixture();first=book['raw']['ref']['market_id'];second='second'
        other=deepcopy(book);other['raw']['ref']['market_id']=second
        for mid,b in ((first,book),(second,other)):
            w.raw_pending[mid]=b;w.raw_context[mid]=('owner',2,'old');w.raw_since[mid]=1.0
        original=w.raw_pending.encoded[second];entered=threading.Event();release=threading.Event()
        def fail(*args,**kwargs):
            entered.set()
            assert release.wait(5)
            raise RuntimeError('fixture storage failure')
        with patch('app.collection.bulk_checkpoint.save_images',side_effect=fail):
            task=asyncio.create_task(w.persist_raw())
            try:
                assert await asyncio.to_thread(entered.wait,5)
                replacement=deepcopy(book);replacement['inspection']='new arrival'
                w.raw_pending[first]=replacement;w.raw_context[first]=('owner',3,'new');w.raw_since[first]=2.0
                newer=w.raw_pending.encoded[first]
            finally:release.set()
            try:await task
            except RuntimeError:pass
            else:raise AssertionError('storage failure was hidden')
        assert w.raw_pending.encoded[first] is newer
        assert w.raw_pending.encoded[second] is original
        assert w.raw_context=={first:('owner',3,'new'),second:('owner',2,'old')}
        assert w.raw_since=={first:2.0,second:1.0}
        assert w.raw_pending.encoded_bytes==sum(map(len,w.raw_pending.encoded.values()))
        assert not w.raw_inflight and w.metrics['raw_inflight_images']==0
    asyncio.run(run())


def test_cancelled_raw_storage_joins_write_before_restoring_batch_ownership():
    import asyncio,threading
    from types import SimpleNamespace
    from app.collection.current_native import NativeWorker
    from app.collection.current_policy import DEFAULT
    async def run():
        w=NativeWorker(SimpleNamespace(config=DEFAULT,dispatch=True,database_mode=True,runtime_id='owner'),'kalshi')
        _,book=native_fixture();mid=book['raw']['ref']['market_id']
        w.raw_pending[mid]=book;w.raw_context[mid]=('owner',2,'census');w.raw_since[mid]=1.0
        encoded=w.raw_pending.encoded[mid];entered=threading.Event();release=threading.Event();finished=threading.Event()
        def save(*args,**kwargs):
            entered.set()
            assert release.wait(5)
            finished.set()
        with patch('app.collection.bulk_checkpoint.save_images',side_effect=save):
            task=asyncio.create_task(w.persist_raw())
            try:
                assert await asyncio.to_thread(entered.wait,5)
                task.cancel();await asyncio.sleep(0)
                assert not task.done() and mid not in w.raw_pending
            finally:release.set()
            try:await task
            except asyncio.CancelledError:pass
            else:raise AssertionError('cancellation was hidden')
        assert finished.is_set()
        assert w.raw_pending.encoded[mid] is encoded
        assert w.raw_context[mid]==('owner',2,'census')
        assert not w.raw_inflight
    asyncio.run(run())
