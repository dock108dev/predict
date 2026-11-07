"""Ordinary mode of the existing board owner, replacing legacy calculation loops."""
import asyncio
from app.collection.background_work import AcquisitionDeferred
from app.collection.coverage_worker import run
from app.diagnostics import failure
from .latest_board import LatestBoardOwner
from .store import ROOT
from .current_games import utc


class OrdinaryOwner(LatestBoardOwner):
    async def start(self):
        await asyncio.to_thread(self.retire_legacy)
        # One turn seals observations then their optional finance. No legacy
        # observation/estimate owner runs alongside this ordinary projection.
        self.task = asyncio.create_task(self.run_ordinary(), name='predict-ordinary-comparison-owner')
        self.coverage_task = asyncio.create_task(self.run_coverage(), name='predict-coverage-owner')

    def retire_legacy(self):
        from .ordinary_publication import retire_legacy
        with self.connection() as db:
            retire_legacy(db)

    async def run_ordinary(self):
        while not self.closed:
            completed=False
            try:
                async with self.auxiliary_lock:
                    self.last = await run(lambda: self.closed, root=ROOT,
                        module='app.collection.ordinary_worker')
                self.observation_error = self.estimate_error = self.error = None
                self.progress['ordinary'] = dict(at=utc(), **self.last)
                completed=True
            except AcquisitionDeferred:
                self.progress['ordinary'] = dict(at=utc(), deferred=True, reason='native_acquisition_catching_up')
            except Exception as exc:
                if self.closed: return
                failure(__name__, 'ordinary_publication', exc)
                self.error = self.observation_error = 'ordinary_publication_failed'
                self.progress['ordinary'] = dict(at=utc(), error=self.error)
            # A completed bounded turn with known remaining work need not spend
            # another two seconds polling. The shared lane rechecks acquisition
            # pressure and Stop before admitting every successor child.
            delay=.05 if completed and self.last.get('published') and self.last.get('remaining_components',0)>0 else 2
            try: await asyncio.wait_for(self.wake.wait(), timeout=delay)
            except TimeoutError: pass
            self.wake.clear()

    async def run_coverage(self):
        # Keep the existing reserved optional-thread lane for this census. A
        # multi-minute auxiliary census must not sit ahead of native prices.
        from app.collection.background_work import optional_thread
        while not self.closed:
            try:
                self.last_coverage = await optional_thread(self.coverage_tick)
                self.coverage_error = None
            except AcquisitionDeferred:
                self.last_coverage = dict(deferred=True, reason='native_acquisition_catching_up')
            except Exception as exc:
                if self.closed: return
                failure(__name__, 'ordinary_coverage', exc)
                self.coverage_error = 'background_coverage_unavailable'
            for _ in range(240):
                if self.closed: return
                await asyncio.sleep(.5)
