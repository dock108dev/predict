"""Exact pregame execution identity and completed-game settlement inputs."""

from datetime import datetime
from fractions import Fraction as F

from app.storage.store import exact_time

from . import current_pregame

LEAGUES = frozenset(('NFL', 'NCAAF', 'NBA', 'NCAAB', 'MLB', 'NHL'))
VENUES = frozenset(('novig', 'kalshi', 'polymarket_us', 'prophetx'))
FAMILIES = frozenset(('moneyline', 'spread', 'total'))
NO_EQUALITY = frozenset(('not_feasible', 'not_possible'))


def clock(value):
    return exact_time(value.isoformat() if isinstance(value, datetime) else value)


def expected(record):
    """Use the same reference-side and signed-line owner as posted EV."""
    from app.storage.current_rows import contract_id

    event, market = record['event'], record['market_identity']
    family, side, line = current_pregame.reference_key(record)
    if family == 'spread' and side == 'away':
        line = -line
    return dict(contract_id=contract_id(record), league=event['competition'], family=family,
                period=market['period'], starts_at=event['scheduled_start'], selected_side=side,
                signed_line=None if line is None else str(line))


def validate_receipt(receipt, at, expected=None):
    """Confirm a source-admitted, exact native image is usable at this decision."""
    contract = receipt['contract']
    league, family = contract['league'], contract['family']
    if (receipt['venue'] not in VENUES or league not in LEAGUES or family not in FAMILIES
            or contract['period'] != 'full_game'):
        raise ValueError('depth_contract_outside_scope')
    if (not all(receipt.get(key) for key in ('event_id', 'market_id', 'outcome_id'))
            or receipt['venue'] != 'prophetx' and (not receipt.get('opposite_outcome_id')
                or receipt['opposite_outcome_id'] == receipt['outcome_id'])):
        raise ValueError('depth_native_identity_unverified')
    if not (contract.get('phase') == 'pregame' or contract.get('event_status') == 'OPEN_PREGAME'
            and contract.get('market_status') == 'OPEN'):
        raise ValueError('depth_pregame_phase_unverified')
    sides = ('over', 'under') if family == 'total' else ('home', 'away')
    line = contract['signed_line']
    if (contract['selected_side'] not in sides or (family == 'moneyline') != (line is None)
            or line is not None and F(line).denominator not in (1, 2)):
        raise ValueError('depth_native_identity_unverified')
    if expected is not None:
        fields = ('league', 'family', 'period', 'selected_side')
        if (any(contract[field] != expected[field] for field in fields)
                or clock(contract['starts_at']) != clock(expected['starts_at'])
                or (None if line is None else F(line)) != (
                    None if expected['signed_line'] is None else F(expected['signed_line']))
                or receipt.get('contract_id') is not None and expected.get('contract_id') is not None
                    and receipt['contract_id'] != expected['contract_id']):
            raise ValueError('depth_native_identity_mismatch')
    received, expires, decision = (clock(value) for value in (receipt['received_at'], receipt['valid_until'], at))
    if not received <= decision < clock(contract['starts_at']):
        raise ValueError('depth_receipt_outside_decision')
    if decision > expires:
        raise ValueError('stale')
    if receipt.get('source_at') and clock(receipt['source_at']) > received:
        raise ValueError('depth_source_clock_invalid')
    if receipt.get('currency', 'USD') != 'USD':
        raise ValueError('depth_currency_unverified')
    return contract


def settled_partition(contract, probability, probabilities=None, cashflow_rules=None):
    """Verify the reference-equivalent scored outcomes before computing EV.

    The result is conditional on the game completing. Administrative events
    with an unpriced refund or fair-market payoff are not treated as losses.
    """
    settlement = contract.get('settlement') or {}
    if not settlement.get('available') or not (settlement.get('rule_id') or settlement.get('evidence')):
        raise ValueError(settlement.get('reason') or 'depth_settlement_unverified')
    league, family = contract['league'], contract['family']
    if (settlement.get('overtime') not in (('included', 'not_applicable') if league == 'MLB' else ('included',))
            or league == 'MLB' and settlement.get('extra_innings') != 'included'
            or league == 'NHL' and settlement.get('shootout') != 'official_final_score'
            or league == 'NHL' and family != 'moneyline'
                and settlement.get('shootout_count') != 'one_goal_to_winning_team'
            or F(settlement.get('normal_win', '1')) != 1 or F(settlement.get('normal_loss', '0')) != 0):
        raise ValueError('depth_settlement_scoring_mismatch')
    line, equality = contract['signed_line'], settlement.get('equality')
    if family != 'moneyline' and F(line).denominator == 2:
        # At an integer-score half-line, predicate equality is unreachable
        # even if a venue's generic rule still describes which side gets it.
        if equality not in (*NO_EQUALITY, 'predicate'):
            raise ValueError('depth_settlement_equality_mismatch')
        equality = 'not_feasible'
    rules = cashflow_rules or {}
    if family == 'moneyline' and league != 'NFL' and equality in ('half_face', 'void_without_official_winner'):
        # Official completed NBA/NCAA games and NHL shootout finals produce
        # one winner. An exceptional tie/void is outside this conditional EV.
        equality = 'not_feasible'
    if equality in NO_EQUALITY:
        if family != 'moneyline' and F(line).denominator == 1:
            raise ValueError('depth_settlement_equality_mismatch')
        if probability is None:
            raise ValueError('depth_reference_unavailable')
        p = F(probability)
        if not 0 < p < 1:
            raise ValueError('depth_reference_probability_invalid')
        return dict(win=p, loss=1-p), {}
    if not probabilities or rules.get('reference_equivalent') is not True:
        raise ValueError('depth_equality_probability_unverified')
    state = 'tie' if family == 'moneyline' else 'refund'
    if equality == 'half_face':
        basis = dict(face_fraction='0.5')
    elif equality in ('push_refund', 'stake_refund', 'draw_refund'):
        basis = settlement.get('equality_cashflow')
        if basis not in ('stake_only', 'full_outlay'):
            raise ValueError('depth_equality_cashflow_unverified')
    elif equality == 'draw_loses':
        basis = 'zero'
    elif equality == 'predicate' and settlement.get('equality_cashflow') in ('ordinary_win', 'zero'):
        basis = settlement['equality_cashflow']
    else:
        raise ValueError('depth_equality_cashflow_unverified')
    reference_basis = rules.get(state)
    if isinstance(basis, dict) and isinstance(reference_basis, dict) and 'face_fraction' in reference_basis:
        reference_basis = dict(face_fraction=str(F(reference_basis['face_fraction'])))
        basis = dict(face_fraction=str(F(basis['face_fraction'])))
    if reference_basis != basis or set(probabilities) != {'win', 'loss', state}:
        raise ValueError('depth_settlement_equality_mismatch')
    partition = {name: F(value) for name, value in probabilities.items()}
    if min(partition.values()) < 0 or sum(partition.values()) != 1 or not (partition['win'] and partition['loss']):
        raise ValueError('depth_reference_probability_invalid')
    if probability is not None and F(probability) != partition['win'] / (partition['win'] + partition['loss']):
        raise ValueError('depth_reference_probability_mismatch')
    return partition, {state: basis}
