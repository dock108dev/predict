"""Bind an SGO quote to independently observed native contract metadata."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from fractions import Fraction
import re

from app.normalization.registry import Registry
from app.storage.store import stamp

VERSION = 'sgo-native-contract-1'
CATALOG_SOURCE = 'novig-public-v3-catalog'
CATALOG_AGE = timedelta(minutes=15)
HOST = 'https://api.novig.com'
FEE_URL = 'https://docs.novig.com/api/concepts/fees'
RULE_HOST = 'https://ludlow-filings.s3.us-east-1.amazonaws.com/'
UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
MARKET_TYPES = {'MONEY': 'moneyline', 'SPREAD': 'spread', 'TOTAL': 'total'}
RULES = {
    ('NFL', 'moneyline'): ('NFLWIN', 'NFL-winner-anchor-2.0-a.pdf', 'NFL%20Winner%20Class%20Certification.pdf', 'half_face'),
    ('NFL', 'spread'): ('NFLSPR', 'NFL-spread-anchor-2.0-a.pdf', 'NFL%20Spread%20Class%20Certification.pdf', 'not_possible'),
    ('NFL', 'total'): ('NFLTOT', 'NFL-total-anchor-2.0-a.pdf', 'NFL%20Total%20Class%20Certification%20.pdf', 'not_possible'),
    ('NCAAF', 'moneyline'): ('NCAAFWIN', 'NCAAF-winner-anchor-2.0-a.pdf', 'NCAAF-Winner-Class-Certification.pdf', 'half_face'),
    ('NCAAF', 'spread'): ('NCAAFSPR', 'NCAAF-spread-anchor-2.0-a.pdf', 'NCAAF-Spread-Class-Certification-2.0.pdf', 'not_possible'),
    ('NCAAF', 'total'): ('NCAAFTOT', 'NCAAF-total-anchor-2.0-a.pdf', 'NCAAF-Total-Class-Certification-2.0.pdf', 'not_possible'),
    ('NBA', 'moneyline'): ('NBAWIN', 'NBA-winner-anchor-2.0-a.pdf', 'NBA-Winner-Class-Certification.pdf', 'void_without_official_winner'),
    ('NBA', 'spread'): ('NBASPR', 'NBA-spread-anchor-2.0-a.pdf', 'NBA-Spread-Class-Certification.pdf', 'not_possible'),
    ('NBA', 'total'): ('NBATOT', 'NBA-total-anchor-2.0-a.pdf', 'NBA-Total-Class-Certification.pdf', 'not_possible'),
    ('NCAAB', 'moneyline'): ('NCAAMWIN', 'NCAAM-winner-anchor-3.0-a.pdf', 'NCAAM-Winner-Class-Certification-3.0.pdf', 'void_without_official_winner'),
    ('NCAAB', 'spread'): ('NCAAMSPR', 'NCAAM-spread-anchor-3.0-a.pdf', 'NCAAM-Spread-Class-Certification-3.0.pdf', 'not_possible'),
    ('NCAAB', 'total'): ('NCAAMTOT', 'NCAAM-total-anchor-3.0-a.pdf', 'NCAAM-Total-Class-Certification-3.0.pdf', 'not_possible'),
    ('NHL', 'moneyline'): ('NHLWIN', 'NHL-winner-anchor-2.0-a.pdf', 'NHL-Winner-Class-Certification.pdf', 'half_face'),
    ('NHL', 'spread'): ('NHLSPR', 'NHL-spread-anchor-2.0-a.pdf', 'NHL-Spread-Class-Certification.pdf', 'not_possible'),
    ('NHL', 'total'): ('NHLTOT', 'NHL-total-anchor-2.0-a.pdf', 'NHL-Total-Class-Certification.pdf', 'not_possible'),
    ('MLB', 'moneyline'): ('MLBWIN', 'MLB-winner-anchor-2.0-a.pdf', 'MLB%20Winner%20Class%20Certification.pdf', 'void_without_official_winner'),
    ('MLB', 'spread'): ('MLBSPR', 'MLB-spread-anchor-2.0-a.pdf', 'MLB%20Spread%20Class%20Certification.pdf', 'not_possible'),
    ('MLB', 'total'): ('MLBTOT', 'MLB-total-anchor-2.0-a.pdf', 'MLB%20Total%20Class%20Certification.pdf', 'not_possible'),
}
SIDES = {
    'points-home-game-ml-home': 'home', 'points-away-game-ml-away': 'away',
    'points-home-game-sp-home': 'home', 'points-away-game-sp-away': 'away',
    'points-all-game-ou-over': 'over', 'points-all-game-ou-under': 'under',
}
OPPOSITE = {'home':'away','away':'home','over':'under','under':'over'}


def _link_id(value, route):
    if not isinstance(value, dict) or value.get('host') != 'novig.com':
        return None
    path = value.get('path')
    match = re.fullmatch(f'/{route}/({UUID})/sportsgameodds', path) if isinstance(path, str) else None
    return match[1] if match else None


def event_link_id(value):
    return _link_id(value, 'event-markets')


def outcome_link_id(value):
    return _link_id(value, 'events')


def _uuid(value):
    return isinstance(value, str) and re.fullmatch(UUID, value) is not None


def _start(value):
    if type(value) is not int or not 0 < value < 4_000_000_000_000:
        raise ValueError('native_catalog_start_unverified')
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)


def _receipt(value, expected_path):
    return (isinstance(value, dict) and value.get('path') == expected_path
            and isinstance(value.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', value['sha256']))


def _receipt_times(receipt, path):
    if not _receipt(receipt, path):
        raise ValueError('sgo_native_catalog_receipt_invalid')
    observed = stamp(receipt['observed_at'])
    original = observed
    if receipt.get('date'):
        original = parsedate_to_datetime(receipt['date'])
        if original.utcoffset() is None or original > observed + timedelta(seconds=2):
            raise ValueError('sgo_native_catalog_receipt_clock')
    if receipt.get('age') is not None:
        age = receipt['age']
        if not isinstance(age, str) or not re.fullmatch('[0-9]{1,5}', age):
            raise ValueError('sgo_native_catalog_receipt_age')
        original = min(original, observed - timedelta(seconds=int(age)))
    return observed, min(original, observed) + CATALOG_AGE


def _spread_subject_roles(markets, links, sgo_frame):
    """Orient official subjects with two original outcome links and a typed strike."""
    roles, anchors, visited = {}, [], set()
    if not isinstance(links, dict) or not isinstance(sgo_frame, str) or not re.fullmatch('[0-9a-f]{64}', sgo_frame):
        return roles, anchors, False
    for market in markets.values():
        market_id = market['marketId']
        if market['marketType'] != 'SPREAD' or market_id in visited:
            continue
        visited.add(market_id)
        try:
            typed = {}
            strike = Fraction(market['strike'])
            if not strike:
                continue
            for outcome in market['outcomes']:
                outcome_id = outcome['outcomeId']
                candidates = links.get(outcome_id, [])
                if len(candidates) != 1 or not _uuid(outcome.get('subjectId')):
                    break
                link = candidates[0]
                side = link['side']
                if (side not in ('home','away') or side in typed or link['market'] != 'spread'
                        or link['period'] != 'game' or link['odd_id'] != f'points-{side}-game-sp-{side}'
                        or Fraction(link['line']) != (strike if side == 'home' else -strike)):
                    break
                # This display value only vetoes contradictions. Event and
                # outcome IDs, reciprocal quote sides and strike are the anchor.
                _, separator, label_line = outcome['name'].rpartition(' ')
                if not separator or Fraction(label_line) != Fraction(link['line']):
                    break
                typed[side] = (outcome, link)
            if set(typed) != {'home','away'}:
                continue
            home, home_link = typed['home']
            away, away_link = typed['away']
            if (home_link['opposing_odd_id'] != away_link['odd_id'] or away_link['opposing_odd_id'] != home_link['odd_id']
                    or home['subjectId'] == away['subjectId']):
                continue
            candidate = dict(home=home['subjectId'], away=away['subjectId'])
            if roles and candidate != roles:
                return {}, [], True
            roles = candidate
            anchors.append(dict(sgo_frame=sgo_frame, market_id=market_id, strike=market['strike'],
                home_outcome=home['outcomeId'],away_outcome=away['outcomeId'],home_subject=roles['home'],
                away_subject=roles['away'], source_url='https://docs.novig.com/api/catalog'))
        except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError):
            continue
    return roles, anchors, False


def capture_catalog(sgo_event_id, event_id, event, event_receipt, pages, linked_outcomes, *, sgo_frame=None):
    """Retain official membership and terms for named SGO outcomes only."""
    if (not isinstance(event, dict) or event.get('eventId') != event_id or not _uuid(event_id)
            or event.get('league') not in ('NFL','NBA','MLB','NHL','NCAAF','NCAAB')):
        raise ValueError('sgo_native_catalog_event_invalid')
    _start(event['startsTs'])
    clocks = [_receipt_times(event_receipt, '/v3/public/catalog/events/' + event_id)]
    matched, seen_market, seen_outcome = {}, set(), set()
    selected_outcomes = set(linked_outcomes)
    if not 1 <= len(pages) <= 2:
        raise ValueError('sgo_native_catalog_page_limit')
    for page, receipt in pages:
        if not isinstance(page, dict) or not isinstance(page.get('items'), list) or len(page['items']) > 240:
            raise ValueError('sgo_native_catalog_market_page_invalid')
        clocks.append(_receipt_times(receipt, '/v3/public/catalog/markets'))
        for market in page['items']:
            if not isinstance(market, dict) or not isinstance(market.get('outcomes'), list):
                raise ValueError('sgo_native_catalog_market_invalid')
            outcome_ids = [item['outcomeId'] for item in market['outcomes']]
            market_id = market.get('marketId')
            if (market.get('eventId') != event_id or market.get('marketType') not in MARKET_TYPES
                    or not _uuid(market_id) or market_id in seen_market
                    or not all(_uuid(outcome_id) for outcome_id in outcome_ids)
                    or len(set(outcome_ids)) != len(outcome_ids) or seen_outcome.intersection(outcome_ids)):
                raise ValueError('sgo_native_catalog_membership_conflict')
            seen_market.add(market_id)
            seen_outcome.update(outcome_ids)
            selected = selected_outcomes.intersection(outcome_ids)
            if not selected or len(outcome_ids) != 2:
                continue
            normalized = {key:market.get(key) for key in ('marketId','eventId','marketType','startsTs',
                                                          'status','strike','voids')}
            fee = market.get('fee')
            normalized['fee'] = {key:fee.get(key) for key in ('coefficient','makerCredit','charged')} if isinstance(fee, dict) else None
            normalized['outcomes'] = [{key:item.get(key) for key in ('outcomeId','name','status','subjectId')}
                                      for item in market['outcomes']]
            normalized['receipt'] = receipt
            matched.update(dict.fromkeys(selected, normalized))
    observed, expiry = max(t[0] for t in clocks), min(t[1] for t in clocks)
    if observed >= expiry:
        raise ValueError('sgo_native_catalog_receipt_expired')
    roles, anchors, conflicts = _spread_subject_roles(matched, linked_outcomes, sgo_frame)
    return dict(source=CATALOG_SOURCE, sgo_event_id=sgo_event_id, observed_at=observed.isoformat(),
                expires_at=expiry.isoformat(), event_receipt=event_receipt, markets=matched,
                subject_roles=roles, subject_role_anchors=anchors, subject_role_conflict=conflicts,
                event={key:event.get(key) for key in ('eventId','league','startsTs','status')})


def _team(name, league, expected):
    if expected.startswith('sportsgameodds:'):
        return None
    result = Registry.current().resolve('team', name, league=league, venue='novig')
    if result.status != 'resolved':
        return None
    return result.canonical_id == expected


def _side_matches(outcome, side, event, family, line, subject_roles):
    """Corroborate the link's side; outcome names never select a contract."""
    name = outcome['name']
    if not isinstance(name, str) or not 0 < len(name) <= 180:
        return False
    if family == 'total':
        direction, separator, label_line = name.partition(' ')
        return (not outcome.get('subjectId') and bool(separator)
                and direction == side.title() and Fraction(label_line) == line)
    if not _uuid(outcome.get('subjectId')):
        return False
    if family == 'spread':
        name, separator, label_line = name.rpartition(' ')
        if not separator or Fraction(label_line) != line:
            return False
    resolved = _team(name, event['competition'], event[side])
    if resolved is False or subject_roles and outcome['subjectId'] != subject_roles.get(side):
        return False
    return resolved is True or bool(subject_roles)


