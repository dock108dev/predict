"""One explicitly bound retrospective estimate; never used by rankings or scoring."""
from decimal import Decimal, Context, localcontext
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from app.opportunities.board import leg_value, expected, display
from app.reference.research_loop import calculation

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def retained():
    path = ROOT/'evidence/page-research/target-comparison.json'
    assessment = json.loads((ROOT/'evidence/page-ev-integration/ordinary-winner-assessment.json').read_text())
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != assessment['comparison_sha256']:
        raise ValueError('Saved research comparison changed')
    comparison = json.loads(raw)
    if calculation(comparison['source_dependencies']) != comparison['source_result']:
        raise ValueError('Saved page estimate does not recompute')
    return comparison, assessment


def binding_matches(comparison, assessment, game):
    b = assessment['binding'];p = comparison['source_result']['page'];c = comparison['target_contract']
    return (game == comparison['target_identity']
            and game['id'] == b['game_id'] and game['scheduled_start'] == b['scheduled_start']
            and game['sources']['kalshi']['market_id'] == b['target_market_id']
            and game['sides']['kalshi:yes']['predicate'] == 'win'
            and game['sides']['kalshi:yes']['participant'] == c['team'] == b['target_team']
            and c['id'] == 'kalshi:yes' and c['side'] == b['target_side'] == 'yes'
            and c['book_id'] == b['target_book_id']
            and p['event_id'] == b['source_event_id'] and p['bookmaker'] == b['source_bookmaker']
            and p['market'] == b['source_market'] and p['raw_sha256'] == b['source_sha256']
            and comparison['target_fee_assessment']['sources']['kalshi']['source']['sha256'] == b['target_rules_sha256'])


def estimate(comparison, assessment, game, quantity='10', scenario='cent'):
    """Walk the original ladder at requested size; insufficient depth stays unavailable."""
    if not binding_matches(comparison, assessment, game):
        raise ValueError('Ordinary-winner assessment binding mismatch')
    if scenario not in ('cent', 'direct', 'unknown'):
        raise ValueError('Unknown fee scenario')
    with localcontext(Context(prec=100)):
        q = Decimal(quantity)
        if not q.is_finite() or q <= 0 or q != q.to_integral_value() or q > 100000000:
            raise ValueError('Use a positive whole-contract quantity up to 100,000,000')
        page = comparison['source_result']['page']
        probability = Decimal(next(s['probability'] for s in page['sides'] if s['team'] == comparison['target_contract']['team']))
        leg = leg_value(comparison['target_contract'], comparison['target_fee_assessment'],
                        comparison['target_cutoff'], q, scenario, game)
        ev = expected(leg, probability if assessment['ordinary_winner_comparable'] is True else None, q, game)
        ev['probability_source'] = 'Saved page-derived proportional de-vig estimate'
        reasons = list(leg['reasons'])
        if assessment['ordinary_winner_comparable'] is not True:
            reasons.append(assessment.get('unavailable_reason') or 'Ordinary-winner comparability unassessed')
        ev.update(probability=str(probability), quantity=str(q), unconditional_ev=None,
                  current_executable=False, prospective_evaluation_eligible=False,
                  label='Retrospective, time-mismatched research comparison',
                  reference_retrieved_at=comparison['reference_retrieved_at'],
                  target_received_at=comparison['target_received_at'], target_cutoff=comparison['target_cutoff'],
                  source_url=page['url'], bookmaker=page['bookmaker'],
                  sides=[dict(team=s['team'],odds=s['american_price'],probability=s['probability'],
                              percent=display(Decimal(s['probability'])*100,4)) for s in page['sides']],
                  fee_scenario=scenario, target_team=comparison['target_contract']['team'],
                  arithmetic=comparison['source_result']['arithmetic'],
                  fee_basis=('Material fee inputs unresolved; net calculation unavailable.' if scenario == 'unknown' else
                    'Historical kalshi-july7-observed-sep12 schedule; '+('cent' if scenario == 'cent' else '0.0001')+
                    ' balance, multiplier 1, no event override, one new taker order, one fill per consumed level; no extra account charges or rebates; applicability unverified.'),
                  leg=leg, reasons=reasons, assessment=assessment,
                  limitations=assessment['limitations'])
        ev['display'] = {k:display(ev[k]) for k in ('expected_profit','expected_payout','return_pct')}
        ev['display'].update({k:display(leg[k]) for k in ('notional','cash','fee')})
        return ev


def for_saved_game(session, game, quantity, scenario, *, live=False):
    from app.reference.multi_page import saved_comparisons, SESSION
    if live or session != SESSION:
        return None
    entry = saved_comparisons().get(game['id'])
    if not entry or entry.get('comparison') is None:
        return None
    comparison, assessment = entry['comparison'], entry['assessment']
    if not binding_matches(comparison, assessment, game):
        return None
    return estimate(comparison, assessment, game, quantity, scenario)
