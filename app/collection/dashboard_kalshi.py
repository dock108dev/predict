"""Read-only Kalshi discovery from explicit game milestones and event tickers."""

import asyncio
import json
from collections import defaultdict
from datetime import timedelta
from fractions import Fraction as F

from app.adapters.kalshi import REST_URL, identity
from app.comparison import execution_contract, scanner_kalshi
from app.comparison.native_scoring_scope import source_rules
from app.dashboard.session_projection import stable
from app.fees.evidence import applies
from app.fees.product_schedules import for_offer
from app.storage.store import stamp

from .admission_enrichment import TEAM_KEYS, resolve_team
from .native_experiment_depth import ERRORS
from .native_fee_metadata import context
from .native_scope_bindings import series_binding
from .native_score_binding import bind

TYPES = dict(NFL='football_game', NCAAF='football_game', NBA='basketball_game',
             NCAAB='basketball_game', NHL='hockey_match', MLB='baseball_game')
NATIVE_LEAGUES = dict(NCAAF='NCAAFB', NCAAB='NCAAMB')
IDENTITY_AGE = timedelta(seconds=60)
DOCUMENT_BYTES = 3 * 1024 * 1024
PAGE_SIZE = 72
MAX_PAGES = 3
MAX_EVENTS = 16


def _compatible(event, expected):
    return (event['competition'] == expected[0] and stamp(event['scheduled_start']) == expected[1]
            and (event['home'], event['away']) == expected[2:])


def _role_proof(league, milestone, listed, bindings):
    details = milestone['details']
    ids = {side: details[side+'_team_id'] for side in ('home', 'away')}
    main = details['main_game_event_ticker']
    if main not in listed or bindings[main]['family'] != 'moneyline' or len(set(ids.values())) != 2:
        raise ValueError('native_event_roles_unverified')
    roles, labels = {}, {}
    for side, team_id in ids.items():
        options = {}
        for market in listed[main]['markets']:
            label = market.get('yes_sub_title')
            if (not isinstance(label, str) or market['event_ticker'] != main
                    or market.get('strike_type') != 'structured'
                    or (market.get('custom_strike') or {}).get(TEAM_KEYS[league]) != team_id
                    or not market['rules_primary'].startswith('If '+label+' wins ')
                    or not market['rules_primary'].endswith(', then the market resolves to Yes.')):
                continue
            canonical = resolve_team(dict(id=team_id, name=label), league, 'kalshi')
            if canonical:
                options[label] = canonical
        if len(options) != 1:
            raise ValueError('native_event_roles_unverified')
        labels[side], roles[side] = next(iter(options.items()))
    if roles['home'] == roles['away']:
        raise ValueError('native_event_roles_unverified')
    witness = dict(version='kalshi-structured-role-1', event_id=main, roles=roles,
                   witnesses=[dict(canonical=roles[s], native_id=ids[s], label=labels[s]) for s in roles])
    return roles, ids, labels, witness


def _outcomes(raw, cell, main, roles, ids, labels, witness):
    family = cell['family']
    if family == 'moneyline':
        for side, label in labels.items():
            if ((raw.get('custom_strike') or {}).get(TEAM_KEYS[cell['sport']]) == ids[side]
                    and raw['strike_type'] == 'structured' and raw['yes_sub_title'] == label
                    and raw['rules_primary'].startswith('If '+label+' wins ')
                    and raw['rules_primary'].endswith(', then the market resolves to Yes.')):
                return [(side, None, 'yes')]
        return []
    predicate = bind(raw, cell, revised=True, event=dict(id=main, native_role_evidence=witness))
    if not predicate:
        return []
    line = F(predicate['line'])
    if family == 'total':
        return [('over', line, 'yes'), ('under', line, 'no')]
    side = next((s for s in roles if roles[s] == predicate['participant']), None)
    if side is None:
        return []
    return [(side, line, 'yes'), ('away' if side == 'home' else 'home', -line, 'no')]