def settlement_profile(league, family, line, voids):
    """Describe the filed full-game rule while leaving exceptional payoffs open."""
    rule = RULES.get((league,family))
    if (not rule or voids != 'FMV'
            or (line is not None if family == 'moneyline' else line is None or line.denominator != 2)):
        return dict(available=False, reason='sgo_native_settlement_rules_unreviewed')
    rule_id, anchor, class_filing, equality = rule
    if family == 'moneyline':
        shortened = 'governing_body_official_winner_or_filed_tie_rule'
        forfeit = ('official_winner_after_commencement' if league in ('NBA','NCAAB') else
                   'forfeit_only_winner_does_not_qualify')
    else:
        shortened = ('completion_under_competition_shortened_play_rule_or_unequivocal_criterion'
                     if league in ('NBA','NCAAB','NCAAF','NHL') else
                     'played_to_conclusion_or_unequivocal_criterion')
        forfeit = ('recorded_play_excluding_administrative_forfeit_score' if league in ('NBA','NCAAB','NCAAF','NHL') else
                   'void_unless_recorded_play_determines_criterion')
    return dict(available=True, rule_id=rule_id, source_url=RULE_HOST+anchor, class_url=RULE_HOST+class_filing,
        scope='completed_full_game', overtime='not_applicable' if league == 'MLB' else 'included',
        extra_innings='included' if league == 'MLB' else 'not_applicable',
        shootout='official_final_score' if league == 'NHL' else 'not_applicable',
        shootout_count='one_goal_to_winning_team' if league == 'NHL' else None,
        shortened_game=shortened, forfeit=forfeit,
        normal_win='1', normal_loss='0', equality=equality,
        equality_payout='0.5' if equality == 'half_face' else None,
        void='fair_market_value', void_payout=None, exceptional_payoff_available=False)


