"""Visible-game fairness without acquisition, queue growth or weaker guards."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.collection.current_database import DatabasePipeline
from app.comparison.estimated_policy import DEFAULT_POLICY
from app.dashboard.comparison_slate import schedule


class Queue:
    MAX_PENDING=4
    def __init__(self):self.pending={};self.closed=False;self.requested=[]
    def request(self,key,policy):
        if len(self.pending)>=self.MAX_PENDING:raise ValueError('saved_calculation_queue_capacity')
        self.pending[(key,policy.revision)]=policy;self.requested.append(key)


class SlateFairness(TestCase):
    def test_every_visible_game_gets_a_turn_when_early_games_keep_changing(self):
        queue=Queue();keys=['game:'+str(i) for i in range(28)]
        for _ in range(7):
            schedule(queue,keys,DEFAULT_POLICY)
            self.assertLessEqual(len(queue.pending),4)
            queue.pending.clear()  # Authored worker completion; all inputs may change again.
        self.assertEqual(queue.requested,keys)

    def test_hot_queued_game_does_not_starve_later_admissions(self):
        queue=Queue();keys=['hot']+['game:'+str(i) for i in range(12)]
        schedule(queue,keys,DEFAULT_POLICY)
        for _ in range(4):
            queue.pending={k:v for k,v in queue.pending.items() if k[0]=='hot'}
            schedule(queue,keys,DEFAULT_POLICY)
        self.assertTrue(set(keys)<=set(queue.requested))
        self.assertLessEqual(len(queue.pending),4)
        self.assertEqual(queue.requested.count('hot'),1)

    def test_closed_or_full_queue_never_changes_owned_work(self):
        queue=Queue();schedule(queue,['a','b','c','d'],DEFAULT_POLICY)
        before=dict(queue.pending);cursor=queue._slate_schedule_cursor
        schedule(queue,['a','b','c','d','e'],DEFAULT_POLICY)
        self.assertEqual(queue.pending,before);self.assertEqual(queue._slate_schedule_cursor,cursor)
        queue.closed=True;schedule(queue,['f'],DEFAULT_POLICY)
        self.assertEqual(queue.pending,before)

    def test_refused_publication_rotates_same_generation_without_weakening_guard(self):
        service=SimpleNamespace(config={'cleanup_seconds':1},journal=SimpleNamespace(paths=lambda:[]))
        pipe=DatabasePipeline(service,[])
        for key in ('hot','healthy'):pipe.request(key,DEFAULT_POLICY)
        generation=dict(pipe.generations);calculated=[];latest=[]
        store=SimpleNamespace(publish=lambda snapshot,result,allow_latest: (latest.append((result,allow_latest)) or ('id',result=='healthy')))
        def capture(s,key,policy):return dict(projection=dict(inputs=dict(game_key=key)))
        def calculate(snapshot):
            key=snapshot['projection']['inputs']['game_key'];calculated.append(key);return key
        with patch('app.collection.current_database.connect',return_value=nullcontext(object())), \
                patch('app.collection.current_database.Store',return_value=SimpleNamespace(migrate=lambda:None)), \
                patch('app.collection.current_database.GameStore',return_value=store), \
                patch('app.collection.current_database.sql_usage',return_value=0), \
                patch('app.collection.current_database.require_disk_space'), \
                patch('app.collection.current_database.calculate',side_effect=calculate), \
                patch('app.storage.comparison_board.capture',side_effect=capture), \
                patch('app.storage.comparison_board.saved',return_value=None):
            pipe.tick(ingress=False);pipe.tick(ingress=False)
        self.assertEqual(calculated,['hot','healthy'])
        self.assertEqual(latest,[('hot',True),('healthy',True)])
        self.assertEqual(list(pipe.pending),[('hot',DEFAULT_POLICY.revision)])
        self.assertEqual(pipe.generations,generation)
        self.assertEqual(pipe.MAX_PENDING,4)
