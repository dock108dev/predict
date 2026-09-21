"""Explicit local-fixture boundary and D3a adapter; no collector implementation."""
from pathlib import Path
from urllib.parse import urlsplit

from .odds_http import mock_endpoint
from .journal_encoding import VERSION, encode


def validate_mock(spec, endpoints, credentials=None):
    if spec.get('mode') != 'mock' or spec.get('reference_enabled', False) or credentials:
        raise ValueError('segmented collector requires prediction-only mock mode without credentials')
    if set(endpoints) != {'kalshi', 'polymarket_us'}:
        raise ValueError('explicit fixture endpoints required for both feeds')
    for venue in endpoints.values():
        if set(venue) != {'rest', 'ws'}: raise ValueError('invalid fixture endpoints')
        for name, scheme in (('rest', 'http'), ('ws', 'ws')):
            value = mock_endpoint(venue[name]); parsed = urlsplit(value)
            if parsed.scheme != scheme or not parsed.port or (name == 'rest' and parsed.path not in ('', '/')):
                raise ValueError('explicit numeric loopback fixture port required')


def fixture_endpoints(session):
    validate_mock(session.spec, session.endpoints, session.credentials)
    return session.endpoints


class SegmentedTransportJournal:
    """Adapt the existing transport journal contract to D3a, without new rows.

    TransportSession alone creates the real lifecycle terminal. Closing an absent
    or failed terminal cannot promote the history to complete.
    """
    encoding = VERSION

    def __init__(self, output, profile_name=None, *, label=None):
        from .segmented import SegmentedJournal
        self.history = SegmentedJournal(Path(output)/'history',
            label=label or 'synthetic local collector; new mock observations, no venue collection',
            output_root=Path(output).parent, profile_name=profile_name)
        self.path = self.history.folder/'manifest.json'
        self.cleanup_complete = False

    def encoded(self, row): return encode(row)
    @property
    def bytes(self): return self.history.accounting()['journal_encoded_bytes']
    @property
    def expanded_bytes(self): return self.history.accounting()['journal_expanded_payload_bytes']
    @property
    def count(self): return self.history.accounting()['physical_records']
    @property
    def attempted(self): return self.history.accounting()['physical_write_attempts']
    @property
    def previous(self): return self.history.active.previous
    @property
    def terminal_acknowledged(self): return self.history.terminal

    def save(self, row):
        self.history.save(row)
        if row['type'] == 'session_finished':
            self.cleanup_complete = not row['cleanup_errors']

    def close(self):
        if self.history.closed: return
        if self.history.failed: self.history.abort()
        else: self.history.finish(cleanup_complete=self.cleanup_complete)
