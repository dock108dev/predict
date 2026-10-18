"""Implemented ordinary-ingress capabilities, distinct from observed coverage.

The registry is derived from configured sources, their retained native selectors
and the shared representation registries. A supported class is conditional on
each record's identity and source facts; it never qualifies an unseen offering.
"""
from app.collection.current_aggregate_policy import POLICY as AGGREGATE_POLICY
from app.collection.current_policy import (
    DEFAULT, SPORTS as CONFIGURED_SPORTS, aggregate_scope, native_scope, native_markets,
)

SPORTS = tuple(CONFIGURED_SPORTS)
CORE_FAMILIES = tuple(DEFAULT['families'])
NATIVE_SOURCES = ('kalshi', 'polymarket_us')
SOURCES = NATIVE_SOURCES + AGGREGATE_POLICY.bookmakers


def _representations():
    from app.collection.source_bindings import required_cells
    from app.collection.native_scope_bindings import catalog_cell_bindings
    from app.collection.public_contracts import load
    cells = {(r['sport'], r['family'], r['period']) for r in required_cells()}
    bindings = catalog_cell_bindings()
    for rows in bindings.values():
        cells.update((r['sport'], r['family'], r['period']) for r in rows)
    for row in load()['us_types'].values():
        cells.update((sport, row['family'], row['period']) for sport in row['competitions']
                     if sport in SPORTS)
    return cells, bindings


def inventory(config=None, encountered=()):
    """Return every known cell, including absent and unsupported retained types.

    ``configured`` means included in ordinary acquisition configuration, while
    ``acquisition_enabled`` additionally reflects the configured source switch.
    Runtime pauses/holds remain independent operational facts in coverage.
    Additional source types are retained as inventory, never silently enabled.
    """
    from app.adapters.polymarket_us import full_game_types
    from app.collection.native_selectors import LEAGUES
    from app.collection.public_contracts import load
    from .sporting_scope import supported
    config = DEFAULT if config is None else config
    representations, bindings = _representations()
    cells = {(sport, source, family, period) for sport, family, period in representations
             for source in SOURCES}
    encountered_keys = set()
    for row in encountered:
        sport = row.get('league', row.get('sport'))
        source = row.get('source', row.get('venue'))
        family, period = row.get('family'), row.get('period') or 'unknown'
        if sport in SPORTS and source in SOURCES and isinstance(family, str) and family:
            key = sport, source, family, period
            cells.add(key); encountered_keys.add(key)
    native_sports, native_families = native_scope(config), native_markets(config)
    aggregate_sports, aggregate_families = aggregate_scope(config), config['families']
    us_types=load()['us_types']
    result = []
    for sport, source, family, period in sorted(cells):
        native = source in NATIVE_SOURCES
        reference = source == 'pinnacle'
        core = family in CORE_FAMILIES and period == 'full_game'
        configured = core and sport in (native_sports if native else aggregate_sports) and family in (
            native_families if native else aggregate_families)
        selectors = []
        if source == 'kalshi':
            selectors = sorted({r['series_ticker'] for rows in bindings.values() for r in rows
                if (r['sport'], r['family'], r['period']) == (sport, family, period)})
        elif source == 'polymarket_us':
            selectors = list(full_game_types(LEAGUES[sport], (family,))) if core else sorted(
                kind for kind,row in us_types.items() if sport in row['competitions'] and
                (row['family'],row['period'])==(family,period))
        elif not native and core:
            selectors = [{'moneyline':'h2h', 'spread':'spreads', 'total':'totals'}[family]]
        # Ordinary discovery currently requests the full-game core. Other
        # retained catalog selectors are disclosed without claiming that the
        # running worker traverses them or that their predicates are normalized.
        discovery = core and bool(selectors)
        normalization = bool(selectors) and (core or native and supported(sport,family,period) and (
            source=='kalshi' or period=='first_half'))
        comparison = normalization and not reference
        reasons = []
        if not normalization:
            reasons.append('team_total_subject_binding_unimplemented' if family=='team_total' else
                'futures_award_and_field_binding_incomplete' if family=='futures' else
                'source_period_predicate_binding_unimplemented' if period!='full_game' else
                'source_family_predicate_binding_unimplemented')
        if not selectors:
            reasons.append('source_type_selector_unestablished')
        if reference:
            reasons.append('reference_only_source')
        if not configured:
            reasons.append('outside_configured_acquisition_scope')
        state = 'reference_only' if reference and normalization else 'implemented' if comparison else 'unsupported'
        result.append(dict(league=sport, source=source, source_role='reference' if reference else 'native' if native else 'aggregate_venue',
            acquisition_provider=source if native else 'the_odds_api', family=family, period=period,
            configured=configured, acquisition_enabled=configured and bool(config.get('enabled')) and (
                native or bool(config.get('aggregate_enabled'))),
            discovery_supported=discovery, normalization_supported=normalization,
            comparison_supported=comparison, capability_state=state, capability_reasons=reasons,
            native_selectors=selectors, encountered=(sport, source, family, period) in encountered_keys,
            representation_registered=(sport, family, period) in representations,
            qualification='Implemented class requires captured per-record identity, predicate, equality and scoring facts; observed support is measured separately.'))
    return result
