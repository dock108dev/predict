from datetime import datetime, timezone
import json
import pytest

from app.collection.sportsgameodds_usage import parse_usage

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def body():
    return {'success': True, 'data': {'isActive': True, 'tier': 'amateur', 'keyID': 'private',
        'rateLimits': {'per-minute': {'max-requests': 10},
                       'per-month': {'max-entities': 2500, 'current-entities': 11}}}}


def test_nonsecret_projection_does_not_invent_reset():
    value = parse_usage(json.dumps(body()).encode(), NOW)
    assert value == {'tier':'amateur', 'limit':2500, 'used':11, 'requests_per_minute':10, 'reset_at':None, 'at':NOW}


def test_evidenced_reset_and_bad_usage():
    raw = body()
    raw['data']['rateLimits']['per-month']['currentIntervalEndTime'] = '2026-12-10T00:00:00Z'
    assert parse_usage(json.dumps(raw).encode(), NOW)['reset_at'].month == 12
    raw['data']['rateLimits']['per-month']['current-entities'] = -1
    with pytest.raises(ValueError):
        parse_usage(json.dumps(raw).encode(), NOW)
