"""Exact images, independent transaction candidates, and bounded decode ownership."""
from copy import deepcopy
from unittest.mock import patch
from app.collection.current_book_images import CurrentBookImages
from app.collection.current_database import normalize_current
from tests.test_current_service import native_fixture


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
