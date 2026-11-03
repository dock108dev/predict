"""An unavailable SQL observation must never become a zero-byte measurement."""
import json
from unittest.mock import patch
from scripts import pipeline_storage_report as report


def test_failed_probe_retains_unknown_bytes_without_connection_details(tmp_path):
    destination=tmp_path/'storage.json'
    with patch.object(report,'connect',side_effect=RuntimeError('private connection detail')), \
         patch('sys.argv',['pipeline_storage_report.py',str(destination)]):
        assert report.main()==1
    result=json.loads(destination.read_text())
    assert result['evidence_class']=='unavailable'
    assert result['measured_database_bytes'] is None
    assert 'private connection detail' not in destination.read_text()
