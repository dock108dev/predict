"""Server-owned sizing defaults and pure contracts without acquisition.

Legacy cost policies remain in costs.py. Versioned estimate policies supply
funding, buffer and provisional probability inputs without qualifying execution."""
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
import json
from pathlib import Path
from typing import Protocol

from .cashflows import exact_wire
from .costs import ComparisonCostPolicy
from .current_dependencies import digest
from .domain import ExactNumber

VERSION = 'predict-estimate-policy-2'
INPUT_VERSION = 'predict-estimate-input-1'
RESULT_VERSION = 'predict-estimate-result-1'
SCOPE = ('NFL', 'regular_season', 'pregame', 'full_game', 'winner', 'including_overtime')
STATES = ('a_wins', 'b_wins', 'tie', 'terminal_noncompletion')
CONFIG_PATH = Path(__file__).resolve().parents[2] / '.local' / 'estimate-policy.json'


def number(value):
    if not isinstance(value, (str, Fraction, ExactNumber)):
        raise ValueError('exact financial string or rational required')
    return value if isinstance(value, Fraction) else (
        value.value if isinstance(value, ExactNumber) else ExactNumber.parse(value).value)


@dataclass(frozen=True)
class EstimatePolicy:
    version: str = VERSION
    capital_ceiling_usd: str = '1000'
    buffer_rate: str = '0.005'
    tie: str = '0.005'
    terminal_noncompletion: str = '0.001'

    def __post_init__(self):
        if any(not isinstance(v, str) for v in asdict(self).values()):
            raise ValueError('policy wire values must be exact strings')
        if self.version != VERSION:
            raise ValueError('unsupported estimate policy version')
        if not 0 < number(self.capital_ceiling_usd) <= 100000:
            raise ValueError('comparison ceiling outside bounds')
        if not 0 <= number(self.buffer_rate) <= 1:
            raise ValueError('buffer rate outside bounds')
        if not 0 <= number(self.tie) <= 1 or not 0 <= number(self.terminal_noncompletion) <= 1:
            raise ValueError('exceptional probability outside bounds')
        if number(self.tie) + number(self.terminal_noncompletion) > 1:
            raise ValueError('exceptional states exceed probability partition')

    def with_ceiling(self, ceiling):
        return self if ceiling is None else replace(self, capital_ceiling_usd=ceiling)

    @property
    def revision(self):
        return digest(asdict(self))

    def cost_policy(self):
        # Reuse the legacy fee/funding/age machinery at an explicit ceiling.
        # Its adverse-price stress remains a separate sensitivity.
        return replace(ComparisonCostPolicy(), ceiling_usd=self.capital_ceiling_usd)

    def reference(self):
        """Compact metric reference; full assumptions are published once per API."""
        return dict(version=self.version, revision=self.revision,
            capital_ceiling_usd=self.capital_ceiling_usd, buffer_rate=self.buffer_rate)

    def to_dict(self):
        return dict(asdict(self), revision=self.revision,
            execution_role='taker', execution_channel='direct_site', portfolio_basis='standalone',
            funding_basis='already_funded', holding_period='to_settlement',
            denominator='actual_deployed_capital',
            funding_components=['acquisition_or_stake', 'unavoidable_upfront_fees', 'independent_funded_collateral'],
            buffer=dict(rate=self.buffer_rate, basis='actual_deployed_capital',
                treatment='model_haircut', applications_per_opportunity=1, consumes_funding=False),
            probability_defaults=dict(scope=list(SCOPE), basis='provisional_prior',
                measured_rate=False, states=list(STATES),
                tie=dict(central=self.tie, low='0', high='0.01'),
                terminal_noncompletion=dict(central=self.terminal_noncompletion, low='0', high='0.005')),
            size_statuses=['supported_size', 'modeled_size', 'size_unverified'],
            input_bases=['observed_fact', 'published_template', 'provisional_assumption', 'unknown_actual'],
            input_version=INPUT_VERSION, result_version=RESULT_VERSION,
            legacy_sensitivity='adverse_price_stress', buffer_applied_to_existing_metrics=False)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('estimate policy object required')
        target = RequestedTradePolicy if value.get('version') == REQUESTED_VERSION else cls
        result = target(**{k: value[k] for k in target.__dataclass_fields__})
        if value != result.to_dict():
            raise ValueError('estimate policy metadata or revision conflict')
        return result


REQUESTED_VERSION = 'predict-estimate-policy-3'


