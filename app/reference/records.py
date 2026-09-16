"""Immutable receipt and knowledge records with exact, versioned serialization."""
from dataclasses import dataclass, asdict
from hashlib import sha256
import base64
import json
from decimal import Decimal

from app.edge_contracts import ReferenceQuote, dumps as edge_dumps, loads as edge_loads
from app.storage.store import exact_time

VERSION = 'reference-bundle-1'
PROVIDER = 'the_odds_api'
EVENT = 'synthetic-atl-pit-e2'
SCOPE = 'synthetic:americanfootball_nfl:synthetic-atl-pit-e2:pinnacle:h2h'


def _json_scalar(value):
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError('unsupported reference JSON value')


def packed(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False, default=_json_scalar)


def digest(v):
    return sha256(packed(v).encode()).hexdigest()


def time_check(*values):
    for value in values:
        if value is not None:
            exact_time(value)


@dataclass(frozen=True, kw_only=True)
class SourceRevision:
    id: str
    effective_at: str
    known_at: str
    family: str | None = None
    origin: str | None = None
    copied_from: tuple[str, ...] | None = None
    evidence: tuple[str, ...] = ()
    provider: str = PROVIDER
    book: str = 'pinnacle'
    mode: str = 'synthetic'

    def __post_init__(self):
        time_check(self.effective_at, self.known_at)
        if type(self.evidence) is not tuple or (self.copied_from is not None and type(self.copied_from) is not tuple):
            raise ValueError('immutable source evidence tuples required')
        if (self.provider, self.book, self.mode) != (PROVIDER, 'pinnacle', 'synthetic'):
            raise ValueError('offline single-source scope required')
        if (self.family is not None or self.origin is not None or self.copied_from is not None) and not self.evidence:
            raise ValueError('assessed source facts require evidence')
        if any(not e.startswith('synthetic:') for e in self.evidence):
            raise ValueError('E2 positive evidence must be explicitly synthetic')


@dataclass(frozen=True, kw_only=True)
class Receipt:
    id: str
    session_id: str
    received_at: str
    request_started_at: str
    body_b64: str
    body_sha256: str
    status: int
    request_json: str
    headers: tuple[tuple[str, str], ...]
    scope: str = SCOPE
    mode: str = 'synthetic'
    entitlement: str | None = None

    def __post_init__(self):
        if type(self.headers) is not tuple or any(type(h) is not tuple or len(h) != 2 for h in self.headers):
            raise ValueError('immutable headers required')
        time_check(self.received_at, self.request_started_at)
        if exact_time(self.request_started_at) > exact_time(self.received_at):
            raise ValueError('request starts after ingress')
        if self.scope != SCOPE or self.mode != 'synthetic':
            raise ValueError('offline synthetic scope required')
        if sha256(self.body).hexdigest() != self.body_sha256:
            raise ValueError('raw body hash mismatch')
        request = json.loads(self.request_json)
        if set(request) != {'path', 'params'} or request != request_metadata():
            raise ValueError('request metadata must be the fixed sanitized scope')
        if any(k not in HEADER_ALLOWLIST for k, _ in self.headers):
            raise ValueError('unsanitized response headers')

    @property
    def body(self):
        return base64.b64decode(self.body_b64, validate=True)


HEADER_ALLOWLIST = {'x-requests-remaining', 'x-requests-used', 'x-requests-last', 'retry-after', 'date'}


def request_metadata():
    return {'path': f'/v4/sports/americanfootball_nfl/events/{EVENT}/odds',
            'params': {'markets': 'h2h', 'bookmakers': 'pinnacle', 'oddsFormat': 'decimal',
                       'dateFormat': 'iso', 'includeSids': 'true'}}


@dataclass(frozen=True, kw_only=True)
class QuoteRevision:
    id: str
    session_id: str
    receipt_id: str
    source_id: str
    known_at: str
    effective_at: str
    quote: ReferenceQuote | None
    reasons: tuple[str, ...]
    evidence_json: str
    version: str = 'reference-enrichment-1'

    def __post_init__(self):
        if type(self.reasons) is not tuple:
            raise ValueError('immutable reasons required')
        time_check(self.known_at, self.effective_at)
        if self.version != 'reference-enrichment-1':
            raise ValueError('unsupported enrichment version')
        json.loads(self.evidence_json)
        if self.quote is not None and self.quote.receipt_id != self.receipt_id:
            raise ValueError('receipt binding mismatch')


