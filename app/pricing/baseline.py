"""Receipt-bound proportional de-vig, with an immutable self-contained audit.

The only estimated probabilities are conditional on a normal team-winner result.
Exceptional scenario mass and unconditional target value are deliberately unknown.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal, localcontext, Context, ROUND_HALF_EVEN
import json

from app.edge_contracts import MarketTerms, dumps, loads
from app.models.core import Venue
from app.reference.records import (Receipt, QuoteRevision, SourceRevision, import_records,
                                   as_of, packed, digest, wire)
from app.settlement import compare_profiles, payout, SCENARIOS, VERSION as SETTLEMENT_VERSION
from app.storage.store import exact_time

METHOD = 'proportional-devig-1'
FORMAT = 'fair-price-bundle-1'


@dataclass(frozen=True)
class Policy:
    version: str = 'offline-eligibility-1'
    max_receipt_age_seconds: int = 30
    max_provider_read_age_seconds: int = 45
    pregame_buffer_seconds: int = 1
    time_precision: int = 80
    precision: int = 50
    rounding: str = ROUND_HALF_EVEN
    probability_quantum: str = '0.000000000000000001'
    pairing: str = 'synthetic_verified_only'
    latest_snapshot: str = 'provider_scope_before_eligibility; receipt_time_then_id'
    family_selection: str = 'one_bookmaker_one_family; latest_receipt_then_id'
    target_exclusion: str = 'provider_origin_family_and_all_known_copies'
    freshness_basis: str = 'offline_test_policy; provider_last_read_not_bookmaker_change'
    probability_basis: str = 'conditional_on_normal_team_winner'
    diversity: str = 'one_family_always_degraded'

    def __post_init__(self):
        defaults = {f: getattr(Policy, f) for f in self.__dataclass_fields__}
        configurable = {'max_receipt_age_seconds', 'max_provider_read_age_seconds', 'pregame_buffer_seconds'}
        for name, value in asdict(self).items():
            if name in configurable:
                if type(value) is not int or value <= 0:
                    raise ValueError('positive integer offline time policy required')
            elif value != defaults[name]:
                raise ValueError('unsupported policy parameters/version')


@dataclass(frozen=True)
class Target:
    venue: str
    terms_json: str
    outcome: str
    known_at: str
    effective_at: str
    evidence: tuple[str, ...]
    predicate: str = 'win'

    def __post_init__(self):
        if Venue(self.venue) not in (Venue.KALSHI, Venue.POLYMARKET_US):
            raise ValueError('E3 target scope')
        terms = loads(self.terms_json)
        if not isinstance(terms, MarketTerms) or self.outcome not in terms.outcomes or self.predicate not in ('win', 'not_win'):
            raise ValueError('invalid target contract')
        exact_time(self.known_at); exact_time(self.effective_at)
        if type(self.evidence) is not tuple or not self.evidence or any(not e.startswith('synthetic:') for e in self.evidence):
            raise ValueError('synthetic target assessment evidence required')


def devig(odds, policy=Policy()):
    """50 significant digits, HALF_EVEN; both probabilities rounded to 18 places.

    Original Decimal spellings are retained; no float or ambient-context math.
    """
    if len(odds) != 2 or any(type(x) is not Decimal or not x.is_finite() or x <= 1 for x in odds):
        raise ValueError('two finite decimal odds greater than one required')
    with localcontext(Context(prec=policy.precision, rounding=policy.rounding)):
        implied = tuple(Decimal(1) / x for x in odds)
        total = sum(implied, Decimal(0))
        probabilities = tuple((x / total).quantize(Decimal(policy.probability_quantum)) for x in implied)
        if sum(probabilities) != 1 or any(not 0 <= x <= 1 for x in probabilities):
            raise ValueError('invalid normalized probabilities')
        return {'decimal_odds': [str(x) for x in odds], 'odds_unit': 'gross_return_per_stake',
                'implied_probabilities': [str(x) for x in implied], 'implied_sum': str(total),
                'overround': str(total - 1), 'probabilities': [str(x) for x in probabilities],
                'probability_unit': 'fraction', 'basis': policy.probability_basis}


@dataclass(frozen=True)
class Estimate:
    """Canonical JSON string avoids mutable nested state in an immutable record."""
    payload_json: str

    @property
    def data(self):
        return json.loads(self.payload_json)

    @property
    def id(self):
        return digest(self.data)

    def export(self):
        return packed({'format': FORMAT, 'sha256': self.id, 'payload': self.data})


def calculate(replay, *, target, cutoff, estimated_at, policy=Policy()):
    """Requires a validated E2 as-of bundle, never detached quote objects."""
    with localcontext(Context(prec=policy.time_precision, rounding=policy.rounding)):
        return _calculate(replay, target=target, cutoff=cutoff, estimated_at=estimated_at, policy=policy)


def _calculate(replay, *, target, cutoff, estimated_at, policy):
    records = import_records(replay)
    if as_of(records, cutoff) != replay:
        raise ValueError('input must be exact receipt/knowledge as-of replay')
    limit = exact_time(cutoff)
    if exact_time(estimated_at) < limit:
        raise ValueError('estimate precedes cutoff')
    if max(exact_time(target.known_at), exact_time(target.effective_at)) > limit:
        raise ValueError('target dependency after cutoff')
    terms = loads(target.terms_json)
    global_reasons = []
    if not terms.complete or terms.phase != 'pregame' or terms.league != 'NFL' or terms.period != 'full_game':
        global_reasons.append('unknown_or_unsupported_target_terms')
    if limit >= exact_time(terms.scheduled_start.isoformat()) - policy.pregame_buffer_seconds:
        global_reasons.append('pregame_cutoff_reached')
    receipts = sorted((r for r in records if isinstance(r, Receipt)), key=lambda r: (exact_time(r.received_at), r.id), reverse=True)
    revisions = {r.receipt_id: r for r in records if isinstance(r, QuoteRevision)}
    sources = {r.id: r for r in records if isinstance(r, SourceRevision)}
    seen_paths, families, candidates = set(), set(), []
    chosen = None
    for receipt in receipts:
        rev = revisions.get(receipt.id)
        src = sources.get(rev.source_id) if rev else None
        q = rev.quote if rev else None
        evidence = json.loads(rev.evidence_json) if rev else {}
        reasons = list(global_reasons)
        # E2 scope is fixed provider/event/book; session IDs are delivery paths,
        # never separate opinions. A rejected newest receipt still takes the slot.
        path = receipt.scope
        if path in seen_paths:
            reasons.append('superseded_snapshot')
            if src and src.family in families:
                reasons.append('duplicate_source_family')
        seen_paths.add(path)
        if src and src.family:
            families.add(src.family)
        if limit - exact_time(receipt.received_at) > policy.max_receipt_age_seconds:
            reasons.append('stale_receipt')
        if rev is None:
            reasons.append('no_enrichment_known_at_cutoff')
        else:
            reasons.extend(rev.reasons)
            if max(exact_time(rev.effective_at), exact_time(src.effective_at)) > exact_time(receipt.received_at):
                reasons.append('knowledge_not_effective_at_receipt')
        comparison = None
        if q is None:
            reasons.append('rejected_or_incomplete_snapshot')
        else:
            if evidence.get('pair_evidence') != 'synthetic_verified':
                reasons.append('unknown_pairing')
            if not src.family or not src.origin or src.copied_from is None or not src.evidence:
                reasons.append('unknown_source_lineage')
            if target.venue in (src.provider, src.origin, src.family, *(src.copied_from or ())):
                reasons.append('target_venue_or_known_copy')
            if None in q.decimal_odds:
                reasons.append('missing_paired_outcome')
            source_time = evidence.get('native_time_text')
            if source_time is None:
                reasons.append('unknown_provider_read_time')
            elif exact_time(source_time) > min(limit, exact_time(receipt.received_at)):
                reasons.append('provider_read_after_receipt_or_cutoff')
            elif limit - exact_time(source_time) > policy.max_provider_read_age_seconds:
                reasons.append('stale_provider_read')
            if (q.terms.canonical_event_id, q.terms.canonical_market_id, q.terms.scheduled_start,
                q.terms.outcomes, q.terms.market_type, q.terms.period, q.terms.phase, q.terms.league) != (
                terms.canonical_event_id, terms.canonical_market_id, terms.scheduled_start,
                terms.outcomes, terms.market_type, terms.period, terms.phase, terms.league):
                reasons.append('incompatible_target_identity_or_terms')
            if not q.terms.rules_profile_json or not terms.rules_profile_json:
                reasons.append('unknown_target_or_source_rules')
            else:
                comparison = compare_profiles(json.loads(q.terms.rules_profile_json), json.loads(terms.rules_profile_json))
                if comparison['status'] != 'EXACT':
                    reasons.append('incompatible_or_unknown_target_rules')
        if not reasons and chosen is not None:
            reasons.append('one_family_baseline_limit')
        row = {'receipt_id': receipt.id, 'receipt_sha256': digest(wire(receipt)),
               'enrichment_id': rev.id if rev else None, 'enrichment_sha256': digest(wire(rev)) if rev else None,
               'source_id': src.id if src else None, 'source_sha256': digest(wire(src)) if src else None,
               'family': src.family if src else None, 'rule_comparison': comparison,
               'assessment_sha256': digest(evidence['assessment']) if rev else None,
               'registry_sha256': evidence.get('registry_sha256'),
               'original_odds': [str(x) if x is not None else None for x in q.decimal_odds] if q else None,
               'provider_last_read': evidence.get('native_time_text'), 'bookmaker_change_time': None,
               'included': not reasons, 'reasons': sorted(set(reasons)) or ['eligible_synthetic_pair']}
        candidates.append(row)
        if not reasons:
            chosen = q
    calculation = devig(chosen.decimal_odds, policy) if chosen else None
    conditional = None
    if calculation:
        conditional = calculation['probabilities'][terms.outcomes.index(target.outcome)]
        if target.predicate == 'not_win':
            # Select the other already-rounded probability, avoiding ambient math.
            conditional = calculation['probabilities'][1 - terms.outcomes.index(target.outcome)]
    scenario_payouts = None
    if terms.rules_profile_json:
        profile = json.loads(terms.rules_profile_json)
        side = {'participant': target.outcome, 'predicate': target.predicate}
        scenario_payouts = {s: payout(side, s, profile) for s in [*('winner:' + o for o in terms.outcomes), *SCENARIOS]}
    data = {'method': METHOD, 'policy': asdict(policy), 'settlement_version': SETTLEMENT_VERSION,
            'mode': 'synthetic', 'target': asdict(target), 'as_of': cutoff, 'estimated_at': estimated_at,
            'dependencies': replay, 'candidates': candidates, 'calculation': calculation,
            'status': 'degraded' if calculation else 'unavailable',
            'reasons': ['one_information_family', 'uncalibrated_synthetic_baseline', 'exceptional_probability_mass_unknown'] if calculation else sorted(set(global_reasons + ['no_eligible_pair'])),
            'conditional_target_probability': conditional, 'probability_unit': 'fraction',
            'unconditional_target_probability': None, 'target_fair_value_usd': None,
            'exceptional_probabilities': {s: None for s in SCENARIOS}, 'target_scenario_payouts': scenario_payouts,
            'net_expected_profit': None, 'limits': ['synthetic_pairing_and_lineage_assumptions',
                'offline_freshness_thresholds_not_live_qualified', 'bookmaker_change_time_unknown',
                'no_independent_source_disagreement_or_statistical_uncertainty', 'fees_not_removed_by_devig']}
    return Estimate(packed(data))


def recompute(estimate):
    d = estimate.data
    if d['method'] != METHOD or d['settlement_version'] != SETTLEMENT_VERSION:
        raise ValueError('unsupported calculation version')
    target = dict(d['target']); target['evidence'] = tuple(target['evidence'])
    result = calculate(d['dependencies'], target=Target(**target), cutoff=d['as_of'],
                       estimated_at=d['estimated_at'], policy=Policy(**d['policy']))
    if result != estimate:
        raise ValueError('saved estimate differs from exact recomputation')
    return result


def restore(text):
    value = json.loads(text)
    if value['format'] != FORMAT or digest(value['payload']) != value['sha256']:
        raise ValueError('fair price version/hash mismatch')
    result = Estimate(packed(value['payload']))
    recompute(result)
    if result.export() != text:
        raise ValueError('noncanonical fair price bundle')
    return result
