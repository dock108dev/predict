"""Explicit isolated synthetic U5 browser harness; zero credential/provider I/O."""
import argparse
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
from aiohttp import web
from app.collection.current_service import CurrentService
from app.collection.current_quota import QuotaLedger
from app.collection.local_ownership import LocalOwnership
from app.dashboard.multi_game_server import create_app
from app.dashboard.current_state import CURRENT_KEY
from tests.test_current_service import FakeWorker,native_fixture
from tests.test_current_admin import IdleAggregate
from tests.test_current_state import owner
from tests.test_current_quota import WINDOW,quota

class SyntheticService(CurrentService):
    def status(self):
        raw=super().status();raw['evidence_class']='SYNTHETIC ADMIN TEST — fictional source inputs and accounting; no provider requests.'
        return raw

def main():
    p=argparse.ArgumentParser();p.add_argument('--synthetic-test',action='store_true',required=True);p.add_argument('--port',type=int,default=8798);a=p.parse_args()
    temp=tempfile.TemporaryDirectory();root=Path(temp.name);q=QuotaLedger(root/'quota')
    now=datetime.now(timezone.utc);window=dict(WINDOW,starts_at=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat(),ends_at=(now.replace(day=28)+timedelta(days=4)).replace(day=1,hour=0,minute=0,second=0,microsecond=0).isoformat())
    service=SyntheticService(directory=root/'attempts',ownership=LocalOwnership(root/'owner'),worker_factory=FakeWorker,
        aggregate_factory=lambda svc:IdleAggregate(svc,ledger=q,window_loader=lambda:window))
    app=create_app(owner=owner(),sessions={},current_provider=service)
    async def populate(app):
        q.bind_window(window);aid=q.reserve(service.ownership,service.digest,dict(path='/v4/sports',params={}),0,bootstrap=True)
        q.dispatched(aid,service.ownership);q.reconcile(aid,quota(248))
        cat,book=native_fixture();service.catalog('kalshi',cat);service.book('kalshi',book)
        service.issue('polymarket_us','authentication','dedicated_credential_missing_or_invalid')
        service.workers['the_odds_api'].state('budget_delayed','aggregate_budget_delayed','Synthetic scheduled delay; native paths remain independent.')
    app.on_startup.append(populate)
    async def cleanup(app):temp.cleanup()
    app.on_cleanup.append(cleanup)
    async def bound(app):
        async def stop():
            await asyncio.sleep(600);await service.close()
        app['synthetic_deadline']=asyncio.create_task(stop())
    app.on_startup.append(bound)
    web.run_app(app,host='127.0.0.1',port=a.port,access_log=None)
if __name__=='__main__':main()