def _contract(raw, cell, expected):
    league, family = cell['sport'], cell['family']
    rule = next((r for r in source_rules(detached=False) if r['provider'] == 'kalshi'
                 and r['native_type'] == cell['series_ticker']), {})
    primary, secondary = raw['rules_primary'], raw.get('rules_secondary', '')
    text = (primary+' '+secondary).lower()
    available = rule.get('evidence_available') is True and not any(
        clause in text for clause in ('regulation only', 'excluding overtime', 'overtime is excluded',
                                      'shootout does not count', 'extra innings excluded'))
    equality = 'predicate'
    if family == 'moneyline':
        equality = ('half_face' if scanner_kalshi.HALF_TIE.search(secondary) else 'unknown') if league == 'NFL' else 'not_feasible'
    elif F(expected['signed_line']).denominator == 1:
        # No fair tie/push partition is inferred from a two-runner quote.
        equality = 'unknown'
    settlement = dict(available=available, rule_id=rule.get('source_sha256'),
        evidence=rule.get('evidence'), overtime=rule.get('overtime'),
        extra_innings=rule.get('extra_innings'), shootout=rule.get('shootout'), equality=equality,
        reason=None if available else 'native_settlement_equivalence_unverified')
    if 'Rule 84.4' in (rule.get('evidence') or {}).get('clause', ''):
        settlement['shootout_count'] = 'one_goal_to_winning_team'
    return dict(expected, phase='pregame', settlement=settlement)


def _fee(series, changes, history, *, review, event, market, at, evidence):
    effective_at = max(stamp(r['received_at']) for r in evidence)
    value = context(series, changes, history, series['ticker'], event, effective_at.isoformat())
    observed = stamp(review['reviewed_at'])
    future = [stamp(r['scheduled_ts']) for r in value['series_changes']+value['event_changes']
              if stamp(r['scheduled_ts']) > effective_at]
    expiry = min([effective_at+IDENTITY_AGE, *future]
                 + ([stamp(review['review_before'])] if review.get('review_before') else []))
    if not observed <= effective_at <= at < expiry:
        raise ValueError('kalshi_fee_review_unavailable')
    schedule = dict(venue='kalshi', product='event_contract', version=review['version'],
        coefficient=review['fee_rate'], effective_from=observed.isoformat(), effective_to=expiry.isoformat(),
        sources=[dict(url=review['source_url'], sha256=review['sha256'])])
    application = dict(venue='kalshi', environment='production', market_id=market, product='event_contract',
        trade_time=at.isoformat(), calculation_time=at.isoformat(), series_id=series['ticker'], event_id=event,
        kalshi_metadata=value, complete_order_history=True, balance_precision='0.0001',
        applicability_evidence=dict(receipts=[r['sha256'] for r in evidence]))
    terms = dict(context=application, registry=dict(schema=1, schedules=[schedule]), account_verified=False,
                 includes_intermediary_charges=False)
    return dict(model='kalshi_direct_taker_bound', terms=terms, schedule_revision=stable(value)), expiry


def _grid(raw, event, market, side, listing):
    revision = stable(raw)
    observed = dict(status='observed', native_event_id=event, native_market_id=market,
        source=dict(body_sha256=listing['sha256']), material_sha256=revision, values=raw)
    source = dict(native_event_id=event, native_market_id=market, native_side=side)
    # Validate the published legal grid independently from execution. The
    # actual offers and every modeled fill are validated against it later.
    probe = next(F(b['start'])+F(b['step']) for b in raw['price_ranges']
                 if F(b['start'])+F(b['step']) < 1)
    grid, _ = scanner_kalshi._market_grid(dict(source=source, original=dict(
        value=str(probe if side == 'yes' else 1-probe))),
        dict(market=raw, selected_market_observation=observed, material_sha256=revision))
    return grid, revision


