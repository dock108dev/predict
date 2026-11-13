"""Poll the documented free full-game board under the data owner's lifecycle."""
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile

from aiohttp import ClientError, ClientSession, ClientTimeout

from app.comparison.public_sportsbook_estimate import HISTORY_SLOTS, MAX_BYTES, SPORTS, allowed, cache_path
from app.storage.store import stamp
from .current_policy import aggregate_scope, native_scope

POLL_SECONDS = 300
BOARD_URL = 'https://oddslink.app/v1/public/board/'


async def fetch_board(client, league):
    async with client.get(BOARD_URL + league.lower(), allow_redirects=False) as response:
        if response.status != 200:
            retry = response.headers.get('Retry-After', '')
            return None, f'http_{response.status}', int(retry) if retry.isascii() and retry.isdigit() and len(retry) <= 8 else 0
        body = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            if len(body) + len(chunk) > MAX_BYTES:
                raise ValueError('Board exceeds capture limit')
            body.extend(chunk)
    at = datetime.now(timezone.utc)
    wire = json.loads(body)
    if not isinstance(wire, dict):
        raise ValueError('Invalid board response')
    fixtures = wire['fixtures']
    if (wire['sport_key'] != league.lower() or stamp(wire['generated_at']) > at
            or not isinstance(fixtures, list) or len(fixtures) > 60):
        raise ValueError('Invalid board league, time or capacity')
    return dict(wire, received_at=at.isoformat(), sha256=sha256(body).hexdigest()), None, 0


def store_capture(root, league, capture):
    target = cache_path(root, league)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(capture, stream, separators=(',', ':'))
        if target.is_file():
            history = target.parent / 'public-sportsbook-history'
            history.mkdir(mode=0o700, exist_ok=True)
            for slot in range(HISTORY_SLOTS - 1, 0, -1):
                prior = history / f'{league.lower()}-{slot - 1}.json'
                if prior.is_file():
                    os.replace(prior, history / f'{league.lower()}-{slot}.json')
            shutil.copyfile(target, history / f'{league.lower()}-0.json')
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class PublicSportsbookWorker:
    def __init__(self, service):
        self.service = service
        self.closed = False
        self.metrics = dict(state='waiting', poll_target_seconds=POLL_SECONDS, leagues={}, paid_objects=0)

    def enabled(self):
        return not self.closed and allowed(dict(active=self.service.dispatch, config=self.service.config,
            global_stopped=self.service.globally_stopped, paused_sources=self.service.paused_sources))

    async def run(self):
        from app.storage.store import ROOT

        scope = set(aggregate_scope(self.service.config)) & set(native_scope(self.service.config))
        leagues = [league for league in SPORTS if league in scope]
        async with ClientSession(timeout=ClientTimeout(total=8), trust_env=True) as client:
            while self.enabled() and leagues:
                loop = asyncio.get_running_loop()
                next_poll = loop.time() + POLL_SECONDS
                for league in leagues:
                    if not self.enabled():
                        return
                    metrics = self.metrics['leagues'].setdefault(league, dict(attempts=0, completed=0))
                    metrics.update(attempts=metrics['attempts'] + 1, attempted_at=datetime.now(timezone.utc).isoformat())
                    try:
                        capture, reason, delay = await fetch_board(client, league)
                        if not self.enabled():
                            return
                        if capture is None:
                            metrics.update(state='deferred', reason=reason)
                            if delay or reason == 'http_429':
                                next_poll = max(next_poll, loop.time() + max(delay, POLL_SECONDS))
                                break
                        else:
                            store_capture(ROOT, league, capture)
                            previous = metrics.get('received_at')
                            metrics.update(state='captured', reason=None, completed=metrics['completed'] + 1,
                                fixtures=len(capture['fixtures']), received_at=capture['received_at'],
                                generated_at=capture['generated_at'],
                                previous_received_at=previous,
                                interval_seconds=(stamp(capture['received_at']) - stamp(previous)).total_seconds() if previous else None)
                    except (ClientError, TimeoutError, OSError, KeyError, ValueError, TypeError, AttributeError) as error:
                        metrics.update(state='deferred', reason=type(error).__name__)
                    await asyncio.sleep(1)
                self.metrics['state'] = 'polling'
                await asyncio.sleep(max(0, next_poll - loop.time()))

    async def close(self):
        self.closed = True
