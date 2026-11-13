"""An independent read-only census of source evidence and ordinary desk output."""
from collections import Counter, defaultdict
from datetime import timedelta
from itertools import product

from app.collection.current_policy import aggregate_scope, native_markets, native_scope
from app.comparison.game_phase import LIVE_SECONDS, PREGAME_SPORTSBOOK_SECONDS
from app.comparison.sgo_reference import BEST_BOOKS

from .fee_coverage import WORKING_PHASE_SQL, source_key

NATIVE_VENUES = ('kalshi', 'polymarket_us')
SGO_OFFER_VENUES = ('kalshi', 'novig')
SGO_REFERENCE_VENUES = (*BEST_BOOKS, 'pinnacle')
PHASES = ('pregame', 'in_game')


def native_observations(cells, *, origin):
    # Coverage captures query inventories and book-image units before ordinary
    # publication. Family queries have no phase partition of book-image units.
    observations = []
    for cell in cells:
        if cell['venue'] not in NATIVE_VENUES:
            continue
        for family in cell.get('family_queries', ()):
            latest = family.get('latest') or {}
            inventory = latest.get('inventory') or {}
            if not inventory:
                continue
            fields = ('unique_listing_games', 'unique_listing_markets', 'known_unselected_markets',
                      'received', 'admitted', 'rejected', 'pending', 'listing_only_markets',
                      'observed_market_images', 'last_receipt_at', 'last_source_at', 'pages',
                      'continuation', 'exhausted', 'failures', 'started_at', 'completed_at',
                      'denominator_status', 'count_scope', 'native_unit_definition', 'omission_reasons')
            observations.append(dict(provider=cell['venue'], venue=cell['venue'], league=cell['sport'],
                family=_family(family['family']), period='full_game', phase=None,
                evidence_origin=origin,
                checked_at=latest.get('checked_at'), query_status=latest.get('status'),
                query_reason=latest.get('reason'), offered_price_units=inventory.get('offered_price_units'),
                provider_universe_complete=inventory.get('provider_universe_complete', False),
                **{field: inventory.get(field) for field in fields}))
    return observations


def native_query_inventory(db, owner):
    cells = (owner.get('status') or {}).get('coverage', {}).get('cells', ())
    current = native_observations(cells, origin='current_runtime_query')
    prior = db.execute("SELECT facts->'query_observations' AS cells FROM coverage_latest WHERE singleton").fetchone()
    saved = native_observations(prior['cells'] or (), origin='retained_coverage_query') if prior else []
    queries = {_cohort(row): row for row in saved}
    queries.update({_cohort(row): row for row in current})
    return sorted(queries.values(), key=_cohort)


def _family(family):
    return 'winner' if family == 'moneyline' else family


def _cohort(row):
    return tuple(row[field] for field in ('provider', 'venue', 'league', 'family', 'period', 'phase'))


def _labels(key):
    return dict(zip(('provider', 'venue', 'league', 'family', 'period', 'phase'), key))


def working_inventory(db, deps, result, *, at):
    published = {source_key(row) for row in result['rows']}
    current = {source_key(row) for row in result['rows'] if row['price_current']}
    return db.execute('''WITH units AS (
        SELECT e.provider,c.venue,e.competition AS league,c.id,
            CASE c.facts#>>'{market_identity,family}' WHEN 'moneyline' THEN 'winner'
                 ELSE c.facts#>>'{market_identity,family}' END AS family,
            c.facts#>>'{market_identity,period}' AS period,
            ''' + WORKING_PHASE_SQL + ''' AS phase,
            o.facts->>'state' AS state
        FROM current_offer o JOIN current_contract c ON o.contract_id=c.id
        JOIN current_event e ON e.id=c.event_id WHERE c.id=ANY(%(working)s))
        SELECT provider,venue,league,family,period,phase,count(*) AS retained_working_prices,
            count(*) FILTER(WHERE state='available') AS retained_available_prices,
            count(*) FILTER(WHERE state IS DISTINCT FROM 'available') AS retained_unavailable_prices,
            count(*) FILTER(WHERE id=ANY(%(published)s)) AS published_working_prices,
            count(*) FILTER(WHERE NOT id=ANY(%(published)s)) AS awaiting_or_excluded_from_publication,
            count(*) FILTER(WHERE id=ANY(%(current)s)) AS current_working_prices
        FROM units GROUP BY provider,venue,league,family,period,phase''',
        {'at': at, 'working': list(deps), 'published': list(published), 'current': list(current)}).fetchall()


