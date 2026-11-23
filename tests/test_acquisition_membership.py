"""Owner timing boundary and policy-candidate membership, without a provider."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import pytest

from app.comparison.acquisition import validate, calculation
from app.comparison import current_pregame as math
from app.storage.acquisition_snapshot import coverage, requested_families
from app.comparison.reference_scope import REQUEST_BOOKS
from tests.test_current_pregame_reference_policy import RECORD, pair, AT

START = datetime(2026,11,23,tzinfo=timezone.utc)


def proof(seconds=0, pull='one'):
    return dict(pull_id=pull,attempt_id=pull+'-attempt',receipt_sha256='a'*64,
                received_at=(START+timedelta(seconds=seconds)).isoformat())


@pytest.mark.parametrize('seconds,accepted', [(600,True),(600.000001,False)])
def test_whole_input_receipt_boundary(seconds,accepted):
    if accepted:
        assert validate([proof(),proof(seconds)])['receipt_span_seconds'] == 600
    else:
        with pytest.raises(ValueError,match='receipt_span_exceeded'):
            validate([proof(),proof(seconds)])


def test_adjacent_gaps_do_not_replace_complete_input_span():
    with pytest.raises(ValueError,match='receipt_span_exceeded'):
        validate([proof(),proof(590),proof(1180)])


def test_identical_bytes_and_one_second_gap_do_not_merge_acquisitions():
    with pytest.raises(ValueError,match='pull_mismatch'):
        validate([proof(),proof(1,'two')])


def test_source_clocks_do_not_define_acquisition_span():
    a,b = dict(proof(),source_at='2020-01-01T00:00:00Z'),dict(proof(10),source_at='2026-01-01T00:00:00Z')
    assert validate([a,b])['receipt_span_seconds'] == 10


def test_unselected_trusted_candidate_is_required_input():
    rows = pair('fanduel','-110','-110')+pair('draftkings','-105','-115')
    for row in rows:
        row['facts']['acquisition'] = dict(proof(),received_at=row['facts']['received_at'])
    rows[0]['facts']['acquisition']['pull_id'] = 'different'
    record = deepcopy(RECORD)
    record['quote'] = dict(times=dict(received_at=rows[-1]['facts']['received_at']))
    record['comparison_source_metadata'] = dict(acquisition=proof())
    reference = math.reference(record,{'event':rows},at=AT)
    assert reference['book'] == 'draftkings'
    assert len(reference['required_input_prices']) == 4
    with pytest.raises(ValueError,match='pull_mismatch'):
        calculation(record,reference)


def test_family_scope_and_narrow_book_coverage():
    params = dict(bookmakerID=','.join(REQUEST_BOOKS),oddID='points-home-game-ml-home',
                  includeAltLines=True,includeOpposingOdds=True)
    assert requested_families(params) == ('moneyline',)
    assert coverage(params,'moneyline')['covers_board']
    assert not coverage(params,'spread')['covers_board']
    assert not coverage(dict(params,bookmakerID='fanduel,kalshi'),'moneyline')['covers_board']
    assert not coverage(dict(params,includeAltLines=False),'moneyline')['covers_board']