def bind(record, witness, *, at):
    """Confirm the exact event, instrument, outcome, line, phase and terms."""
    def missing(reason):
        return dict(available=False, reason=reason)

    try:
        quote, event, market = (record[key] for key in ('quote','event','market_identity'))
        source, meta = quote['source'], record['comparison_source_metadata']
        if source['provider'] != 'sportsgameodds':
            return missing('sgo_native_binding_not_aggregate')
        outcome_id = outcome_link_id(meta.get('bookmaker_market_link'))
        if quote['venue'] != 'novig' or not outcome_id:
            return missing('sgo_native_outcome_link_unavailable')
        event_id = (event.get('shared_provider_ids') or {}).get('novig_event')
        if not _uuid(event_id):
            return missing('sgo_native_event_link_unavailable')
        if not witness or witness.get('source') != CATALOG_SOURCE:
            return missing('sgo_native_catalog_unavailable')
        at = stamp(at)
        observed, expiry = stamp(witness['observed_at']), stamp(witness['expires_at'])
        if not observed <= at < expiry or expiry - observed > CATALOG_AGE:
            return missing('sgo_native_catalog_expired')
        native_event = witness['event']
        native_market = witness['markets'].get(outcome_id)
        if not native_market:
            return missing('sgo_native_outcome_absent_from_catalog')
        market_id = native_market['marketId']
        if (not _receipt(witness['event_receipt'], '/v3/public/catalog/events/'+event_id)
                or not _receipt(native_market['receipt'], '/v3/public/catalog/markets')
                or not _uuid(market_id) or witness['sgo_event_id'] != source['native_event_id']
                or event_id != native_event['eventId'] or event_id != native_market['eventId']):
            return missing('sgo_native_catalog_identity_conflict')
        league, family = event['competition'], market['family']
        kickoff = _start(native_event['startsTs'])
        if (native_event['league'] != league or native_market['startsTs'] != native_event['startsTs']
                or kickoff != stamp(event['scheduled_start']) or kickoff != stamp(market['scheduled_start'])
                or MARKET_TYPES.get(native_market['marketType']) != family or market['period'] != 'full_game'):
            return missing('sgo_native_market_scope_conflict')
        side = SIDES.get(source['native_outcome_id'])
        line = None if source['native_line'] is None else Fraction(source['native_line'])
        selection = record['selection']
        signed = None if selection.get('signed_line') is None else Fraction(selection['signed_line'])
        if not side or line != signed or (family == 'total' and side != selection['predicate']) or (
                family != 'total' and selection.get('participant') != event.get(side)):
            return missing('sgo_native_selected_side_conflict')
        strike = native_market.get('strike')
        if family == 'moneyline':
            if line is not None or strike is not None and Fraction(strike) != 0:
                return missing('sgo_native_line_conflict')
        else:
            expected = -line if family == 'spread' and side == 'away' else line
            if not isinstance(strike, str) or Fraction(strike) != expected:
                return missing('sgo_native_line_conflict')
        outcomes = native_market['outcomes']
        if (len(outcomes) != 2 or len({item['outcomeId'] for item in outcomes}) != 2
                or not all(_uuid(item['outcomeId']) for item in outcomes)):
            return missing('sgo_native_outcome_set_unverified')
        selected = next(item for item in outcomes if item['outcomeId'] == outcome_id)
        other = next(item for item in outcomes if item['outcomeId'] != outcome_id)
        other_line = -line if family == 'spread' else line
        if family != 'total' and witness.get('subject_role_conflict'):
            return missing('sgo_native_subject_roles_conflict')
        subject_roles = witness.get('subject_roles') or {}
        if (not _side_matches(selected, side, event, family, line, subject_roles)
                or not _side_matches(other, OPPOSITE[side], event, family, other_line, subject_roles)
                or family != 'total' and selected['subjectId'] == other['subjectId']):
            return missing('sgo_native_selected_side_conflict')
        phase = {'OPEN_PREGAME':'scheduled','OPEN_INGAME':'live'}.get(native_event['status'])
        matched_phase = (phase == 'scheduled' and at < kickoff and meta.get('provider_phase') == 'pregame' or
                         phase == 'live' and at >= kickoff and meta.get('provider_phase') == 'live')
        phase_verified = matched_phase and native_market['status'] == 'OPEN' and all(o['status'] == 'TBD' for o in outcomes)
        settlement = settlement_profile(league, family, line, native_market.get('voids'))
        original = quote['original']
        quote_available = (quote['state'] == 'available' and original['units'] == 'american_odds'
                           and original['payout'] == '1' and original['payout_units'] == 'USD'
                           and abs(Fraction(original['value'])) >= 100)
        return dict(available=True, reason=None, version=VERSION, venue='novig', phase=phase,
            phase_verified=phase_verified, quote_available=quote_available,
            event_id=event_id, market_id=market_id, outcome_id=outcome_id, opposite_outcome_id=other['outcomeId'],
            original_link=meta['bookmaker_market_link'], original_event_link=event_id,
            selected_side=side, signed_line=source['native_line'], settlement=settlement,
            subject_role_anchors=witness.get('subject_role_anchors', []) if family != 'total' else [],
            venue_fee=native_market.get('fee'), revision=witness['revision'],
            event_receipt=witness['event_receipt'], market_receipt=native_market['receipt'],
            current_until=(min(kickoff, expiry) if phase_verified and phase == 'scheduled' else expiry).isoformat())
    except (ArithmeticError, AttributeError, KeyError, StopIteration, TypeError, ValueError):
        return missing('sgo_native_catalog_evidence_invalid')