@dataclass(frozen=True)
class RequestedTradePolicy(EstimatePolicy):
    """Requested funding with explicit sizing and a named decisive probability basis.

    capital_ceiling_usd remains the funded request's wire amount for compatibility
    with fee/funding owners. No additional amount or buffer funding is introduced.
    """
    version: str = REQUESTED_VERSION
    sizing_mode: str = 'requested_trade'
    benchmark_venue: str = 'pinnacle'
    benchmark_method: str = 'proportional_no_vig'

    def __post_init__(self):
        from .benchmark import supported_venue
        if self.version != REQUESTED_VERSION:
            raise ValueError('unsupported requested policy version')
        # Validate all predecessor numerical bounds under their original version.
        EstimatePolicy(VERSION, self.capital_ceiling_usd, self.buffer_rate,
                       self.tie, self.terminal_noncompletion)
        if self.sizing_mode not in ('requested_trade', 'ceiling'):
            raise ValueError('unsupported sizing mode')
        if not supported_venue(self.benchmark_venue) or self.benchmark_method != 'proportional_no_vig':
            raise ValueError('unsupported selected benchmark or method')

    @property
    def requested_amount_usd(self):
        return self.capital_ceiling_usd

    def reference(self):
        return dict(super().reference(), sizing_mode=self.sizing_mode,
                    requested_amount_usd=self.requested_amount_usd,
                    benchmark_venue=self.benchmark_venue, benchmark_method=self.benchmark_method)

    def to_dict(self):
        return dict(super().to_dict(), requested_amount_usd=self.requested_amount_usd,
                    result_version='predict-estimate-result-2')


LEGACY_POLICY = EstimatePolicy()
DEFAULT_POLICY = RequestedTradePolicy()


def load(path=None):
    """Optional local calculation config, independent of source configuration."""
    path = CONFIG_PATH if path is None else Path(path)
    if not path.exists():
        return DEFAULT_POLICY
    if path.stat().st_size > 4096:
        raise ValueError('estimate policy configuration exceeds bound')
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) - set(RequestedTradePolicy.__dataclass_fields__):
        raise ValueError('unsupported estimate policy configuration')
    target = EstimatePolicy if value.get('version') == VERSION else RequestedTradePolicy
    return target(**value)


def buffer_usd(deployed_capital, buffer_rate=DEFAULT_POLICY.buffer_rate):
    capital, rate = number(deployed_capital), number(buffer_rate)
    if capital < 0 or not 0 <= rate <= 1:
        raise ValueError('nonnegative capital and bounded buffer rate required')
    return capital * rate


def buffered_profit(fee_adjusted_expected_profit, deployed_capital, buffer_rate=DEFAULT_POLICY.buffer_rate):
    return number(fee_adjusted_expected_profit) - buffer_usd(deployed_capital, buffer_rate)


def probability_partition(decisive_a_weight, *, scope, policy=DEFAULT_POLICY,
                          exceptional_states=('tie', 'terminal_noncompletion')):
    """Disjoint terminal states, never delayed-game or duplicate cancellation mass."""
    if (not isinstance(scope, (tuple, list)) or tuple(scope) != SCOPE or
            not isinstance(exceptional_states, (tuple, list)) or tuple(exceptional_states) != STATES[2:]):
        raise ValueError('unsupported prior scope or overlapping exceptional states')
    c, t, u = number(decisive_a_weight), number(policy.tie), number(policy.terminal_noncompletion)
    if not 0 <= c <= 1:
        raise ValueError('decisive probability outside bounds')
    values = dict(zip(STATES, ((1-t-u)*c, (1-t-u)*(1-c), t, u)))
    if any(v < 0 for v in values.values()) or sum(values.values()) != 1:
        raise ValueError('invalid disjoint probability partition')
    return values


@dataclass(frozen=True)
class EstimateInput:
    """Replacement input retains actual unknown beside a disclosed model value."""
    provider_kind: str
    provider_version: str
    basis: str
    scope_id: str
    actual_value: str | None
    modeled_value: str | None
    version: str = INPUT_VERSION

    def __post_init__(self):
        if self.version != INPUT_VERSION or self.provider_kind not in ('fee', 'payout', 'probability', 'liquidity'):
            raise ValueError('versioned supported provider kind required')
        if self.basis not in ('observed_fact', 'published_template', 'provisional_assumption', 'unknown_actual'):
            raise ValueError('explicit input provenance required')
        if any(not isinstance(v, str) or not 1 <= len(v) <= 256 for v in (self.provider_version, self.scope_id)):
            raise ValueError('exact provider version and scope required')
        for v in (self.actual_value, self.modeled_value):
            if v is not None:
                if not isinstance(v, str):
                    raise ValueError('provider wire values must be exact strings')
                number(v)
        if self.basis != 'observed_fact' and self.actual_value is not None:
            raise ValueError('modeled inputs cannot promote actual facts')
        if self.basis == 'observed_fact' and self.actual_value is None:
            raise ValueError('observed fact requires an actual value')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        return cls(**value)


