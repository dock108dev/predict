"""Versioned, exact pregame reference selection and settlement assessment."""
from datetime import timedelta
from fractions import Fraction

from app.storage.store import hashed, stamp
from .cashflows import exact_wire
from .sgo_reference import BEST_BOOKS, MAX_AGE_SECONDS, american_probability

VERSION = 'pregame-sportsbook-priority-1'
ORDINARY_OUTCOMES = {'moneyline': ('home', 'away'), 'spread': ('home', 'away'), 'total': ('over', 'under')}
REFUNDS = {'push_refund': 'if_no_push', 'draw_refund': 'if_no_draw'}
SCORING = ('scope', 'overtime', 'extra_innings', 'shootout', 'shootout_count')
ADMIN = ('void', 'cancellation', 'shortened_game', 'forfeit', 'refund_charges')


def target(family, side, signed_line):
    """Use the home handicap for a spread partition and the shared total strike."""
    if side not in (*ORDINARY_OUTCOMES[family], *(('draw',) if family == 'moneyline' else ())):
        raise ValueError('reference_selected_outcome_unverified')
    if (family == 'moneyline') != (signed_line is None):
        raise ValueError('reference_exact_line_unverified')
    line = None if signed_line is None else Fraction(signed_line)
    if family == 'spread' and side == 'away':
        line = -line
    return line


def state_probabilities(probability, rule, market, refund_model=None):
    equality = rule['equality']
    if equality not in REFUNDS:
        return {'win': exact_wire(probability), 'loss': exact_wire(1 - probability)}, None
    reason = 'push_probability_missing' if equality == 'push_refund' else 'draw_probability_missing'
    if not (refund_model and refund_model.get('market') == market and refund_model.get('version')
            and refund_model.get('source')):
        return None, reason
    try:
        value = refund_model['probability']
        if not isinstance(value, str):
            raise ValueError
        u = Fraction(value)
        if not 0 <= u <= 1:
            raise ValueError
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return None, 'refund_probability_invalid'
    return {k: exact_wire(p) for k, p in
            dict(win=(1-u)*probability, loss=(1-u)*(1-probability), refund=u).items()}, None


def supported_refund(basis):
    if basis in ('full_outlay', 'stake_only'):
        return True
    try:
        return isinstance(basis, dict) and 0 <= Fraction(basis['stake_fraction']) <= 1
    except (KeyError, ArithmeticError, TypeError, ValueError):
        return False


def assess(reference, venue_rule, *, venue_reason=None, refund_model=None):
    """Compare normal outcome states, then the cash flows of exceptional states."""
    book_rule = reference.get('rules')
    result = dict(available=False, state_probabilities=None, venue_rules=venue_rule, sportsbook_rules=book_rule,
                  scope='event_goes_ahead', version=VERSION)
    if venue_reason:
        return dict(result, reason=venue_reason)
    if not venue_rule or not venue_rule.get('available') or not venue_rule.get('evidence'):
        return dict(result, reason='venue_settlement_rules_unverified')
    if not book_rule:
        return dict(result, reason=reference.get('reason') or 'sportsbook_settlement_rules_unverified')
    if any(book_rule.get(name) != venue_rule.get(name) for name in SCORING):
        return dict(result, reason='settlement_scoring_mismatch', comparable=False)
    if (book_rule.get('equality') != venue_rule.get('equality')
            or venue_rule.get('outcomes') != book_rule['outcomes']):
        return dict(result, reason='settlement_outcome_partition_mismatch', comparable=False)
    if book_rule.get('equality') not in (*REFUNDS, 'not_possible', 'draw_loses'):
        return dict(result, reason='settlement_equality_cashflows_unverified', comparable=False)
    result['comparable'] = True
    probabilities, missing = state_probabilities(Fraction(reference['probability']), book_rule,
                                                  reference['market'], refund_model)
    result.update(state_probabilities=probabilities, probability_missing=missing)
    if probabilities and refund_model and 'refund' in probabilities:
        result['refund_probability_evidence'] = refund_model
    if book_rule['equality'] in REFUNDS:
        receipts = {side: rule.get('equality_cashflow') for side, rule in
                    (('sportsbook', book_rule), ('venue', venue_rule))}
        result['refund_cashflows'] = receipts
        if receipts['sportsbook'] != 'full_outlay' or not supported_refund(receipts['venue']):
            return dict(result, reason='settlement_refund_cashflows_differ')
    if (any(book_rule.get(name) is None or venue_rule.get(name) is None for name in ADMIN)
            or any(book_rule[name] != venue_rule[name] for name in ADMIN)
            or any(book_rule[name] != 'full_outlay' for name in ('void', 'cancellation'))
            or book_rule['refund_charges'] != 'none'):
        return dict(result, reason='settlement_exceptional_cashflows_unverified_or_different')
    return dict(result, available=not missing, reason=missing)


