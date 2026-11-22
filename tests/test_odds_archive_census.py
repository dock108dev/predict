"""Portable archive census proof: verified rows, source events and actual clocks."""
from datetime import date
import gzip
import json

import pytest

from app.storage.odds_archive import digest, observation
from app.storage.odds_archive_census import census
from app.storage.store import encoded
from app.storage.research_coverage import archive_census_snapshot


def shard(root, feed, day, items):
    path=root/'v1'/feed/day
    path.mkdir(parents=True,exist_ok=True)
    rows=[[item['id'],*item['body']] for item in items]
    file=path/(digest([feed,day,sorted(item['id']for item in items)])+'.jsonl.gz')
    file.write_bytes(gzip.compress(b'\n'.join(encoded(row)for row in rows)+b'\n'))
    return file


def test_census_counts_actual_receipts_and_distinct_events_without_implying_coverage(tmp_path):
    home=observation('sportsgameodds','top','home','game-one','2026-11-18T16:00:00Z',
        '2026-11-18T12:00:01-05:00',None,dict(price='-110'))
    away=observation('sportsgameodds','top','away','game-one','2026-11-18T16:00:00Z',
        '2026-11-18T17:00:02Z',None,dict(price='-110'))
    later=observation('sportsgameodds','runtime_status','runtime',None,None,
        '2026-11-20T17:00:00Z',None,dict(dispatch=False))
    first=shard(tmp_path,'sportsgameodds','2026-11-18',[home,away])
    last=shard(tmp_path,'sportsgameodds','2026-11-20',[later])
    result=census(tmp_path)
    feed=result['feeds']['sportsgameodds']
    assert feed['verified_records']==3
    assert feed['distinct_events']==1
    assert feed['first_received_at']==home['received_at']
    assert feed['last_received_at']==later['received_at']
    assert feed['first_source_at']=='2026-11-18T16:00:00Z'
    assert feed['missing_receipt_days']==['2026-11-19']
    assert feed['compressed_bytes']==first.stat().st_size+last.stat().st_size
    assert feed['records_by_kind']==dict(top=2,runtime_status=1)
    assert feed['coverage']=='verified_files_with_gaps_not_complete_collection'
    assert result['provider_requests']==0
    assert result['feeds']['kalshi']['verified_records']==0
    restricted=census(tmp_path,first_day=date(2026,11,20))['feeds']['sportsgameodds']
    assert restricted['verified_records']==1
    assert restricted['distinct_events']==0


def test_census_fails_on_a_corrupted_change_instead_of_counting_it(tmp_path):
    item=observation('kalshi','top','home','game-one',None,'2026-11-18T17:00:01Z',None,['0.51'])
    path=shard(tmp_path,'kalshi','2026-11-18',[item])
    row=json.loads(gzip.decompress(path.read_bytes()))
    row[-1]=['0.52']
    path.write_bytes(gzip.compress(encoded(row)+b'\n'))
    with pytest.raises(ValueError,match='odds_archive_change_identity'):
        census(tmp_path)


def test_optional_saved_census_never_turns_absent_or_invalid_state_into_coverage(tmp_path):
    path=tmp_path/'census.json'
    assert archive_census_snapshot(path)['state']=='not_recorded'
    for body in ('broken','[]','{"version":"predict-odds-archive-census-1","feeds":{"kalshi":[]}}'):
        path.write_text(body)
        assert archive_census_snapshot(path)['state']=='unavailable'
    path.write_text(json.dumps(census(tmp_path)))
    value=archive_census_snapshot(path)
    assert value['state']=='available'
    assert value['feeds']['kalshi']['verified_records']==0
