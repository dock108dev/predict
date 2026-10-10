"""Typed exact reference inputs. Existing gross engine and shared feed remain owners."""
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from .domain import CanonicalSelection, ExactNumber
from .event_links import digest, instant

VERSION='comparison-pinnacle-inputs-1'
GROSS_MAXIMUM_AGE=1800


@dataclass(frozen=True)
class ReferenceOutcome:
    selection: CanonicalSelection
    decimal_odds: ExactNumber
    book_at: str | None
    market_at: str | None
    received_at: str
    revision: str

    def __post_init__(self):
        if not isinstance(self.selection,CanonicalSelection) or self.selection.native.venue!='pinnacle':
            raise ValueError('Exact Pinnacle selection required')
        if not isinstance(self.decimal_odds,ExactNumber) or self.decimal_odds.value<=1:
            raise ValueError('Original decimal odds greater than one required')
        if self.selection.price.unit!='decimal_odds' or self.selection.price.amount.original!=self.decimal_odds.original:
            raise ValueError('Original reference odds association conflict')
        instant(self.received_at)
        for at in (self.book_at,self.market_at):
            if at is not None:instant(at)
        if not isinstance(self.revision,str) or not self.revision:raise ValueError('Exact reference revision required')

    @property
    def source_at(self):
        return self.market_at if self.market_at is not None else self.book_at

    def to_dict(self):
        return dict(selection=self.selection.to_dict(),decimal_odds=self.decimal_odds.original,
            book_at=self.book_at,market_at=self.market_at,received_at=self.received_at,revision=self.revision)


@dataclass(frozen=True)
class ReferenceSet:
    outcomes: tuple[ReferenceOutcome,...]
    receipt_sha256: str
    conditioning: str
    partition_evidence_sha256: str | None = None

    def __post_init__(self):
        if not isinstance(self.outcomes,tuple) or len(self.outcomes) not in (2,3):raise ValueError('Complete bounded reference outcomes required')
        if any(not isinstance(x,ReferenceOutcome) for x in self.outcomes):raise ValueError('Typed reference outcome required')
        if not isinstance(self.receipt_sha256,str):raise ValueError('Reference receipt hash required')
        for h in (self.receipt_sha256,self.partition_evidence_sha256):
            if h is not None and (not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h)):raise ValueError('Exact reference evidence hash required')
        first=self.outcomes[0].selection
        for item in self.outcomes:
            s=item.selection
            if s.event.key!=first.event.key or s.scope.key!=first.scope.key or s.family!=first.family or s.native.market_id!=first.native.market_id:
                raise ValueError('Reference occurrence/family/scope/market conflict')
            if s.predicate.domain!=first.predicate.domain or s.predicate.subject_id!=first.predicate.subject_id or s.predicate.threshold.value!=first.predicate.threshold.value:
                raise ValueError('Exact reference line/domain conflict')
            if s.native.event_id!=first.native.event_id:raise ValueError('Reference provider event conflict')
        if len({x.selection.native.key for x in self.outcomes})!=len(self.outcomes):raise ValueError('Duplicate reference instruments')
        operators={x.selection.predicate.operator for x in self.outcomes}
        if len(self.outcomes)==2:
            if self.conditioning!='decisive_win_loss' or operators!={'gt','lt'}:
                raise ValueError('Exact disjoint decisive reference opposition required')
        else:
            if self.conditioning!='explicit_three_way' or self.partition_evidence_sha256 is None or operators!={'gt','eq','lt'}:
                raise ValueError('Evidenced disjoint exhaustive three-way partition required')
            if first.family!='moneyline' or first.predicate.domain!='home_margin' or first.predicate.threshold.value!=0:
                raise ValueError('Supported explicit home/draw/away partition required')

    @property
    def revision(self):
        return digest(dict(version=VERSION,outcomes=[x.to_dict() for x in self.outcomes],receipt=self.receipt_sha256,
            conditioning=self.conditioning,partition=self.partition_evidence_sha256))


def bind(selection:CanonicalSelection, reference:ReferenceSet, at:datetime):
    """Return typed originals and conditional weights, or a short local reason."""
    if not isinstance(at,datetime) or at.tzinfo is None:raise ValueError('Aware reference evaluation instant required')
    missing=lambda reason:dict(schema=VERSION,available=False,reason=reason,reference_revision=reference.revision,
        selected_odds=None,probabilities=None)
    try:target=selection.semantic_key()
    except ValueError:return missing('selection_scope_unresolved')
    family=lambda s:'winner' if s.family in ('moneyline','team_binary') else s.family
    matches=[i for i,x in enumerate(reference.outcomes) if x.selection.semantic_key()==target and family(x.selection)==family(selection)]
    if len(matches)!=1:return missing('exact_reference_selection_missing')
    for x in reference.outcomes:
        if x.source_at is None:return missing('reference_source_clock_unknown')
        age=(at-instant(x.source_at)).total_seconds()
        if age<0 or instant(x.received_at)>at:return missing('reference_clock_future')
        if age>GROSS_MAXIMUM_AGE:return missing('reference_expired')
    i=matches[0]
    implied=tuple(Fraction(1,x.decimal_odds.value) for x in reference.outcomes)
    weights=tuple(x/sum(implied) for x in implied)
    return dict(schema=VERSION,available=True,reason=None,reference_revision=reference.revision,
        receipt_sha256=reference.receipt_sha256,selected_index=i,selected_odds=reference.outcomes[i].decimal_odds.original,
        original_odds=[x.decimal_odds.original for x in reference.outcomes],
        source_clocks=[dict(book=x.book_at,market=x.market_at,selected=x.source_at,received=x.received_at) for x in reference.outcomes],
        probabilities=[str(x) for x in weights],conditioning=reference.conditioning,
        unknown_mass=(['exceptional']+(['tie'] if family(selection)=='winner' else ['push'] if selection.predicate.threshold.value.denominator==1 else [])) if len(weights)==2 else ['exceptional'],maximum_age_seconds=GROSS_MAXIMUM_AGE)
