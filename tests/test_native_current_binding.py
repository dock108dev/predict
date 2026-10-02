"""Offline current-binding controls over unchanged complete four-event NFL receipts.

Changed fields and a later receipt are constructed controls, never new provider
coverage. The original corpus and all prior interpretations remain unmodified.
"""
import base64
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.collection import coverage
from app.collection.continuous import Discovery
from app.collection.native_payload import TRANSPORT_CONTRACT
from app.collection.native_review_binding import apply, successor, revalidated_sources, POLICY, SOURCE_POLICY
from app.collection.native_review_contract import contract
from app.dashboard.native_reviews import records
from app.dashboard.session_projection import SessionProjection, stable, stamp
from tests.test_native_retained_coverage import FOLDER, projection, verified


def retained(source_settings=None):
    original = list(verified(FOLDER)['rows'])
    reviews, _ = records(projection())
    templates = deepcopy(reviews)
    for template in templates:
        for venue, source in template['sources'].items():
            source['semantic_review_contract'] = contract(venue,
                source['catalog_evidence']['event']['native_metadata'], source['metadata'])
        template.pop('sha256')
        template['sha256'] = stable(template)
    pages = deepcopy([r for r in original if r['type'] == 'prediction_discovery_http'])
    at = max(stamp(p['received_at']) for p in pages) + timedelta(seconds=1)
    spec = deepcopy(original[0]['spec'])
    spec.pop('two_source_qualification')
    spec.update(duration=180, native_transport=deepcopy(TRANSPORT_CONTRACT), native_review_records=templates)
    if source_settings is not None:
        spec['source_session'] = deepcopy(source_settings)
    p = SessionProjection()
    p.apply(dict(original[0], spec=spec))
    for page in pages:
        p.apply(page)
    emitted = []
    def emit(source, row):
        wrapped = dict(row, source=source, session_id=p.sid, observed_at=at.isoformat())
        emitted.append(wrapped)
        p.apply(wrapped)
    session = SimpleNamespace(spec=spec, sid=p.sid, projection=p, emit=emit)
    d = Discovery(session)
    d.pages = pages
    return d, p, templates, at, emitted, original


def catalogs(d, at):
    return {v: coverage.catalog(d.pages, v, at) for v in ('kalshi', 'polymarket_us')}


