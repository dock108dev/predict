from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from app.storage.scanner_publication import current_revision
from app.storage.store import hashed


class Database:
    tail='original'
    def transaction(self):return nullcontext()
    def execute(self,*args):return SimpleNamespace(fetchone=lambda:dict(epoch='epoch'))
    def cursor(self,**kwargs):return nullcontext(Cursor(self))


class Cursor:
    def __init__(self,db):self.db=db
    def execute(self,query):self.offers='FROM current_offer ' in query
    def __iter__(self):
        if self.offers:
            for i in range(33000):
                yield dict(contract_id=f'{i:08}',revision=self.db.tail if i==32999 else 'revision')


def test_busy_slate_witness_is_streamed_without_truncating_tail():
    db=Database();first=current_revision(db)
    expected={f'{i:08}':'original' if i==32999 else 'revision' for i in range(33000)}
    assert first['current_rows_revision']==hashed(['epoch',expected,{}])
    assert current_revision(db)==first
    db.tail='changed';second=current_revision(db)
    assert second['current_rows_revision']!=first['current_rows_revision']
    assert second['facts_revision']==first['facts_revision']


def test_probe_byte_work_guard_still_refuses():
    with patch('app.storage.scanner_publication.MAX_PROBE_BYTES',100):
        with pytest.raises(ValueError,match='scanner_revision_probe_capacity'):
            current_revision(Database())
