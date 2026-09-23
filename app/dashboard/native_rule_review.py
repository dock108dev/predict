"""Fourth opt-in interpretation: branch evidence, never a native qualification override."""
from decimal import Decimal, localcontext
from pathlib import Path
import hashlib
VERSION = 'atl-gb-native-review-4'
ROOT = Path(__file__).resolve().parents[2]
PINNED = {
 'evidence/slice-9/research/kalshi-pdf-browser.json': '1c6f99bd0b2b733170d47e6ab6c213d004d956547f8114e2e51e27eb53acba0f',
 'evidence/slice-9/research/kalshi-schedule.pdf': '2e48eb1925b8fa9824f5704b7362950d30daba2118ea152e84b1689c2cdb232d',
 'evidence/slice-9/research/sources.json': '544f3c55fd3f55e8b21d4ba680c9bb92bb19762fd85be996008d9f96eef7e605',
 'evidence/b6-native-review-20260923-v1/retained-terms.json': '1d8fbec2fac4122656d2e62d213b1763e61bd52fc86587eef284ee83248aae49',
}

def evidence():
    for name, expected in PINNED.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Rule review evidence mismatch: '+name)
    return dict(hashes=PINNED, kalshi_fee=dict(
        status='Retained browser extraction, not successful original PDF response bytes',
        effective_date_in_extraction='2026-07-07', taker_formula='M * 0.07 * C * P * (1-P)',
        maker_formula='M * 0.0175 * C * P * (1-P)', listed_series='KXNFLGAME',
        listed_maker_multiplier='1', listed_taker_multiplier='1', settlement_charge_in_extraction='0',
        source_url='https://kalshi.com/docs/kalshi-fee-schedule.pdf',
        historical_applicability=False,
        remaining='Prove no intervening series/schedule changes and precedence at the observation. PDF extraction rounds fee plus cost to centicent; undated API docs distinguish two account grids and refunds; example table uses cents. Do not select a rule silently.',
        limitations='Direct retained PDF fetch was HTTP429 challenge, not PDF bytes. Extraction supports conditional interpretation only; no retry or bypass. FCM/private charges separate.'),
        settlement_equivalent=False, historical_state_recoverable=False,
        branches=[
         dict(outcome='ordinary final winner',status='compatible conditional branch',kalshi='winning team 1; losing team 0',us='winning team 1; losing team 0',basis='selected native market terms'),
         dict(outcome='full-game tie',status='compatible conditional branch',kalshi='0.50',us='0.50',basis='selected native market terms'),
         dict(outcome='overtime',status='current documents agree; historical Kalshi coverage unproved',kalshi='included unless specified otherwise',us='included if played',basis='current undated FOOTBALLGAMEWIN + selected US terms'),
         dict(outcome='postponement',status='different contractual triggers',kalshi='must begin within 48 hours of original start',us='must be rescheduled to a date within two days of original date',basis='selected native market terms; calendar-date boundary is not elapsed hours'),
         dict(outcome='fair-price resolution',status='no guaranteed complementary payout',kalshi='Kalshi discretionary fair price',us='US last fair market price',basis='selected terms; equal words do not establish equal valuations'),
         dict(outcome='suspension/abandonment',status='current rule divergence plus missing US detail',kalshi='before55 / after55 / official-final branches; exact55 unresolved',us='two-day rescheduling clause includes suspension; 55-minute override absent',basis='current undated Kalshi PDF vs selected US terms; precedence still needed'),
         dict(outcome='pregame forfeit / disqualification',status='missing US documentation',kalshi='current terms: fair price',us=None,basis='undated Kalshi PDF; absence of US clause is not opposite payout'),
         dict(outcome='poststart forfeit / disqualification',status='missing US documentation',kalshi='official result / disqualified team NO and declared opponent winner YES',us=None,basis='undated Kalshi PDF'),
         dict(outcome='venue or home-away change',status='missing US documentation',kalshi='same home-away and within48h: final; reversed or outside week: fair price; other branches unresolved',us=None,basis='undated Kalshi PDF'),
         dict(outcome='corrections, source priority and review',status='missing US documentation and historical Kalshi applicability',kalshi='first official final; pre-expiry correction discretion; post-expiry ignored; hierarchy; Rule7.1/7.2',us='relevant governing body only',basis='undated PDF vs selected native US terms')])

def conditional_payout(outcome, quantity, *, exceptional=False):
    """Total complementary pair payout only for proven ordinary/tie branches.

    Explicit exceptional flag prevents a tied or winning score from overriding a
    cancellation, forfeit or review branch. No fair-price numeric substitute.
    """
    q=Decimal(quantity)
    if not q.is_finite() or q<=0 or len(q.as_tuple().digits)>24 or abs(q.as_tuple().exponent)>12:
        raise ValueError('bounded positive quantity required')
    if exceptional or outcome not in ('ordinary_final_winner','full_game_tie'):
        return None
    return str(q)

def partial_margin(candidate):
    """Propagate the already reviewed US bound; excludes every other charge."""
    bound=next(l['review_entry_fee_bound'] for l in candidate['legs'] if l['venue']=='polymarket_us')
    if candidate['notional'] is None or not bound['available']:
        return dict(available=False,lower=None,upper=None)
    with localcontext() as ctx:
        ctx.prec=100
        gross=Decimal(conditional_payout('ordinary_final_winner',candidate['modeled_quantity']))-Decimal(candidate['notional'])
        return dict(available=True,lower=str(gross-Decimal(bound['upper'])),upper=str(gross-Decimal(bound['lower'])),
            qualification='Conditional ordinary-winner or full-game-tie margin after US gross entry commission ONLY. Same new all-taker order and split-independent cap assumptions as review3. Excludes Kalshi fees, settlement/private charges and rebates. Not net profit or executable opportunity.')

def conditional_kalshi_model(fills):
    """Raw all-taker formula from retained extraction, before disputed rounding."""
    with localcontext() as ctx:
        ctx.prec=100
        raw=Decimal(0)
        if not fills:return dict(available=False,raw_fee=None)
        for fill in fills:
            p=Decimal(fill['price']);q=Decimal(fill['quantity'])
            if not p.is_finite() or not q.is_finite() or not 0<p<1 or q<=0 or any(len(v.as_tuple().digits)>24 or abs(v.as_tuple().exponent)>12 for v in (p,q)):
                raise ValueError('Unsupported modeled fills')
            raw+=Decimal('.07')*q*p*(1-p)
        return dict(available=True,raw_fee=str(raw),charged_fee=None,multiplier_assumption='1',role_assumption='all taker',
            qualification='Conditional unrounded July-extraction formula only. Not an applicable September fee, bound, account debit or net result; rounding precedence and effective schedule unresolved.')

def annotate(result):
    result['retained_review'].update(version=VERSION,rule_review=evidence(),
        note='Review4 preserves review3 US coefficient and bounds. Retained browser-extracted Kalshi schedule is distinct from original response bytes. Conditional branches never establish all-outcome equivalence or historical qualification.')
    for candidate in result['candidates']:
        candidate['review_partial_margin']=partial_margin(candidate)
        leg=next(l for l in candidate['legs'] if l['venue']=='kalshi')
        candidate['review_kalshi_raw_model']=conditional_kalshi_model(leg['fills'])
        candidate['review_settlement_branches']={k:conditional_payout(k,candidate['modeled_quantity']) for k in ('ordinary_final_winner','full_game_tie','postponement','suspension','forfeit','fair_price','unknown')}
    return result