def sgo_observations(db, *, at):
    # Newer observations rejected by source ordering can remain in the frame
    # without a corresponding retained revision. Count those members separately.
    # A missing member is neither a withdrawal nor an entitlement conclusion.
    if not db.execute("SELECT to_regclass('public.current_sgo_delivery_clock') AS name").fetchone()['name']:
        return []
    return db.execute('''WITH frames AS (
        SELECT event_id, received_order, facts->'members' AS members,
            facts#>>'{event_context,league}' AS league,
            facts#>>'{event_context,phase}' AS phase,
            (facts->>'starts_at')::timestamptz AS starts_at
        FROM current_sgo_event_frame WHERE expires_at > %(at)s
          AND (facts->>'starts_at')::timestamptz >= %(start)s
          AND (facts->>'starts_at')::timestamptz < %(end)s),
      members AS (
        SELECT f.event_id,f.received_order,f.league,f.phase,f.starts_at,m.value->>0 AS id,m.value->>1 AS revision
        FROM frames f CROSS JOIN LATERAL jsonb_array_elements(f.members) AS m),
      units AS (
        SELECT m.league,m.phase,r.bookmaker_id AS venue,
            CASE r.facts->>'market' WHEN 'moneyline' THEN 'winner' ELSE r.facts->>'market' END AS family,
            CASE r.facts->>'period' WHEN 'game' THEN 'full_game' ELSE r.facts->>'period' END AS period,
            r.id IS NOT NULL AS matched_revision,
            r.facts->>'available'='true' AS available,r.facts->>'unavailable_reason' AS unavailable_reason,
            r.source_order AS source_order, r.received_order AS original_receipt,
            extract(epoch FROM m.starts_at) AS start_order, m.received_order AS latest_receipt,
            extract(epoch FROM d.admitted_at) AS admitted_order,
            extract(epoch FROM d.first_publication_write_at) AS page_published_order
        FROM members m LEFT JOIN current_sgo_reference r ON r.id=m.id AND r.event_id=m.event_id
          AND r.revision=m.revision AND r.expires_at > %(at)s
        LEFT JOIN current_sgo_delivery_clock d ON d.league=m.league AND d.received_at=to_timestamp(m.received_order)),
      phased AS (
        SELECT *, CASE phase WHEN 'live' THEN %(live)s WHEN 'pregame' THEN %(pregame)s END AS max_age,
            (phase='live' AND source_order>=start_order AND original_receipt>=start_order)
              OR (phase='pregame' AND source_order<start_order AND original_receipt<start_order) AS phase_verified,
            extract(epoch FROM %(at)s::timestamptz) AS sampled_order FROM units)
      SELECT 'sportsgameodds' AS provider,venue,league,family,period,
        CASE phase WHEN 'live' THEN 'in_game' ELSE phase END AS phase,
        count(*) AS received_frame_members,
        count(*) FILTER(WHERE matched_revision) AS retained_matching_revisions,
        count(*) FILTER(WHERE NOT matched_revision) AS without_matching_retained_revision,
        count(*) FILTER(WHERE available) AS available_retained_originals,
        count(*) FILTER(WHERE matched_revision AND NOT available) AS unavailable_retained_originals,
        count(*) FILTER(WHERE available AND source_order IS NULL) AS missing_source_clock,
        count(*) FILTER(WHERE available AND source_order>original_receipt) AS source_clock_after_receipt,
        count(*) FILTER(WHERE available AND phase_verified IS NOT TRUE AND source_order IS NOT NULL) AS clock_phase_unverified,
        count(*) FILTER(WHERE available AND phase_verified AND original_receipt-source_order BETWEEN 0 AND max_age) AS fresh_at_original_receipt,
        count(*) FILTER(WHERE available AND phase_verified AND source_order<=original_receipt
          AND latest_receipt-source_order BETWEEN 0 AND max_age) AS fresh_at_latest_frame_receipt,
        count(*) FILTER(WHERE available AND phase_verified AND source_order<=original_receipt
          AND admitted_order>=latest_receipt AND admitted_order-source_order BETWEEN 0 AND max_age) AS fresh_at_frame_admission,
        count(*) FILTER(WHERE available AND phase_verified AND source_order<=original_receipt
          AND page_published_order>=admitted_order AND page_published_order-source_order BETWEEN 0 AND max_age) AS fresh_at_first_page_publication,
        count(*) FILTER(WHERE available AND phase_verified AND source_order<=original_receipt
          AND sampled_order-source_order BETWEEN 0 AND max_age
          AND (phase<>'pregame' OR sampled_order<start_order)) AS fresh_at_read,
        count(*) FILTER(WHERE admitted_order IS NOT NULL) AS with_frame_admission_clock,
        count(*) FILTER(WHERE page_published_order IS NOT NULL) AS with_page_publication_clock,
        to_char(to_timestamp(max(latest_receipt)) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS last_frame_receipt_at
      FROM phased GROUP BY venue,league,family,period,phase''',
      {'at': at, 'start': at-timedelta(hours=24), 'end': at+timedelta(hours=72),
       'live': LIVE_SECONDS, 'pregame': PREGAME_SPORTSBOOK_SECONDS}).fetchall()


