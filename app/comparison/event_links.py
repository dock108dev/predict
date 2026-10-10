"""Bounded evidenced occurrence edges. No title/time inference or acquisition.

Provider IDs are durable source-local identities. A cross-provider occurrence
requires an explicit, independently versioned edge with roles and applicability.
Historical sport event_key functions remain sealed historical contracts.
"""
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

VERSION = 'comparison-event-links-1'
MAX_EDGES = 256
MAX_REVIEWS = 64


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Exact edge instant required')
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('Edge timezone required')
    return at.astimezone(timezone.utc)


@dataclass(frozen=True)
class ProviderEdge:
    provider: str
    provider_event_id: str
    occurrence_id: str
    league: str
    home_id: str
    away_id: str
    source_sha256: str
    observed_at: str
    effective_from: str
    effective_until: str | None
    evidence_class: str
    review_class: str
    supersedes: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ('provider', 'provider_event_id', 'occurrence_id', 'league', 'home_id', 'away_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError('Bounded exact provider identity required')
        if self.home_id == self.away_id:
            raise ValueError('Distinct occurrence roles required')
        if len(self.source_sha256) != 64 or any(c not in '0123456789abcdef' for c in self.source_sha256):
            raise ValueError('Edge source hash required')
        instant(self.observed_at)
        start = instant(self.effective_from)
        if self.effective_until is not None and instant(self.effective_until) <= start:
            raise ValueError('Positive edge effective interval required')
        if self.evidence_class not in ('authored', 'retained_reviewed', 'source_documented') or self.review_class not in ('manual_review', 'shared_provider_id'):
            raise ValueError('Explicit edge evidence and confidence class required')
        if len(self.supersedes) > 8 or len(set(self.supersedes)) != len(self.supersedes):
            raise ValueError('Bounded distinct supersession edges required')

    @property
    def id(self):
        return digest(asdict(self))

    def active(self, at):
        return instant(self.observed_at) <= at and instant(self.effective_from) <= at and (self.effective_until is None or at < instant(self.effective_until))


class EventLinks:
    def __init__(self, edges=()):
        edges = tuple(edges)
        if len(edges) > MAX_EDGES or len({e.id for e in edges}) != len(edges):
            raise ValueError('Bounded unique occurrence edges required')
        self.edges = edges
        by_id = {e.id: e for e in edges}
        for e in edges:
            for previous in e.supersedes:
                old = by_id.get(previous)
                if old is None or (old.provider, old.provider_event_id) != (e.provider, e.provider_event_id) or instant(e.effective_from) <= instant(old.effective_from) or instant(e.observed_at)<instant(old.observed_at):
                    raise ValueError('Explicit older same-provider supersession required')
        self.pending_reviews = {}

    def resolve(self, provider, native_id, league, home, away, at):
        if at.tzinfo is None:
            raise ValueError('Evaluation timezone required')
        candidates = [e for e in self.edges if e.provider == provider and e.provider_event_id == native_id]
        active = [e for e in candidates if e.active(at)]
        # Supersession consumes prior applicability across the entire registry.
        # An expired successor cannot resurrect an older open-ended edge.
        superseded = {old for e in self.edges if instant(e.observed_at)<=at and instant(e.effective_from)<=at for old in e.supersedes}
        active = [e for e in active if e.id not in superseded]
        if not active:
            return None, 'provider_edge_expired_or_not_effective' if candidates else 'provider_edge_review_required'
        if len({(e.occurrence_id, e.league, e.home_id, e.away_id) for e in active}) != 1:
            return None, 'provider_edge_conflict'
        if any((e.league, e.home_id, e.away_id) != (league, home, away) for e in active):
            return None, 'provider_edge_role_conflict'
        # One occurrence cannot acquire contradictory roles through another edge.
        e = active[-1]
        peers = [p for p in self.edges if p.occurrence_id == e.occurrence_id and p.active(at) and p.id not in superseded]
        if any((p.league, p.home_id, p.away_id) != (league, home, away) for p in peers):
            return None, 'occurrence_edge_conflict'
        return e, None

    def review(self, provider, native_id, evidence_sha256, reason):
        if any(not isinstance(v,str) or not v or len(v)>256 for v in (provider,native_id)):
            raise ValueError('Bounded review identity required')
        if len(evidence_sha256) != 64 or any(c not in '0123456789abcdef' for c in evidence_sha256):
            raise ValueError('Review input evidence hash required')
        if reason not in ('provider_edge_review_required', 'provider_edge_conflict', 'provider_edge_role_conflict', 'occurrence_edge_conflict', 'provider_edge_expired_or_not_effective'):
            raise ValueError('Exact local review reason required')
        key = digest([provider, native_id, evidence_sha256])
        if key not in self.pending_reviews and len(self.pending_reviews) >= MAX_REVIEWS:
            raise ValueError('Occurrence review queue bound')
        self.pending_reviews[key] = dict(provider=provider, native_event_id=native_id, evidence_sha256=evidence_sha256, reason=reason, status='unresolved')
        return deepcopy(self.pending_reviews[key])

    def reference(self, edge):
        from .domain import EventReference, EvidenceReference
        if edge not in self.edges:raise ValueError('Registry-owned occurrence edge required')
        mode={'authored':'authored','retained_reviewed':'retained','source_documented':'primary_source'}[edge.evidence_class]
        return EventReference(edge.occurrence_id,edge.league,edge.home_id,edge.away_id,
            (EvidenceReference('provider-edge:'+edge.id,edge.source_sha256,mode),))

    def to_dict(self):
        return dict(version=VERSION, edges=[asdict(e) for e in self.edges])

    @classmethod
    def from_dict(cls, value):
        if value.get('version') != VERSION or set(value) != {'version', 'edges'}:
            raise ValueError('Versioned exact occurrence registry required')
        return cls(ProviderEdge(**dict(e, supersedes=tuple(e.get('supersedes', ())))) for e in value['edges'])


def reviewed_links():
    """Dated retained evidence only; never extends its elapsed applicability."""
    path = Path(__file__).resolve().parents[1] / 'fixtures/comparison-event-links-v1.json'
    return EventLinks.from_dict(json.loads(path.read_text())['retained_registry'])


def provider_key(provider, event):
    """Stable source-local identity; schedule, score, and status are metadata."""
    fields = [event.get(k) for k in ('competition', 'id', 'home', 'away')]
    if any(not isinstance(v, str) or not v for v in fields) or fields[2] == fields[3]:
        raise ValueError('Exact provider event and roles required')
    return ['comparison-provider-occurrence-1', provider, *fields]


def current_event_key(event):
    """Current reviewed occurrences use shared IDs; old keys stay historical."""
    from app.resolution.core import event_key
    baseline=deepcopy(event)
    # The historical contract validates the evidenced original occurrence. Current
    # schedule/status are independently versioned metadata and payout eligibility.
    baseline['scheduled_start']=baseline['original_start']
    baseline['schedule_status']='scheduled'
    event_key(baseline)
    return ['comparison-reviewed-occurrence-1', event['competition'], event['game_id'], event['home'], event['away'], event.get('game_number')]


def semantic_market(record):
    market = deepcopy(record['market_identity'])
    market.pop('scheduled_start', None)
    return market
