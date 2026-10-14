"""Explicitly supplied two-way sportsbook benchmark without source gathering.

Original selections are validated without relabeling Pinnacle observations.
Decisive probability scope is independent of execution exceptional payouts;
versioned Pinnacle types/readers retain their own contract."""
from dataclasses import dataclass
from fractions import Fraction

from .domain import CanonicalSelection, ExactNumber
from .pinnacle import ReferenceOutcome, ReferenceSet, GROSS_MAXIMUM_AGE
from .current_dependencies import digest, instant

VERSION = 'comparison-two-way-benchmark-1'
METHOD = 'proportional_no_vig'
SPORTSBOOKS = ('pinnacle', 'novig', 'prophetx')


def supported_venue(venue):
    # These are the sportsbooks supported by the existing exact domain. Native
    # binary execution quotes cannot be used as a two-way sportsbook reference.
    return venue in SPORTSBOOKS


@dataclass(frozen=True)
class SportsbookOutcome(ReferenceOutcome):
    def __post_init__(self):
        if not isinstance(self.selection, CanonicalSelection) or not supported_venue(self.selection.native.venue):
            raise ValueError('benchmark_original_sportsbook_selection_required')
        if not isinstance(self.decimal_odds, ExactNumber) or self.decimal_odds.value <= 1:
            raise ValueError('benchmark_original_decimal_odds_required')
        if self.selection.price.unit != 'decimal_odds' or self.selection.price.amount.original != self.decimal_odds.original:
            raise ValueError('benchmark_original_odds_association_conflict')
        if not isinstance(self.revision, str) or not self.revision:
            raise ValueError('benchmark_original_revision_required')
        instant(self.received_at)
        for clock in (self.book_at, self.market_at):
            if clock is not None:
                instant(clock)


@dataclass(frozen=True)
class TwoWayBenchmark(ReferenceSet):
    venue: str = 'pinnacle'
    method: str = METHOD
    source_revision: str = ''

    def __post_init__(self):
        super().__post_init__()
        if not supported_venue(self.venue) or self.method != METHOD or not isinstance(self.source_revision,str) or not 1 <= len(self.source_revision) <= 256:
            raise ValueError('benchmark_venue_method_revision_required')
        if len(self.outcomes) != 2 or self.conditioning != 'decisive_win_loss':
            raise ValueError('benchmark_two_decisive_originals_required')
        first = self.outcomes[0]
        for row in self.outcomes:
            s = row.selection
            role = 'home' if s.participant_id == s.event.home_id else 'away' if s.participant_id == s.event.away_id else None
            if (s.native.venue != self.venue or s.family != 'moneyline' or
                    s.scope.period != 'full_game' or s.scope.overtime != 'included' or s.predicate.domain != 'home_margin' or
                    s.predicate.threshold.value != 0 or role is None or
                    s.predicate.operator != ('gt' if role == 'home' else 'lt')):
                raise ValueError('benchmark_crossed_book_role_or_scope')
            if row.received_at != first.received_at or row.book_at != first.book_at or row.market_at != first.market_at:
                raise ValueError('benchmark_incompatible_observation_revisions')
            if not s.native.evidence or any(e.sha256 != self.receipt_sha256 for e in s.native.evidence):
                raise ValueError('benchmark_original_receipt_evidence_conflict')

    @property
    def revision(self):
        return digest(self.to_dict(include_revision=False))

    def to_dict(self, *, include_revision=True):
        result = dict(version=VERSION, venue=self.venue, method=self.method,
            source_revision=self.source_revision, outcomes=[r.to_dict() for r in self.outcomes],
            receipt_sha256=self.receipt_sha256, conditioning=self.conditioning,
            partition_evidence_sha256=self.partition_evidence_sha256,
            source_at=[r.source_at for r in self.outcomes])
        return dict(result, revision=self.revision) if include_revision else result

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('benchmark_object_required')
        try:
            rows = tuple(SportsbookOutcome(CanonicalSelection.from_dict(r['selection']),
                ExactNumber.parse(r['decimal_odds']), r['book_at'], r['market_at'], r['received_at'], r['revision'])
                for r in value['outcomes'])
            result = cls(rows, value['receipt_sha256'], value['conditioning'],
                value['partition_evidence_sha256'], value['venue'], value['method'], value['source_revision'])
        except (KeyError, TypeError, AttributeError):
            raise ValueError('benchmark_original_fields_required') from None
        if result.to_dict() != value:
            raise ValueError('benchmark_wire_or_revision_conflict')
        return result

    def fair_probabilities(self):
        """Exact proportional no-vig weights shared by calculation and display."""
        implied = {r.selection.participant_id:1/r.decimal_odds.value for r in self.outcomes}
        total = sum(implied.values(), Fraction(0))
        return {participant: value/total for participant, value in implied.items()}

    def clock_status(self, at):
        """Original source/receipt clocks alone establish reference freshness."""
        for row in self.outcomes:
            if row.source_at is None:
                return 'unknown'
            source = instant(row.source_at); receipt = instant(row.received_at)
            if source > receipt or source > at or receipt > at:
                return 'future'
            if (at-source).total_seconds() > GROSS_MAXIMUM_AGE:
                return 'expired'
        return 'current'

    def weight(self, selected, *, at, venue, method):
        if self.venue != venue or self.method != method:
            raise ValueError('selected_benchmark_missing; no substitution')
        for row in self.outcomes:
            s = row.selection
            if s.event.key != selected.event.key or s.scope.period != selected.scope.period:
                raise ValueError('benchmark_occurrence_period_conflict')
        status = self.clock_status(at)
        if status != 'current':
            reason = {'unknown':'source_clock_unknown', 'future':'clock_future', 'expired':'expired'}[status]
            raise ValueError('benchmark_' + reason)
        return self.fair_probabilities()[selected.event.home_id]


def resolve(supplied, selected, policy, at):
    if isinstance(supplied, dict):
        supplied = TwoWayBenchmark.from_dict(supplied)
    if not isinstance(supplied, TwoWayBenchmark):
        raise ValueError('explicit_two_way_benchmark_required')
    return supplied.weight(selected, at=at, venue=policy.benchmark_venue,
                           method=policy.benchmark_method), supplied


def metadata(reference, policy):
    return dict(version=VERSION, venue=policy.benchmark_venue, method=policy.benchmark_method,
        available=reference is not None, revision=None if reference is None else reference.revision,
        originals=[] if reference is None else [r.to_dict() for r in reference.outcomes],
        receipt_sha256=None if reference is None else reference.receipt_sha256,
        conditioning='decisive_home_or_away_win', actual_probability=None)
