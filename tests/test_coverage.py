"""D1 synthetic boundaries and read-only retained-catalog reconciliation."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from app.collection.coverage import build, load_pages, stamp, traversal, main

AS_OF=stamp('2026-09-16T16:00:00Z')
START='2026-09-20T17:00:00Z'
SOURCE=dict(path='isolated fixture',sha256='synthetic',classification='synthetic')


def page(venue, data, *, field='events', position=None, limit=2, eid=None):
    q=dict(limit=limit)
    if venue=='kalshi':
        q['cursor']=position or ''
        if field=='events':q['series_ticker']='KXNFLGAME'
        else:q['event_ticker']=eid
    else:q.update(offset=position or 0,tagSlug='nfl')
    raw=json.dumps(data).encode()
    return dict(source=venue,path='/'+field,params=q,received_at='2026-09-16T14:00:00Z',
                status=200,complete=True,body_b64=base64.b64encode(raw).decode(),body_sha256=sha256(raw).hexdigest())


def ke(eid='k',title='Detroit vs Buffalo',start=START):
    return dict(event_ticker=eid,series_ticker='KXNFLGAME',title=title),dict(category='Sports',type='football_game',start_date=start,related_event_tickers=[eid])


def km(mid='km',eid='k'):
    return dict(ticker=mid,event_ticker=eid,title='Detroit wins',yes_sub_title='Detroit',no_sub_title='Not Detroit',status='active')


def pm(mid='pm'):
    return dict(id=mid,question='Winner',marketType='moneyline',sportsMarketType='football_team_full_game_winner',status='OPEN',gameStartTime=START,
                marketSides=[dict(id=mid+'L',long=True,description='Detroit'),dict(id=mid+'S',long=False,description='Buffalo')])


def pe(eid='p',teams=('Detroit Lions','Buffalo Bills')):
    return dict(id=eid,title='fixture',startTime=START,teams=[dict(name=n,league='nfl') for n in teams],period='NS',markets=[pm(eid+'m')])


def fixture():
    e,m=ke()
    return [page('kalshi',dict(events=[e],milestones=[m],cursor='')),
            page('kalshi',dict(markets=[km()],cursor=''),field='markets',eid='k'),
            page('polymarket_us',dict(events=[pe()]))]


class CoverageTests(unittest.TestCase):
    def test_cursor_and_offset_exhaustion(self):
        k=page('kalshi',dict(events=[],cursor='next'))
        end=page('kalshi',dict(events=[],cursor=''),position='next')
        self.assertEqual(traversal([k,end],'kalshi','events')[1]['state'],'exhausted')
        p=page('polymarket_us',dict(events=[pe(),pe('p2')]))
        end=page('polymarket_us',dict(events=[]),position=2)
        self.assertEqual(traversal([p,end],'polymarket_us','events')[1]['state'],'exhausted')

    def test_bounds_gaps_missing_cursor_and_failures(self):
        k=page('kalshi',dict(events=[],cursor='next'))
        self.assertEqual(traversal([k],'kalshi','events')[1]['state'],'bounded/truncated')
        self.assertEqual(traversal([page('kalshi',dict(events=[]))],'kalshi','events')[1]['state'],'unknown')
        repeated=page('kalshi',dict(events=[],cursor='next'),position='next')
        self.assertEqual(traversal([k,repeated],'kalshi','events')[1]['state'],'failed')
        p=page('polymarket_us',dict(events=[pe(),pe('p2')]))
        self.assertEqual(traversal([p],'polymarket_us','events')[1]['state'],'bounded/truncated')
        gap=page('polymarket_us',dict(events=[]),position=4)
        self.assertEqual(traversal([p,gap],'polymarket_us','events')[1]['state'],'failed')
        p['complete']=False
        self.assertEqual(traversal([p],'polymarket_us','events')[1]['state'],'failed')
        self.assertEqual(traversal([],'kalshi','events')[1]['state'],'unknown')

    def test_duplicates_conflicts_and_partition_counts(self):
        e,m=ke();bad=deepcopy(e);bad['title']='Other vs Team'
        pages=fixture();pages[0]=page('kalshi',dict(events=[e,e,bad],milestones=[m],cursor=''),limit=10)
        pages[1]=page('kalshi',dict(markets=[km(),km()],cursor=''),field='markets',eid='k')
        cat=build(pages,SOURCE,AS_OF)['venues']['kalshi'];c=cat['counts']
        self.assertEqual(c['events']['discovered'],1)
        self.assertEqual(c['events']['duplicates'],2)
        self.assertEqual(c['events']['excluded'],1)
        self.assertEqual(c['markets']['duplicates'],1)
        self.assertEqual(c['markets']['excluded'],1)
        self.assertEqual(len(cat['events'][0]['provenance']),3)

    def test_unmatched_unknown_and_sides_without_intersection(self):
        pages=fixture();pages[-1]=page('polymarket_us',dict(events=[pe(),pe('unknown',('Mystery','Buffalo Bills')),pe('alone',('Chicago Bears','Minnesota Vikings'))]),limit=10)
        cats=build(pages,SOURCE,AS_OF)['venues'];p=cats['polymarket_us'];c=p['counts']
        self.assertEqual(c['events']['matching'],dict(matched=1,unmatched=1,unresolved=1))
        self.assertEqual(c['events']['in_scope'],3)
        self.assertEqual(c['sides'],dict(supported=3,unsupported=3,unknown=0,total=6))
        self.assertEqual(cats['kalshi']['counts']['sides']['supported'],2)

    def test_identical_duplicate_keeps_resolved_identity(self):
        e,m=ke()
        pages=[page('kalshi',dict(events=[e,e],milestones=[m],cursor=''))]
        cat=build(pages,SOURCE,AS_OF)['venues']['kalshi']
        self.assertEqual(cat['events'][0]['identity'],'resolved')
        self.assertEqual(cat['events'][0]['matching_status'],'unmatched')
        self.assertEqual(cat['counts']['events']['duplicates'],1)

    def test_ambiguous_identity_and_missing_market(self):
        pages=fixture();pages.pop(1)
        c=build(pages,SOURCE,AS_OF)['venues']
        self.assertEqual(c['polymarket_us']['markets'][0]['matching_status'],'unmatched_missing_market')
        self.assertEqual(c['kalshi']['events'][0]['market_discovery'],'unknown')
        pages[-1]=page('polymarket_us',dict(events=[pe(),pe('p2')]),limit=10)
        c=build(pages,SOURCE,AS_OF)['venues']
        self.assertEqual(c['kalshi']['events'][0]['matching_status'],'ambiguous')

    def test_schedule_phase_type_and_unknown_side_exclusions(self):
        p1=pe('live');p1['live']=True
        p2=pe('period');p2['markets'][0]['sportsMarketType']='first_half_winner'
        p3=pe('badside');del p3['markets'][0]['marketSides'][0]['long']
        p4=pe('schedule');p4['startTime']=None
        pages=[page('polymarket_us',dict(events=[p1,p2,p3,p4]),limit=10)]
        c=build(pages,SOURCE,AS_OF)['venues']['polymarket_us']['counts']
        self.assertEqual(c['events']['excluded'],2)
        self.assertEqual(c['markets']['excluded'],4)
        self.assertEqual(c['sides']['unknown'],2)
        self.assertEqual(sum(c['markets']['exclusions'].values()),4)

    def test_more_than_six_and_first_traversal_only(self):
        rows=[pe(str(i)) for i in range(9)]
        p=page('polymarket_us',dict(events=rows),limit=10)
        cat=build([p,p],SOURCE,AS_OF)['venues']['polymarket_us']
        self.assertEqual(cat['counts']['events']['discovered'],9)
        self.assertEqual(cat['discovery'][0]['unused_pages'],1)

    def test_conflicting_schedule_and_independent_failure(self):
        e,m=ke();e2,m2=ke(start='2026-09-21T17:00:00Z')
        a=page('kalshi',dict(events=[e],milestones=[m],cursor='next'))
        b=page('kalshi',dict(events=[e2],milestones=[m2],cursor=''),position='next')
        cats=build([a,b,fixture()[-1]],SOURCE,AS_OF)['venues']
        self.assertEqual(cats['kalshi']['events'][0]['exclusion'],'conflicting_duplicate')
        a['complete']=False
        cats=build([a,fixture()[-1]],SOURCE,AS_OF)['venues']
        self.assertEqual(cats['kalshi']['event_discovery'],'failed')
        self.assertEqual(cats['kalshi']['market_completeness'],'unestablished')
        self.assertEqual(cats['polymarket_us']['counts']['events']['discovered'],1)

    def test_hash_and_query_scope(self):
        p=fixture()[0];p['body_sha256']='bad'
        self.assertEqual(traversal([p],'kalshi','events')[1]['state'],'failed')
        p=fixture()[-1];p['params']['tagSlug']='nba'
        cat=build([p],SOURCE,AS_OF)['venues']['polymarket_us']
        self.assertEqual(cat['counts']['events']['excluded'],1)

    def test_retained_counts_and_inputs_immutable_no_network(self):
        path=Path('evidence/multi-game/sessions/5accf9ee-94b9-4b09-8130-6849f842155e/saved-observations.json')
        before=path.read_bytes()
        with patch.object(socket,'socket',side_effect=AssertionError('network forbidden')):
            pages,source=load_pages(path);report=build(pages,source,AS_OF)
        k=report['venues']['kalshi']['counts'];p=report['venues']['polymarket_us']['counts']
        self.assertEqual((k['events']['discovered'],k['markets']['discovered'],k['events_without_retained_markets']),(32,12,26))
        self.assertEqual((p['events']['discovered'],p['markets']['discovered'],p['sides']['unsupported']),(32,32,32))
        self.assertEqual(p['markets']['matching'],dict(matched=6,unmatched_missing_market=26))
        self.assertFalse(report['current_full_coverage'])
        self.assertEqual(path.read_bytes(),before)

    def test_cli_reproducible_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'pages.json'
            src.write_text(json.dumps(dict(format='coverage-pages-1',classification='synthetic',pages=fixture())))
            for name in ('a','b'):
                with patch('sys.argv',['coverage','--input',str(src),'--as-of',AS_OF.isoformat(),'--output',str(root/name)]),patch('builtins.print'):
                    main()
            self.assertEqual((root/'a/coverage.json').read_bytes(),(root/'b/coverage.json').read_bytes())
            with patch('sys.argv',['coverage','--input',str(src),'--as-of',AS_OF.isoformat(),'--output',str(root/'a')]):
                with self.assertRaises(FileExistsError):main()
