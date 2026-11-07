from copy import deepcopy
from unittest.mock import patch
import pytest
from app.storage.recovery_codec import freeze,thaw


def test_lossless_original_metadata_and_parsed_receipt_with_exact_numbers():
    original=dict(id='source-market',title='原',period='full_game',sides=[dict(id='yes')],
        evidence=dict(number=10**100,decimal='0.123456789012345678901234567890',
            raw='literal original provider text '+('duplicate evidence\n'*1000)),
        raw=dict(received_at='2026-11-05T00:00:00Z',json_text='exact body\n'))
    before=deepcopy(original);packed=freeze(original)
    assert '_predict_storage'in packed
    assert packed['title']==original['title']
    assert thaw(packed)==original==before
    assert thaw(original)==original
    changed=thaw(packed);changed['raw']['received_at']='other'
    assert thaw(packed)==before
    with patch('app.storage.recovery_codec.MAX_BYTES',1):assert freeze(original)==original


def test_corrupt_or_crossed_display_fails_closed():
    packed=freeze(dict(title='valid',evidence='a'*4000))
    for key,value in (('sha256','f'*64),('length',100000000)):
        bad=deepcopy(packed);bad['_predict_storage'][key]=value
        with pytest.raises(ValueError):thaw(bad)
    bad=deepcopy(packed);bad['title']='another market'
    with pytest.raises(ValueError,match='display_conflict'):thaw(bad)
