"""Read-only batching preserves exact originals, membership and financial IDs."""
import base64
import json
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from app.collection.current_aggregate_admission import admit
from app.comparison.combined_inputs import build, _ADMITTED_CACHE
from app.dashboard.current_normalized import catalog_from_normalized
from app.storage.comparison_board import ReadContext, catalog, discover, source_guard
from app.storage.store import encoded, hashed
from tests.test_ev09_n01 import envelopes, AT, SELECTED


def frame():
    originals=envelopes();projections={}
    for item in sorted(originals,key=lambda e:e['record']['retained_at']):
        r=item['record'];v=r['value'];source=r['source'];kind=r['kind'];values=[]
        if kind=='aggregate_batch':
            body=base64.b64decode(v['body_b64'])
            for venue in ('novig','prophetx','pinnacle'):
                for value in admit(body,v['sport'],v['received_at'],venue=venue):
                    q=value['quote'];s=q['source']
                    values.append(('quote',hashed([q['venue'],s['native_event_id'],s['native_market_id'],s['native_outcome_id']]),value))
        elif kind=='catalog':values=[('catalog',source,v['inventory'])]
        elif kind=='admitted_books':
            for value in v['observations']:
                ref=value['book']['raw']['ref'];values.append(('book',ref['event_id']+':'+ref['market_id'],value))
        for projected_kind,native,value in values:
            projections[(source,projected_kind,native)]=dict(source=source,kind=projected_kind,native_id=native,
                envelope_id=item['id'],payload=encoded(value).decode())
    rows=[projections[k] for k in sorted(projections)]
    used={r['envelope_id'] for r in rows}
    return [e for e in originals if e['id'] in used],{k:r['envelope_id'] for k,r in projections.items()},rows


class RetainedStore:
    def __init__(self):self.frame=frame();self.reads=0
    def combined_read_capture(self):
        self.reads+=1
        return deepcopy(self.frame)


