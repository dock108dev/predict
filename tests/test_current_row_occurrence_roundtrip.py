"""Exact compact source witnesses survive current SQL without storing raw events."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import unittest
from uuid import uuid4
from psycopg import sql
from app.storage.store import connect,Store
from app.storage.current_rows import CurrentRowStore
from app.comparison.occurrence_matching import OccurrenceResolver
from app.comparison.event_links import EventLinks
from tests.test_ev02_occurrence import rows,HOME,AWAY

AT='2026-10-15T12:00:00Z'
START=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()


def authored(provider,native,*,shared=None,raw=None):
    result=rows(provider,native,shared=shared)
    for row in result:
        row['event']['scheduled_start']=row['market_identity']['scheduled_start']=START
        row['quote']['times'].update(source_at=AT,received_at=AT,projected_at=AT)
        if raw is not None:row['event']['_native']=deepcopy(raw)
    return result


def audit(records):
    resolved=OccurrenceResolver(links=EventLinks()).resolve(records,clock=AT)
    return {(r['quote']['source']['provider'],r['quote']['source']['native_event_id'],r['quote']['source']['native_outcome_id']):
        {k:r['quote']['occurrence_match'][k] for k in ('occurrence_id','method','estimated','status','members','conflicts','candidate_members')}
        for r in resolved}


class CurrentOccurrenceRoundtrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='prediction_arb_d03_matching_'+uuid4().hex[:10]
        with connect() as db:db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(cls.name)))
        cls.db=connect(cls.name);Store(cls.db).migrate();cls.store=CurrentRowStore(cls.db)
    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        with connect() as db:db.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(cls.name)))
    def setUp(self):self.db.execute('TRUNCATE current_event CASCADE')
    def roundtrip(self,records):
        self.store.upsert_records(records)
        after=self.store.capture(include_depth=False)['records']
        self.assertEqual(audit(records),audit(after))
        # The compact event itself retains every fact consumed by the resolver.
        resolver=OccurrenceResolver(links=EventLinks())
        before_facts={(r['quote']['source']['provider'],r['event']['id']):resolver._facts(r) for r in records}
        for row in after:
            key=(row['quote']['source']['provider'],row['event']['id'])
            self.assertEqual({k:v for k,v in before_facts[key].items() if k!='event'},
                             {k:v for k,v in resolver._facts(row).items() if k!='event'})
            self.assertNotIn('_native',row['event']);self.assertNotIn('native_metadata',row['event'])
        return after
    def test_repeated_opponents_keep_exact_shared_ids_and_game_number(self):
        a=authored('kalshi','k',shared={'sportradar':'game-one'})
        for r in a:r['event']['game_number']=1
        b=authored('polymarket_us','p1',raw=dict(sportradarGameId='game-one',gameNumber=1))
        c=authored('polymarket_us','p2',raw=dict(sportradarGameId='game-two',gameNumber=2))
        after=self.roundtrip(a+b+c);result=audit(after)
        self.assertTrue(all(v['method']=='shared_provider_id' and not v['estimated'] for v in result.values()))
    def test_partially_shared_provider_namespaces_preserve_exact_witness(self):
        a=authored('kalshi','k',shared={'sportradar':'shared-game','another_provider':'other-explicit-id'})
        b=authored('polymarket_us','p',raw=dict(sportradarGameId='shared-game'))
        self.roundtrip(a+b)
    def test_source_role_conflict_survives_and_neutral_does_not_erase_it(self):
        a=authored('kalshi','k',shared={'sportradar':'shared-game'})
        b=authored('polymarket_us','p',raw=dict(sportradarGameId='shared-game'))
        for r in b:r['event'].update(source_participant_roles=dict(home=AWAY,away=HOME),neutral_venue=True)
        after=self.roundtrip(a+b)
        self.assertTrue(any(v['status']=='unresolved' for v in audit(after).values()))
    def test_neutral_role_reversal_is_preserved(self):
        a=authored('kalshi','k',shared={'sportradar':'shared-game'})
        b=authored('polymarket_us','p',raw=dict(sportradarGameId='shared-game'))
        for r in a+b:r['event']['neutral_venue']=True
        for r in b:r['event'].update(home=AWAY,away=HOME)
        self.roundtrip(a+b)
    def test_original_start_replacement_and_reschedule_fallbacks(self):
        for native,raw in (
            ('replacement',dict(sportradarGameId='replacement-game',originalStartTime=START,gameNumber=3,replacementGameId='new-game')),
            ('reschedule',dict(sportradarGameId='rescheduled-game',originalStartTime=START,gameNumber=4,rescheduledFromGameId='old-game')),
        ):
            record=authored('polymarket_us',native,raw=raw)
            self.roundtrip(record)
            self.db.execute('TRUNCATE current_event CASCADE')
    def test_typed_identity_fact_namespace_conflict_is_preserved(self):
        record=authored('polymarket_us','p',raw=dict(sportradarGameId='raw-game'))
        for r in record:r['event']['observed_identity_facts']=[dict(source_provider='sportradar',source_id='conflicting-game')]
        self.roundtrip(record)

if __name__=='__main__':unittest.main()
