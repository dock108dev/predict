"""Ordinary mode of the existing board owner, replacing legacy calculation loops."""
import asyncio
from app.collection.background_work import AcquisitionDeferred
from app.collection.coverage_worker import run
from app.diagnostics import failure
from .store import ROOT
from .current_games import utc


class OrdinaryOwner:
    def __init__(self, service):
        self.service = service
        self.closed = False
        self.task = self.coverage_task = self.drain_task = None
        self.last = self.last_coverage = None
        self.error = self.observation_error = self.estimate_error = self.coverage_error = None
        self.progress = {}
        self.wake = asyncio.Event()

    async def start(self):
        self.service.ingress.on_sgo_admitted = self.wake.set
        self.service.ingress.on_native_admitted = self.wake.set
        # One turn seals observations then their optional finance. No legacy
        # observation/estimate owner runs alongside this ordinary projection.
        self.task = asyncio.create_task(self.run_ordinary(), name='predict-ordinary-comparison-owner')
        self.coverage_task = asyncio.create_task(self.run_coverage(), name='predict-coverage-owner')

    async def close(self):
        self.closed = True
        self.wake.set()
        tasks = [task for task in (self.task, self.coverage_task) if task]
        if not tasks:
            return
        # The child runner observes closed, drains the process and releases
        # its admission. A caller timing out still leaves that drain owned.
        if self.drain_task is None:
            self.drain_task = asyncio.gather(*tasks, return_exceptions=True)
        results = await asyncio.wait_for(asyncio.shield(self.drain_task), self.service.config['cleanup_seconds'])
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def run_ordinary(self):
        while not self.closed:
            completed=False
            try:
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
            if completed and self.last.get('reason') == 'snapshot_operation_running':
                # Coalesce incoming updates while a rewrite owns the slot.
                self.wake.clear()
                await asyncio.sleep(.25)
                continue
            delay=.05 if completed and self.last.get('published') and self.last.get('remaining_components',0)>0 else 2
            try: await asyncio.wait_for(self.wake.wait(), timeout=delay)
            except TimeoutError: pass
            self.wake.clear()

    async def run_coverage(self):
        # The full census must neither hold the publication lane nor allocate
        # its JSON graph in the socket process. Native sampling found its GC
        # scans holding the GIL while receive callbacks waited. The existing
        # coverage runner owns one child, its memory/deadline and Stop cleanup.
        while not self.closed:
            try:
                self.last_coverage = await run(lambda:self.closed,root=ROOT,wait_for_admission=False)
                self.coverage_error = None
            except AcquisitionDeferred:
                self.last_coverage = dict(deferred=True, reason='native_acquisition_catching_up')
                await asyncio.sleep(2)
                continue
            except Exception as exc:
                if self.closed: return
                failure(__name__, 'ordinary_coverage', exc)
                self.coverage_error = 'background_coverage_unavailable'
            for _ in range(240):
                if self.closed: return
                await asyncio.sleep(.5)
