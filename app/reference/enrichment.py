"""Reference identity boundary reusing the normalization and event/rule matchers.

No ReferenceQuote is converted to a Venue, native executable market, or book.
"""
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
import json
from uuid import uuid4

from app.edge_contracts import MarketTerms, ReferenceQuote, dumps as edge_dumps, loads as edge_loads
from app.models.core import MarketType, reject_constant
from app.normalization.registry import Registry
from app.matching import compare
from app.moneyline import rule_binding
from app.settlement import compare_profiles
from app.storage.store import exact_time
from .records import EVENT, PROVIDER, QuoteRevision, packed, digest

PAIR_ASSUMPTION = 'synthetic:paired-snapshot-assessed'


@dataclass(frozen=True, kw_only=True)
class Assessment:
    """Receipt-bound knowledge, supplied explicitly; never learned during parsing."""
    known_at: str
    effective_at: str
    target: MarketTerms
    rules_json: str | None = None
    pairing_verified: bool = False
    evidence: tuple[str, ...] = ()
    phase: str = 'unknown'
    period: str | None = None

    def __post_init__(self):
        exact_time(self.known_at); exact_time(self.effective_at)
        if self.phase not in ('unknown', 'pregame'):
            raise ValueError('offline pregame assessment only')
        if (self.pairing_verified or self.rules_json or self.phase == 'pregame' or self.period) and (not self.evidence or any(not e.startswith('synthetic:') for e in self.evidence)):
            raise ValueError('positive fixture facts require invented synthetic evidence')


def parse_body(receipt):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('duplicate_json_key')
            result[key] = value
        return result
    result = json.loads(receipt.body, parse_float=Decimal, parse_int=Decimal,
                        parse_constant=reject_constant, object_pairs_hook=unique)
    if not isinstance(result, dict): raise ValueError('malformed_response')
    return result


