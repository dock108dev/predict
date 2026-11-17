"""Wake the ordinary calculation worker for app-only retained installations."""
import asyncio

from aiohttp import web

from app.collection.coverage_worker import run
from app.diagnostics import failure
from app.storage.store import ROOT

WAKE = web.AppKey('pregame_unit_publication_wake', asyncio.Event)


def mount(app):
    wake = app[WAKE] = asyncio.Event()
    wake.set()

    async def lifecycle(_app):
        async def serve():
            while True:
                await wake.wait()
                wake.clear()
                try:
                    result = await run(lambda: False, root=ROOT, module='app.collection.ordinary_worker',
                                       arguments=('--units-only',))
                    if result.get('more'):
                        wake.set()
                except Exception as exc:
                    failure(__name__, 'pregame_unit_publication', exc)
                # Coalesce browser polls and allow the normal publisher to
                # resume immediately if its SQL owner comes back.
                await asyncio.sleep(0.25)

        task = asyncio.create_task(serve(), name='predict-pregame-unit-publication')
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    app.cleanup_ctx.append(lifecycle)