class EstimateProvider(Protocol):
    """Versioned fee/payout/probability/liquidity resolvers use exact scope IDs."""
    version: str

    def resolve(self, scope_id: str) -> EstimateInput: ...


@dataclass(frozen=True)
class EstimateResult:
    """Fixed allocation result seam; no sizing, fee or probability oracle here."""
    policy: EstimatePolicy
    deployed_capital_usd: str
    fee_adjusted_expected_profit_usd: str | None
    conditioning: str
    size_status: str
    supported_capital_usd: str | None = None
    inputs: tuple[EstimateInput, ...] = ()
    version: str = RESULT_VERSION

    def __post_init__(self):
        if self.version not in (RESULT_VERSION, 'predict-estimate-result-2') or not isinstance(self.policy, EstimatePolicy):
            raise ValueError('versioned result and policy required')
        if any(v is not None and not isinstance(v, str) for v in (self.deployed_capital_usd,
                self.fee_adjusted_expected_profit_usd, self.supported_capital_usd)):
            raise ValueError('result wire values must be exact strings')
        if not 0 < number(self.deployed_capital_usd) <= number(self.policy.capital_ceiling_usd):
            raise ValueError('positive deployed funding within total ceiling required')
        if self.conditioning not in ('modeled_complete', 'modeled_conditional', 'unavailable'):
            raise ValueError('explicit estimate conditioning required')
        if self.size_status not in ('supported_size', 'modeled_size', 'size_unverified'):
            raise ValueError('explicit size support required')
        if self.supported_capital_usd is not None and not 0 <= number(self.supported_capital_usd) <= number(self.policy.capital_ceiling_usd):
            raise ValueError('supported capital outside ceiling')
        if self.size_status == 'supported_size' and (self.supported_capital_usd is None or
                number(self.supported_capital_usd) < number(self.deployed_capital_usd)):
            raise ValueError('supported size requires explicit funded support')
        if not isinstance(self.inputs, tuple) or len(self.inputs) > 128 or not all(isinstance(v, EstimateInput) for v in self.inputs):
            raise ValueError('immutable typed provider inputs required')
        if self.fee_adjusted_expected_profit_usd is not None:
            number(self.fee_adjusted_expected_profit_usd)
        if (self.conditioning == 'unavailable') != (self.fee_adjusted_expected_profit_usd is None):
            raise ValueError('unavailable result preserves unknown expected profit')

    def to_dict(self):
        capital = number(self.deployed_capital_usd)
        profit = None if self.fee_adjusted_expected_profit_usd is None else number(self.fee_adjusted_expected_profit_usd)
        haircut = buffer_usd(capital, self.policy.buffer_rate)
        result = dict(version=self.version, policy_version=self.policy.version, policy_revision=self.policy.revision,
            target_ceiling_usd=self.policy.capital_ceiling_usd, deployed_capital_usd=exact_wire(capital),
            unused_cash_usd=exact_wire(number(self.policy.capital_ceiling_usd)-capital),
            fee_adjusted_expected_profit_usd=None if profit is None else exact_wire(profit),
            unbuffered_return_percent=None if profit is None else exact_wire(profit/capital*100),
            buffer_usd=exact_wire(haircut), buffer_treatment='model_haircut',
            buffered_profit_usd=None if profit is None else exact_wire(profit-haircut),
            buffered_return_percent=None if profit is None else exact_wire((profit-haircut)/capital*100),
            conditioning=self.conditioning, size_status=self.size_status,
            supported_capital_usd=self.supported_capital_usd, inputs=[v.to_dict() for v in self.inputs])
        if isinstance(self.policy, RequestedTradePolicy):
            result.update(version='predict-estimate-result-2', sizing_mode=self.policy.sizing_mode,
                requested_amount_usd=self.policy.requested_amount_usd, benchmark_venue=self.policy.benchmark_venue,
                benchmark_method=self.policy.benchmark_method)
        return dict(result, revision=digest(result))

    @classmethod
    def from_dict(cls, value, *, policy):
        result = cls(policy, value['deployed_capital_usd'], value['fee_adjusted_expected_profit_usd'],
            value['conditioning'], value['size_status'], value['supported_capital_usd'],
            tuple(EstimateInput.from_dict(v) for v in value['inputs']), value['version'])
        if result.to_dict() != value:
            raise ValueError('estimate result or policy revision conflict')
        return result
