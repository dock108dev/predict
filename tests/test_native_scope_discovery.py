"""Retained typed catalog identifiers through ordinary bounded HTTP discovery."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit, parse_qs

from app.collection import native_scope_discovery as scoped
from app.collection.continuous import Discovery
from app.collection.native_payload import TRANSPORT_CONTRACT
from app.collection.native_scope_bindings import POLICY, selectors_for
from app.collection.native_selectors import SPORTS, POLICY as DIRECTED, validate_probe
from app.collection.odds_http import BudgetStop
from app.collection.prediction_producer import PredictionBudget
from app.collection.source_bindings import required_cells
from app.collection.source_session import normalize_native_scopes
from app.collection.run_spec import preflight
from tests.test_native_http_reader import server, fixed
from tests.test_ordinary_native_transport import configuration


def spec(cells,requests=48):
    value=configuration();value['prediction']['discovery_requests']=requests
    for key in ('event','participants','scheduled_start'):value.pop(key,None)
    for source in ('kalshi','polymarket_us'):
        value['sources'][source]={k:v for k,v in value['sources'][source].items()
                                  if k in ('credential_reference','entitlement_reference')}
    value['native_discovery']=dict(policy=DIRECTED,sports=list(SPORTS),discovery_only=True,generations=1,
                                   native_scopes={'kalshi':cells})
    return value


class ScopeValidation(unittest.TestCase):
    def test_metadata_scopes_need_new_explicit_transport_and_expand_exact63(self):
        value=spec('required-63-v1')
        self.assertTrue(preflight(value)['valid'],preflight(value)['errors'])
        drift=deepcopy(value);drift['native_transport']['json_depth']=32.0
        self.assertFalse(scoped.enabled(drift,'kalshi'))
        value.pop('native_transport');self.assertFalse(preflight(value)['valid'])
        expanded=normalize_native_scopes({'kalshi':'required-63-v1'})['kalshi']
        self.assertEqual(len(expanded),63)
        self.assertEqual({scoped.cell_id(c) for c in expanded},{c['cell_id'] for c in required_cells()})
        with self.assertRaises(ValueError):normalize_native_scopes({'kalshi':[expanded[0],expanded[0]]})
        validate_probe(dict(policy=DIRECTED,sports=list(SPORTS),discovery_only=True,generations=1))


class OrdinaryTypedHTTP(unittest.IsolatedAsyncioTestCase):
    async def run_scope(self,cells,requests=48,venue='kalshi',market_failure=False):
        calls=[];rows=[];stops=[];value=spec(cells,requests)
        value['native_discovery']['native_scopes']={venue:cells}
        selected={};schedule=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
        async def deliver(writer):
            # The production server reads the request; its captured bytes are
            # available only after reply. Every supported response is synthetic.
            path,query=next_request[0]
            if path=='/v1/events':
                body=dict(events=[])
            elif path=='/trade-api/v2/events':
                ticker=query['series_ticker'][0];eid=ticker+'-SIMULATED'
                selected[eid]=ticker
                body=dict(events=[dict(event_ticker=eid,series_ticker=ticker,title='Detroit Lions at Buffalo Bills')],
                    milestones=[dict(category='Sports',type='football_game',start_date=schedule,related_event_tickers=[eid])],cursor='')
            else:
                eid=query['event_ticker'][0];ticker=selected[eid]
                body=dict(markets=[dict(ticker=ticker+'-SIMULATED-DET',event_ticker=eid,
                    title='Detroit',yes_sub_title='Detroit',no_sub_title='Not Detroit',status='active')],cursor='')
            writer.write(fixed(json.dumps(body).encode(),status=b'503 Service Unavailable')
                if market_failure and path=='/trade-api/v2/markets' else fixed(json.dumps(body).encode()));await writer.drain()
        # This server variant reads the exact ordinary request before preparing
        # a response, including the real selector query and its finite page size.
        tasks=set();next_request=[None]
        async def handle(reader,writer):
            task=asyncio.current_task();tasks.add(task)
            try:
                request=await reader.readuntil(b'\r\n\r\n');target=request.split(b' ')[1].decode();url=urlsplit(target)
                query=parse_qs(url.query);calls.append((url.path,query));next_request[0]=(url.path,query)
                await deliver(writer)
            finally:
                writer.close();await writer.wait_closed();tasks.discard(task)
        listener=await asyncio.start_server(handle,'127.0.0.1',0)
        endpoint='http://127.0.0.1:'+str(listener.sockets[0].getsockname()[1])
        s=SimpleNamespace(spec=value,credentials={},producers={v:SimpleNamespace(budget=PredictionBudget(value['prediction']),groups={})
            for v in ('kalshi','polymarket_us')},emit=lambda v,r:rows.append(dict(r,source=v)),request_stop=stops.append)
        d=Discovery(s);s.discovery=d;d.generation=1;d.selection_time=datetime.now(timezone.utc)
        endpoints={v:dict(rest=endpoint,ws=endpoint.replace('http:','ws:')+'/ws') for v in ('kalshi','polymarket_us')}
        try:
            with patch('app.collection.continuous.endpoints_for',return_value=endpoints):await d.venue(venue)
        finally:
            for client in d.clients.values():await client.aclose()
            listener.close();await listener.wait_closed()
            if tasks:await asyncio.gather(*tasks)
        return d,calls,rows,stops

    async def test_h1_selector_and_market_metadata_are_ordinary_retained_typed_receipts(self):
        cell=next(c for c in required_cells() if c['cell_id']=='NFL/first_half/spread')
        descriptor={k:v for k,v in cell.items() if k!='cell_id'}
        d,calls,rows,stops=await self.run_scope([descriptor])
        self.assertEqual(len(calls),2);self.assertFalse(stops)
        known={s['binding']['series_ticker'] for s in selectors_for(cell['cell_id'])}
        self.assertIn(calls[0][1]['series_ticker'][0],known)
        self.assertEqual(calls[0][1]['limit'],['1']);self.assertEqual(calls[1][1]['limit'],['5'])
        receipts=[r for r in rows if r['type']=='prediction_discovery_http']
        self.assertTrue(all(r['native_scope_policy']==POLICY and r['usable_metadata'] for r in receipts))
        self.assertTrue(all(r['native_scope_binding']['period']=='first_half' for r in receipts))
        decision=next(r for r in rows if r['type']=='native_scope_discovery')
        self.assertEqual(decision['cells'][cell['cell_id']]['metadata'],'complete_bounded_market_page')
        self.assertEqual(d.clients['kalshi'].budget.bytes,sum(r['resource_usage']['wire_bytes'] for r in receipts))
        # A native series/title does not supply oriented line or settlement terms.
        from app.collection.coverage import catalog
        result=catalog(d.pages,'kalshi',d.selection_time)
        excluded=result.get('excluded_catalog',{}).get('markets',[])
        self.assertTrue(excluded or any(m.get('exclusion') for m in result['markets']))

    async def test_non200_market_page_never_reports_complete_metadata(self):
        cell=next(c for c in required_cells() if c['cell_id']=='NFL/first_half/spread')
        descriptor={k:v for k,v in cell.items() if k!='cell_id'}
        d,calls,rows,stops=await self.run_scope([descriptor],market_failure=True)
        self.assertEqual(len(calls),2);self.assertFalse(stops)
        receipt=next(r for r in rows if r['type']=='prediction_discovery_http' and r['path']=='/trade-api/v2/markets')
        self.assertTrue(receipt['complete']);self.assertFalse(receipt['usable_metadata'])
        self.assertEqual(receipt['delivery_reason'],'native_http_status_503')
        decision=next(r for r in rows if r['type']=='native_scope_discovery')['cells'][cell['cell_id']]
        self.assertEqual(decision['metadata'],'query_failed')
        self.assertEqual(decision['metadata_reason'],'catalog_http_503')
        self.assertFalse(d.source_stops)

    async def test_budget_omissions_keep_every_requested_cell_and_do_not_invent_absence(self):
        d,calls,rows,stops=await self.run_scope('required-63-v1',requests=3)
        self.assertEqual(len(calls),3);self.assertFalse(stops)
        decision=next(r for r in rows if r['type']=='native_scope_discovery')
        self.assertEqual(len(decision['cells']),63)
        self.assertTrue(any(r['state']=='not_reached_request_allowance' for r in decision['cells'].values()))
        self.assertTrue(any(r['state']=='selector_unestablished' for r in decision['cells'].values()))
        self.assertFalse(d.source_stops)

    async def test_us_fair_game_queries_stop_before_generation_allowance(self):
        d,calls,rows,stops=await self.run_scope('required-63-v1',requests=3,venue='polymarket_us')
        self.assertEqual(len(calls),3);self.assertFalse(stops)
        self.assertEqual([c[1]['tagSlug'][0] for c in calls],['nfl','cfb','nba'])
        self.assertEqual([c[1]['limit'] for c in calls],[['20'],['5'],['5']])
        decision=next(r for r in rows if r['type']=='native_scope_discovery')
        self.assertEqual(len(decision['cells']),63)
        self.assertEqual(decision['cells']['NHL/full_game/moneyline']['state'],'not_reached_request_allowance')
        self.assertEqual(decision['cells']['NFL/first_half/spread']['state'],'documented_locator_awaiting_exact_game')
        self.assertFalse(d.source_stops)

    async def test_global_journal_or_storage_budget_is_never_a_local_query_gap(self):
        value=spec('required-63-v1');d=SimpleNamespace(session=SimpleNamespace(spec=value),generation=1,
            clients={'kalshi':SimpleNamespace(limits=value['prediction'],requests=0)},source_stops={},pages=[],
            pages_for=AsyncMock(side_effect=BudgetStop('observation_storage_cap')))
        with self.assertRaisesRegex(BudgetStop,'observation_storage_cap'):await scoped.discover(d,'kalshi')


if __name__=='__main__':unittest.main()
