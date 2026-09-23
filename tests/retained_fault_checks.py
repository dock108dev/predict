"""Run purposeful existing integration faults while retaining disposable evidence."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from app.dashboard import session_history
from app.collection.segmented import SegmentedJournal
from tests.test_session_projection import fixture

def main(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    class RetainedDirectory:
        def __init__(self,*a,**kw):
            self.name=str(root/('case-'+str(uuid4())));Path(self.name).mkdir()
        def __enter__(self):return self.name
        def __exit__(self,*a):return False
    names=[
      'tests.test_segmented_collector.Integration.test_rotation_io_failure_preserves_interrupted_history_without_terminal',
      'tests.test_segmented_collector.Integration.test_resource_stop_before_intended_stop_is_not_operator_success',
      'tests.test_segmented_collector.Integration.test_stop_with_pending_work_drains_before_terminal',
      'tests.test_segmented_collector.Integration.test_final_manifest_failure_is_not_successful_stop']
    with patch.object(tempfile,'TemporaryDirectory',RetainedDirectory):
        result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    assert result.wasSuccessful()
    retain_prefix(root,names)

def retain_prefix(root,names):
    folder=root/'b2-fixture';folder.mkdir()
    journal=SegmentedJournal(folder/'history',label='B6 synthetic interrupted prefix',output_root=root)
    for row in fixture():journal.save(row)
    journal.finish(cleanup_complete=False)
    snap=session_history.load(folder)
    assert snap['state']=='incomplete' and len(snap['games'])==6
    summary=dict(tests=names,all_passed=True,prefix_state=snap['state'],prefix_games=len(snap['games']),prefix_cutoff=snap['durable_cursor'],
                 reports={str(p.relative_to(root)):json.loads(p.read_text()) for p in root.rglob('report.json')})
    (root/'fault-report.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='reports'},indent=2))

if __name__=='__main__':main(sys.argv[1])
