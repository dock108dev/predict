"""Controlled injection seam for offline launcher checks; never production credentials."""
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

from app.collection.delivery_capture import KalshiTransport
from app.collection.venue_access import Credential
from tests.delivery_fixture import NetworkGuard, Server


def fake_data():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    return dict(key_id='diagnostic-fixture-key-only',private_key=key.private_bytes(
        serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode())


class FixtureTransport(KalshiTransport):
    """Validate native URLs first, then dial only the controlled loopback server."""
    def __init__(self,credential,endpoints):
        super().__init__(credential)
        from app.collection.delivery_capture import LoopbackTransport
        LoopbackTransport({'kalshi':endpoints})  # Reject nonliteral loopback injection.
        self.fixture=endpoints;self.mode='synthetic'

    def http_url(self,path,params):
        super().http_url(path,params)
        return self.fixture['rest']+path

    def ws_url(self):
        super().ws_url()
        return self.fixture['ws']


class Runtime:
    def __init__(self,spec,options):
        self.spec=spec;self.options=options;self.server=None;self.session=None;self.observations=[]
        if set(options)-{'load_failure','worker_crash','block_worker','block_finalizer'}:
            raise ValueError('unknown_fixture_fault')

    def guard(self):return NetworkGuard()

    def load(self):
        from app.collection.delivery_live import load_kalshi
        from keyring.backends.macOS import Keyring
        marker=Path(self.spec['ownership'])/(self.spec['attempt']+'.attempt.json')
        bound=json.loads(marker.read_text())
        if bound['output']!=self.spec['output'] or not (Path(self.spec['output'])/'candidate.json').exists():
            raise AssertionError('credential_before_marker')
        if self.options.get('worker_crash'):os._exit(7)
        if self.options.get('block_worker'):time.sleep(360)
        calls=[]
        def get(_self,service,account):
            calls.append((service,account))
            if (service,account)!=('prediction-arb.kalshi.production','market-data'):
                raise AssertionError('US_or_wrong_credential_lookup')
            if self.options.get('load_failure'):raise RuntimeError('fixture-secret-must-not-leak')
            return json.dumps(fake_data())
        with patch.object(Keyring,'get_password',get):value=load_kalshi()
        if calls!=[('prediction-arb.kalshi.production','market-data')]:raise AssertionError('credential_call_count')
        return value

    async def transport(self,credential):
        self.server=Server(busy=True,observe=self.observe)
        transport=await self.server.start()
        return FixtureTransport(credential,transport.endpoints)

    def before_stop(self,session):pass

    async def before_finalize(self,session):
        if self.options.get('block_finalizer'):time.sleep(360)

    async def close(self):
        if self.server:
            await self.server.close()
            from app.collection.delivery_live import write_once, OUTER_BYTES
            from app.collection.delivery_manifest import packed
            from app.collection.delivery_budget import CAP
            output=Path(self.spec['output'])
            marker=Path(self.spec['ownership'])/(self.spec['attempt']+'.attempt.json')
            value=dict(observations=self.observations,http_calls=self.server.http_calls,
                       ws_calls=self.server.ws_calls,closed=True)
            used=sum(p.stat().st_size for p in output.iterdir() if p.is_file())+marker.stat().st_size
            if used+len(packed(value))+OUTER_BYTES>CAP['helper_bytes']:raise ValueError('fixture_helper_cap')
            write_once(output/'fixture-observations.json',value)

    def observe(self,value):
        from app.collection.delivery_manifest import packed
        if len(self.observations)>=98 or len(packed(self.observations+[value]))>32768:
            raise ValueError('fixture_observation_cap')
        self.observations.append(value)


class JumpClock:
    """Picklable process-test clock. Advance only the independent deadline domain."""
    def __init__(self,offset,after=0):self.offset=offset;self.after=after;self.origin=time.monotonic()
    def __call__(self):
        now=time.monotonic()
        return now+(self.offset if now-self.origin>=self.after else 0)


def blocked_worker(pipe,ignore_term=False):
    import signal
    if ignore_term:signal.signal(signal.SIGTERM,signal.SIG_IGN)
    pipe.send(os.getpid())
    # A real blocked event loop, not a mocked cancellation.
    async def block():time.sleep(360)
    asyncio.run(block())


def orphan_supervisor(spec,manifest,approval,pipe,stall=False):
    from app.collection.delivery_live import Launcher
    async def run():
        launcher=Launcher(manifest,spec,fixture_options={'block_worker':True})
        await launcher.start(approval)
        pipe.send(dict(worker=launcher.process.pid,watchdog=launcher.guard.pid))
        if stall:time.sleep(360)  # Actual blocked control/heartbeat loop.
        await asyncio.Event().wait()
    asyncio.run(run())