def pregame_fee(binding):
    """Apply only the native market's observed pregame zero-fee term."""
    from .snapshot_fee_outcome import unavailable

    if not binding.get('available'):
        return unavailable(binding.get('reason') or 'sgo_native_catalog_unavailable')
    if not binding.get('phase_verified') or not binding.get('quote_available'):
        return unavailable('sgo_native_catalog_phase_or_quote_unverified')
    if binding['phase'] != 'scheduled':
        return unavailable('sgo_native_live_fee_requires_signed_book')
    fee = binding.get('venue_fee') or {}
    if fee.get('charged') != 'WHEN_LIVE':
        return unavailable('sgo_native_pregame_fee_terms_unverified')
    return dict(available=True, classification='exact_public', reason=None, trade_fee_usd='0',
        quantity='1', quantity_unit='USD payout claim', fill_count=1, liquidity_role='taker',
        fee_payment='at_fill', fee_cashflows={'at_fill_usd':'0'}, profile='manual_retail',
        assumptions=['The exact Novig game contract charges taker fees only while in-game.'],
        evidence=dict(version=VERSION, source_url=FEE_URL, fee_rate='0',
            reviewed_at=binding['market_receipt']['observed_at'],review_before=binding['current_until'],
            native_market_id=binding['market_id'],native_outcome_id=binding['outcome_id'],
            market_receipt=binding['market_receipt'], native_binding_revision=binding['revision']))
