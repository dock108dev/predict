import json
from pathlib import Path
import unittest
from app.dashboard.session_status import interpret_session

FIXTURE=Path(__file__).parent/'fixtures/saved_session_status.json'

def event(kind='shutdown', **detail):
    return dict(kind=kind,detail=detail)

class SavedStatusTests(unittest.TestCase):
    def status(self,state='complete',events=()):
        return interpret_session(dict(state=state,evidence_class='current'),events)

    def test_clean_bounded_end(self):
        s=self.status(events=[event(reason='Time limit reached',queued_unprocessed=0,rejected=0),
                              event('coverage',continuous_coverage=False)])
        self.assertEqual(s['label'],'Saved successfully')
        self.assertEqual(s['stop_reason'],'Time limit reached')

    def test_retained_legacy_evidence(self):
        for fixture in json.loads(FIXTURE.read_text()):
            with self.subTest(sid=fixture['session']['id']):
                s=interpret_session(fixture['session'],fixture['coverage'])
                self.assertEqual(s['label'],'Saved with capture gaps')
                self.assertEqual(s['unprocessed'],32)
                self.assertIsNone(s['rejected']);self.assertIsNone(s['messages'])
                self.assertEqual(s['lifecycle'],'complete')

    def test_missing_and_old_bounded_counts_stay_unknown(self):
        for events in ([],[event('coverage',continuous_coverage=False)],
                       [event(reason='Time limit reached'),event('gap',reason='Time limit reached',queued_unprocessed=0,continuous_coverage=False,censored=True)]):
            self.assertEqual(self.status(events=events)['coverage'],'unknown')

    def test_failed_interrupted_and_unfinished(self):
        for state in ('failed','interrupted','running'):
            s=self.status(state,[event(unprocessed=0,rejected=0)])
            self.assertEqual(s['coverage'],'unknown')
            self.assertTrue(s['label'].startswith('Unfinished' if state=='running' else state.capitalize()))
        self.assertEqual(self.status('failed',[event('failure',reason='write failed')])['coverage'],'unknown')

    def test_all_evidence_and_no_double_count(self):
        s=self.status(events=[event('coverage') for _ in range(101)]+[
            event(reason='Stop',unprocessed=32,queued_unprocessed=32,rejected=2),
            event('gap',queued_unprocessed=32)])
        self.assertEqual(s['unprocessed'],32);self.assertEqual(s['rejected'],2)
        self.assertEqual(s['coverage'],'gaps')

    def test_retained_clean_deadline_does_not_prove_loss(self):
        saved=json.loads((FIXTURE.parents[2]/'evidence/slice-13/live-final-saved.json').read_text())
        s=interpret_session(saved['session'],saved['coverage'])
        self.assertEqual(s['coverage'],'unknown')
        self.assertEqual(s['unprocessed'],0);self.assertIsNone(s['rejected'])
        self.assertEqual(s['stop_reason'],'Scan deadline reached')

    def test_real_gap_is_not_erased_by_zero_backlog(self):
        s=self.status(events=[event('gap',reason='Backpressure: lost observation',queued_unprocessed=0,continuous_coverage=False,censored=True)])
        self.assertEqual(s['coverage'],'gaps')
