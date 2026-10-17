"""Exact server-retained destinations. Empty production catalog is fail closed.

Authored catalog entries exercise mapping only; they never qualify a venue.
No client URL, homepage fallback, account token or inferred slug is accepted.
"""
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit, quote
import json
from .current_dependencies import digest

HOSTS = {'kalshi': {'kalshi.com'}, 'polymarket_us': {'polymarket.us'},
         'novig': {'novig.us', 'app.novig.us'}, 'prophetx': {'prophetx.co', 'app.prophetx.co'}}
PATH = Path(__file__).resolve().parents[1] / 'fixtures/scanner-destinations-v1.json'


def binding(instrument):
    return {k: deepcopy(instrument[k]) for k in
            ('venue', 'native_key', 'native_contract_id', 'terms_sha256', 'predicate')}


class Destinations:
    def __init__(self, catalog=None):
        self.catalog = deepcopy(catalog if catalog is not None else json.loads(PATH.read_text()))
        if self.catalog.get('version') != 'predict-market-destinations-1':
            raise ValueError('destination_catalog_version')
        if len(json.dumps(self.catalog)) > 256 * 1024:
            raise ValueError('destination_catalog_capacity')
        self.revision = digest(self.catalog)

    def resolve(self, instrument):
        unavailable = dict(state='unavailable', url=None, reason='verified_exact_market_destination_missing',
                           catalog_revision=self.revision, provenance=None)
        exact = binding(instrument)
        matches = [x for x in self.catalog['markets'] if x.get('binding') == exact]
        if len(matches) != 1:
            return unavailable
        item = matches[0]
        try:
            route = self.catalog['routes'][item['route_id']]
            # Evidence is retained and hashed, including route and matching position.
            for evidence in (route['evidence'], item['evidence']):
                assert evidence['sha256'] == digest(evidence['retained'])
                assert evidence['class'] in ('authored_fixture', 'reviewed_source')
                assert evidence['retained']
            assert route['venue'] == instrument['venue']
            assert route['evidence']['retained']['documented_template'] == route['template']
            assert item['evidence']['retained']['binding'] == exact
            assert item['evidence']['retained']['url'] == item['url']
            params = item['parameters']
            assert all(isinstance(v, str) and 0 < len(v) <= 256 for v in params.values())
            url = route['template'].format(**{k: quote(v, safe='') for k, v in params.items()})
            parsed = urlsplit(url)
            assert url == item['url'] and len(url) <= 2048
            assert parsed.scheme == 'https' and parsed.hostname in HOSTS[instrument['venue']]
            assert parsed.netloc == parsed.hostname and not parsed.username and not parsed.password
            assert not parsed.query and not parsed.fragment and parsed.path not in ('', '/')
            assert '%' not in parsed.netloc and '..' not in parsed.path and '\\' not in url
            assert all(ord(c) > 32 for c in url)
        except (KeyError, ValueError, AssertionError, TypeError):
            return dict(unavailable, reason='destination_evidence_unsafe_or_unsupported')
        evidence_class = ('reviewed_source' if all(x['evidence']['class'] == 'reviewed_source'
                          for x in (route, item)) else 'authored_fixture')
        return dict(state='verified', url=url, reason=None, catalog_revision=self.revision,
                    provenance=dict(route_id=item['route_id'], route_sha256=route['evidence']['sha256'],
                                    market_sha256=item['evidence']['sha256'], evidence_class=evidence_class))
