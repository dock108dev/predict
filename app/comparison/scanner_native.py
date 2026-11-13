"""Bind current native execution evidence and calculate observed cashflows."""

from fractions import Fraction as F

from .current_dependencies import digest, instant
from .estimated_ev import _path
from .costs import UnitSpec
from .net_costs import wire


VENUES = ('kalshi', 'polymarket_us')
VERSION = 'scanner-native-execution-1'


class NativeEvidenceError(ValueError):
    """A stable, authored reason suitable for readiness responses."""


def pair_context(model):
    return tuple(model[key] for key in ('partition', 'phase', 'scoring'))


def adapter(venue):
    if venue == 'kalshi':
        from . import scanner_kalshi
        return scanner_kalshi
    if venue == 'polymarket_us':
        from . import scanner_polymarket
        return scanner_polymarket
    raise NativeEvidenceError('native_execution_venue_unsupported')


def model(quote, record, event, group, book, fee_review, *, at):
    from .estimated_content import native_contract
    from .game_phase import original_price_phase

    meta = record.get('comparison_source_metadata', {})
    source = quote['source']
    if not quote['binding']['verified'] or source['provider'] != quote['venue']:
        raise NativeEvidenceError('native_execution_identity_unqualified')
    if not book or not book.get('is_current') or not book.get('book_id'):
        raise NativeEvidenceError('native_execution_book_missing')
    if (quote['original']['units'], quote['original']['quantity_units'], quote['original']['payout_units']) != (
            'usd_per_contract', 'contracts', 'USD') or F(quote['original']['payout']) != 1:
        raise NativeEvidenceError('native_execution_units_unsupported')
    contract = native_contract(quote, group)
    if meta.get('material_sha256') != contract['material_sha256'] or not contract['wording']:
        raise NativeEvidenceError('native_execution_market_evidence_missing')
    descriptor = contract.get('same_outcome') or {}
    predicate = descriptor.get('predicate')
    scope = contract['scope']
    if (scope['period'] != 'full_game' or scope['overtime'] != 'included' or not predicate
            or predicate['domain'] != ('combined_score' if group['market']=='total' else 'home_margin')
            or predicate['operator'] not in ('gt', 'ge', 'lt', 'le')):
        raise NativeEvidenceError('native_execution_score_scope_unqualified')
    phase = original_price_phase(record, at.isoformat())
    if phase['state'] not in ('scheduled', 'live') or phase['reason'] is not None:
        raise NativeEvidenceError('native_execution_phase_unqualified')
    evidence = dict(meta, fee_review=fee_review, event=event, group=group,
                    phase='pregame' if phase['state']=='scheduled' else 'live',
                    market_phase=phase['state'], native_contract=contract)
    resolved = adapter(quote['venue']).resolve(quote, evidence, at=at)
    payout = resolved['payout']
    direction = 'home' if predicate['operator'] in ('gt','ge') else 'away'
    if payout.get('binary_face') == '1':
        payout = dict(payout, below='0' if direction=='home' else '1', above='1' if direction=='home' else '0')
        equality = descriptor.get('equality') or {}
        if payout.get('equal') is None and equality.get('treatment')=='predicate':
            payout['equal'] = '1' if predicate['operator'] in ('le','ge') else '0'
    if (F(payout['above']), F(payout['below'])) != ((1,0) if direction=='home' else (0,1)):
        raise NativeEvidenceError('native_execution_payout_conflict')
    for state in ('equal','terminal'):
        if payout.get(state) is not None and not 0 <= F(payout[state]) <= 1:
            raise NativeEvidenceError('native_execution_payout_conflict')
    threshold = F(predicate['threshold'])
    scoring = descriptor.get('scoring') or {}
    shootout = scoring.get('shootout','not_applicable')
    if event['league']=='NHL' and shootout in ('included','official_final_score'):
        # Exact NHL source terms count the shootout winner's one official goal.
        shootout = 'official_final_score'
    extra_innings = scoring.get('extra_innings','not_applicable')
    if shootout=='unknown' or extra_innings=='unknown' or scoring.get('score_domain','integer')!='integer':
        raise NativeEvidenceError('native_execution_score_scope_unqualified')
    grid = resolved['grid']
    minimum, increment = F(grid['minimum']), F(grid['increment'])
    if minimum <= 0 or increment <= 0:
        raise NativeEvidenceError('native_execution_grid_unqualified')
    result = dict(resolved, version=VERSION, venue=quote['venue'], payout=payout,
                  partition=dict(domain=predicate['domain'], threshold=str(threshold)), direction=direction,
                  scoring=dict(shootout=shootout,extra_innings=extra_innings),
                  phase=evidence['phase'], phase_until=phase.get('current_until'),
                  equality_feasible=threshold.denominator==1 and payout.get('equal_feasible', True),
                  contract_id=contract['id'])
    result['revision'] = digest(result)
    return result