def enrich(receipt, source, assessment, *, registry=None, revision_id=None):
    registry = registry or Registry.load()
    reasons, quote = [], None
    evidence = {'normalizer': registry.version, 'registry_sha256': registry.fingerprint,
                'registry_json': registry.to_json(), 'odds_conversion': 'exact-native-decimal-1',
                'target_terms': edge_dumps(assessment.target),
                'assessment': {'known_at': assessment.known_at, 'effective_at': assessment.effective_at,
                    'evidence': assessment.evidence, 'rules_json': assessment.rules_json,
                    'phase': assessment.phase, 'period': assessment.period},
                'pair_evidence': 'synthetic_verified' if assessment.pairing_verified else 'co_delivered_only',
                'upstream_synchronization': 'invented test assumption' if assessment.pairing_verified else None,
                'side_timestamps': [None, None], 'native_id_kinds': {'event': 'provider_id', 'market': 'scoped_key', 'outcomes': 'label', 'sid': 'optional_provider_id'},
                'source_revision_sha256': digest(asdict(source))}
    known = max((assessment.known_at, source.known_at, receipt.received_at), key=exact_time)
    try:
        if receipt.status != 200: raise ValueError('http_status_' + str(receipt.status))
        if (assessment.target.market_type != MarketType.MONEYLINE or assessment.target.period != 'full_game'
                or assessment.target.phase != 'pregame'):
            raise ValueError('incompatible_target_terms')
        data = parse_body(receipt)
        evidence['historical_snapshot'] = {k: data.get(k) for k in ('timestamp', 'previous_timestamp', 'next_timestamp')}
        event = data.get('data', data)
        if not isinstance(event, dict): raise ValueError('malformed_event')
        if event.get('id') != EVENT or event.get('sport_key') != 'americanfootball_nfl': raise ValueError('missing_or_wrong_event_identity')
        if event.get('phase') not in (None, 'pregame') or event.get('status') not in (None, 'scheduled'):
            raise ValueError('phase_unresolved')
        try:
            start = datetime.fromisoformat(event['commence_time'].replace('Z', '+00:00'))
            exact_time(event['commence_time'])
        except (KeyError, ValueError, AttributeError, TypeError) as exc:
            raise ValueError('schedule_unresolved') from exc
        if exact_time(receipt.received_at) >= exact_time(event['commence_time']): raise ValueError('kickoff_reached')
        names = (event.get('home_team'), event.get('away_team'))
        if any(not isinstance(n, str) or not n.strip() for n in names): raise ValueError('missing_participant_identity')
        resolved = tuple(registry.resolve('team', n, league='NFL') for n in names)
        evidence['participant_mapping'] = [asdict(r) for r in resolved]
        ids = tuple(r.canonical_id for r in resolved)
        if any(r.status != 'resolved' for r in resolved) or len(set(ids)) != 2: raise ValueError('ambiguous_or_missing_participants')
        # Existing matcher with exact schedule policy. Target identity is an assessment,
        # not a new canonical invented from a provider title.
        base = {'scope': ['synthetic', 'reference'], 'league': 'NFL', 'valid_identity': True,
                'registry': [(registry.version, registry.fingerprint)], 'roles': {},
                'role_conflict': False, 'uninterpreted_roles': [], 'schedule_status': 'known', 'game_number': None}
        native = dict(base, participants=sorted(ids), start=start.isoformat())
        target = dict(base, participants=sorted(assessment.target.outcomes), start=assessment.target.scheduled_start.isoformat(), league=assessment.target.league)
        status, match_reasons = compare(native, target, 0)
        evidence['event_match'] = {'status': status, 'reasons': match_reasons, 'native': native, 'target': target,
                                   'canonical_event_id': assessment.target.canonical_event_id,
                                   'canonical_market_id': assessment.target.canonical_market_id}
        if status != 'matched': raise ValueError('schedule_or_identity_unresolved')
        if assessment.phase != 'pregame': reasons.append('phase_unresolved')
        if assessment.period != 'full_game': reasons.append('period_unresolved')
        books = event.get('bookmakers', [])
        if not isinstance(books, list): raise ValueError('malformed_bookmakers')
        if len(books) != 1 or books[0].get('key') != 'pinnacle': raise ValueError('missing_or_unsupported_book')
        book = books[0]
        markets = book.get('markets', [])
        if len(markets) != 1 or markets[0].get('key') != 'h2h': raise ValueError('missing_or_unsupported_market')
        market = markets[0]
        if market.get('point') is not None or market.get('period') not in (None, 'full_game'): raise ValueError('incompatible_market_terms')
        outcomes = market.get('outcomes', [])
        if not isinstance(outcomes, list) or len(outcomes) > 2: raise ValueError('unsupported_outcome_count')
        mapped = {}
        for outcome in outcomes:
            if outcome.get('point') is not None: raise ValueError('unsupported_outcome_terms')
            name = outcome.get('name')
            if not isinstance(name, str): raise ValueError('missing_outcome_identity')
            resolved_outcome = registry.resolve('team', name, league='NFL')
            identity = resolved_outcome.canonical_id
            if resolved_outcome.status != 'resolved' or identity not in ids: raise ValueError('unsupported_outcome_identity')
            if identity in mapped: raise ValueError('duplicate_outcome')
            price = outcome.get('price')
            if price is not None and (not isinstance(price, (Decimal, str)) or isinstance(price, bool)):
                raise ValueError('invalid_decimal_price')
            price = Decimal(price) if price is not None else None
            if price is not None and (not price.is_finite() or price <= 1): raise ValueError('invalid_decimal_price')
            mapped[identity] = (name, price, outcome.get('sid'))
        ordered = assessment.target.outcomes
        fallback_names = dict(zip(ids, names))
        slots = [mapped.get(i, (fallback_names[i], None, None)) for i in ordered]
        if any(s[1] is None for s in slots): reasons.append('missing_paired_outcome')
        source_text = market.get('last_update')
        if source_text is not None: exact_time(source_text)
        evidence.update(native_sids={'bookmaker_event': book.get('sid'), 'market': market.get('sid'), 'outcomes': [s[2] for s in slots]},
                        native_time_text=source_text, bookmaker_time_text=book.get('last_update'),
                        source_time_meaning='provider last-read; not bookmaker last-change', timestamp_precision='as supplied in raw text',
                        optional_bet_limits=[o.get('bet_limit') for o in outcomes])
        if not assessment.pairing_verified: reasons.append('unverified_pairing')
        if source.family is None or source.origin is None or source.copied_from is None or not source.evidence: reasons.append('unknown_source_lineage')
        rules = assessment.rules_json
        if rules is None: reasons.append('unknown_rules')
        else:
            profile = json.loads(rules)
            target_profile = json.loads(assessment.target.rules_profile_json) if assessment.target.rules_profile_json else None
            compatibility = compare_profiles(profile, target_profile) if target_profile else {'status': 'UNKNOWN'}
            evidence['rule_comparison'] = compatibility
            evidence['rule_binding'] = rule_binding({'event': EVENT, 'market': 'h2h'}, PROVIDER, ['synthetic', 'reference'], profile)
            if compatibility['status'] != 'EXACT': reasons.append('incompatible_or_unknown_rules')
        if exact_time(assessment.effective_at) > exact_time(receipt.received_at): reasons.append('assessment_not_effective')
        terms = MarketTerms(canonical_event_id=assessment.target.canonical_event_id,
            canonical_market_id=assessment.target.canonical_market_id, league='NFL', scheduled_start=start,
            market_type=MarketType.MONEYLINE, period=assessment.period, phase=assessment.phase,
            outcomes=ordered, line=None, rules_profile_json=rules)
        quote = ReferenceQuote(receipt_id=receipt.id, provider=PROVIDER, underlying_source=source.origin,
            source_family=source.family, copied_from=source.copied_from,
            identity_evidence=source.evidence + ((PAIR_ASSUMPTION,) if assessment.pairing_verified else ()),
            native_event_id=EVENT, native_market_id=f'{PROVIDER}:{EVENT}:pinnacle:h2h',
            native_outcome_ids=tuple(s[0] for s in slots), terms=terms, decimal_odds=tuple(s[1] for s in slots),
            source_at=datetime.fromisoformat(source_text.replace('Z', '+00:00')) if source_text else None,
            received_at=datetime.fromisoformat(receipt.received_at), source_time_semantics='snapshot' if source_text else 'unknown',
            raw_source='synthetic:' + json.loads(receipt.request_json)['path'], raw_json=receipt.body.decode('utf-8'),
            mode='synthetic', coverage='sampled polling only; unseen upstream changes unknown', permitted_use_evidence=None,
            limits=None, unknowns=tuple(reasons) + ('limits_unknown', 'live_entitlement_unverified', 'source_clock_accuracy_unknown'))
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError, UnicodeError) as exc:
        reasons.append(str(exc) if isinstance(exc, ValueError) else 'malformed_response:' + type(exc).__name__)
    return QuoteRevision(id=revision_id or str(uuid4()), session_id=receipt.session_id, receipt_id=receipt.id,
                         source_id=source.id, known_at=known, effective_at=assessment.effective_at,
                         quote=quote, reasons=tuple(reasons), evidence_json=packed(evidence))


def replay_revision(receipt, source, revision):
    """Re-run matching from the exact retained registry/knowledge, never today's files."""
    evidence = json.loads(revision.evidence_json)
    assessment_data = evidence['assessment']
    assessed = Assessment(known_at=assessment_data['known_at'], effective_at=assessment_data['effective_at'],
        target=edge_loads(evidence['target_terms']), rules_json=assessment_data['rules_json'],
        pairing_verified=evidence['pair_evidence'] == 'synthetic_verified',
        phase=assessment_data['phase'], period=assessment_data['period'], evidence=tuple(assessment_data['evidence']))
    reproduced = enrich(receipt, source, assessed, registry=Registry(json.loads(evidence['registry_json'])), revision_id=revision.id)
    if reproduced != revision:
        raise ValueError('enrichment replay differs from retained evidence')
    return reproduced
