"""Explain the selected offer's saved settlement terms without assigning probabilities."""
from fractions import Fraction

from .cashflows import exact_wire as wire
from .domain import EqualityDescriptor, ScorePredicate


def _saved_wording(contract, metadata):
    wording = {**(metadata.get('original_wording') or {}), **(contract.get('wording') or {})}
    return [dict(label=label, text=text[:4096], excerpt=len(text) > 4096)
            for key, label in (('rules_primary', 'Primary rules'), ('rules_secondary', 'Additional rules'),
                               ('description', 'Market description'))
            if isinstance(text := wording.get(key), str) and text.strip()]


def _equality_payout(facts, cost):
    if facts.get('reason') or not facts.get('equality'):
        return None, 'Exact tie or push treatment is unverified.'
    try:
        equal = EqualityDescriptor.from_dict(facts['equality'])
        predicate = ScorePredicate.from_dict(facts['predicate'])
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None, 'The saved equality evidence could not be verified.'
    if predicate.threshold.value.denominator != 1 and (
        equal.treatment == 'not_feasible' or (facts.get('scoring') or {}).get('score_domain') == 'integer'
    ):
        return None, 'The score cannot land exactly on this half-point line.'
    if equal.treatment == 'not_feasible':
        return None, 'The recorded scoring rule has no equality outcome.'
    if equal.treatment == 'fraction':
        return equal.payout.value, 'Fractional settlement at the recorded payout.'
    if equal.treatment == 'stake_refund':
        fees = {'returned': 'Fees returned.', 'retained': 'Fees retained.'}
        return cost, 'Acquisition cost returned. ' + fees.get(equal.refund_fees, 'Fee treatment unverified.')
    if equal.treatment == 'predicate':
        # Test equality against the original side operator, including NO.
        wins = predicate.operator in ('ge', 'le', 'eq')
        return Fraction(int(wins)), 'Graded a win under the selected rule.' if wins else 'Graded a loss under the selected rule.'
    return None, 'Exact tie or push treatment is unverified.'


def settlement_terms(row, original=None):
    """Present per-claim cashflows and gaps for this exact saved listing."""
    original = original or {}
    contract = original.get('native_contract') or {}
    record = original.get('original_record') or {}
    metadata = record.get('comparison_source_metadata') or {}
    practice = (row.get('source') or {}).get('provider') == 'practice'
    wording = _saved_wording(contract, metadata)
    facts = contract.get('same_outcome') or {}
    verified = bool((original.get('binding') or {}).get('verified'))
    if not verified:
        facts = {}
    scoring = facts.get('scoring') or {}
    saved_cost = row.get('cost_per_normal_claim')
    cost = Fraction(saved_cost) if saved_cost is not None else None
    if cost is None and (original.get('common_odds') or {}).get('supported'):
        from app.dashboard.current_contract import price
        try:
            value = price(original)
            if 0 < value <= 1:
                cost = value
        except (KeyError, TypeError, ValueError, ArithmeticError):
            pass

    def outcome(label, payout, note=None):
        return dict(label=label, payout_usd=wire(payout),
                    profit_usd=wire(payout - cost) if payout is not None and cost is not None else None,
                    note=note)

    equality_payout, equality_note = _equality_payout(facts, cost)
    equality_label = 'Game ends tied' if row.get('market', {}).get('market') == 'winner' else 'Score lands exactly on the line'
    if practice:
        equality_note = 'The fictional scenario assumes decisive outcomes.'
    if wording:
        exception_note = 'See the saved rule text for timing and settlement conditions. A fixed payout is unverified.'
    else:
        exception_note = 'No exact cancellation, postponement or abandonment payout is captured.'
    normal = facts.get('normal_payout') or {}
    normalized = cost is not None or verified and normal.get('payout') == '1' and normal.get('payout_units') == 'USD'
    return dict(
        wording=wording, fictional=practice, scoring=scoring,
        cost_usd=wire(cost), equality_can_affect_ev=equality_payout is not None,
        outcomes=[outcome('Selected side wins', Fraction(1) if normalized else None),
                  outcome('Selected side loses', Fraction(0) if normalized else None),
                  outcome(equality_label, equality_payout, equality_note),
                  outcome('Game cancelled, postponed or abandoned', None, exception_note)],
    )