def configured_cohorts(config):
    if not config.get('sports') or not config.get('families'):
        return set()
    native = {(venue, venue, league, _family(family), 'full_game', phase)
              for venue, league, family, phase in product(NATIVE_VENUES, native_scope(config), native_markets(config), PHASES)}
    if not config.get('aggregate_enabled') or config.get('aggregate_provider') != 'sportsgameodds':
        return native
    return native | {('sportsgameodds', venue, league, _family(family), 'full_game', phase)
                     for venue, league, family, phase in product((*SGO_OFFER_VENUES, *SGO_REFERENCE_VENUES),
                         aggregate_scope(config), config['families'], PHASES)}


def measure(db, result, deps, counts, owner, *, at, phase=''):
    selected_phase = {'pregame': 'pregame', 'live': 'in_game'}.get(phase)

    def in_scope(key):
        return selected_phase is None or key[-2:] == ('full_game', selected_phase)

    by_publication = {_cohort(row): row for row in counts['by_provider']}
    price_gaps = defaultdict(Counter)
    identity = defaultdict(Counter)
    for row in result['rows']:
        row_phase = {'scheduled': 'pregame', 'live': 'in_game'}.get(row.get('game_state'), row.get('game_state', 'unknown'))
        key = (row.get('source', {}).get('provider') or 'unknown', row['venue'], row['league'],
               row['market']['market'], row['market']['period'], row_phase)
        if row['price_current']:
            supported = bool((row.get('same_outcome') or {}).get('supported'))
            identity[key]['current_supported_outcome' if supported else 'current_unresolved_outcome'] += 1
        else:
            price_gaps[key].update(row.get('price_reasons') or ['source_price_not_current'])
    working = {_cohort(row): row for row in working_inventory(db, deps, result, at=at)}
    for row in working.values():
        row['published_current_working_prices'] = row['current_working_prices']
    originals = {_cohort(row): row for row in sgo_observations(db, at=at)}
    configured = configured_cohorts(owner.get('config') or {})
    keys = set(working) | set(by_publication) | configured
    outside = defaultdict(Counter)
    for key, facts in originals.items():
        if not in_scope(key):
            continue
        if key in keys or key[1] in (*SGO_OFFER_VENUES, *SGO_REFERENCE_VENUES, None):
            keys.add(key)
            continue
        outside[key[1]].update({field: facts[field] for field in (
            'received_frame_members', 'available_retained_originals', 'unavailable_retained_originals')})
    cohorts = []
    for key in sorted(keys, key=str):
        if not in_scope(key):
            continue
        provider, venue, _, _, _, _ = key
        role = ('unattributed_frame_member' if venue is None else
                'reference_only' if provider == 'sportsgameodds' and venue in SGO_REFERENCE_VENUES else
                'reference_or_audit_only' if provider == 'sportsgameodds' and venue not in SGO_OFFER_VENUES else 'offer')
        boundary = (owner.get('states') or {}).get(provider, {})
        cohorts.append(dict(_labels(key), role=role, configured=key in configured, offered_price_units=None,
            provider_universe_complete=False, source_originals=originals.get(key),
            sql_working=working.get(key), ordinary_publication=by_publication.get(key),
            publication_price_gaps=dict(price_gaps[key]), outcome_identity=dict(identity[key]),
            source_state=boundary.get('state'), source_reason=boundary.get('reason_code')))

    return dict(read_at=at.isoformat(), publication_captured_at=result.get('captured_at'),
        provider_price_universe_complete=False, offered_price_units=None,
        native_query_observations=native_query_inventory(db, owner), cohorts=cohorts,
        other_sgo_bookmakers=[dict(venue=venue, **facts) for venue, facts in sorted(outside.items())],
        boundaries=dict(native_queries='Listing and observed book-side units are different populations; phase is unmeasured here.',
            sgo='Latest committed event-frame members and retained originals in the desk horizon; missing pages or revisions do not establish withdrawals.',
            phase='Original phase for SGO facts, admitted schedule and explicit status for SQL, and validated price lifecycle for ordinary publication.',
            counts='Stages use their own units and evidence clocks. Only working-to-published keys are directly reconciled.',
            published_current_working_prices='Working keys with an already-current desk row. Use the independent finance audit for all current working keys.',
            price_reasons='More than one reason can apply to one retained presentation.',
            page_clock='A page publication can serve different facts from that page.'),
        ev=dict(independently_eligible_offer_reference_inputs=None, completeness='unmeasured',
            published_indicative_sportsbook=counts['total']['sportsbook_ev'], published_before_fee=counts['total']['before_fee_ev'],
            published_reviewed_after_fee=counts['total']['reviewed_after_fee_ev'],
            published_conservative_after_fee=counts['total']['conservative_after_fee_ev']),
        arb=dict(independently_eligible_opposing_inputs=None, completeness='unmeasured',
            published=counts['pair_coverage']['current_before_fee_pairs'],
            published_with_both_fees=counts['pair_coverage']['both_legs_have_normalized_fee']))