def snapshot(occurrence, family, line, outcomes, observation, book, *, at, rules_for):
    start = occurrence[1]
    captured = stamp(observation['frame_received_at'])
    if not observation['scheduled'] or not captured <= at < start or captured >= start:
        raise ValueError('reference_frame_not_pregame')
    keys = [(family, side, -line if family == 'spread' and side == 'away' else line) for side in outcomes]
    three_way = len(outcomes) == 3
    values = [[leg for leg in observation['quotes'].get(key, {}).get(book, [])
               if (leg.get('partition') == 'three_way') == three_way] for key in keys]
    if any(len(items) > 1 for items in values):
        raise ValueError('reference_duplicate_outcome')
    if any(not items for items in values):
        raise ValueError('reference_exact_partition_incomplete')
    legs = [items[0] for items in values]
    if any(leg.get('available', True) is not True for leg in legs):
        raise ValueError('reference_quote_withdrawn')
    if observation['source'] == 'sportsgameodds':
        ids = {leg.get('odd_id') for leg in legs}
        if None in ids or len(ids) != len(legs):
            raise ValueError('reference_outcome_identity_unverified')
        if len(legs) == 2 and any(legs[i].get('opposing_odd_id') != legs[1-i]['odd_id'] for i in (0, 1)):
            raise ValueError('reference_outcome_identity_unverified')
    clocks = [stamp(leg['source_at']) for leg in legs]
    if any(not clock <= stamp(leg.get('received_at', observation['frame_received_at'])) <= captured
           for clock, leg in zip(clocks, legs, strict=True)):
        raise ValueError('reference_source_clocks_unverified')
    implied = [american_probability(leg['price_american']) for leg in legs]
    rule = rules_for(observation, book, family, legs, at)
    if rule:
        if tuple(rule['outcomes']) != outcomes:
            raise ValueError('reference_rule_partition_conflict')
        if not rule.get('evidence') or not all(key in rule for key in (*SCORING, 'equality')):
            raise ValueError('reference_rule_scope_unverified')
    market = dict(league=occurrence[0], kickoff=start.isoformat(), home=occurrence[2], away=occurrence[3],
                  family=family, period='full_game', line=None if line is None else exact_wire(line),
                  outcomes=list(outcomes))
    payload = dict(policy_version=VERSION, market=market, book=book, rules=rule, prices=legs,
                   source=observation['source'], event_id=observation['event_id'], frame_id=observation['frame_id'],
                   frame_received_at=observation['frame_received_at'],
                   implied=dict(zip(outcomes, map(exact_wire, implied), strict=True)),
                   probabilities={side: exact_wire(q / sum(implied)) for side, q in zip(outcomes, implied, strict=True)})
    return dict(payload, snapshot_id=hashed(payload)), tuple(sorted(clocks))


