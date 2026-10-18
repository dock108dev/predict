"""Disposable source payload controls; no acquisition or admission authority."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace
import unittest

from app.collection.native_identity_trace import identity_trace, MAX_BYTES
from tests.multisport_fixtures import SPORTS, source_case


def receipt(venue, path, body):
    raw = json.dumps(body).encode()
    return dict(source=venue, path=path, params={}, status=200, complete=True,
        received_at='2026-10-17T15:00:00Z', body_b64=base64.b64encode(raw).decode(),
        body_sha256=sha256(raw).hexdigest())


def records(venue, cases, *, singular=False):
    events, markets, pages = [], [], []
    for case in cases:
        native = deepcopy(case['events'][venue]); market = deepcopy(case['markets'][venue])
        eid = native.get('event_ticker', native.get('id'))
        mid = market.get('ticker', market.get('id'))
        if venue == 'kalshi':
            body = dict(events=[native], milestones=[deepcopy(case['milestone'])])
            ep = receipt(venue, '/trade-api/v2/events', body)
            mp = receipt(venue, '/trade-api/v2/markets', dict(markets=[market]))
        elif singular:
            native.pop('markets', None)
            ep = receipt(venue, '/v1/event/id/'+eid, dict(event=native))
            mp = receipt(venue, '/v1/market/id/'+mid, dict(market=market))
        else:
            ep = receipt(venue, '/v1/events', dict(events=[native])); mp = ep
        proof = lambda p: {k: p[k] for k in ('path', 'received_at', 'body_sha256')}
        events.append(dict(id=eid, competition=case['league'], _native=native,
            provenance=[proof(ep)], season=None, stage=None))
        markets.append(dict(id=mid, event_id=eid, _native=market, provenance=[proof(mp)],
            v1_raw_binding=dict(status='IDENTITY_BLOCKED',
                blockers=['Exact game identity facts unavailable: season, stage'])))
        pages.extend([ep] if ep is mp else [ep, mp])
    return dict(events=events, markets=markets), pages


def field_set(trace, section, name):
    return trace['field_sets'][section[name+'_ref']]


def page_proof(trace, section):
    return trace['page_proofs'][section['page_ref']]


class IdentityTrace(unittest.TestCase):
    def test_six_leagues_preserve_raw_missingness_roles_and_exact_proof(self):
        cases = [source_case(s, 'moneyline', 'trace-'+s) for s in SPORTS]
        for case in cases:
            native = case['events']['polymarket_us']
            native.pop('season'); native.pop('stage')
            native['rescheduledFromGameId'] = None
        catalog, pages = records('polymarket_us', cases)
        before = deepcopy((catalog, pages))
        trace = identity_trace(catalog, 'polymarket_us', pages=pages, pass_number=3)
        self.assertLessEqual(len(json.dumps(trace, separators=(',', ':'), ensure_ascii=False).encode()), MAX_BYTES)
        self.assertEqual({s['league'] for s in trace['samples']}, set(SPORTS))
        for sample in trace['samples']:
            self.assertNotIn('season', sample['event']['values'])
            self.assertIn('season', field_set(trace, sample['event'], 'missing_fields'))
            self.assertIn('stage', field_set(trace, sample['event'], 'missing_fields'))
            self.assertIsNone(sample['event']['values']['rescheduledFromGameId'])
            self.assertNotIn('rescheduledFromGameId', field_set(trace, sample['event'], 'missing_fields'))
            self.assertEqual(sample['event_proof']['row_path'], '/events/0')
            self.assertEqual(sample['market_proof']['row_path'], '/events/0/markets/0')
            self.assertIn(page_proof(trace, sample['event_proof'])['body_sha256'], {p['body_sha256'] for p in pages})
            teams = [trace['team_facts'][t['trace_team_ref']] for t in sample['event']['values']['teams']]
            self.assertEqual({t['ordering'] for t in teams}, {'home', 'away'})
            sides = sample['market']['values']['marketSides']
            self.assertEqual({s['long'] for s in sides}, {True, False})
        self.assertEqual((catalog, pages), before)

    def test_blocked_selected_priority_and_rotating_peers(self):
        cases = [source_case('NBA', 'moneyline', str(i)) for i in range(4)]
        catalog, pages = records('polymarket_us', cases)
        catalog['markets'][0]['v1_raw_binding']['status'] = 'BOUND_RAW_PREDICATE'
        selected = [catalog['markets'][0]['id']]
        selected_events = [catalog['events'][1]['id'], catalog['events'][2]['id']]
        found = set()
        for number in range(4):
            trace = identity_trace(catalog, 'polymarket_us', pages=pages, selected=selected,
                selected_events=selected_events, pass_number=number)
            sample = trace['samples'][0]
            self.assertTrue(sample['blocked']); self.assertTrue(sample['event_selected'])
            found.add(sample['event_id'])
        self.assertEqual(found, set(selected_events))

    def test_linked_milestone_typed_source_identifiers_are_not_discarded(self):
        case = source_case('NBA', 'spread', 'linked')
        case['milestone']['source_ids'] = {'source_3_id': 'uuid-game', 'sportradar': {'id': 'sr:match:12'}}
        case['milestone']['details']['source_id'] = 'nested-own-id'
        case['milestone']['details']['source_ids'] = [{'provider': 'sportradar', 'id': 'nested-provider-id'}]
        catalog, pages = records('kalshi', [case])
        body = json.loads(base64.b64decode(pages[0]['body_b64']))
        body['milestones'].append(dict(case['milestone'], id='unrelated', related_event_tickers=['other']))
        pages[0] = receipt('kalshi', '/trade-api/v2/events', body)
        catalog['events'][0]['provenance'][0]['body_sha256'] = pages[0]['body_sha256']
        trace = identity_trace(catalog, 'kalshi', pages=pages)
        sample = trace['samples'][0]; facts = sample['linked_milestones']
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['values']['source_ids'], case['milestone']['source_ids'])
        self.assertEqual(facts[0]['details']['values']['source_id'], 'nested-own-id')
        self.assertEqual(facts[0]['details']['values']['source_ids'], case['milestone']['details']['source_ids'])
        self.assertEqual(facts[0]['proof']['row_path'], '/milestones/0')
        self.assertEqual(page_proof(trace, facts[0]['proof'])['body_sha256'], pages[0]['body_sha256'])
        self.assertNotIn('season', sample['event']['values'])
        self.assertIn('season', facts[0]['details']['values'])

    def test_singular_routes_keep_original_json_paths(self):
        catalog, pages = records('polymarket_us', [source_case('MLB', 'spread', 'singular')], singular=True)
        sample = identity_trace(catalog, 'polymarket_us', pages=pages)['samples'][0]
        self.assertEqual(sample['event_proof']['row_path'], '/event')
        self.assertEqual(sample['market_proof']['row_path'], '/market')

    def test_explicit_flat_season_and_source_fields_keep_own_values(self):
        case = source_case('NBA', 'moneyline', 'flat-own-context')
        detail = case['milestone']['details']
        detail.pop('season')
        detail.update(season_type='AUTHORED_SOURCE_ENUM', season_year=2026,
            source={'name': 'AUTHORED_NAMESPACE', 'id': 'own-source-id'})
        catalog, pages = records('kalshi', [case])
        trace = identity_trace(catalog, 'kalshi', pages=pages)
        sample = trace['samples'][0]; facts = sample['linked_milestones'][0]['details']
        for key in ('season_type', 'season_year', 'source'):
            self.assertEqual(facts['values'][key], detail[key])
            self.assertIn(key, field_set(trace, facts, 'native_keys'))
            self.assertNotIn(key, field_set(trace, facts, 'missing_fields'))
        self.assertIn('season', field_set(trace, facts, 'missing_fields'))
        self.assertIsNone(sample['normalized']['season'])
        self.assertIsNone(sample['normalized']['stage'])

    def test_separate_milestone_receipt_has_its_own_hash_and_path(self):
        case = source_case('NHL', 'moneyline', 'external-milestone')
        catalog, pages = records('kalshi', [case])
        native = case['events']['kalshi']
        pages[0] = receipt('kalshi', '/trade-api/v2/events', dict(events=[native]))
        catalog['events'][0]['provenance'][0]['body_sha256'] = pages[0]['body_sha256']
        extra = receipt('kalshi', '/trade-api/v2/milestones', dict(milestones=[case['milestone']]))
        pages.append(extra)
        trace = identity_trace(catalog, 'kalshi', pages=pages)
        facts = trace['samples'][0]['linked_milestones'][0]
        self.assertEqual(page_proof(trace, facts['proof'])['body_sha256'], extra['body_sha256'])
        self.assertEqual(facts['proof']['row_path'], '/milestones/0')

    def test_missing_or_corrupted_receipt_is_explicit_catalog_fallback(self):
        catalog, pages = records('polymarket_us', [source_case('NCAAF', 'moneyline', 'no-proof')])
        pages[0]['body_sha256'] = '0'*64
        for supplied in ([], pages):
            sample = identity_trace(catalog, 'polymarket_us', pages=supplied)['samples'][0]
            self.assertTrue(sample['event_proof']['raw_page_missing'])
            self.assertEqual(sample['event_proof']['lookup'], 'catalog_native_metadata')

    def test_long_values_and_large_catalog_remain_bounded_without_false_prefixes(self):
        cases = [source_case(s, 'moneyline', 'oversized-'+s) for s in SPORTS]
        for case in cases:
            native = case['events']['polymarket_us']
            native['title'] = 'huge-value-'*2000
            native['credential_secret'] = 'NEVER_COPY_THIS_VALUE'
            native['teams'][0]['credential_secret'] = 'NEVER_COPY_THIS_VALUE'
        catalog, pages = records('polymarket_us', cases)
        for cap in (2048, MAX_BYTES):
            trace = identity_trace(catalog, 'polymarket_us', pages=pages, byte_cap=cap)
            encoded = json.dumps(trace, separators=(',', ':'), ensure_ascii=False).encode()
            self.assertLessEqual(len(encoded), cap)
            self.assertLessEqual(len(json.dumps(trace, separators=(',', ':')).encode()), cap)
            self.assertNotIn(b'NEVER_COPY_THIS_VALUE', encoded)
            for sample in trace['samples']:
                if 'event' in sample:
                    value = sample['event']['values']['title']
                    self.assertTrue(value['truncated']); self.assertEqual(value['sha256'], sha256(('huge-value-'*2000).encode()).hexdigest())
            self.assertTrue(trace['truncated'] or all(s.get('event', {}).get('values', {}).get('title', {}).get('truncated') for s in trace['samples']))

    def test_two_maximum_diagnostics_fit_actual_runtime_status_write(self):
        from app.collection.current_admin import issue
        from app.collection.current_native import identity_diagnostics
        from app.collection.current_policy import DEFAULT
        from app.collection.current_service import CurrentService
        from app.collection.runtime_status import RuntimeState, STATUS_BYTES
        service = CurrentService(config=dict(DEFAULT, enabled=False, aggregate_enabled=False,
            native_sports=list(SPORTS)))
        for venue in ('kalshi', 'polymarket_us'):
            catalog, pages = records(venue, [source_case(s, 'moneyline', 'status-'+s) for s in SPORTS])
            trace = identity_trace(catalog, venue, pages=pages)
            blocked = [dict(id='market-'+str(i), v1_raw_binding=dict(status='IDENTITY_BLOCKED',
                blockers=['Bounded authored admission reason '*8]*6)) for i in range(200)]
            trace_size = len(json.dumps(trace, separators=(',', ':')).encode())
            entries, omitted = identity_diagnostics(dict(events=[], markets=blocked),
                byte_cap=24*1024-trace_size-256)
            self.assertLessEqual(trace_size+len(json.dumps(entries, separators=(',', ':')).encode()), 24*1024)
            self.assertGreater(len(json.dumps(entries)), 10*1024)
            findings = [dict(sport=s, family=f, state='budget_limited',
                reason='shared_event_or_metadata_cap', queried=True, selected=['selected-1', 'selected-2'],
                discovered=5, next_position='authored-cursor-'*5)
                for s in SPORTS for f in ('moneyline', 'spread', 'total')]
            service.workers[venue] = SimpleNamespace(metrics=dict(identity_exclusions=entries,
                identity_exclusions_omitted=omitted, native_identity_trace=trace, coverage=findings))
        service.issues = [issue(service, 'kalshi', 'identity_exclusion', 'native_identity_exclusion') for _ in range(32)]
        class Database:
            def __init__(self): self.calls = []
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, statement, params): self.calls.append((statement, params))
        database = Database()
        RuntimeState(connector=lambda: database).write(service)
        self.assertEqual(len(database.calls), 1)
        stored = database.calls[0][1][8].obj
        self.assertLessEqual(len(json.dumps(stored, separators=(',', ':')).encode()), STATUS_BYTES)
        self.assertEqual(len(stored['issues']), 32)
        self.assertEqual(set(stored['metrics']), {'kalshi', 'polymarket_us'})

    def test_non_ascii_source_values_respect_persisted_ascii_byte_bound(self):
        cases = [source_case(s, 'moneyline', 'unicode-'+s) for s in SPORTS]
        for case in cases:
            for team in case['events']['polymarket_us']['teams']:
                team['name'] = 'é'*120; team['safeName'] = '球'*90
            case['events']['polymarket_us']['title'] = 'é'*150
        catalog, pages = records('polymarket_us', cases)
        trace = identity_trace(catalog, 'polymarket_us', pages=pages)
        self.assertLessEqual(len(json.dumps(trace, separators=(',', ':')).encode()), MAX_BYTES)
        self.assertLessEqual(len(json.dumps(trace, separators=(',', ':'), ensure_ascii=False).encode()), MAX_BYTES)


if __name__ == '__main__':
    unittest.main()