@dataclass(frozen=True, kw_only=True)
class ReferenceGap:
    id: str
    session_id: str
    detected_at: str
    reason: str
    receipt_id: str | None = None
    prior_gap_id: str | None = None
    last_success_at: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    recovery: str = 'unresolved'
    scope: str = SCOPE

    def __post_init__(self):
        time_check(self.detected_at, self.last_success_at, self.start_at, self.end_at)
        if self.scope != SCOPE or self.start_at is not None:
            raise ValueError('outage onset is unknown for sampled E2 polling')
        if self.recovery == 'fresh_snapshot' and (not self.receipt_id or not self.prior_gap_id or self.end_at != self.detected_at):
            raise ValueError('recovery needs a new receipt and earlier failure binding')


TYPES = {c.__name__: c for c in (SourceRevision, Receipt, QuoteRevision, ReferenceGap)}


def wire(record):
    if type(record).__name__ not in TYPES:
        raise ValueError('unsupported reference record')
    data = asdict(record)
    if isinstance(record, QuoteRevision):
        data['quote'] = edge_dumps(record.quote) if record.quote is not None else None
    return {'type': type(record).__name__, 'data': data}


def unwire(value):
    cls = TYPES[value['type']]
    data = dict(value['data'])
    for k in ('copied_from', 'evidence', 'reasons'):
        if k in data and data[k] is not None:
            data[k] = tuple(data[k])
    if cls is Receipt:
        data['headers'] = tuple(tuple(x) for x in data['headers'])
    if cls is QuoteRevision and data['quote'] is not None:
        data['quote'] = edge_loads(data['quote'])
    return cls(**data)


def validate_bindings(records):
    sources, receipts, gaps = {}, {}, {}
    seen = set()
    for r in records:
        key = (type(r).__name__, r.id)
        if key in seen:
            raise ValueError('duplicate record identity')
        seen.add(key)
        if isinstance(r, SourceRevision): sources[r.id] = r
        if isinstance(r, Receipt): receipts[r.id] = r
        if isinstance(r, ReferenceGap): gaps[r.id] = r
    for r in records:
        if isinstance(r, QuoteRevision):
            receipt, source = receipts[r.receipt_id], sources[r.source_id]
            if r.session_id != receipt.session_id or exact_time(r.known_at) < max(exact_time(receipt.received_at), exact_time(source.known_at)):
                raise ValueError('revision precedes its receipt/source knowledge')
            if exact_time(source.effective_at) > exact_time(receipt.received_at):
                raise ValueError('source not effective at receipt')
            from .enrichment import replay_revision
            replay_revision(receipt, source, r)
            if r.quote and (r.quote.raw_json.encode() != receipt.body or r.quote.received_at.isoformat() != receipt.received_at):
                raise ValueError('quote/raw ingress binding mismatch')
        if isinstance(r, ReferenceGap):
            if r.receipt_id and (receipts[r.receipt_id].session_id != r.session_id or exact_time(receipts[r.receipt_id].received_at) > exact_time(r.detected_at)):
                raise ValueError('gap receipt binding mismatch')
            if r.prior_gap_id and (gaps[r.prior_gap_id].session_id != r.session_id or exact_time(gaps[r.prior_gap_id].detected_at) > exact_time(r.detected_at)):
                raise ValueError('recovery precedes gap')


def export_records(records):
    records = tuple(records)
    validate_bindings(records)
    payload = {'format': VERSION, 'records': sorted((wire(r) for r in records), key=lambda r: (r['type'], r['data']['id']))}
    return packed({'sha256': digest(payload), 'payload': payload})


def import_records(text):
    envelope = json.loads(text)
    payload = envelope['payload']
    if payload['format'] != VERSION or digest(payload) != envelope['sha256']:
        raise ValueError('reference bundle version/hash mismatch')
    records = tuple(unwire(r) for r in payload['records'])
    validate_bindings(records)
    return records


def as_of(records, cutoff):
    """Inclusive receipt AND knowledge cutoff; latest known enrichment per receipt."""
    records = tuple(records)
    validate_bindings(records)
    limit = exact_time(cutoff)
    sources = {r.id: r for r in records if isinstance(r, SourceRevision) and exact_time(r.known_at) <= limit and exact_time(r.effective_at) <= limit}
    receipts = {r.id: r for r in records if isinstance(r, Receipt) and exact_time(r.received_at) <= limit}
    revisions = {}
    for r in records:
        if isinstance(r, QuoteRevision) and r.receipt_id in receipts and r.source_id in sources and exact_time(r.known_at) <= limit and exact_time(r.effective_at) <= limit:
            old = revisions.get(r.receipt_id)
            if old is None or (exact_time(r.known_at), r.id) > (exact_time(old.known_at), old.id): revisions[r.receipt_id] = r
    gaps = [r for r in records if isinstance(r, ReferenceGap) and exact_time(r.detected_at) <= limit]
    return export_records([*sources.values(), *receipts.values(), *revisions.values(), *gaps])
