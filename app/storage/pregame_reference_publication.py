"""Prepare a common sportsbook snapshot before valuing any placement offer."""
from collections import defaultdict
from functools import lru_cache
from hashlib import sha256
from fractions import Fraction
import json

from app.comparison import pregame_reference as model
from app.comparison.cashflows import exact_wire
from app.comparison.public_sportsbook_estimate import outcome, signature
from app.comparison.sgo_rule_evidence import RULES, owned_bindings, settlement_key
from app.dashboard.current_contract import price
from .store import hashed, stamp
from .sgo_schedule_review import canonical_roles


def reviewed_rules():
    registry = owned_bindings()
    body = RULES.read_bytes()
    rules = json.loads(body)
    digest = sha256(body).hexdigest()

    def resolve(observation, book, family, legs, at):
        if observation['source'] != 'sportsgameodds' or stamp(rules['reviewed_at']) > at:
            return None
        league = observation['market']['league'] if 'market' in observation else observation['league']
        matches = [registry.resolve(dict(leg, provider=observation['source'], venue=book,
            event_id=observation['event_id'], frame_id=observation['frame_id'], league=league,
            market=family, period='game'), at.isoformat()) for leg in legs]
        if not all(matches) or len({identity['jurisdiction'] for identity, _ in matches}) != 1:
            return None
        if any(stamp(witness['effective_from']) > stamp(leg['source_at'])
               for leg, (_, witness) in zip(legs, matches, strict=True)):
            return None
        jurisdiction = matches[0][0]['jurisdiction']
        profile = rules['profiles'].get(book + ':' + jurisdiction, {})
        settlement = settlement_key(league, family, 'game')
        rule = profile.get('settlement_profiles', {}).get(settlement)
        if not rule:
            return None
        return dict(rule, evidence=dict(source_url=profile['source'], version=rules['version'],
            rules_sha256=digest, reviewed_at=rules['reviewed_at'], jurisdiction=jurisdiction,
            market_reviews=[witness['evidence_sha256'] for _, witness in matches]))

    return resolve


def prior_snapshots(quotes):
    partitions = defaultdict(dict)
    for row in quotes:
        reference = row.get('pregame_reference') or {}
        item = reference if reference.get('available') else reference.get('observed_snapshot')
        if not item:
            continue
        market = item['market']
        key = (market['league'], stamp(market['kickoff']), market['home'], market['away'])
        partitions[key][item['snapshot_id']] = item
    return {key: tuple(items.values()) for key, items in partitions.items()}


def occurrence_key(event, provider, *, at):
    occurrence = signature(event, event['competition'])
    return canonical_roles(event['id'], occurrence, at=at) if provider == 'sportsgameodds' else occurrence


def venue_rules(row):
    binding = row.get('sgo_native_contract') or {}
    if row['venue'] == 'novig' and row['source']['provider'] == 'sportsgameodds':
        if not binding.get('available'):
            return None, binding.get('reason') or 'sgo_native_catalog_unavailable'
        if not binding.get('phase_verified'):
            return None, 'sgo_native_catalog_phase_or_quote_unverified'
        rule = binding['settlement']
        if not rule.get('available'):
            return None, rule.get('reason')
        family = (row['original_record']['market_identity'])['family']
        return dict(rule, outcomes=list(model.ORDINARY_OUTCOMES[family]),
                    evidence=dict(version=binding['version'], catalog_revision=binding['revision'],
                                  source_url=rule['source_url'], market_receipt=binding['market_receipt'])), None
    record = row['original_record']
    native = row.get('native_contract') or {}
    contract = native.get('same_outcome') or {}
    if (row.get('binding') or {}).get('verified') and contract.get('reason') is None:
        market = record['market_identity']
        scoring = contract.get('scoring') or {}
        equality = contract.get('equality') or {}
        evidence = contract.get('predicate_evidence') or (record.get('comparison_source_metadata') or {}).get('scoring_scope')
        treatment = equality.get('treatment')
        if (market.get('period') == 'full_game' and market.get('family') in model.ORDINARY_OUTCOMES
                and evidence and scoring and treatment in ('not_feasible', 'stake_refund')):
            refund = market['family'] == 'moneyline' and 'draw_refund' or 'push_refund'
            return dict(available=True, scope='completed_full_game',
                **{key: scoring.get(key) for key in model.SCORING if key != 'scope'},
                outcomes=list(model.ORDINARY_OUTCOMES[market['family']]),
                equality=refund if treatment == 'stake_refund' else 'not_possible',
                equality_cashflow='full_outlay' if equality.get('refund_fees') == 'returned' else None,
                evidence=dict(version=row['source'].get('binding_version'), rule=evidence)), None
    return None, 'venue_settlement_rules_unverified'


