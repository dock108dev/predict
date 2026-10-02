"""Versioned raw correspondence within one ordinary native/aggregate session.

Canonical identities and reviewed score predicates are required. Aggregate odds
remain observations with unknown cashflows and no purchasable quantity. The
normal-win display scale does not establish equal settlement or hedged returns.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal

from app.dashboard.session_projection import stable
from app.reference.product import time

POLICY = 'source-correspondence-1'
LIMIT = 128
BYTE_LIMIT = 4 * 1024 * 1024
EXCLUSION_LIMIT = 128


def _listing_state(market, venue):
    from app.collection.native_review_contract import eligibility, valid_observations
    raw = market.get('native', {}).get('native_metadata')
    return bool(isinstance(raw, dict) and not eligibility(venue, raw)
                and valid_observations(venue, raw))


def _revalidated_source(review, venue):
    policy = review.get('current_session_revalidation', {}).get('policy')
    if policy in ('native-current-review-binding-1', 'native-current-source-binding-1'):
        from app.collection.native_review_binding import revalidated_sources
        return venue in revalidated_sources(review)
    return True


def _independent_native_rows(snapshot, at, existing):
    """Reuse per-source review admission and shared purchase formatting.

    The native paired comparison can be absent because the other native book is
    absent. Its per-source assessment already validates exact metadata, receipt,
    review and book references; it is the sole source of this extension's legs.
    """
    from app.dashboard.session_projection import format_book
    from app.opportunities.board import contracts
    from app.dashboard.native_book_comparison import entry
    reviews = snapshot.get('native_comparison_review', {}).get('records', {})
    used = {(r['native_review']['record']['sha256'], l['venue'], l['side'])
            for r in existing for l in r['legs']}
    result = []; games = {}
    for market in snapshot.get('market_catalog', []):
        venue = market['source_id']; book = market.get('native_book')
        if venue not in ('kalshi', 'polymarket_us') or not book or market.get('native_review_exclusion'):
            continue
        for assessment in market.get('native_review_assessments', []):
            review = reviews.get(assessment['review_sha256'])
            if not review or assessment.get('status') == 'METADATA_ONLY':
                continue
            if not _revalidated_source(review, venue):
                continue
            source = review['sources'][venue]
            raw = book['raw']; expected = dict(venue=venue, event_id=source['event_id'], market_id=source['market_id'])
            if raw['ref'] != expected or time(raw['received_at']) > time(at) or raw['kind'] != review['evidence_mode']:
                continue
            if not market.get('quotes') or book['state'] not in ('active', 'unknown') or book['sync'] != 'synchronized':
                continue
            if not _listing_state(market, venue):
                continue
            row = dict(source=venue, book=book, ingress_id=stable([expected, raw['json_text'], raw['received_at']]),
                observed_at=raw['received_at'], packets=[dict(normalized=dict(raw_kind=raw['kind'], quotes=market['quotes']))])
            if venue == 'polymarket_us' and any(o['asks'] is None for o in book['outcomes']) and any(
                    o.get('native_direction') == 'long' for o in source['outcomes'].values()) and not any(
                    o.get('comparison_outcome') for o in source['outcomes'].values()):
                from app.collection.native_semantics import purchase_saved_book
                row = purchase_saved_book(row, source['outcomes'])
            sides = {venue + ':' + n: dict(s, native_id=n) for n, s in source['outcomes'].items()}
            formatted = format_book(row, {venue:{n:(s['participant'],n) for n,s in source['outcomes'].items()}})
            health = market.get('health') or {}
            connection = health.get('state', 'unknown')
            age = str(Decimal(str((time(at) - time(raw['received_at'])).total_seconds())))
            ident = dict(review['identity'], event=review['event'],
                         scheduled_start=market['identity']['scheduled_start'], rules=review['sha256'])
            gid = 'native-correspondence-leg-' + stable([review['sha256'], expected])
            game = dict(id=gid, product_identity=ident, teams=sorted(review['participants'].values()), sides=sides)
            games[gid] = game
            point = dict(at=at, cards=[dict(venue=venue, label='Kalshi' if venue=='kalshi' else 'Polymarket US',
                         book=formatted, connection=connection, age_seconds=age, receipt_stale=Decimal(age)>15)])
            for leg in contracts(point, game).values():
                if (review['sha256'], venue, leg['side']) in used or leg['ask'] is None:
                    continue
                used.add((review['sha256'], venue, leg['side']))
                leg.update(native_identity=dict(event_id=source['event_id'], market_id=source['market_id']),
                    native_outcome=source['outcomes'][leg['side']], market_state=book['state'],
                    local_timing=None, source_age_seconds=None,
                    depth_limit='Selected native depth only; no aggregate execution inferred',
                    entry=entry(leg, Decimal(100), at, ident, dict(source,
                                native_review=review, native_review_version='native-book-comparison-4')))
                winner = source['outcomes'][leg['side']].get('normal_winner') or source['outcomes'][leg['side']].get('comparison_outcome') or leg['team']
                result.append(dict(game_id=gid, game_title=' vs '.join(review['participants'].values()),
                    outcome=winner, identity=ident, legs=[leg], native_review=dict(record=review)))
    return result, games


def _event_key(game, record):
    identity = game['product_identity']
    if identity['family'] == 'futures':
        raise ValueError('Championship season/award/complete-field correspondence unavailable')
    participants = record['participants']
    if len(participants) != 2 or any(':' not in k or k.startswith(('the_odds_api:', 'SYNTHETIC:')) for k in participants):
        raise ValueError('Native canonical participant pair unavailable')
    if identity['competition'] == 'MLB':
        from app.normalization.comparison_identity import baseball
        exact=baseball(record.get('normalized_event',{}))
        return (identity['competition'],time(identity['scheduled_start']).isoformat(),tuple(sorted(participants)),identity['period'],identity['family'],exact)
    return (identity['competition'], time(identity['scheduled_start']).isoformat(),
            tuple(sorted(participants)), identity['period'], identity['family'])


def _aggregate_event(record):
    identity = record['identity']; raw = record['original']
    if identity['family']=='futures':raise ValueError('Exact native award correspondence unavailable; provider-local award pair preserved')
    participants = identity['event'][-1]
    values = [participants.get('home_team'), participants.get('away_team')]
    if any(not v or v.startswith('the_odds_api:') for v in values) or len(set(values)) != 2:
        raise ValueError('Aggregate canonical home/away identities unavailable; provider-local comparison preserved')
    if record['reasons']:
        raise ValueError('; '.join(record['reasons']))
    result=(identity['competition'], time(raw['scheduled_start']).isoformat(), tuple(sorted(values)),identity['period'], identity['family'])
    if identity['competition']=='MLB':
        from app.normalization.comparison_identity import baseball
        # Provider-local price pairs remain valid independently. A native join
        # requires an explicitly reviewed source-to-canonical occurrence mapping.
        exact=raw.get('v1_event_identity',{})
        result+= (baseball(exact),)
        if exact['home']!=participants['home_team'] or exact['away']!=participants['away_team'] or time(exact['scheduled_start'])!=time(raw['scheduled_start']):
            raise ValueError('Aggregate MLB occurrence conflicts with provider participant/schedule')
    return result,participants


def _native_predicate(game, review, leg):
    identity = game['product_identity']; source = review['sources'][leg['venue']]
    outcome = source['outcomes'][leg['side']]
    if identity['family'] == 'moneyline' and identity['period'] == 'full_game':
        winner = outcome.get('normal_winner') or outcome.get('comparison_outcome')
        if winner is None and outcome.get('predicate') in ('win', 'not_win'):
            winner = (outcome['participant'] if outcome['predicate'] == 'win'
                      else next(name for name in review['participants'].values() if name != outcome['participant']))
        matches = [canonical for canonical, name in review['participants'].items() if name == winner]
        if len(matches) != 1:
            raise ValueError('Reviewed native winner orientation unavailable')
        return ('team_win', matches[0])
    from app.normalization.score_lines import orient_descriptor
    event = review['normalized_event']; descriptor = source['descriptor']
    if {event['home'], event['away']} != set(review['participants']):
        raise ValueError('Reviewed normalized home/away identity disagreement')
    canonical, sides = orient_descriptor(event, descriptor)
    side = next(s for s in sides if s['native_id'] == leg['side'])
    return (canonical['domain'], event['home'], event['away'],
            str(Decimal(canonical['threshold']).normalize()), side['operator'])


def _aggregate_predicate(record, participants, review):
    identity = record['identity']; raw = record['original']
    if identity['family'] == 'moneyline' and identity['period'] == 'full_game':
        return ('team_win', record['participant'])
    event = review.get('normalized_event')
    if not event or event.get('home') != participants['home_team'] or event.get('away') != participants['away_team']:
        raise ValueError('Exact reviewed native home/away roles missing or conflict with aggregate roles')
    if identity['family'] == 'total':
        return ('combined_score', event['home'], event['away'],
                str(Decimal(raw['point']).normalize()), 'gt' if raw['outcome'] == 'Over' else 'lt')
    if identity['family'] == 'spread':
        point = Decimal(raw['point']); home = record['participant'] == event['home']
        return ('home_margin', event['home'], event['away'],
                str((-point if home else point).normalize()), 'gt' if home else 'lt')
    if identity['family'] == 'moneyline':
        operator = 'eq' if record['predicate'] == 'draw' else 'gt' if record['participant'] == event['home'] else 'lt'
        return ('home_margin', event['home'], event['away'], '0', operator)
    raise ValueError('Unsupported source scoring predicate')


def _aggregate_leg(record):
    raw = record['original']; source = raw['bookmaker']; fields = raw['source_fields']
    return dict(id=record['id'], venue=source, label='Novig' if source == 'novig' else 'ProphetX',
        side=raw['outcome'], contract=record['id'], ask=record['implied'], decimal_odds=raw['decimal_odds'],
        price_basis='aggregate_raw_implied_probability', top_size=None,
        visible_size=None, levels=[], available=None, book_id=record['id'],
        received_at=raw['received_at'], source_at=raw['source_at'], age_seconds=None,
        source_age_seconds=None, connection='aggregate observation', market_state='unknown',
        native_identity=dict(event_id=raw['source_event_id'], market_id=fields['market'].get('sid') or raw['market'],
                             provider_id='the_odds_api', origin_id=source),
        native_outcome=dict(participant=record['participant'], predicate=record['predicate'], native_label=raw['outcome']),
        provenance=record, status='aggregate cashflows/state unverified', url=None,
        depth_limit='Aggregate odds have no executable quantity or depth',
        transformation='Raw 1 / decimal odds display scale; not an executable $1 contract price or fair probability',
        warnings=['Aggregate payout/fee units, settlement, source delay and active state remain unverified'],
        entry=dict(lower=None, upper=None, net=None, notional=None, quantity='100',
                   reason='Aggregate observations cannot be sized as native contracts',
                   basis='Odds observation only; published limits are not executable depth'))


def augment(snapshot, settings, effective_at=None):
    """Opt-in extension; older policies and historical hashes remain unchanged."""
    if settings.get('correspondence_policy') != POLICY:
        return
    snapshot['source_correspondence_comparisons'] = []
    from app.dashboard.price_comparison import comparisons as source_comparisons
    from app.reference.aggregate import bind
    native = [r for r in source_comparisons(snapshot, {}) if r.get('native_raw')]
    native = [r for primary in native for r in (primary, *primary.get('alternatives', []))]
    by_game = {g['id']: g for g in snapshot['games']}
    at = effective_at or snapshot['last_update']
    independent, independent_games = _independent_native_rows(snapshot, at, native)
    native.extend(independent); by_game.update(independent_games)
    aggregate = bind([m['aggregate']['original'] for m in snapshot['market_catalog']
                      if m.get('aggregate') and m['source_id'] in ('novig', 'prophetx')])
    exclusions = []; event_ids = defaultdict(set); native_groups = defaultdict(list)
    native_ids = defaultdict(lambda: defaultdict(set)); aggregate_ids = defaultdict(set)
    for record in aggregate:
        try:
            key, _ = _aggregate_event(record)
            aggregate_ids[key].add(record['original']['source_event_id'])
        except (ValueError, KeyError, TypeError, ArithmeticError):
            pass

    def exclude(reason, **identity):
        if len(exclusions) < EXCLUSION_LIMIT:
            item = dict(reason=str(reason)[:512], **identity)
            if item not in exclusions:
                exclusions.append(item)

    for row in native:
        game = by_game[row['game_id']]; review = row['native_review']['record']
        try:
            key = _event_key(game, review)
            event_ids[key].add(stable(review['event']))
        except (ValueError, KeyError, TypeError, StopIteration, ArithmeticError) as exc:
            exclude(exc, game_id=game['id']); continue
        for leg in row['legs']:
            try:
                source = review['sources'][leg['venue']]
                if not _revalidated_source(review, leg['venue']):
                    raise ValueError('Native source is not revalidated by the current source binding')
                native_ids[key][leg['venue']].add(source['event_id'])
                selected = [m for m in snapshot['market_catalog'] if m['source_id']==leg['venue'] and m['market_id']==source['market_id']]
                if len(selected)!=1 or selected[0].get('native_review_exclusion'):
                    raise ValueError('Source-specific selected native review admission unavailable')
                native_book = selected[0].get('native_book')
                if not native_book or native_book['state'] not in ('active','unknown') or native_book['sync']!='synchronized' or not _listing_state(selected[0], leg['venue']):
                    raise ValueError('Selected native book inactive or unsynchronized')
                if snapshot['view_mode']=='current' and leg.get('connection')!='connected':
                    raise ValueError('Current selected native connection is not eligible')
                predicate = _native_predicate(game, review, leg)
                native_groups[key].append((row, leg, predicate, review))
            except (ValueError, KeyError, TypeError, StopIteration, ArithmeticError) as exc:
                exclude(exc, game_id=game['id'], source=leg['venue'])
    created = set(); used_bytes = 0
    for record in aggregate:
        try:
            key, participants = _aggregate_event(record)
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            exclude(exc, aggregate_record=record['id']); continue
        if not native_groups.get(key):
            exclude('No exact reviewed native sport/participant/schedule/period/family counterpart in this session',
                    aggregate_event=record['original']['source_event_id']); continue
        if len(event_ids[key]) != 1:
            exclude('Ambiguous native canonical event association; no title or latest-record fallback',
                    aggregate_event=record['original']['source_event_id']); continue
        if len(aggregate_ids[key])!=1 or any(len(ids)!=1 for ids in native_ids[key].values()):
            exclude('Ambiguous source-specific native/aggregate event IDs; no participant/time-only fallback',
                    aggregate_event=record['original']['source_event_id']); continue
        for row, native_leg, predicate, review in native_groups[key]:
            try:
                aggregate_predicate = _aggregate_predicate(record, participants, review)
                if predicate != aggregate_predicate:
                    continue
                skew = abs(Decimal(str((time(native_leg['received_at']) - time(record['original']['received_at'])).total_seconds())))
                if skew > 5:
                    raise ValueError('Native/aggregate receipts exceed unchanged 5-second alignment ceiling')
                now = time(at)
                if time(record['original']['received_at']) > now or time(native_leg['received_at']) > now:
                    raise ValueError('Source observation after selected durable cutoff')
                if now >= time(record['original']['scheduled_start']):
                    raise ValueError('Pregame correspondence is invalid after scheduled start')
                logical = [row['game_id'], native_leg['venue'], record['original']['bookmaker'],
                           record['original']['source_event_id'], record['original']['market'],
                           record['original']['outcome'], record['original']['point']]
                gid = 'source-correspondence-' + stable(logical)
                if gid in created:
                    continue
                if len(created) >= LIMIT:
                    raise ValueError('Source correspondence comparison bound')
                left, right = deepcopy(native_leg), _aggregate_leg(record)
                left['price_basis'] = 'native_contract_price'
                native_source = review['sources'][left['venue']]
                left['native_identity'] = dict(event_id=native_source['event_id'], market_id=native_source['market_id'],
                    native_metadata_sha256=native_source['native_metadata_sha256'], native_review_sha256=review['sha256'])
                # The original native game owns the complete raw book; mixed
                # views freeze its receipt/hash and native ladder values once.
                left.pop('original_native_input', None)
                left['provenance'] = dict(response=review['sha256'], registry_sha256=review.get('registry_sha256'),
                                          native_review_sha256=review['sha256'])
                ages = []
                for leg in (left, right):
                    age = Decimal(str((now - time(leg['received_at'])).total_seconds()))
                    leg['age_seconds'] = str(age); ages.append(age)
                    try:
                        leg['source_age_seconds'] = str(Decimal(str((now - time(leg['source_at'])).total_seconds())))
                    except (ValueError, TypeError, AttributeError):
                        leg['source_age_seconds'] = None
                binding = dict(version=POLICY, session_id=snapshot['session_id'], cutoff=snapshot['durable_cursor'],
                    canonical_event=list(key[:3]), period=key[3], family=key[4], predicate=list(predicate),
                    native_review_sha256=review['sha256'], native_market_id=left['native_identity']['market_id'],
                    native_book_id=left['book_id'], native_received_at=left['received_at'],
                    native_wire_sha256=(left.get('local_timing') or {}).get('wire_sha256'),
                    aggregate_record_sha256=record['id'], aggregate_receipt_sha256=record['response'],
                    aggregate_provider_event_id=record['original']['source_event_id'],
                    aggregate_native_source_ids={k: record['original']['source_fields'][k].get('sid') for k in ('book', 'market', 'outcome')},
                    aggregate_received_at=right['received_at'],
                    home_away_scope='Exact reviewed roles for score predicates; team winner predicate is independent of home/away role',
                    qualification='Raw normal-event predicate correspondence only; no effective cashflow, execution or freshness qualification')
                binding['sha256'] = stable(binding)
                prices = [None if l['ask'] is None else Decimal(l['ask']) for l in (left, right)]
                gap = None if None in prices else abs(prices[0] - prices[1])
                result = dict(id=gid, game_id=gid, event_key=stable(binding['canonical_event']),
                    game_title=row['game_title'], outcome=row['outcome'], identity=deepcopy(row['identity']),
                    session=snapshot['session_id'] + '~' + gid, hash=snapshot['session_id'],
                    cutoff=snapshot['durable_cursor'], at=at, contract=left['id'], candidate='',
                    legs=[left, right], alternatives=[], raw_difference=None if gap is None else str(gap),
                    lower_raw=None if gap is None else 'Equal' if gap == 0 else [left, right][prices.index(min(prices))]['label'],
                    entry_lower=None, net=None, ev=None, mode=snapshot['data_mode'], historical=snapshot['view_mode'] != 'current',
                    aggregated=True, cross_source=True, source_correspondence=binding,
                    raw_comparison_units='Native $ per $1 normal-win claim versus aggregate raw implied odds; different cashflow/fee units',
                    timing=dict(receipt_skew_seconds=str(skew), receipt_limits_pass=all(0 <= age <= 15 for age in ages),
                                synchronized=False, reason='Same session and aligned receipt images; source clocks/delay and eligible-state continuity remain unqualified'),
                    settlement_audit=None, settlement_status='UNKNOWN',
                    settlement='Native outcome predicate and aggregate quoted outcome correspond. Aggregate effective settlement/payout/fee units remain unknown; native reviewed conflicts are not resolved.',
                    ranking_eligibility='Raw display scale only; no executable cash-gap, hedge, net/EV or source-qualified signal')
                import json
                encoded_bytes = len(json.dumps(result).encode()) + len(json.dumps(review).encode())
                if used_bytes + encoded_bytes > BYTE_LIMIT:
                    raise ValueError('Source correspondence expanded byte bound')
                used_bytes += encoded_bytes; created.add(gid)
                snapshot['source_correspondence_comparisons'].append(result)
                snapshot['games'].append(dict(id=gid, aggregated=True, cross_source=True, title=row['game_title'],
                    scheduled_start=result['identity']['scheduled_start'], teams=by_game[row['game_id']]['teams'],
                    sides={}, sources={l['venue']: l['native_identity'] for l in (left, right)},
                    candidates=[], product_identity=result['identity'], source_correspondence=binding))
                snapshot['points'][gid] = dict(id=snapshot['durable_cursor'], at=at, label='Same-session source correspondence', cards=[])
                snapshot['rows_by_game'][gid] = [dict(source_correspondence=binding, native_review=review,
                                                     native_leg=left, aggregate_record=record)]
            except (ValueError, KeyError, TypeError, StopIteration, ArithmeticError) as exc:
                exclude(exc, native_market=native_leg['native_identity'].get('market_id'), aggregate_record=record['id'])
    snapshot['cross_source_mapping'] = dict(version=POLICY,
        status='raw_correspondence' if created else 'unavailable', comparisons=len(created),
        exclusions=exclusions, exclusion_limit=EXCLUSION_LIMIT, comparison_limit=LIMIT,
        bytes=used_bytes, byte_limit=BYTE_LIMIT,
        reason='Exact canonical predicate and same-session receipts required; provider-local comparisons retained independently')


def comparisons(snapshot, query):
    result = []
    for original in snapshot.get('source_correspondence_comparisons', []):
        if any(query.get(k) and original['identity'].get(k) != query[k] for k in ('competition', 'season', 'period', 'family')):
            continue
        if query.get('search', '').lower() not in original['game_title'].lower():
            continue
        if query.get('venue') and not set(query['venue'].split('+')) <= {l['venue'] for l in original['legs']}:
            continue
        if query.get('positive') == 'true' or query.get('freshness') == 'usable':
            continue
        row = deepcopy(original)
        for leg in row['legs']:
            leg['entry']['quantity'] = query.get('quantity', '100')
            # Native depth stays visible as evidence; a mixed pair has no
            # supported aggregate units or complete purchase cashflows.
            leg['entry'].update(lower=None, upper=None, net=None,
                reason='Cross-source aggregate units, fees, settlement and executable quantity unavailable')
        result.append(row)
    return result
