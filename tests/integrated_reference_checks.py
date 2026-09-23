"""Short actual collector/API reference changes and clean second-session check."""
import asyncio
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import patch
from tests.integrated_workload import Runtime,save
from tests.test_reference_integration import references
from app.reference.product import receipt,published_value,at_cutoff
from app.dashboard import product_view,session_history

async def run(root):
    runtime=Runtime(root)
    with patch('app.collection.native_product.load_native_secret',side_effect=AssertionError('no credentials')):
        await runtime.open(8819)
        try:
            sid=(await runtime.request('/api/start',dict(duration=30)))['session'];o=runtime.owner;s=o.session;f=runtime.fixture
            await f.wait(lambda:len(f.active())==2 and s.discovery.generation>=1)
            await f.images();await runtime.annotated_books(metadata=True)
            snap=o.current_snapshot();g=next(g for g in snap['games'] if g['product_identity']['competition']=='NFL' and set(g['sources'])=={'kalshi','polymarket_us'})
            refs=references(g,datetime.now(timezone.utc).isoformat())
            await runtime.request('/api/references',refs)
            old=o.current_snapshot();old=o.cutoffs[old['durable_cursor']]
            key=next(k for k,v in g['sides'].items() if k.startswith('polymarket_us:') and v['participant']==refs[0]['participant'])
            a=product_view.calculate(old,g,dict(contract=key,reference=refs[0]['id']))
            assert a['ev']['expected_profit'] is not None
            r=refs[0];body=r['receipt']['body'].replace('60.0%','65.0%');rr=receipt(body,provider=r['provider_id'],url=r['receipt']['url'],received_at=datetime.now(timezone.utc).isoformat(),mode='synthetic')
            new=published_value(rr,r['binding'],start=r['extraction']['start'],end=r['extraction']['end'],kind='game_probability',convention='percent',source_at=rr['received_at'],model_version='SYNTHETIC changed 65 percent')
            await runtime.request('/api/references',[new]);latest=o.current_snapshot();latest=o.cutoffs[latest['durable_cursor']]
            b=product_view.calculate(latest,g,dict(contract=key,reference=new['id']))
            assert Decimal(b['ev']['expected_profit'])-Decimal(a['ev']['expected_profit'])==Decimal('5')
            rating=product_view.calculate(latest,g,dict(contract=key,reference=refs[2]['id']))
            assert rating['ev']['expected_profit'] is None
            manual=product_view.calculate(latest,g,dict(contract=key,probability='.5'))
            assert manual['reference_id'] is None and manual['ev']['probability'] in ('.5','0.5')
            assert at_cutoff([new],old['last_update'])==[]
            missing=product_view.calculate(latest,g,dict(contract=key))
            assert missing['ev']['expected_profit'] is None
            await runtime.request('/api/stop',{});await o.finalizer;assert o.error is None
            reopened=session_history.load(s.output,old['durable_cursor']);assert product_view.calculate(reopened,g,dict(contract=key,reference=r['id']))['ev']==a['ev']
            save(Path(root)/'reference-oracle.json',dict(session=sid,old_cutoff=old['durable_cursor'],new_cutoff=latest['durable_cursor'],old=a,new=b,manual=manual,rating=rating,missing=missing,exact_change='5',old_cutoff_unchanged=True,no_future_leak=True))
            f.connections=[]
            sid2=(await runtime.request('/api/start',dict(duration=15)))['session'];s2=o.session
            assert sid2!=sid and not s2.projection.references and not s2.projection.resolutions and not s2.projection.books
            await f.wait(lambda:len(f.active())==2 and s2.discovery.generation>=1);await f.images()
            assert not s2.projection.references and not s2.projection.resolutions
            await runtime.request('/api/stop',{});await o.finalizer;assert o.error is None
            assert not session_history.load(s2.output)['references']
            save(Path(root)/'second-session.json',dict(session=sid2,prior=sid,no_book_reference_resolution_leak=True,cleanup=s2.cleanup_complete))
            print('PASS: actual collector/API model 60→65, +$5 exact EV, unsupported rating, separate manual, missing model, immutable old cutoff, clean second session')
        finally:await runtime.close()

if __name__=='__main__':asyncio.run(run(sys.argv[1]))