class Catalog:
    def __init__(self):
        self.cache = {}

    async def get(self, client, path, params, cutoff):
        key = path, tuple(sorted(params.items()))
        prior = self.cache.get(key)
        at = client.now()
        if prior and stamp(prior[1]['received_at'])+IDENTITY_AGE > at:
            return prior
        body, evidence, reason = await client._read('kalshi', REST_URL+path, cutoff, params=params,
                                                    body_limit=DOCUMENT_BYTES)
        if reason:
            return None, evidence, reason
        if len(self.cache) >= 192:
            self.cache = {k:v for k,v in self.cache.items() if stamp(v[1]['received_at'])+IDENTITY_AGE > at}
            if len(self.cache) >= 192:
                self.cache.pop(next(iter(self.cache)))
        self.cache[key] = body, evidence, reason
        return body, evidence, reason

    async def read(self, client, league, events, *, cutoff, products):
        if not events or not any(r['quote']['venue'] == 'kalshi' for rows in events.values() for _,_,r in rows):
            return {}
        times = {stamp(rows[0][2]['event']['scheduled_start']) for rows in events.values()}
        start, end = min(times), max(times)
        cursor, previous, prospects = '', None, []
        for _ in range(MAX_PAGES):
            body, evidence, failure = await self.get(client, '/milestones', dict(category='Sports',
                type=TYPES[league], minimum_start_date=start.isoformat(), limit=PAGE_SIZE, cursor=cursor), cutoff)
            if failure:
                return {}
            rows = body['milestones']
            starts = [stamp(row['start_date']) for row in rows]
            if starts != sorted(starts) or starts and previous and starts[0] < previous:
                return {}
            prospects.extend((row, evidence) for row, kickoff in zip(rows, starts, strict=True)
                if kickoff in times and row.get('category') == 'Sports' and row.get('type') == TYPES[league]
                and row.get('details', {}).get('league') == NATIVE_LEAGUES.get(league, league)
                and row['details'].get('status') == 'scheduled')
            cursor = body['cursor']
            if not cursor or starts and starts[-1] > end:
                break
            if starts:
                previous = starts[-1]
        else:
            return {}

        if not prospects or len(prospects) > MAX_EVENTS:
            return {}
        candidates = await asyncio.gather(*(self._event(client, league, events, row, receipt, cutoff)
                                              for row, receipt in prospects))
        exact = defaultdict(list)
        for outcome in candidates:
            for cid, match in outcome.items():
                exact[cid].extend(match)
        selected = {cid: rows[0] for cid, rows in exact.items() if len(rows) == 1}
        by_event = defaultdict(list)
        for cid, row in selected.items():
            by_event[row[1]['event_ticker'], row[2]['series_ticker']].append((cid, row))
        output = await asyncio.gather(*(self._bindings(client, products, entries, event, series, cutoff)
                                        for (event,series), entries in by_event.items()))
        return {cid: binding for group in output for cid, binding in group.items()}

    async def _event(self, client, league, events, milestone, witness, cutoff):
        try:
            choices = {}
            for ticker in dict.fromkeys(milestone['related_event_tickers']):
                cell = series_binding(ticker.split('-', 1)[0])
                if cell and cell['sport'] == league and cell['period'] == 'full_game' and cell['family'] in (
                        'moneyline', 'spread', 'total'):
                    choices[identity(ticker)] = cell
            if not 1 <= len(choices) <= 6:
                return {}
            body, listing, reason = await self.get(client, '/events', dict(tickers=','.join(sorted(choices)),
                with_nested_markets='true', limit=len(choices)), cutoff)
            if reason or body['cursor']:
                return {}
            # Preserve fixed-point strikes as strings for the shared native witness hash.
            rows = json.loads(json.dumps(body['events'], default=str))
            listed = {r['event_ticker']: r for r in rows}
            if (len(listed) != len(body['events']) or set(listed)-choices.keys()
                    or any(row['series_ticker'] != choices[t]['series_ticker'] for t,row in listed.items())):
                return {}
            roles, ids, labels, role_witness = _role_proof(league, milestone, listed, choices)
            start = stamp(milestone['start_date'])
            occurrence = league, start, roles['home'], roles['away']
            identity_rows = dict(milestone=milestone.get('id'), kickoff=milestone['start_date'],
                native_team_ids=ids, roles=roles, source_sha256=witness['sha256'], observed_at=witness['received_at'])
            records = defaultdict(list)
            for records_for_game in events.values():
                for cid, _, record in records_for_game:
                    if record['quote']['venue'] == 'kalshi' and _compatible(record['event'], occurrence):
                        try:
                            expected = execution_contract.expected(record)
                            records[(expected['family'], expected['selected_side'],
                                None if expected['signed_line'] is None else F(expected['signed_line']))].append((cid,expected))
                        except ERRORS:
                            continue
            matches = defaultdict(list)
            for ticker, row in listed.items():
                cell = choices[ticker]
                for raw in row['markets']:
                    if raw['event_ticker'] != ticker or raw.get('status') != 'active':
                        continue
                    try:
                        outcomes = _outcomes(raw, cell, role_witness['event_id'], roles, ids, labels, role_witness)
                    except ERRORS:
                        continue
                    for side, line, native_side in outcomes:
                        for cid, expected in records[cell['family'], side, line]:
                            matches[cid].append((expected, raw, cell, native_side, listing, witness, identity_rows))
            return matches
        except ERRORS:
            return {}

    async def _bindings(self, client, products, entries, event, series, cutoff):
        results = await asyncio.gather(
            self.get(client, '/series/'+identity(series), {}, cutoff),
            self.get(client, '/series/fee_changes', dict(series_ticker=series, show_historical='true'), cutoff),
            self.get(client, '/events/fee_changes', dict(event_ticker=event, limit=100, cursor=''), cutoff))
        at = client.now()
        review = for_offer(products, dict(venue='kalshi'), at)
        output = {}
        for cid, (expected, raw, cell, side, listing, witness, occurrence) in entries:
            market = identity(raw['ticker'])
            contract = _contract(raw, cell, expected)
            base = dict(venue='kalshi', event_id=event, market_id=market, route=market,
                outcome_id=side, native_side=side, opposite_outcome_id='no' if side=='yes' else 'yes',
                levels=[], receipts=[], complete=False, contract=contract,
                scheduled_start=expected['starts_at'], contract_id=cid,
                identity_receipts=[witness, listing, occurrence], binding_method='public_milestone_and_exact_strike')
            try:
                grid, revision = _grid(raw, event, market, side, listing)
                if (not review or review.get('unavailable_reason') or not applies(review, at)
                        or any(reason for _,_,reason in results)):
                    raise ValueError('kalshi_fee_review_unavailable')
                (series_row, changes, history), evidence, _ = zip(*results, strict=True)
                if series_row['series']['contract_terms_url'] != next(
                        r['contract_terms_url'] for r in source_rules(detached=False)
                        if r['provider']=='kalshi' and r['native_type']==series):
                    raise ValueError('kalshi_governing_terms_changed')
                fee, expiry = _fee(series_row['series'], changes, history, review=review, event=event,
                    market=market, at=at, evidence=evidence)
                terms_clock = min(expiry, stamp(listing['received_at'])+IDENTITY_AGE,
                                  stamp(witness['received_at'])+IDENTITY_AGE)
                output[cid] = dict(base, reason=None, market_revision=revision, payout_usd='1',
                    quantity_increment=grid['increment'], quantity_minimum=grid['minimum'],
                    price_bands=grid['price_ranges'], fee=fee, terms_valid_until=terms_clock.isoformat(),
                    identity_receipts=[*base['identity_receipts'],*evidence])
            except ERRORS as error:
                reason = str(error) if isinstance(error, ValueError) and str(error).startswith('kalshi_') else 'kalshi_market_terms_unavailable'
                output[cid] = dict(base, reason=reason)
        return output