def selection(occurrence, family, side, signed_line, observations, *, at, rules_for,
              previous=(), outcomes=None, scoring_partition=()):
    """Find the first eligible book from complete co-observed snapshots."""
    line = target(family, side, signed_line)
    outcomes = outcomes or ORDINARY_OUTCOMES[family]
    legal = (ORDINARY_OUTCOMES[family], ('home', 'draw', 'away')) if family == 'moneyline' else (ORDINARY_OUTCOMES[family],)
    if outcomes not in legal or side not in outcomes or occurrence[2] == occurrence[3]:
        return dict(available=False, reason='reference_rule_partition_conflict', policy_version=VERSION)
    failures, raw = {}, None
    if at >= occurrence[1]:
        return dict(available=False, reason='reference_kickoff_reached', policy_version=VERSION)
    for book in BEST_BOOKS:
        candidates = []
        reasons = set()
        for observation in observations:
            try:
                item, clocks = snapshot(occurrence, family, line, outcomes, observation, book, at=at, rules_for=rules_for)
            except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
                reasons.add(str(exc) if str(exc).startswith('reference_') else 'reference_price_or_clock_invalid')
                continue
            candidates.append((clocks, False, item))
        for saved in previous:
            market = saved.get('market') or {}
            if (saved.get('book') != book or saved.get('policy_version') != VERSION
                    or (market.get('league'), market.get('kickoff'), market.get('home'), market.get('away'))
                    != (occurrence[0], occurrence[1].isoformat(), *occurrence[2:])
                    or market.get('family') != family or market.get('line') != (None if line is None else exact_wire(line))
                    or tuple(market.get('outcomes', ())) != outcomes):
                continue
            if any(withdraws(observation, saved) for observation in observations):
                reasons.add('reference_quote_withdrawn')
                continue
            try:
                clock = tuple(sorted(stamp(leg['source_at']) for leg in saved['prices']))
                saved_rules = rules_for(saved, book, family, saved['prices'], at)
                if saved_rules == saved['rules']:
                    candidates.append((clock, True, saved))
            except (KeyError, TypeError, ValueError):
                continue
        # A redispatch of an unchanged book must leave the committed ID and clocks alone.
        for clocks, committed, item in sorted(candidates, key=lambda candidate: candidate[:2], reverse=True):
            if any(withdraws(observation, item) for observation in observations):
                reasons.add('reference_quote_withdrawn')
                continue
            quoted = [leg['price_american'] for leg in item['prices']]
            if not committed and any(other_clocks == clocks and
                                     [leg['price_american'] for leg in other['prices']] != quoted
                                     for other_clocks, _, other in candidates):
                reasons.add('reference_same_clock_conflict')
                continue
            if item.get('rules') and all(item['rules'].get(k) == v for k, v in scoring_partition):
                return for_side(item, side, failures)
            if item.get('rules'):
                reasons.add('reference_rule_partition_conflict')
                continue
            if raw is None:
                raw = item
            reasons.add('sportsbook_settlement_rules_unverified')
        failures[book] = sorted(reasons) or ['reference_exact_partition_incomplete']
    reasons = {reason for failures_ in failures.values() for reason in failures_}
    reason = next((reason for reason in ('reference_quote_withdrawn', 'reference_rule_partition_conflict',
                                         'reference_same_clock_conflict')
                   if reason in reasons), 'reference_exact_partition_incomplete')
    return dict(available=False, reason='sportsbook_settlement_rules_unverified' if raw else reason, policy_version=VERSION,
                exclusions=failures, observed_snapshot=for_side(raw, side, {}) if raw else None)


def withdraws(observation, item):
    if (observation['source'], observation['event_id']) != (item['source'], item['event_id']):
        return False
    if stamp(observation['frame_received_at']) <= stamp(item['frame_received_at']):
        return False
    if not observation['scheduled']:
        return True
    retired = observation.get('retired', {})
    return any((item['book'], leg.get('odd_id'), leg.get('line')) in retired
               and stamp(retired[item['book'], leg.get('odd_id'), leg.get('line')]) >= stamp(leg['source_at'])
               for leg in item['prices'])


def for_side(item, side, failures):
    fair = Fraction(item['probabilities'][side])
    return dict(item, available=bool(item['rules']), selected_outcome=side,
                probability=exact_wire(fair), fair_decimal_odds=exact_wire(1 / fair),
                conditioning=REFUNDS.get((item['rules'] or {}).get('equality')),
                exclusions=dict(failures))
