"""The fee switch uses the existing owner boundary and central setting owner."""
import asyncio
from contextlib import nullcontext
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.dashboard.request_guard import dashboard_guard
from app.dashboard.workspace_routes import mount


class DB:
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def transaction(self):return nullcontext()
    def execute(self,*args):return SimpleNamespace(fetchone=lambda:None)


def test_fee_status_and_owner_toggle_share_persisted_boolean_without_acquisition():
    asyncio.run(fee_api_flow())


async def fee_api_flow():
    state={'enabled':False,'revision':'initial-off','version':'fee-mode-fixture-1','assumption':'zero_fees'}
    read=Mock(side_effect=lambda db:dict(state))
    def update(db,enabled):
        state.update(enabled=enabled,revision='enabled' if enabled else 'disabled',
                     assumption='existing_fee_models' if enabled else 'zero_fees')
        return dict(state,queued_events=2)
    setter=Mock(side_effect=update)
    central=SimpleNamespace(read=read,set_enabled=setter)
    app=web.Application(middlewares=[dashboard_guard(None,logger=__name__)])
    mount(app,Path(__file__).resolve().parents[1]/'app/dashboard')
    with patch.dict(sys.modules,{'app.comparison.fee_mode':central}), \
         patch('app.storage.store.connect',side_effect=DB), \
         patch('app.research.experiment.status',return_value={'storage':{}}), \
         patch('app.research.readiness.report',return_value={'state':'ready'}), \
         patch('app.collection.sportsgameodds_transport.SportsgameoddsTransport.fetch',side_effect=AssertionError('provider acquisition')):
        async with TestClient(TestServer(app)) as client:
            origin=str(client.make_url('/')).rstrip('/')
            response=await client.get('/api/workspace/status')
            assert response.status==200
            value=await response.json()
            assert value['fee_mode']['enabled'] is False
            assert value['provider_requests']==value['scheduled_calculations']==0
            setter.assert_not_called()
            for enabled in (True,False):
                changed=await client.patch('/api/workspace/fees',json={'enabled':enabled},headers={'Origin':origin})
                assert changed.status==200
                saved=await changed.json()
                assert saved['enabled'] is enabled
                assert saved['provider_requests']==0
                reread=await (await client.get('/api/workspace/status')).json()
                assert reread['fee_mode']['enabled'] is enabled
            assert [call.args[1] for call in setter.call_args_list]==[True,False]


def test_fee_toggle_rejects_cross_origin_and_non_boolean_or_extra_settings():
    asyncio.run(fee_invalid_flow())


async def fee_invalid_flow():
    setter=Mock(return_value={'enabled':True})
    app=web.Application(middlewares=[dashboard_guard(None,logger=__name__)])
    mount(app,Path(__file__).resolve().parents[1]/'app/dashboard')
    with patch.dict(sys.modules,{'app.comparison.fee_mode':SimpleNamespace(set_enabled=setter)}), \
         patch('app.storage.store.connect',side_effect=DB):
        async with TestClient(TestServer(app)) as client:
            origin=str(client.make_url('/')).rstrip('/')
            assert (await client.patch('/api/workspace/fees',json={'enabled':True})).status==403
            assert (await client.patch('/api/workspace/fees',json={'enabled':True},headers={'Origin':'https://unrelated.invalid'})).status==403
            for body in ({},{'enabled':1},{'enabled':'false'},{'enabled':False,'mode':'live'},[]):
                response=await client.patch('/api/workspace/fees',json=body,headers={'Origin':origin})
                assert response.status==422
            assert (await client.patch('/api/workspace/fees?collect=1',json={'enabled':True},headers={'Origin':origin})).status==422
            setter.assert_not_called()


def test_settings_fee_checkbox_uses_confirmed_state_and_preserves_failed_change():
    import subprocess
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/workspace_fee_settings_client.cjs'],cwd=root,
                          text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