class Leg:
    """A funded native contract over the exact selected book's ask levels."""

    def __init__(self, inputs, at, *, policy):
        self.q = inputs['quote']
        self.model = inputs['native_execution']
        self.event = inputs['event']
        self.group = inputs['group']
        self.policy = policy
        if (self.model['version'] != VERSION or self.model['venue'] != self.q['venue']
                or digest({k:v for k,v in self.model.items() if k!='revision'}) != self.model['revision']
                or any(self.model.get(k) and at >= instant(self.model[k]) for k in ('valid_until','phase_until'))):
            raise ValueError('native_execution_model_expired_or_invalid')
        self.unit = UnitSpec('dollar_face_contracts','1')
        grid = self.model['grid']
        self.grid = dict(minimum_native=grid['minimum'], increment_native=grid['increment'],
                         legal_price_tick=grid['tick'], qualification='reviewed_native_grid')
        self.minimum = F(grid['minimum'])
        self.increment = F(grid['increment'])
        low = F(grid.get('minimum_price','0'))
        high = F(grid.get('maximum_price','1'))
        depth = []
        for level in self.q.get('depth', ()):
            if len(depth)==100 or not low <= F(level['price']) <= high:
                break
            depth.append(level)
        self.path = _path(dict(self.q,depth=depth), self.unit, self.grid)
        if not self.path['levels']:
            raise ValueError('native_execution_depth_missing')
        self.sign = 1 if self.model['direction']=='home' else -1
        self.exposure_per_native = F(1)
        from .estimated_pair import EXPOSURE_FLOOR
        self.lower = self.ceil(max(self.minimum, EXPOSURE_FLOOR))
        self.liquidity_ids = set()
        self.shared_depth = None
        self.conditions = None
        self.cache = {}

    def floor(self, quantity):
        return self.minimum + max(0, (quantity-self.minimum)//self.increment)*self.increment

    def ceil(self, quantity):
        return self.minimum + max(0, -((self.minimum-quantity)//self.increment))*self.increment

    def get(self, quantity):
        if quantity in self.cache:
            return self.cache[quantity]
        left = quantity
        fills = []
        for price, available in self.path['levels']:
            filled = min(left, available)
            fills.append((filled, price))
            left -= filled
            if not left:
                break
        if left or quantity < self.minimum or self.floor(quantity) != quantity:
            raise ValueError('native_execution_size_unavailable')
        acquisition = sum((size*price for size,price in fills), F(0))
        entry = adapter(self.q['venue']).entry_fee(self.model, fills)
        if entry < 0:
            raise ValueError('native_execution_fee_conflict')
        capital = acquisition+entry
        payouts = self.model['payout']
        profits = {}
        for scenario, cell in (('a_wins','above'),('b_wins','below'),('tie','equal'),('terminal_noncompletion','terminal')):
            amount = payouts.get(cell)
            receipt = None if amount is None else F(amount)*quantity
            if cell=='equal' and self.q['venue']=='polymarket_us' and receipt is not None and (receipt*100).denominator!=1:
                receipt = None  # The published per-contract tie rate does not bind half-cent balance rounding.
            profits[scenario] = None if receipt is None else wire(receipt-capital)
        value = dict(acquisition_usd=wire(acquisition), deployed_capital_usd=wire(capital), entry_fee_usd=wire(entry),
                     pair_support=wire(quantity), _pair_capital=capital, _pair_exposure=quantity, profits=profits)
        self.cache[quantity] = value
        return value


def cashflows(legs, components):
    """Prove decisive states and keep unresolved exceptional states explicit."""
    first, second = legs
    if pair_context(first.model) != pair_context(second.model):
        raise ValueError('native_execution_pair_scope_conflict')
    states = {}
    for scenario in ('a_wins','b_wins','tie','terminal_noncompletion'):
        if scenario=='tie' and not any(x.model['equality_feasible'] for x in legs):
            continue
        values = [item['profits'][scenario] for item in components]
        states[scenario] = dict(profit_usd=None if any(v is None for v in values) else wire(sum(map(F, values))))
    # Different or discretionary completion rules cannot prove a joint terminal partition.
    shared = first.model.get('completion')
    if not shared or shared != second.model.get('completion'):
        states['terminal_noncompletion']['profit_usd'] = None
    return sum(item['_pair_capital'] for item in components), states
