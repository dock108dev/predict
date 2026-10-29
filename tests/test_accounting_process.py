"""Real spawned accounting against disposable files, no provider transport."""
import asyncio
from datetime import datetime, timezone, timedelta
import fcntl
from pathlib import Path
import tempfile
from unittest import IsolatedAsyncioTestCase
from app.collection.accounting_process import AccountingProcess
from app.collection.current_quota import QuotaLedger, now
from app.collection.local_ownership import LocalOwnership


class ProcessAccounting(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.owner=LocalOwnership(self.root/'owner');self.owner.acquire('fixture-runtime')
        self.ledger=QuotaLedger(self.root/'quota')
        at=datetime.now(timezone.utc)
        self.ledger.bind_window(dict(id='fixture-window',starts_at=(at-timedelta(days=1)).isoformat(),
            ends_at=(at+timedelta(days=29)).isoformat(),evidence='fixture',evidence_sha256='a'*64))
        self.worker=AccountingProcess(self.ledger,self.owner)

    async def asyncTearDown(self):
        await self.worker.close();self.owner.release();self.temp.cleanup()

    async def bootstrap(self):
        aid=await self.worker.call('reserve','fixture',dict(path='/v4/sports',params={}),0,bootstrap=True)
        await self.worker.call('dispatched',aid)
        receipt=dict(status=200,received_at=now(),headers=[('x-requests-used','20'),('x-requests-remaining','480'),('x-requests-last','0')])
        charged,q=await self.worker.call('account_response',aid,receipt)
        self.assertEqual((charged,q['used']),(0,20))
        self.assertEqual(self.ledger._read()['attempts'][aid]['response_receipt']['status'],200)
        return aid

    async def test_status_process_returns_exact_accounting_without_writing_ledger(self):
        from app.collection.quota_status import AccountProjection
        await self.bootstrap()
        path=self.ledger.directory/'quota.json';original=path.read_bytes()
        status=AccountProjection()
        try:
            result=await status.read(str(self.ledger.directory),None,str(self.ledger.directory),self.ledger.snapshot()['reset'])
            expected=self.ledger.snapshot()
            for value in (result['quota'],expected):value.pop('observation_age_seconds',None)
            self.assertEqual(result['quota'],expected)
            self.assertIsNone(result['pending'])
            self.assertEqual(result['ledger_reason'],self.ledger.recovery_reason(self.ledger.snapshot()['reset']))
            self.assertEqual(path.read_bytes(),original)
            path.write_text('invalid')
            refused=await status.read(str(self.ledger.directory),None,str(self.ledger.directory),None)
            self.assertEqual(refused['quota']['pause'],'quota_ledger_unavailable')
            self.assertEqual(refused['pending'],'quota_ledger_unavailable')
        finally:
            path.write_bytes(original)
            await status.close()

    async def test_clock_preparation_uses_existing_owned_process(self):
        await self.bootstrap();self.ledger.pause('clock_continuity_unknown');before=self.ledger._read()
        await self.worker.call('prepare_clock','fixture-candidate',before['window'],cleanup_safe=True)
        after=self.ledger._read()
        self.assertIsNone(after['pause'])
        for key in ('attempts','observation','next_due_at','bootstrap_due_at','accounting_epoch'):
            self.assertEqual(after[key],before[key])
        self.assertEqual(after['clock_recoveries'][-1]['authority'],'existing_accounting_only')

    async def test_scheduler_snapshot_is_exact_and_read_only(self):
        await self.bootstrap()
        path=self.ledger.directory/'quota.json';before=path.read_bytes()
        value=await self.worker.call('snapshot');expected=self.ledger.snapshot()
        for item in (value,expected):item.pop('observation_age_seconds',None)
        self.assertEqual(value,expected)
        self.assertEqual(path.read_bytes(),before)

    async def test_receipt_commit_and_duplicate_lock_lifecycle(self):
        await self.bootstrap()
        contender=LocalOwnership(self.root/'owner')
        # The actual duplicated lock descriptor survives a parent descriptor close.
        self.owner.release()
        with self.assertRaises(ValueError):contender.acquire('other')
        await self.worker.close()
        contender.acquire('other');contender.release()

    async def test_repeated_cancellation_joins_reservation_and_preserves_consumed_attempt(self):
        await self.bootstrap();result={}
        with (self.root/'quota'/'quota.lock').open('r+') as locked:
            fcntl.flock(locked,fcntl.LOCK_EX)
            task=asyncio.create_task(self.worker.call('reserve','fixture',dict(path='/v4/sports/baseball_mlb/odds',params={}),3,result=result))
            await asyncio.sleep(.05);task.cancel();await asyncio.sleep(.01);task.cancel();await asyncio.sleep(.01)
            self.assertFalse(task.done())
            fcntl.flock(locked,fcntl.LOCK_UN)
            with self.assertRaises(asyncio.CancelledError):await task
        aid=result['id'];await self.worker.call('cancel_before_transport',aid)
        attempt=self.ledger._read()['attempts'][aid]
        self.assertEqual(attempt['state'],'not_dispatched');self.assertTrue(attempt['consumed'])

    async def test_cancelled_response_accounting_still_commits_received_charge(self):
        await self.bootstrap()
        aid=await self.worker.call('reserve','fixture',dict(path='/v4/sports/baseball_mlb/odds',params={}),3)
        await self.worker.call('dispatched',aid)
        receipt=dict(status=200,received_at=now(),headers=[('x-requests-used','23'),('x-requests-remaining','477'),('x-requests-last','3')])
        with (self.root/'quota'/'quota.lock').open('r+') as locked:
            fcntl.flock(locked,fcntl.LOCK_EX)
            task=asyncio.create_task(self.worker.call('account_response',aid,receipt))
            await asyncio.sleep(.05);task.cancel();await asyncio.sleep(.01)
            self.assertFalse(task.done())
            fcntl.flock(locked,fcntl.LOCK_UN)
            with self.assertRaises(asyncio.CancelledError):await task
        attempt=self.ledger._read()['attempts'][aid]
        self.assertEqual((attempt['state'],attempt['charged']),('confirmed',3))
        self.assertEqual(attempt['response_receipt']['headers'],[list(row) for row in receipt['headers']])
