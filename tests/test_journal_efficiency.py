import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from app.collection.journal_encoding import encode,decode,VERSION
from app.collection.transport_session import ObservationJournal,reopen,TransportSession
from app.collection.odds_http import BudgetStop
from app.dashboard.coverage_owner import spec,replay_groups

ORIGINAL=Path('evidence/d2-coverage/validation-20260916T170132Z-2cbe6460/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3/3b9cf13c-0696-4fcb-b643-bdd545d9bbd3.jsonl')

class Encoding(unittest.TestCase):
    def test_exact_original_workload_and_native_replay(self):
        saved=reopen(ORIGINAL)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'journal';j=ObservationJournal(p,encoding=VERSION)
            for row in saved['rows']:j.save(row)
            self.assertTrue(j.terminal_acknowledged);j.close()
            result=reopen(p);self.assertEqual(result['rows'],saved['rows'])
            self.assertEqual(result['state'],'complete')
            r=replay_groups(result)
            self.assertTrue(all(v['exact_packets'] for v in r.values()))
            self.assertEqual(sum(sum(v['exact_native_books'].values()) for v in r.values()),575)

    def test_corrupt_missing_unknown_and_oversized_encoding(self):
        row=encode(dict(type='test',value='a'*1000));self.assertEqual(decode(row)['value'],'a'*1000)
        for mutation in ({'journal_encoding':'unknown'},{'expanded_bytes':2},{'payload_b64':'!!!'}, {'payload_b64':''}):
            with self.assertRaises(ValueError):decode(dict(row,**mutation))
        del row['payload_b64']
        with self.assertRaises(ValueError):decode(row)

    def test_chain_interruption_and_legacy_readability(self):
        with tempfile.TemporaryDirectory() as tmp:
            for version in (None,VERSION):
                p=Path(tmp)/str(version);j=ObservationJournal(p,encoding=version);j.save(dict(type='sample'));j.close()
                self.assertEqual(reopen(p)['state'],'interrupted')
                with p.open('ab') as f:f.write(b'{')
                with self.assertRaises(ValueError):reopen(p)

    def test_record_byte_caps_rejections_and_terminal_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=TransportSession(spec(),Path(tmp),{},credentials={});s.journal=ObservationJournal(Path(tmp)/'j',encoding=VERSION)
            for i in range(2048):
                s.emit('test',dict(type='sample',index=i));s.queue.get_nowait();s.queue.task_done();s.persisted+=1
            with self.assertRaises(BudgetStop):s.emit('test',dict(type='sample',index=2048))
            self.assertEqual(s.counts['rejected'],1);self.assertEqual(s.counts['durably_acknowledged'],2048)
            s.journal.save(dict(type='session_finished'));self.assertTrue(s.journal.terminal_acknowledged);s.journal.close()
            self.assertEqual(len(reopen(Path(tmp)/'j')['rows']),2049)
            s=TransportSession(spec(),Path(tmp),{},credentials={});s.journal=ObservationJournal(Path(tmp)/'b',encoding=VERSION);s.ingress_bytes=16*1024*1024
            with self.assertRaises(BudgetStop):s.emit('test',dict(type='sample'))
            self.assertEqual(s.journal.count,0);self.assertEqual(s.counts['rejected'],1);s.journal.close()
