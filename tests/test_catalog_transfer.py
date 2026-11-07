"""Catalog IPC keeps exact metadata while avoiding a whole-graph reply."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path
from unittest.mock import patch
import pytest
from app.collection import catalog_transfer as transfer
from app.collection.current_ingress import CatalogPreparation


def catalog():
 return dict(events=[dict(id='e',facts={'name':'event','nested':['a',1,True]})],
             markets=[dict(id='m',event_id='e',terms={'fee':'0.2','rules':['x']})],selection={'ids':['m']})


def test_exact_roundtrip_shares_equal_subtrees_but_detaches_writable_rows(tmp_path):
 prior={'kalshi':catalog()};path=tmp_path/'transfer';delta=dict(retained={('kalshi','e','m')},withdraw=set(),refresh=set())
 transfer.write(path,prior,delta);result,actual=transfer.read(path,prior)
 assert result==prior and actual==delta
 assert result['kalshi']['markets'][0] is not prior['kalshi']['markets'][0]
 assert result['kalshi']['markets'][0]['terms'] is prior['kalshi']['markets'][0]['terms']
 result['kalshi']['markets'][0]['diagnostic']='new'
 assert 'diagnostic' not in prior['kalshi']['markets'][0]


def test_changed_terms_and_json_scalar_types_do_not_inherit_previous_values(tmp_path):
 prior={'kalshi':catalog()};changed={'kalshi':catalog()};changed['kalshi']['markets'][0]['terms']['fee']='0.3'
 changed['kalshi']['events'][0]['facts']['nested'][-1]=1
 path=tmp_path/'transfer';transfer.write(path,changed);result,_=transfer.read(path,prior)
 assert result==changed
 assert result['kalshi']['markets'][0]['terms'] is not prior['kalshi']['markets'][0]['terms']
 assert type(result['kalshi']['events'][0]['facts']['nested'][-1]) is int


def test_truncated_and_oversized_transfers_fail_without_partial_adoption(tmp_path):
 path=tmp_path/'transfer';transfer.write(path,{'kalshi':catalog()})
 path.write_bytes(path.read_bytes().rsplit(b'\n',2)[0]+b'\n')
 with pytest.raises(ValueError,match='incomplete'):transfer.read(path)
 transfer.write(path,{'kalshi':catalog()})
 with patch.object(transfer,'MAX_ROW_BYTES',20):
  with pytest.raises(ValueError,match='capacity'):transfer.read(path)
  with pytest.raises(ValueError,match='capacity'):transfer.write(path,{'kalshi':catalog()})


from unittest import IsolatedAsyncioTestCase
class TransferCancellation(IsolatedAsyncioTestCase):
 async def test_cancel_retains_private_files_until_worker_exit(self):
  entered=Event();release=Event();paths=[]
  def worker(input_path,replacement_path,output_path,source,maximum):
   paths.append(Path(input_path).parent);entered.set();release.wait(3)
   assert Path(input_path).exists() and Path(replacement_path).exists()
   transfer.write(output_path,{source:catalog()});return {}
  owner=object.__new__(CatalogPreparation);owner.lock=asyncio.Lock();owner.pool=ThreadPoolExecutor(1);owner.maximum_bytes=3*1024**3;owner.metrics=None
  with patch.object(transfer,'prepare',side_effect=worker):
   task=asyncio.create_task(owner.prepare({'kalshi':catalog()},'kalshi',catalog()))
   while not entered.is_set():await asyncio.sleep(.001)
   task.cancel();await asyncio.sleep(.01)
   assert paths[0].exists() and not task.done()
   release.set()
   with pytest.raises(asyncio.CancelledError):await task
   assert not paths[0].exists()
  await owner.close()


def test_fresh_rows_share_repeated_strings_without_aliasing_mutable_source_facts(tmp_path):
    path = tmp_path / 'catalog'
    terms = {'provider_wording': ['Full game including overtime', False, 0, '0']}
    source = dict(events=[], markets=[dict(id=str(i), terms=terms) for i in range(200)])
    transfer.write(path, {'kalshi': source})
    result, _ = transfer.read(path)
    rows = result['kalshi']['markets']
    assert rows == source['markets']
    first, last = (row['terms']['provider_wording'] for row in (rows[0], rows[-1]))
    assert first[0] is last[0]
    last.append('local annotation')
    assert first == terms['provider_wording']
    assert type(first[1]) is bool and type(first[2]) is int


def test_borrowed_fields_preserve_order_types_and_deletions_under_original_cap(tmp_path):
    path = tmp_path / 'job'
    prior = {'kalshi': catalog()}
    base = prior['kalshi']['markets'][0]
    import random
    base.update(obsolete=True, evidence=[''.join(random.Random(3).choices('abcdefghijklmnopqrstuvwxyz0123456789',k=7000))])
    row = dict(id=base['id'], evidence=base['evidence'], present=None, value=False)
    source = {'kalshi': dict(events=[], markets=[row])}
    with patch.object(transfer, 'MAX_TRANSFER_BYTES', 1024):
        with pytest.raises(ValueError, match='capacity'):
            transfer.write(path, source)
        transfer.write(path, source, previous=prior)
        restored, _ = transfer.read(path, prior)
        with pytest.raises(ValueError, match='patch_base'):
            transfer.read(path)
    actual = restored['kalshi']['markets'][0]
    assert list(actual.items()) == list(row.items())
    assert actual is not row and actual['evidence'] is base['evidence']


def test_compact_transfer_preserves_full_rows_under_unchanged_file_and_decode_guards(tmp_path):
    import json
    path=tmp_path/'compact'
    source={'polymarket_us':catalog()}
    source['polymarket_us']['markets'][0]['evidence']=['exact native terms '*2000,False,1,'1',None]
    with patch.object(transfer,'MAX_TRANSFER_BYTES',4096):
        size=transfer.write(path,source)
        actual,_=transfer.read(path)
        assert actual==source and size<4096
    lines=path.read_bytes().splitlines(keepends=True)
    index=next(i for i,b in enumerate(lines) if json.loads(b)[0]=='gzip-1')
    packet=json.loads(lines[index]);packet[2]='0'*64
    damaged=list(lines);damaged[index]=json.dumps(packet).encode()+b'\n';path.write_bytes(b''.join(damaged))
    with pytest.raises(ValueError,match='integrity'):transfer.read(path)
    packet[1]=transfer.MAX_ROW_BYTES+1;damaged[index]=json.dumps(packet).encode()+b'\n';path.write_bytes(b''.join(damaged))
    with pytest.raises(ValueError,match='capacity'):transfer.read(path)
    with patch.object(transfer,'MAX_ROW_BYTES',4096):
        with pytest.raises(ValueError,match='capacity'):transfer.write(path,source)
