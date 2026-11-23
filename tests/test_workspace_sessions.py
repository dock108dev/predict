"""Legacy session bookmarks inspect verified source inputs without calculations."""
import asyncio
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.dashboard.local_security import PublicRequestError
from app.dashboard.request_guard import dashboard_guard
from app.dashboard.workspace_sessions import read_session, mount, MAX_INPUT_BYTES, load_original


def saved_fixture():
    return dict(session_id='received-session', data_mode='real', state='saved',
                durable_cursor='9-fixed-hash', last_update='2026-11-22T20:00:00Z',
                games=[dict(id='exact-game', title='Authored received-data fixture',
                            scheduled_start='2026-11-22T22:00:00Z',
                            product_identity=dict(family='spread',line='-4.5'),
                            sides={'kalshi:yes:exact':dict(participant='Home',native_label='YES')},
                            sources={'kalshi':dict(event_id='exact-event',market_id='exact-market')})],
                points={'exact-game':dict(id='9-fixed-hash',at='2026-11-22T20:00:00Z',cards=[])},
                rows_by_game={'exact-game':[dict(type='prediction_book',source='kalshi',raw=dict(price=0,received_at='2026-11-22T20:00:00Z'))]},
                references=[])


def test_exact_session_cutoff_contract_and_source_zero_are_preserved():
    with TemporaryDirectory() as folder:
        owner=SimpleNamespace(history_paths=lambda:{'received-session':Path(folder)})
        loader=Mock(return_value=saved_fixture())
        with patch('app.dashboard.product_view.calculate',side_effect=AssertionError('inspection must not recalculate')):
            value=read_session(owner,dict(session='received-session~exact-game',hash='received-session',
                                         cutoff='9-fixed-hash',contract='kalshi:yes:exact',quantity='7'),loader=loader)
        loader.assert_called_once_with(Path(folder),'9-fixed-hash')
        assert value['selected']['selected_contract']=='kalshi:yes:exact'
        assert value['selected']['source_rows'][0]['raw']['price']==0
        assert value['selected']['request_assumptions']=={'quantity':'7'}
        assert value['provider_requests']==value['scheduled_calculations']==0


def test_missing_synthetic_or_different_exact_selection_never_substitutes():
    with TemporaryDirectory() as folder:
        owner=SimpleNamespace(history_paths=lambda:{'received-session':Path(folder)})
        loader=Mock(return_value=saved_fixture())
        for query in (dict(capture='missing-session'),dict(session='received-session~missing-game'),
                      dict(session='received-session~exact-game',contract='kalshi:no:other'),
                      dict(capture='received-session',hash='other-session')):
            with pytest.raises(PublicRequestError):read_session(owner,query,loader=loader)
        synthetic=deepcopy(saved_fixture());synthetic['data_mode']='synthetic'
        with pytest.raises(PublicRequestError,match='genuine'):
            read_session(owner,dict(capture='received-session'),loader=lambda *args:synthetic)
        with pytest.raises(PublicRequestError,match='exact cutoff'):
            read_session(owner,dict(capture='received-session',cutoff='not-retained'),loader=Mock(side_effect=ValueError('unknown cutoff')))


def test_session_http_is_passive_and_no_archived_seed_package_is_loaded():
    asyncio.run(session_http_flow())


async def session_http_flow():
    with TemporaryDirectory() as folder:
        owner=SimpleNamespace(history_paths=lambda:{'received-session':Path(folder)})
        app=web.Application(middlewares=[dashboard_guard(None,logger=__name__)])
        mount(app,owner,loader=lambda *args:saved_fixture())
        async with TestClient(TestServer(app)) as client:
            with patch('app.dashboard.opportunity_board.load_sessions',side_effect=AssertionError('unrelated historical package')):
                response=await client.get('/api/workspace/session?capture=received-session')
                assert response.status==200
                value=await response.json()
                assert value['games'][0]['id']=='exact-game'
                assert value['provider_requests']==value['scheduled_calculations']==0
                missing=await client.get('/api/workspace/session?capture=absent')
                assert missing.status==422
                assert 'not retained' in (await missing.json())['error']


def test_oversized_saved_input_is_refused_before_replay():
    with TemporaryDirectory() as folder:
        path=Path(folder)/'large-saved-session.jsonl'
        with path.open('wb') as stream:stream.truncate(MAX_INPUT_BYTES+1)
        owner=SimpleNamespace(history_paths=lambda:{'received-session':Path(folder)})
        loader=Mock(return_value=saved_fixture())
        with pytest.raises(PublicRequestError,match='could not be verified'):
            read_session(owner,dict(capture='received-session'),loader=loader)
        loader.assert_not_called()


def test_existing_streaming_source_loader_checks_disk_chain_without_review_packages():
    from app.collection.transport_session import ObservationJournal
    from tests.synthetic_market_fixture import session_rows
    # The disk fixture remains explicitly synthetic; this tests the source loader,
    # not production-data admission, which the separate rejection case covers.
    with TemporaryDirectory() as folder:
        package=Path(folder)/'b2-fixture';package.mkdir()
        journal=ObservationJournal(package/'b2-fixture.jsonl')
        for row in session_rows():journal.save(row)
        journal.close()
        with patch('app.dashboard.native_reviews.packaged_index',side_effect=AssertionError('archived native review package')):
            first=load_original(package,None)
            exact=load_original(package,first['durable_cursor'])
        assert exact['session_id']=='b2-fixture'
        assert exact['durable_cursor']==first['durable_cursor']
        assert exact['market_catalog']
        with (package/'b2-fixture.jsonl').open('ab') as stream:stream.write(b'{broken\n')
        with pytest.raises(ValueError):load_original(package,None)
