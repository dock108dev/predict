"""Scoped replacement-input bridge for existing fee/payout machinery.

This module supplies modeled inputs, not a fee catalog, probability model, source
binding or evaluator. A published payout is a hypothetical receipt, not an observed
settlement. Scalars consequently keep actual_value null."""
from copy import deepcopy
from dataclasses import asdict
import json

from .current_dependencies import encoded, profile, public_tree
from .estimated_policy import DEFAULT_POLICY, EstimateInput
from .event_links import digest, instant
from .net_costs import calculate_net_costs
from .payouts import BoundLeg

VERSION = 'predict-estimate-template-provider-1'
PARTS = ('below', 'equal', 'above', 'noncompleted')


def _contract(value, native_key):
    fields = {'version', 'id', 'source', 'predicate', 'wording', 'result_policy',
              'scope', 'material_sha256'}
    if (not isinstance(value, dict) or set(value) != fields or
            value['version'] != 'predict-native-contract-1' or
            value['id'] != 'native-contract:' + digest({k: v for k, v in value.items() if k != 'id'})):
        raise ValueError('Exact versioned native contract required')
    public_tree(value)
    source = value['source']
    if (not isinstance(source, dict) or tuple(source.get(k) for k in
            ('native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')) != tuple(native_key[1:])):
        raise ValueError('Native template instrument/side conflict')
    if (set(value['scope']) != {'period', 'overtime'} or
            value['scope']['overtime'] not in ('included', 'excluded', 'unknown')):
        raise ValueError('Native template scoring scope required')
    return deepcopy(value)


class TemplateProvider:
    """Immutable public rich graph plus exact scoped scalar replacements.

    Factories enforce applicability. Callers select a named component through
    scope_id(component), then the standard EstimateProvider.resolve(scope_id).
    Fee dollars and payout unit rates are distinct components with their units
    retained in Details. Unknown scope IDs refuse instead of choosing a sibling.
    """
    version = VERSION

    def __init__(self, kind, payload, values, *, expires_at=None):
        payload = deepcopy(payload)
        self._key, self._profile = profile(kind, payload, expires_at=expires_at)
        self._inputs = {}
        self._components = {}
        for name, (value, basis) in values.items():
            scope = 'estimate-template:' + digest([VERSION, kind, self._key, name])
            self._components[name] = scope
            self._inputs[scope] = EstimateInput(kind, VERSION + ':' + self._key,
                basis if value is not None else 'unknown_actual', scope, None, value)

    def scope_id(self, component):
        return self._components[component]

    def resolve(self, scope_id):
        try:
            return self._inputs[scope_id]
        except KeyError:
            raise ValueError('Exact estimate template component scope required') from None

    def profile(self):
        """Existing legacy envelope; shared storage may intern it without changing identity."""
        return self._key, deepcopy(self._profile)

    def to_dict(self):
        return dict(version=VERSION, profile_ref=self._key,
            components=deepcopy(self._components), payload=deepcopy(self._profile['payload']))


def payout_provider(native_contract, leg, *, at):
    """Adapt an already bound native selection; recheck current applicability."""
    if not isinstance(leg, BoundLeg):
        raise ValueError('Existing typed payout binding required')
    contract = _contract(native_contract, leg.selection.native.key)
    clock = instant(at)
    p = leg.profile
    if clock < instant(p.effective_from) or p.effective_until is not None and clock >= instant(p.effective_until):
        raise ValueError('Payout template expired or not effective')
    if contract['scope']['period'] != leg.selection.scope.period:
        raise ValueError('Native payout period conflict')
    if contract['scope']['overtime'] != leg.selection.scope.overtime:
        raise ValueError('Native payout overtime conflict')
    values = {}
    cells = {}
    for name in PARTS:
        cell = p.noncompleted if name == 'noncompleted' else leg.normal_payout(name)
        cells[name] = cell.to_dict()
        # Evidenced rule cashflows are still modeled future receipts. Authored
        # source evidence cannot promote a scenario to a published template.
        basis = ('provisional_assumption' if cell.status == 'estimated' or
                 any(e.evidence_class == 'authored' for e in p.source_evidence)
                 else 'published_template')
        values[name] = (None if cell.value is None else cell.value.original, basis)
    payload = p.to_dict()
    payload.update(provider_version=VERSION, native_contract=contract,
        binding_revision=leg.revision, completion_context=leg.context.to_dict(),
        evaluated_at=at, resolved_cells=cells, actual_settlement=None)
    return TemplateProvider('payout', payload, values, expires_at=p.effective_until)


def fee_provider(native_contract, request, scenario, **inputs):
    """Delegate fixed-allocation costs unchanged, then adapt their scalar outputs.

    Existing shared engines retain native scales, per-fill/order rounding, holds,
    withheld charges and deterministic refunds. This does not optimize quantity,
    apply the opportunity buffer or infer scope from occurrence/display matching.
    Private account/portfolio inputs are outside this public bridge.
    """
    if request.account_ref is not None or request.portfolio_basis != 'standalone' or inputs.get('positions') is not None:
        raise ValueError('Public estimate template requires standalone unscoped account inputs')
    data = scenario.to_dict() if hasattr(scenario, 'to_dict') else deepcopy(scenario)
    index = inputs.get('leg_index', 0)
    if type(index) is not int or not 0 <= index < len(data.get('legs', [])):
        raise ValueError('Exact fee template scenario leg required')
    native = data['legs'][index]['native_key']
    contract = _contract(native_contract, native)
    if native[:3] != [request.venue, request.event_id, request.market_id]:
        raise ValueError('Native fee template request conflict')
    inputs.setdefault('ceiling_usd', DEFAULT_POLICY.capital_ceiling_usd)
    result = calculate_net_costs(request, data, **inputs)
    rule = result['rule']['rule']
    basis = ('provisional_assumption' if rule is None or rule['source_kind'] == 'controlled_scenario'
             else 'published_template')
    values = {name: (result[name], basis) for name in
              ('entry_fee_usd', 'rounding_refund_usd', 'net_entry_fee_usd')}
    for state, row in result['states'].items():
        values['settlement_fee_usd:' + state] = (row['settlement_fee_usd'], basis)
    payload = dict(provider_version=VERSION, native_contract=contract,
        provider_rule_version=None if rule is None else rule['version'], rule=rule,
        request=asdict(request), result=result, scalar_unit='USD', actual_charges=None)
    payload = json.loads(encoded(payload))
    # All existing resource/privacy gates apply before this public graph enters
    # a registry; no private baseline or float is retained in shared templates.
    public_tree(payload)
    if len(encoded(payload)) > 32768:
        raise ValueError('Estimate template profile byte capacity')
    ends = [] if rule is None else [rule[k] for k in ('effective_to', 'expires_at') if rule[k] is not None]
    expiry = min(ends, key=instant) if ends else None
    return TemplateProvider('fee', payload, values, expires_at=expiry)