class ComparisonReadContext(TestCase):
    def setUp(self):
        _ADMITTED_CACHE.clear();self.store=RetainedStore()

    def test_bound_inner_winner_remains_a_guard_dependency_despite_outer_disagreement(self):
        row=next(r for r in self.store.frame[2] if r['source']=='kalshi' and r['kind']=='catalog')
        value=json.loads(row['payload'])
        market=next(m for m in value['markets'] if m['market_type']=='moneyline')
        self.assertEqual(market['v1_raw_binding']['identity']['family'],'moneyline')
        market['market_type']='spread';row['payload']=encoded(value).decode()
        context=ReadContext(self.store,at=AT)
        members=next(b['members'] for b in context.catalog_bundles() if list(SELECTED) in b['members'])
        guard=context.guard(members)
        book=next(r for r in self.store.frame[2] if r['source']=='kalshi' and r['kind']=='book')
        changed=json.loads(book['payload']);changed['book']['raw']['exchange_at']='2026-10-14T01:15:10+00:00'
        book['payload']=encoded(changed).decode()
        self.assertNotEqual(ReadContext(self.store,at=AT).guard(members),guard)

    def legacy(self):
        originals,associations,_=self.store.frame
        return build(originals,at=AT,associations=associations)

    def test_slim_catalog_keeps_exact_occurrences_and_native_alternatives(self):
        expected=catalog(self.legacy());context=ReadContext(self.store,at=AT)
        with patch('app.comparison.source_inputs.produce',side_effect=AssertionError('Catalog must not price/profile')):
            actual=context.catalog()
        for games in (actual['games'],expected['games']):
            for game in games:game.pop('input_version')
            games.sort(key=lambda game:game['game_key'])
        self.assertEqual(actual,expected)
        self.assertEqual(self.store.reads,1)

    def test_selected_hydration_equals_legacy_full_original_and_financial_inputs(self):
        expected=next(b for b in self.legacy() if list(SELECTED) in b['members'])
        context=ReadContext(self.store,at=AT);context.catalog()
        with patch('app.comparison.combined_inputs.catalog_from_normalized',wraps=catalog_from_normalized) as hydration:
            actual=discover(self.store,context=context,game=expected['game_key'])
            again=discover(self.store,context=context,selected=SELECTED)
        self.assertEqual(actual,[expected]);self.assertEqual(again,actual)
        self.assertEqual(hydration.call_count,1)
        self.assertEqual(self.store.reads,1)

    def test_selected_no_cache_hydration_keeps_exact_inputs_and_releases_full_bundles(self):
        expected=next(b for b in self.legacy() if list(SELECTED) in b['members'])
        context=ReadContext(self.store,at=AT);context.catalog()
        with patch('app.comparison.combined_inputs.catalog_from_normalized',wraps=catalog_from_normalized) as hydration:
            first=discover(self.store,context=context,game=expected['game_key'],cache=False)
            second=discover(self.store,context=context,game=expected['game_key'],cache=False)
        self.assertEqual(first,[expected]);self.assertEqual(second,first)
        self.assertEqual(context._bundles,{})
        self.assertEqual(hydration.call_count,2)
        self.assertEqual(self.store.reads,1)

    def test_one_context_resolves_once_and_guard_never_rediscovers(self):
        from app.comparison.occurrence_matching import OccurrenceResolver
        original=OccurrenceResolver.resolve
        calls=[]
        def resolve(instance,records,**kwargs):
            calls.append(len(records));return original(instance,records,**kwargs)
        with patch.object(OccurrenceResolver,'resolve',resolve):
            context=ReadContext(self.store,at=AT);bundles=discover(self.store,context=context)
            for b in bundles:
                with patch('app.storage.comparison_board.discover',side_effect=AssertionError('Guard must not rediscover')):
                    first=source_guard(self.store,b['members'],context=context)
                    self.assertEqual(first,source_guard(self.store,b['members'],context=context))
        self.assertEqual(len(calls),1);self.assertEqual(self.store.reads,1)

    def test_current_association_change_gets_a_fresh_guard_despite_immutable_cache(self):
        before=ReadContext(self.store,at=AT)
        members=next(b['members'] for b in before.catalog_bundles() if list(SELECTED) in b['members'])
        guard=before.guard(members)
        originals,associations,rows=self.store.frame
        removed=next(r for r in rows if r['source']=='kalshi' and r['kind']=='book')
        rows.remove(removed);associations.pop((removed['source'],removed['kind'],removed['native_id']))
        after=ReadContext(self.store,at=AT)
        self.assertNotEqual(after.guard(members),guard)
        self.assertEqual(before.guard(members),guard)

    def test_missing_book_is_not_reintroduced_from_a_full_original_receipt(self):
        originals,associations,rows=self.store.frame
        rows[:]=[r for r in rows if not (r['source']=='the_odds_api' and
            json.loads(r['payload'])['quote']['venue']=='pinnacle')]
        associations.clear();associations.update({(r['source'],r['kind'],r['native_id']):r['envelope_id'] for r in rows})
        context=ReadContext(self.store,at=AT);bundle=discover(self.store,context=context,selected=SELECTED)[0]
        self.assertIsNone(bundle['benchmark'])
        self.assertEqual(bundle['benchmark_reason'],'selected_benchmark_two_originals_absent')
        self.assertNotIn('pinnacle',{r['quote']['venue'] for r in bundle['records']})

    def test_projection_price_tampering_refuses_even_with_a_warm_receipt_cache(self):
        ReadContext(self.store,at=AT)
        row=next(r for r in self.store.frame[2] if r['source']=='the_odds_api' and r['kind']=='quote'
            and json.loads(r['payload'])['event']['competition']=='NFL'
            and json.loads(r['payload'])['market_identity']['family']=='moneyline')
        value=json.loads(row['payload']);value['quote']['original']['value']='9.99';row['payload']=encoded(value).decode()
        with self.assertRaisesRegex(ValueError,'projection_original_conflict'):ReadContext(self.store,at=AT)

    def test_bad_receipt_hash_cannot_use_a_cached_normalization(self):
        ReadContext(self.store,at=AT)
        original=next(e for e in self.store.frame[0] if e['record']['kind']=='aggregate_batch')
        original['record']['value']['body_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'envelope_hash_conflict'):ReadContext(self.store,at=AT)

    def test_event_filter_preserves_full_original_receipt_and_clocks(self):
        original=next(e for e in envelopes() if e['record']['kind']=='aggregate_batch')['record']['value']
        body=base64.b64decode(original['body_b64']);rows=admit(body,'NFL',original['received_at'],venue='novig')
        expected=[r for r in rows if r['quote']['source']['native_event_id']==SELECTED[1]]
        self.assertEqual(admit(body,'NFL',original['received_at'],venue='novig',event_ids=[SELECTED[1]]),expected)

    def test_cache_objects_cannot_mutate_later_read_financial_inputs(self):
        first=ReadContext(self.store,at=AT);a=discover(self.store,context=first,selected=SELECTED)[0]
        expected=deepcopy(a);a['records'][0]['quote']['original']['value']='changed by caller'
        second=ReadContext(self.store,at=AT)
        self.assertEqual(discover(self.store,context=second,selected=SELECTED)[0],expected)

    def test_spread_total_changes_do_not_revoke_a_winner_guard(self):
        context=ReadContext(self.store,at=AT)
        members=next(b['members'] for b in context.catalog_bundles() if list(SELECTED) in b['members'])
        expected=context.guard(members)
        rows=self.store.frame[2];changed=0
        for row in rows:
            if row['source']!='the_odds_api' or row['kind']!='quote':continue
            value=json.loads(row['payload'])
            if value['quote']['source']['native_event_id']==SELECTED[1] and value['market_identity']['family'] in ('spread','total'):
                value['quote']['original']['value']='9.99';row['payload']=encoded(value).decode();changed+=1
        self.assertGreater(changed,0)
        self.assertEqual(ReadContext(self.store,at=AT).guard(members),expected)

    def test_native_unknown_or_nonwinner_book_does_not_revoke_winners(self):
        context=ReadContext(self.store,at=AT)
        members=next(b['members'] for b in context.catalog_bundles() if list(SELECTED) in b['members'])
        expected=context.guard(members)
        originals,associations,rows=self.store.frame
        row=deepcopy(next(r for r in rows if r['source']=='kalshi' and r['kind']=='book'))
        value=json.loads(row['payload']);ref=value['book']['raw']['ref'];ref['market_id']='nonwinner-market'
        row['native_id']=ref['event_id']+':'+ref['market_id'];row['payload']=encoded(value).decode()
        rows.append(row);rows.sort(key=lambda r:(r['source'],r['kind'],r['native_id']))
        associations[(row['source'],row['kind'],row['native_id'])]=row['envelope_id']
        self.assertEqual(ReadContext(self.store,at=AT).guard(members),expected)

    def test_native_winner_clock_and_predicate_changes_still_revoke(self):
        context=ReadContext(self.store,at=AT)
        members=next(b['members'] for b in context.catalog_bundles() if list(SELECTED) in b['members'])
        expected=context.guard(members)
        for kind in ('book','catalog'):
            original=deepcopy(self.store.frame)
            row=next(r for r in self.store.frame[2] if r['source']=='kalshi' and r['kind']==kind)
            value=json.loads(row['payload'])
            if kind=='book':value['book']['raw']['exchange_at']='2026-10-14T01:15:10+00:00'
            else:
                market=next(m for m in value['markets'] if m['market_type']=='moneyline')
                market['terms']['description']='Authored different exceptional settlement predicate'
            row['payload']=encoded(value).decode()
            self.assertNotEqual(ReadContext(self.store,at=AT).guard(members),expected)
            self.store.frame=original