def publish(inputs, observations, previous, *, rules_for=None):
    at = stamp(inputs['captured_at'])
    rules_for = rules_for if rules_for is not None else reviewed_rules()
    if 'pregame_refund_models' not in inputs:
        policies = json.loads(RULES.read_bytes())
        inputs['pregame_refund_models'] = policies.get('refund_probability_models', [])
    refund_models = inputs['pregame_refund_models']

    @lru_cache(maxsize=None)
    def selected(occurrence, family, side, signed_line, partition, scoring_partition):
        return model.selection(occurrence, family, side, signed_line,
            observations.get(occurrence, ()), at=at, rules_for=rules_for,
            previous=previous.get(occurrence, ()), outcomes=partition, scoring_partition=scoring_partition)

    for row in inputs['quotes']:
        record = row['original_record']
        if stamp(row['start_at']) <= at:
            continue
        from app.comparison.game_phase import original_price_phase

        lifecycle = original_price_phase(record, at)
        if lifecycle['state'] != 'scheduled':
            continue
        row.pop('sportsbook_baseline', None)
        event, market = record['event'], record['market_identity']
        occurrence = occurrence_key(event, row['source']['provider'], at=at)
        family = market.get('family')
        selection = record['selection']
        venue, venue_reason = venue_rules(row)
        ref = dict(available=False, reason='reference_selected_outcome_unverified', policy_version=model.VERSION)
        if market.get('period') == 'full_game' and family in model.ORDINARY_OUTCOMES:
            selection_key = outcome(family, selection, event['home'], event['away'])
            if family == 'moneyline' and selection.get('predicate') == 'draw' and not selection.get('participant'):
                selection_key = family, 'draw', None
            # A named participant's NO is not the other team's winner, even
            # when its cash flows could agree in a narrower scenario.
            if selection.get('result_interpretation') in (None, 'normal_win') and selection_key:
                _, side, signed_line = selection_key
                partition = tuple(venue['outcomes']) if venue and venue.get('outcomes') else None
                score_partition = tuple((key, venue[key]) for key in (*model.SCORING, 'equality')
                                        if venue and key in venue)
                if side != 'draw' or partition == ('home', 'draw', 'away'):
                    ref = selected(occurrence, family, side, signed_line, partition, score_partition)
        if ref.get('available'):
            ref = dict(ref, bet_id=hashed([ref['market'], ref['selected_outcome'],
                {key: ref['rules'].get(key) for key in (*model.SCORING, 'equality')}]))
        matching_models = [item for item in refund_models
                           if ref.get('available') and item.get('market') == ref['market']]
        assessment = model.assess(ref, venue, venue_reason=venue_reason,
                                  refund_model=matching_models[0] if len(matching_models) == 1 else None)
        if not ref.get('available'):
            assessment['reference_reason'] = ref['reason']
        if venue and venue.get('void') == 'fair_market_value' and venue.get('void_payout') is None:
            assessment['venue_blocker'] = 'settlement_novig_void_fair_value_unverified'
        row.update(pregame_reference=ref, settlement_assessment=assessment,
                   sportsbook_reference_reason=ref.get('reason') or
                   (assessment.get('reason') if assessment.get('comparable') is not True else None))
        if ref.get('available') and assessment.get('comparable'):
            cost = price(row)
            if 0 < cost < 1:
                row['sportsbook_baseline'] = dict(book=ref['book'], source=ref['source'],
                    probability=ref['probability'], fair_decimal_odds=ref['fair_decimal_odds'],
                    prices=sorted(ref['prices'], key=lambda leg: leg['side'] != ref['selected_outcome']),
                    current_until=occurrence[1].isoformat(), indicative=True,
                    snapshot_id=ref['snapshot_id'], conditioning=ref['conditioning'],
                    return_percent=exact_wire(100 * (Fraction(ref['probability']) / cost - 1)))