class CurrentBinding(unittest.TestCase):
    def test_retained_four_event_bindings_use_ordinary_projection(self):
        d, p, templates, at, emitted, original = retained()
        with patch('app.collection.continuous.now', return_value=at), patch('socket.socket.connect', side_effect=AssertionError('offline')):
            cats, markets = d.project()
        self.assertEqual(sum(r['type'] == 'native_review' for r in emitted), 8)
        self.assertEqual(len(cats['kalshi']['selection']['ids']), 8)
        self.assertTrue({t['sources']['polymarket_us']['market_id'] for t in templates}
                        <= set(cats['polymarket_us']['selection']['ids']))
        self.assertTrue(all(f['admitted'] for c in cats.values() for f in c.get('native_review_admission', [])))
        self.assertTrue(markets['kalshi'] and markets['polymarket_us'])
        selected, errors = records(p)
        self.assertFalse(errors)
        self.assertEqual(len(selected), 8)
        self.assertTrue(all(r['current_session_revalidation']['policy'] == POLICY for r in selected))
        inventory = dict(type='coverage_inventory', source='session', session_id=p.sid, observed_at=at.isoformat(),
                         generation=1, previous_generation=None, inventory=cats)
        p.apply(inventory)
        price_rows = []
        for row in original:
            if row['type'] in ('market_selected', 'prediction_book', 'source_health'):
                p.apply(row)
                price_rows.append(row)
        view = p.snapshot()
        self.assertEqual(len(view['games']), 8)
        self.assertFalse(view['native_comparison_review']['errors'])
        self.assertEqual({g['product_identity']['competition'] for g in view['games']}, {'NFL'})
        for old, new in zip(templates, selected):
            for venue, source in new['sources'].items():
                self.assertEqual(source['fee_review']['applicability'], old['applicability'])
        # Fresh process replays this explicit engineering interpretation from
        # unchanged source receipts and the newly generated immutable records.
        rows = [dict(original[0], spec=d.session.spec), *d.pages, *emitted, inventory, *price_rows]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'current-binding-control.json'
            path.write_text(json.dumps(rows))
            code = 'import json,sys; from app.dashboard.session_history import project_rows; from app.dashboard.session_projection import stable; print(stable(project_rows(json.load(open(sys.argv[1])))))'
            result = subprocess.run([sys.executable, '-c', code, str(path)], text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), stable(view))

    def test_material_unknown_state_and_identity_fail_only_affected_market(self):
        for failure in ('unknown', 'closed', 'identity', 'receipt', 'started', 'outcomes'):
            d, p, templates, at, emitted, _ = retained()
            cats = catalogs(d, at)
            t = templates[0]
            mid = t['sources']['kalshi']['market_id']
            market = next(m for m in cats['kalshi']['markets'] if m['id'] == mid)
            event = next(e for e in cats['kalshi']['events'] if e['id'] == market['event_id'])
            if failure == 'unknown':
                market['_native']['unreviewed_material_field'] = 'CONSTRUCTED CONTROL'
            elif failure == 'closed':
                market['_native']['status'] = 'closed'
                market['status'] = 'closed'
            elif failure == 'identity':
                market['event_id'] = 'CONSTRUCTED-OTHER-EVENT'
            elif failure == 'outcomes':
                market['sides'][0]['id'] = 'CONSTRUCTED-OTHER-OUTCOME'
            elif failure == 'started':
                event['scheduled_start'] = at.isoformat()
            else:
                for page in d.pages:
                    if page['body_sha256'] in {p['body_sha256'] for p in market['provenance']}:
                        page['complete'] = False
            apply(d, cats, at)
            self.assertTrue(market.get('subscription_evidence_exclusion'), failure)
            f = next(f for f in cats['kalshi']['native_review_admission'] if f['market_id'] == mid)
            self.assertFalse(f['admitted'], failure)
            if failure in ('closed', 'started'):
                self.assertTrue(f['complete_metadata'], failure)
                self.assertTrue(f['material_terms'], failure)
            self.assertTrue(any(x['admitted'] for x in cats['polymarket_us']['native_review_admission']), failure)
            self.assertLess(sum(r['review']['current_session_revalidation']['policy'] == POLICY for r in emitted), 8, failure)

    def test_future_or_unsupported_template_is_excluded_before_subscription(self):
        for change in ('future', 'unknown'):
            d, p, templates, at, emitted, _ = retained()
            first = deepcopy(templates[0])
            if change == 'future':
                first['applicability']['start'] = (at + timedelta(seconds=1)).isoformat()
            else:
                first['applicability']['status'] = 'UNKNOWN'
            first.pop('sha256'); first['sha256'] = stable(first)
            d.session.spec['native_review_records'] = [first]
            cats = catalogs(d, at)
            apply(d, cats, at)
            self.assertFalse(emitted, change)
            for venue in ('kalshi', 'polymarket_us'):
                finding = cats[venue]['native_review_admission'][0]
                self.assertTrue(finding['complete_metadata'], change)
                self.assertEqual(finding['reason'], 'selected_template_applicability_not_supported_yet')
                self.assertFalse(finding['admitted'], change)

    def test_current_successor_rejects_changed_terms_identity_scope_and_receipts(self):
        for failure in ('session', 'template', 'identity', 'outcomes', 'terms', 'fee', 'receipt', 'interval', 'template_hash'):
            d, p, _, at, emitted, _ = retained()
            apply(d, catalogs(d, at), at)
            value = deepcopy(emitted[0]['review'])
            parent = value['current_session_revalidation']['template_sha256']
            if failure == 'session':
                value['historical_session_id'] = 'CONSTRUCTED-OTHER-SESSION'
            elif failure == 'template':
                value['current_session_revalidation']['template_sha256'] = '0' * 64
            elif failure == 'identity':
                value['identity']['season'] = '2025'
            elif failure == 'outcomes':
                value['sources']['kalshi']['orientation_evidence']['basis'] = 'CONSTRUCTED altered orientation'
            elif failure == 'terms':
                value['sources']['kalshi']['semantic_review_contract']['market']['unreviewed_field'] = True
            elif failure == 'fee':
                value['sources']['kalshi']['fee_review']['applicability'] = deepcopy(value['applicability'])
            elif failure == 'interval':
                value['applicability']['end'] = (at + timedelta(days=1)).isoformat()
            elif failure == 'template_hash':
                value['sources']['kalshi']['reviewed_template_raw_hashes']['event'] = '0' * 64
            else:
                value['sources']['kalshi']['provenance'][0]['body_sha256'] = '0' * 64
            value.pop('sha256')
            value['sha256'] = stable(value)
            p.native_reviews[value['review_id'], value['revision']] = value
            accepted, errors = records(p)
            self.assertTrue(errors, failure)
            self.assertNotIn(value['sha256'], {r['sha256'] for r in accepted}, failure)
            self.assertIn(parent, {r['sha256'] for r in accepted}, failure)

    def test_new_generation_chains_receipt_revisions_without_overlap(self):
        d, p, templates, at, emitted, original = retained()
        cats = catalogs(d, at)
        apply(d, cats, at)
        apply(d, catalogs(d, at), at)
        self.assertEqual(len(emitted), 8)
        with patch('app.collection.continuous.now', return_value=at):
            cats, _ = d.project()
        p.apply(dict(type='coverage_inventory', source='session', session_id=p.sid, observed_at=at.isoformat(),
                     generation=1, previous_generation=None, inventory=cats))
        for row in original:
            if row['type'] in ('market_selected', 'prediction_book', 'source_health'):
                p.apply(row)
        self.assertEqual(len(p.snapshot()['games']), 8)
        page = next(p for p in d.pages if p['source'] == 'kalshi' and p['path'].endswith('/markets'))
        data = json.loads(base64.b64decode(page['body_b64']))
        # Constructed observation changes, never provider evidence or new rules.
        from decimal import Decimal
        for market in data['markets']:
            market['volume_fp'] = str(Decimal(market['volume_fp']) + 1)
        body = json.dumps(data).encode()
        receipt_at = stamp(p.last) + timedelta(seconds=1)
        page.update(body_b64=base64.b64encode(body).decode(), body_sha256=sha256(body).hexdigest(),
                    received_at=receipt_at.isoformat(), observed_at=receipt_at.isoformat())
        p.apply(page)
        later = receipt_at + timedelta(seconds=1)
        apply(d, catalogs(d, later), later)
        accepted, errors = records(p)
        self.assertFalse(errors)
        self.assertEqual(len(accepted), 8)
        self.assertTrue(any(r['revision'] == 3 for r in accepted))
        with patch('app.collection.continuous.now', return_value=later):
            cats, _ = d.project()
        p.apply(dict(type='coverage_inventory', source='session', session_id=p.sid, observed_at=later.isoformat(),
                     generation=2, previous_generation=1, inventory=cats))
        view = p.snapshot()
        self.assertFalse(view['native_comparison_review']['errors'])
        self.assertEqual(len(view['games']), 8)

    def test_identical_complete_body_refresh_keeps_original_current_anchor(self):
        d, p, templates, at, emitted, _ = retained()
        apply(d, catalogs(d, at), at)
        original_anchors = deepcopy(p.native_receipts)
        for page in d.pages:
            page.update(received_at=(at + timedelta(seconds=2)).isoformat(),
                        observed_at=(at + timedelta(seconds=2)).isoformat())
            p.apply(page)
        apply(d, catalogs(d, at + timedelta(seconds=3)), at + timedelta(seconds=3))
        self.assertEqual(len(emitted), 8)
        self.assertEqual(p.native_receipts, original_anchors)
        selected, errors = records(p)
        self.assertFalse(errors)
        for old, new in zip(templates, selected):
            for source in new['sources'].values():
                self.assertEqual(source['fee_review']['applicability'], old['applicability'])

    def test_unchanged_peer_recovery_renews_latest_partial_binding(self):
        for missing in ('kalshi', 'polymarket_us'):
            d, p, templates, at, emitted, _ = retained()
            pages = deepcopy(d.pages)
            apply(d, catalogs(d, at), at)
            d.pages = [page for page in d.pages if page['source'] != missing]
            apply(d, catalogs(d, at + timedelta(seconds=1)), at + timedelta(seconds=1))
            selected, errors = records(p)
            self.assertFalse(errors)
            self.assertTrue(all(revalidated_sources(r) == set(('kalshi', 'polymarket_us')) - {missing}
                                for r in selected))
            d.pages = pages
            apply(d, catalogs(d, at + timedelta(seconds=2)), at + timedelta(seconds=2))
            self.assertEqual(len(emitted), 24, missing)
            selected, errors = records(p)
            self.assertFalse(errors)
            self.assertTrue(all(revalidated_sources(r) == {'kalshi', 'polymarket_us'} for r in selected))
            self.assertTrue(all(r['revision'] == templates[0]['revision'] + 3 for r in selected))
            for old, new in zip(templates, selected):
                self.assertEqual(new['source_template_applicability'],
                                 {venue: old['applicability'] for venue in ('kalshi', 'polymarket_us')})
                for source in new['sources'].values():
                    self.assertEqual(source['fee_review']['applicability'], old['applicability'])
            apply(d, catalogs(d, at + timedelta(seconds=3)), at + timedelta(seconds=3))
            self.assertEqual(len(emitted), 24, missing)

    def test_missing_peer_metadata_keeps_independent_current_native_aggregate_join(self):
        from app.dashboard.price_comparison import comparisons
        from app.reference.aggregate import bind, VERSION
        from app.reference.odds_bindings import normalize_event
        from app.reference.source_correspondence import POLICY as CORRESPONDENCE
        from tests.test_source_session import settings
        for missing in ('kalshi', 'polymarket_us'):
            config = settings(correspondence_policy=CORRESPONDENCE)
            d, p, templates, at, emitted, original = retained(source_settings=config)
            healthy = next(v for v in ('kalshi', 'polymarket_us') if v != missing)
            d.pages = [page for page in d.pages if page['source'] != missing]
            with patch('app.collection.continuous.now', return_value=at):
                cats, _ = d.project()
            inventory = dict(type='coverage_inventory', source='session', session_id=p.sid, observed_at=at.isoformat(),
                             generation=1, previous_generation=None, inventory=cats)
            p.apply(inventory)
            price_rows = []
            for row in original:
                if stamp(row['observed_at']) > at + timedelta(seconds=1):
                    continue
                if row['type'] == 'market_selected' or row['type'] == 'source_health' and row['state'] == 'connected':
                    p.apply(row)
                    price_rows.append(row)
                elif row['type'] == 'prediction_book' and stamp(row['book']['raw']['received_at']) <= at + timedelta(seconds=1):
                    p.apply(row)
                    price_rows.append(row)
            selected, errors = records(p)
            self.assertFalse(errors)
            self.assertTrue(all(r['current_session_revalidation']['policy'] == SOURCE_POLICY for r in selected))
            self.assertTrue(all(revalidated_sources(r) == {healthy} for r in selected))
            for old, new in zip(templates, selected):
                self.assertEqual(new['sources'][missing], old['sources'][missing])
                self.assertEqual(new['source_template_applicability'][missing], old['applicability'])
            stamp_at = (at + timedelta(seconds=1)).isoformat()
            event = next(e for e in cats[healthy]['events'] if e['id'] == templates[0]['sources'][healthy]['event_id'])
            names = list(templates[0]['participants'].values())
            body = dict(id='CONSTRUCTED-AGGREGATE-CONTROL', sport_key='americanfootball_nfl',
                commence_time=event['scheduled_start'], home_team=names[0], away_team=names[1],
                bookmakers=[dict(key=b, markets=[dict(key='h2h', last_update=stamp_at,
                    outcomes=[dict(name=names[0], price='2.0'), dict(name=names[1], price='2.2')])])
                    for b in ('novig', 'prophetx')])
            aggregate = bind(normalize_event(json.dumps(body).encode(), 'NFL', stamp_at))
            aggregate_row = dict(type='aggregate_snapshot', session_id=p.sid, source='the_odds_api', observed_at=stamp_at,
                sport='NFL', event_id=body['id'], received_at=stamp_at, processing_at=stamp_at,
                response_sha256=aggregate[0]['response'], version=VERSION, records=aggregate)
            p.apply(aggregate_row)
            view = p.snapshot(now=stamp_at, mode='current')
            mixed = [r for r in comparisons(view, {}) if r.get('cross_source')]
            self.assertTrue(mixed, (missing, view['cross_source_mapping'],
                [(m['source_id'],m['market_id'],bool(m.get('native_book')),bool(m.get('quotes')),
                  (m.get('health') or {}).get('state'),len(m.get('native_review_assessments',[])),m.get('native_review_exclusion'))
                 for m in view['market_catalog'] if m['source_id']==healthy]))
            self.assertFalse(any(g.get('native_raw') for g in view['games']))
            self.assertEqual({l['venue'] for r in mixed for l in r['legs']}, {healthy, 'novig', 'prophetx'})
            self.assertTrue(all(r['net'] is None and r['ev'] is None for r in mixed))
            # Historical peer receipts/books were deliberately left present;
            # membership rejects their use for both paired and mixed prices.
            self.assertTrue(all(missing not in revalidated_sources(r['native_review'])
                for values in view['rows_by_game'].values() for r in values if 'source_correspondence' in r))
            replay = [dict(original[0],spec=p.spec),
                *[r for r in original if r['type']=='prediction_discovery_http'], *emitted, inventory,
                *price_rows, aggregate_row]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'independent-current-control.json'
                path.write_text(json.dumps(replay))
                code = 'import json,sys; from app.dashboard.session_history import project_rows; from app.dashboard.session_projection import stable; print(stable(project_rows(json.load(open(sys.argv[1])))))'
                result = subprocess.run([sys.executable,'-c',code,str(path)],text=True,capture_output=True,check=True)
                self.assertEqual(result.stdout.strip(),stable(p.snapshot()),missing)

    def test_partial_then_paired_renewal_keeps_original_fee_scopes_and_rejects_tampering(self):
        d, p, templates, at, _, _ = retained()
        cats = catalogs(d, at)
        first = successor(templates[0], cats, p.sid, at,
                          at + timedelta(seconds=120), templates[0]['revision'] + 1, {'kalshi'})
        p.apply(dict(type='native_review', source='session', session_id=p.sid,
                     observed_at=at.isoformat(), review=first))
        second = successor(first, cats, p.sid, at + timedelta(seconds=1),
                           at + timedelta(seconds=120), first['revision'] + 1)
        p.apply(dict(type='native_review', source='session', session_id=p.sid,
                     observed_at=(at + timedelta(seconds=1)).isoformat(), review=second))
        selected, errors = records(p)
        self.assertFalse(errors)
        self.assertIn(second['sha256'], {r['sha256'] for r in selected})
        self.assertEqual(revalidated_sources(second), {'kalshi', 'polymarket_us'})
        for source in second['sources'].values():
            self.assertEqual(source['fee_review']['applicability'], templates[0]['applicability'])
        for change in ('subset', 'unrenewed', 'scope'):
            bad = deepcopy(first)
            if change == 'subset':
                bad['current_revalidated_sources'] = ['kalshi', 'polymarket_us']
            elif change == 'unrenewed':
                bad['sources']['polymarket_us']['orientation_evidence']['basis'] = 'CONSTRUCTED control'
            else:
                bad['source_template_applicability']['polymarket_us'] = first['applicability']
            bad.pop('sha256'); bad['sha256'] = stable(bad)
            from app.collection.native_review_binding import verify_successor
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                verify_successor(bad, templates[0], p.sid)

    def test_legacy_specs_do_not_select_new_policy(self):
        for change in ('absent', 'policy', 'type', 'historical'):
            d, p, _, at, emitted, _ = retained()
            if change == 'absent':
                d.session.spec.pop('native_transport')
            elif change == 'policy':
                d.session.spec['native_transport']['policy'] = 'CONSTRUCTED-OTHER-TRANSPORT'
            elif change == 'type':
                d.session.spec['native_transport']['response_wire_bytes'] = float(
                    d.session.spec['native_transport']['response_wire_bytes'])
            else:
                d.session.spec['two_source_qualification'] = {'CONSTRUCTED': 'old scope'}
            apply(d, catalogs(d, at), at)
            self.assertFalse(emitted, change)

    def test_current_review_expires_at_prestart_margin_without_extending_fees(self):
        from app.dashboard.native_book_comparison import connect_one
        d, p, templates, at, _, _ = retained()
        cats = catalogs(d, at)
        template = templates[0]
        event_id = template['sources']['kalshi']['event_id']
        event = next(e for e in cats['kalshi']['events'] if e['id'] == event_id)
        boundary = stamp(event['scheduled_start']) - timedelta(minutes=5)
        earlier = boundary - timedelta(seconds=1)
        current = successor(template, cats, p.sid, earlier,
                            earlier + timedelta(seconds=180), template['revision'] + 1)
        self.assertEqual(stamp(current['applicability']['end']), boundary)
        for venue, source in current['sources'].items():
            self.assertEqual(source['fee_review']['applicability'], template['applicability'])
        # Constructed later clock, unchanged real metadata. A provider that has
        # not published its phase change cannot keep this binding eligible.
        p.inventory = deepcopy(cats)
        for catalog in p.inventory.values():
            for row in catalog['events'] + catalog['markets']:
                row['native_metadata'] = deepcopy(row['_native'])
        def empty_view():
            return dict(games=[], points={}, rows_by_game={}, sources=[], market_catalog=[],
                native_comparison_review=dict(assessments={}, records={}, reviews={}, rejections={}))
        before = empty_view()
        self.assertIsNone(connect_one(p, before, earlier.isoformat(), current))
        exact = empty_view()
        rejection = connect_one(p, exact, boundary.isoformat(), current)
        self.assertEqual(set(rejection), {'kalshi', 'polymarket_us'})
        self.assertTrue(all('prestart applicability margin' in value for value in rejection.values()))
        self.assertFalse(exact['games'])
        after = empty_view()
        connect_one(p, after, (boundary + timedelta(seconds=1)).isoformat(), current)
        self.assertEqual(after['native_comparison_review']['assessments'][current['sha256']]['status'],
                         'OUTSIDE_REVIEW_INTERVAL')

    def test_current_entry_cannot_use_original_fees_outside_current_interval_or_membership(self):
        from decimal import Decimal
        from app.dashboard.native_book_comparison import entry
        d, p, templates, at, _, _ = retained()
        current = successor(templates[0], catalogs(d, at), p.sid, at,
                            at + timedelta(seconds=120), templates[0]['revision'] + 1, {'kalshi'})
        for venue, when in (('kalshi', at - timedelta(seconds=1)),
                            ('kalshi', at + timedelta(seconds=120)),
                            ('polymarket_us', at + timedelta(seconds=1))):
            source = dict(native_review=current,native_review_version='native-book-comparison-4',
                event_id=current['sources'][venue]['event_id'],market_id=current['sources'][venue]['market_id'])
            value = entry(dict(venue=venue,levels=[dict(price='0.50',quantity='5')]),
                          Decimal('1'),when.isoformat(),dict(rules=current['sha256']),source)
            self.assertEqual(value['fee_status'],'UNKNOWN',(venue,when))
            self.assertTrue(value['reason'],(venue,when))
            self.assertIsNone(value['upper'])
            self.assertIsNone(value['net'])


if __name__ == '__main__':
    unittest.main()
