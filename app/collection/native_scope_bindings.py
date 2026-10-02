"""Retained exact native catalog keys; listing discovery is not admission."""
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

POLICY = 'native-scope-bindings-v1'
PATH = Path(__file__).resolve().parents[1] / 'fixtures/native-scope-bindings-v1.json'
LIMIT = 256 * 1024


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def _catalog():
    if PATH.stat().st_size > LIMIT:
        raise ValueError('Native scope catalog byte bound')
    return validate_catalog(json.loads(PATH.read_text()))


def validate_catalog(value):
    value = deepcopy(value)
    expected = value.pop('sha256', None)
    if expected != _digest(value) or value.get('schema') != POLICY or value.get('collection_authorized') is not False:
        raise ValueError('Native scope catalog digest/schema/authority mismatch')
    from .source_bindings import required_cells
    cells = {c['cell_id'] for c in required_cells()}
    seen = set()
    for row in value['bindings']:
        key = f"{row['sport']}/{row['period']}/{row['category'] or row['family']}"
        ticker = row['series_ticker']
        if key not in cells or ticker in seen or not ticker or row['source_catalog_sha256'] != value['source_catalog_sha256']:
            raise ValueError('Invalid exact native series binding')
        seen.add(ticker)
    return value


def catalog_cell_bindings(catalog=None):
    result = defaultdict(list)
    for row in (validate_catalog(catalog) if catalog is not None else _catalog())['bindings']:
        key = f"{row['sport']}/{row['period']}/{row['category'] or row['family']}"
        result[key].append(deepcopy(row))
    return dict(result)


def series_binding(ticker):
    return next((deepcopy(r) for r in _catalog()['bindings'] if r['series_ticker'] == ticker), None)


def selectors_for(cell_id, source='kalshi'):
    if source != 'kalshi':
        return []
    return [dict(path='/trade-api/v2/events', params=dict(series_ticker=r['series_ticker'],
                 status='open', with_milestones='true', with_nested_markets='false'), binding=r)
            for r in catalog_cell_bindings().get(cell_id, [])]
