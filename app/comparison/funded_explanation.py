"""Selected-only exact reconciliation from the owner's fixed allocation cashflows."""
from fractions import Fraction as F
from .net_costs import wire


def explanation(result, *, pair=False):
    if not result.get('model_available'):
        return None
    if result.get('bound_financial_inputs') and not pair:
        return bound_explanation(result)
    states = result.get('states', {})
    complete = result.get('conditioning') == 'modeled_complete'
    weights = result.get('probabilities') if complete else result.get('conditional_probabilities')
    decisive = result.get('conditional_probabilities')
    entry = F(result['cost_breakdown']['net_upfront_fee_usd'])
    capital = F(result['deployed_capital_usd'])
    def column(row, name):
        values = [leg.get(name) for leg in row['legs']] if pair else [row.get(name)]
        return None if any(v is None for v in values) else sum(map(F, values), F(0))
    def average(probabilities, field):
        if probabilities is None or any(v is None for v in probabilities.values()):
            return None
        total = F(0)
        for state, weight in probabilities.items():
            if not F(weight):
                continue
            value = field(states[state])
            if value is None:
                return None
            total += F(weight)*value
        return total
    def before_fees(row):
        values = [column(row, k) for k in ('receipt_usd', 'returned_hold_usd')]
        return None if any(v is None for v in values) else sum(values, F(0))-capital+entry
    gross = average(decisive, before_fees)
    modeled = average(weights, before_fees)
    charge = average(weights, lambda row: None if row.get('settlement_charge_usd' if pair else 'separately_payable_charge_usd') is None else F(row['settlement_charge_usd' if pair else 'separately_payable_charge_usd']))
    refund = average(weights, lambda row: column(row, 'fee_refund_usd'))
    expected = result.get('buffered_profit_usd')
    net = None if expected is None else F(expected)+F(result['buffer_usd'])
    if modeled is not None and charge is not None and refund is not None:
        if modeled-entry-charge+refund != net:
            raise ValueError('Selected funded explanation does not reconcile')
    withheld = any(leg.get('receipt_charge_treatment') == 'attached_net_receipt'
        for row in states.values() for leg in (row.get('legs', []) if pair else [row]))
    val = lambda n: None if n is None else wire(n)
    return dict(basis='complete modeled states' if complete else 'conditional on decisive home or away win',
        gross_decisive_value_usd=val(gross), settlement_adjustment_usd=val(None if modeled is None or gross is None else modeled-gross),
        net_upfront_fee_usd=wire(entry), expected_payable_charge_usd=val(charge), expected_fee_refund_usd=val(refund),
        expected_total_deduction_usd=val(None if charge is None or refund is None else entry+charge-refund),
        fee_adjusted_expected_profit_usd=val(net), buffer_usd=result['buffer_usd'], buffered_profit_usd=expected,
        gross_value_basis='attached net receipts; separate pre-withholding gross amount unknown' if withheld else 'gross receipts before payable fees',
        withholding='Charges already withheld remain inside attached net receipts and are not deducted again.',
        returned_holds='Funding includes refundable holds; state receipts return each hold separately.',
        commission_pools=[dict(leg=index,slot=term['slot'],pool=term.get('pool'),policy=term['policy']) for index,component in enumerate(result.get('components',[])) for term in component.get('settlement_terms',[])] if pair else [])


def bound_explanation(result):
    """Reconcile the shared owner's partition without inventing state weights.

    A probability bucket can span states with equal net profit but differing
    receipts/charges. Those component expectations remain unknown.
    """
    details=result['bound_details'];costs=details['costs']
    buckets=details['natural']['details']['probability_buckets']
    states=costs['states'];capital=F(result['deployed_capital_usd'])
    entry=F(costs['net_entry_fee_usd'])
    def average(field):
        total=F(0)
        for bucket in buckets:
            weight=F(bucket['probability'])
            if not weight:continue
            values={states[key].get(field) for key in bucket['state_ids']}
            if None in values or len(values)!=1:return None
            total+=weight*F(values.pop())
        return total
    net=average('net_profit_usd')
    expected=F(result['buffered_profit_usd'])+F(result['buffer_usd'])
    if net is None or net!=expected:
        raise ValueError('Selected funded explanation does not reconcile')
    receipt=average('gross_return_usd');holds=average('hold_return_usd')
    charge=average('settlement_fee_usd')
    before=None if receipt is None or holds is None else receipt+holds-capital+entry
    if before is not None and charge is not None and before-entry-charge!=net:
        raise ValueError('Selected funded explanation does not reconcile')
    decisive=details['natural']['conditioning']=='completed_decisive_results_only'
    val=lambda value:None if value is None else wire(value)
    return dict(basis=details['natural']['conditioning'],
        gross_decisive_value_usd=val(before) if decisive else None,
        settlement_adjustment_usd=None,
        net_upfront_fee_usd=wire(entry),expected_payable_charge_usd=val(charge),
        expected_fee_refund_usd=None,
        expected_total_deduction_usd=val(None if charge is None else entry+charge),
        fee_adjusted_expected_profit_usd=wire(net),buffer_usd=result['buffer_usd'],
        buffered_profit_usd=result['buffered_profit_usd'],
        gross_value_basis='Attached receipts; separately payable settlement charges are deducted once.',
        withholding='Already withheld charges stay inside attached receipts.',
        returned_holds='Returned holds use the shared owner state cashflows.',commission_pools=[])
