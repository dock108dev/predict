"""Offline, evidence-addressed source bindings for the actual 63-cell scope.

The ledger is disclosure, never a contract review, current availability assertion,
order book or acquisition authorization. Generating it reads selected retained
evidence only. Serving it reads one bounded, content-addressed fixture.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'app/fixtures/source-bindings-current.json'
SCHEMA = 'source-bindings-1'
SOURCES = ('kalshi', 'polymarket_us', 'novig', 'prophetx')
SPORTS = ('NFL', 'NBA', 'MLB', 'NHL', 'NCAAF', 'NCAAB')
FAMILIES = ('moneyline', 'spread', 'total')
LIMIT = 2 * 1024 * 1024
ENGINEERING_STATES = {'implemented_and_evidenced', 'implemented_awaiting_real_source_evidence',
                      'blocked_by_external_fact', 'demonstrably_unsupported_by_selected_source'}
NATIVE_EVIDENCE = 'evidence/native-retained-coverage-20260930-v1/'
LATEST_EVIDENCE = 'evidence/native-nyi-tor-v3-live-assessment-20260930-v3/'


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=True).encode()).hexdigest()


def required_cells():
    """Owner requirement, independent of whether any source lists the cell."""
    from app.normalization.score_periods import PERIODS
    result = []
    for sport in SPORTS:
        periods = ['full_game'] + (['first_half'] if sport in ('NFL', 'NBA', 'NCAAF', 'NCAAB')
                                   else list(PERIODS[sport]))
        for period in periods:
            for family in FAMILIES:
                result.append(dict(cell_id=f'{sport}/{period}/{family}', sport=sport,
                                   period=period, family=family, category=None))
        for category in ('conference_champion', 'league_champion'):
            result.append(dict(cell_id=f'{sport}/season/{category}', sport=sport,
                               period='season', family='futures', category=category))
    return result


def _key(sport, period, family, category=None):
    return f'{sport}/{period}/{category or family}'


def _dimension(status, reason, **extra):
    return dict(status=status, reason=reason, **extra)


def _base_source(cell, source, documented, native_bindings):
    from app.reference.product import SPORT_KEYS
    from app.reference.odds_bindings import CHAMPIONSHIPS
    from app.collection.native_selectors import SERIES, LEAGUES
    native = source in SOURCES[:2]
    sport, period, family = cell['sport'], cell['period'], cell['family']
    if native:
        winner = period == 'full_game' and family == 'moneyline'
        catalog = native_bindings.get(cell['cell_id'], []) if source == 'kalshi' else []
        binding = dict(status='evidenced_typed_series_selector' if catalog else 'evidenced_game_selector' if winner else 'unresolved',
                       endpoint=('/trade-api/v2/events' if source == 'kalshi' else '/v1/events') if winner or catalog else None,
                       series_ticker=SERIES[sport] if source == 'kalshi' and winner else None,
                       tag_slug=LEAGUES[sport] if source == 'polymarket_us' and winner else None,
                       series_tickers=[r['series_ticker'] for r in catalog],
                       catalog_records=deepcopy(catalog),
                       market_keys=[], basis='Exact retained native catalog series selectors; source market predicates and current availability are independent')
        missing = ['Exact complete native listing, outcome/line/period predicates and effective review for this cell']
        if period == 'season':
            missing += ['Exact current season, conference/league award, complete entrant field and revision, no-award/shared-payout terms']
        elif period != 'full_game':
            missing += ['Explicit pregame segment boundaries, completion, tie/push and excluded later scoring; MLB pitcher/action exceptions where applicable']
        elif family in ('spread', 'total'):
            missing += ['Native strike/line, outcome direction and equality/push rules']
    else:
        documented_cell = documented.get(cell['cell_id'])
        keys = ([{'moneyline': 'h2h', 'spread': 'spreads', 'total': 'totals'}[family]]
                if period == 'full_game' else documented_cell['market_keys'])
        sport_key = (CHAMPIONSHIPS[sport] if cell['category'] == 'league_champion'
                     else SPORT_KEYS[sport] if cell['category'] != 'conference_champion' else None)
        mapped = period == 'full_game' or documented_cell['local_mapping'] == 'raw_only'
        binding = dict(status='documented_raw_mapping' if mapped else 'documented_catalog_only' if keys else 'unresolved',
                       endpoint=f'/v4/sports/{sport_key}/' + ('odds' if period in ('full_game', 'season') else 'events/{eventId}/odds') if sport_key else None,
                       sport_key=sport_key, market_keys=keys,
                       basis='Retained public catalog; selected-book cell availability independent')
        missing = (['Actual event/book/outcome records for this cell'] if mapped
                   else deepcopy(documented_cell['missing']))
    missing += ['Effective listing settlement and fee applicability',
                'Contemporaneous eligible native state, quantity/depth/minimum/increments, fill semantics and source clocks',
                'Complete qualified cashflows and independent probability inputs for net/EV']
    return dict(role='native_prediction' if native else 'aggregate_comparison_observation',
                provider_id=source if native else 'the_odds_api', binding=binding,
                dimensions={
                    'metadata': _dimension('NOT_OBSERVED', 'No complete selected receipt for this cell'),
                    'identity': _dimension('UNBOUND', 'No exact reviewed native identity' if native else 'No response-scoped outcome/line binding'),
                    'state': _dimension('UNKNOWN', 'Historical listings do not establish current eligible state'),
                    'books': _dimension('NOT_OBSERVED' if native else 'NON_EXECUTABLE', 'No admitted native book' if native else 'Aggregate odds never supply executable depth'),
                    'settlement': _dimension('UNKNOWN', 'No effective exact-listing settlement qualification'),
                    'fees': _dimension('UNKNOWN', 'No effective exact-listing fee/units/rounding/mandatory-charge qualification'),
                    'economics': _dimension('UNAVAILABLE', 'Missing qualified settlement, fees, execution, timing and probability'),
                }, counts={}, exact_bindings=[], missing=missing)


def build_ledger(root=ROOT):
    """Rebuild deterministically from retained originals; no network or secrets."""
    root = Path(root)
    manifest = {}

    def read(relative, expected=None):
        path = root / relative
        if not path.is_relative_to(root) or '..' in Path(relative).parts:
            raise ValueError('Unsafe source-binding evidence path')
        body = path.read_bytes()
        value = sha256(body).hexdigest()
        if expected and value != expected:
            raise ValueError('Source-binding original evidence hash changed')
        manifest[relative] = value
        return json.loads(body)

    documented = {_key(r['sport'], r['period'], r['family'], r['category']): r
                  for r in read('evidence/source-bindings-20260929/bindings-45-cells.json')}
    native_catalog = read('app/fixtures/native-scope-bindings-v1.json')
    read(native_catalog['source_path'], native_catalog['source_catalog_sha256'])
    from app.collection.native_scope_bindings import catalog_cell_bindings
    native_bindings = catalog_cell_bindings(native_catalog)
    cells = required_cells()
    for cell in cells:
        cell['sources'] = {source: _base_source(cell, source, documented, native_bindings) for source in SOURCES}
    by_id = {c['cell_id']: c for c in cells}
    accounting = read(NATIVE_EVIDENCE + 'corpus-accounting.json')
    associations = read(NATIVE_EVIDENCE + 'associations.json')
    index = read('app/reviews/native/index-v4.json')
    for live_index in ('app/reviews/native/index-live-engineering-v1.json','app/reviews/native/index-live-engineering-v2.json','app/reviews/native/index-live-engineering-v3.json'):
        if (root/live_index).exists():
            current=read(live_index)
            if current.get('schema')!='live-engineering-native-reviews-1':
                raise ValueError('Invalid current retained review index')
            index['records']={**index['records'],**current['records']}
    book_by_review = defaultdict(lambda: {s: set() for s in SOURCES[:2]})
    for association in associations:
        for review in association['reviews']:
            for source, present in review['books'].items():
                if present:
                    book_by_review[review['sha256']][source].add(association['session_id'])
    # The original sealed WKU record precedes the later association generator.
    # Read its exact indexed product journal; do not borrow books from another
    # source/session or assume all reviewed records are priced.
    from app.dashboard.session_history import verified
    for sid, names in index['historical_sessions'].items():
        if 'retained-wku-nmsu-v1.json' not in names:
            continue
        binding = index['historical_paths'][sid]
        folder = root / binding['folder']
        original = read('app/reviews/native/retained-wku-nmsu-v1.json')
        for row in verified(folder)['rows']:
            if row['type'] == 'prediction_book' and row['source'] in SOURCES[:2]:
                source = row['source']
                if (row.get('native_observation') or {}).get('market_id') == original['sources'][source]['market_id']:
                    book_by_review[original['sha256']][source].add(sid)
        for path in sorted(folder.glob('*.jsonl')):
            manifest[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    from app.dashboard.native_reviews import validate as validate_native
    native_groups = defaultdict(list)
    for name, expected in sorted(index['records'].items()):
        if Path(name).name != name:
            raise ValueError('Unsafe native review reference')
        record = validate_native(read('app/reviews/native/' + name))
        if record['sha256'] != expected or record['evidence_mode'] != 'observation':
            raise ValueError('Source-binding review is not the exact real indexed record')
        i = record['identity']
        cell_id = _key(i['competition'], i['period'], i['family'], i.get('category'))
        if cell_id not in by_id:
            raise ValueError('Native review outside required scope')
        for source in SOURCES[:2]:
            s = record['sources'][source]
            native_groups[(cell_id, source)].append(dict(
                event_id=s['event_id'], market_id=s['market_id'], outcome_ids=sorted(s['outcomes']),
                native_metadata_sha256=s['native_metadata_sha256'], event_metadata_sha256=s['event_metadata_sha256'],
                review_file='app/reviews/native/' + name, review_sha256=expected,
                applicability=record['applicability'],
                receipt_sha256=sorted({p['body_sha256'] for p in s['provenance']}),
                book_sessions=sorted(book_by_review[expected][source]),
                settlement_status=record['settlement_assessment']['status'],
                fee_status=s.get('fee_review', {'status': 'UNKNOWN'})['status']))
    for (cell_id, source), records in native_groups.items():
        entry = by_id[cell_id]['sources'][source]
        entry['exact_bindings'] = records
        priced = {r['market_id'] for r in records if r['book_sessions']}
        entry['counts'] = dict(reviews=len(records), events=len({r['event_id'] for r in records}),
                               markets=len({r['market_id'] for r in records}), markets_with_historical_books=len(priced))
        entry['binding']['status'] = 'reviewed_retained_native_identity'
        entry['binding']['market_keys'] = sorted({r['market_id'] for r in records})
        entry['dimensions']['metadata'] = _dimension('COMPLETE_RETAINED', 'Selected whole receipts are reviewed; delivery completeness has its own evidence')
        entry['dimensions']['identity'] = _dimension('REVIEWED_RETAINED', 'Exact native event/market/outcome predicates at the recorded applicability interval')
        entry['dimensions']['books'] = _dimension('HISTORICAL_BOOKS' if priced else 'METADATA_ONLY', 'Per-review book_sessions are the original captures only; no cross-session pairing')
        entry['dimensions']['settlement'] = _dimension('INCOMPATIBLE' if all(r['settlement_status'] == 'INCOMPATIBLE' for r in records) else 'PER_RECORD', 'Exact selected-record judgments remain independent', statuses=dict(Counter(r['settlement_status'] for r in records)))
        entry['dimensions']['fees'] = _dimension('PER_RECORD', 'No fee judgments are inherited by another instrument', statuses=dict(Counter(r['fee_status'] for r in records)))
        entry['missing'][0] = 'Fresh complete source metadata and applicable review; retained identities are dated'

    # Complete single-source listings remain visible before cross-source review.
    # This includes the real US MLB BOS/NYY listing whose Kalshi sample was a
    # different game; their distinct events must never be forced into a pair.
    catalog = read('evidence/native-gap-derived-20260930-v1/derived-catalog-v1.json')
    for source in SOURCES[:2]:
        events = {e['id']: e for e in catalog[source]['events']}
        for market in catalog[source]['markets']:
            event = events[market['event_id']]
            key = _key(event['competition'], market['period'], market['market_type'])
            if key not in by_id or market.get('exclusion') or market.get('conflicting_duplicate'):
                continue
            entry = by_id[key]['sources'][source]
            entry.setdefault('listing_evidence', []).append(dict(
                event_id=event['id'], market_id=market['id'], native_slug=market['native_slug'],
                native_metadata_sha256=digest(market['native_metadata']),
                outcome_ids=[s['id'] for s in market['sides']],
                canonical_participants=event['participants'], recorded_market_state=market['status'],
                source_receipts=market['provenance'], identity=event['identity'],
                qualification='Complete historical listing only; selected outcomes/terms require independent review'))
            if not entry['exact_bindings']:
                entry['dimensions']['metadata'] = _dimension('COMPLETE_RETAINED', 'Exact complete single-source listing retained; counterpart review unavailable')
                entry['dimensions']['identity'] = _dimension('SINGLE_SOURCE_LISTING', 'Explicit participant and side IDs retained; no native cross-source contract/outcome review')
                entry['missing'][0] = 'Same-event counterpart native market/outcome metadata, followed by exact review and contemporaneous books'
    for association in accounting['event_only_associations']:
        key = _key(association['competition'], 'full_game', 'moneyline')
        for source in SOURCES[:2]:
            by_id[key]['sources'][source].setdefault('event_only_associations', []).append(deepcopy(association))

    # Replay each selected original aggregate body, then use the existing binding.
    from app.reference.odds_sample import normalize
    from app.reference.odds_bindings import normalize_event
    from app.reference.aggregate import bind
    aggregate_rows = []
    for sample in read('evidence/odds-api-five-books-20260929/coverage.json'):
        path = sample['raw_path']
        receipt = read(str(Path(path).parent / 'result.json'))
        if not receipt.get('body_complete') or receipt.get('status') != 200:
            raise ValueError('Incomplete aggregate receipt excluded')
        read(path, sample['raw_sha256'])
        aggregate_rows += normalize((root / path).read_bytes(), sample['sport'], receipt['received_at'])
    raw_path = 'evidence/source-bindings-20260929/acquisition/odds/response.json'
    receipt = read('evidence/source-bindings-20260929/acquisition/odds/receipt.json')
    result = read('evidence/source-bindings-20260929/acquisition/odds/result.json')
    if not result.get('body_complete') or result.get('status') != 200:
        raise ValueError('Incomplete period aggregate receipt excluded')
    read(raw_path, receipt['raw_sha256'])
    aggregate_rows += normalize_event((root / raw_path).read_bytes(), 'NFL', receipt['received_at'])
    aggregate_groups = defaultdict(list)
    for row in bind(aggregate_rows):
        r, i = row['original'], row['identity']
        if r['bookmaker'] not in SOURCES[2:]:
            continue
        aggregate_groups[(_key(i['competition'], i['period'], i['family']), r['bookmaker'])].append(row)
    for (cell_id, source), rows in aggregate_groups.items():
        entry = by_id[cell_id]['sources'][source]
        for row in rows:
            r = row['original']; f = r['source_fields']
            entry['exact_bindings'].append(dict(
                provider_event_id=r['source_event_id'], market_key=r['market'], outcome=r['outcome'], point=r['point'],
                source_ids={kind: f[kind].get('sid') for kind in ('book', 'market', 'outcome')},
                received_at=r['received_at'], source_at=r['source_at'], receipt_sha256=r['receipt_sha256'],
                observation_sha256=row['id'], exclusions=row['reasons'], price_issue=row['price_issue']))
        valid = [r for r in rows if not r['reasons']]
        entry['counts'] = dict(observations=len(rows), bound_observations=len(valid),
                               events=len({r['original']['source_event_id'] for r in rows}),
                               invalid_prices=sum(r['price_issue'] is not None for r in rows))
        entry['binding']['status'] = 'retained_response_scoped_mapping'
        entry['dimensions']['metadata'] = _dimension('COMPLETE_RETAINED', 'Original whole aggregate response replayed exactly')
        entry['dimensions']['identity'] = _dimension('RESPONSE_SCOPED', 'Provider event/outcome/line binding; native source IDs are typed evidence only', bound_observations=len(valid))
        entry['dimensions']['state'] = _dimension('PREGAME_RECEIPT_ONLY' if by_id[cell_id]['period'] != 'full_game' else 'UNKNOWN', 'Receipt/schedule comparison is not native eligible-state continuity')
        entry['dimensions']['books'] = _dimension('NON_EXECUTABLE', 'Retained aggregate quotes are comparison observations; bet limits/source IDs do not become native depth')
        entry['missing'][0] = 'Broader actual selected-book records; retained sample does not prove full source availability'

    # Later complete Kalshi data and failed US delivery supersede the earlier
    # no-books statement only for that exact capture and source.
    delivery = read(LATEST_EVIDENCE + 'current-metadata-assessment.json')
    observations = read(LATEST_EVIDENCE + 'observations.json')
    for source in SOURCES[:2]:
        entry = by_id['NHL/full_game/moneyline']['sources'][source]
        assessment = delivery[source]
        observed = observations['sources'][source]
        entry['latest_capture'] = dict(session_id='5aa176bf-992c-4d48-a40c-7572099af32f',
            attempt_id='315b9167-a753-4e5b-ae18-19dd9724cfb7', consumed=True,
            evidence_path=LATEST_EVIDENCE + 'current-metadata-assessment.json',
            metadata=assessment, selected_event_id=observed['selection']['event_id'],
            selected_market_ids=observed['selection']['market_ids'],
            book_observations=observed['accepted'], price_level_changes=observed['price_level_changes'],
            quantity_changes=observed['quantity_changes'], paired_books=False,
            limitation='Exact historical capture; cannot fill another cutoff or establish current state')
        if source == 'kalshi':
            entry['dimensions']['books'] = _dimension('HISTORICAL_BOOKS', 'Latest exact Kalshi capture adds two snapshots and 52 changes; no simultaneous US books')
            entry['counts']['latest_capture_book_snapshots'] = observed['accepted']['initial_snapshot']
            entry['counts']['latest_capture_book_changes'] = observed['accepted']['price_or_quantity_change']

    unassigned = read(NATIVE_EVIDENCE + 'native-object-ledger.json')
    unresolved = [r for r in unassigned if r['kind'] == 'markets' and any(a.get('exclusion') for a in r['assessments'])]
    catalog_research = read('app/fixtures/source-binding-catalog-20260930.json')
    live_path='app/fixtures/source-live-facts-20260930-v1.json'
    live=read(live_path) if (root/live_path).exists() else None
    if live and (live.get('schema')!='source-live-facts-1' or digest({k:v for k,v in live.items() if k!='sha256'})!=live.get('sha256')):
        raise ValueError('Invalid captured source facts digest')
    for cell in cells:
        for source, entry in cell['sources'].items():
            status = ('implemented_and_evidenced' if entry['exact_bindings']
                      else 'implemented_awaiting_real_source_evidence'
                      if entry['binding']['status'] in ('documented_raw_mapping', 'evidenced_game_selector', 'evidenced_typed_series_selector')
                      else 'blocked_by_external_fact')
            entry['engineering_status'] = status
            entry['unlocks'] = 'Admit the exact source binding through existing discovery/normalization/review/comparison, retaining separate economics qualification'
            if cell['sport'] in ('NBA', 'NCAAB') and source in SOURCES[:2]:
                entry['missing'][:0] = (['Exact current NBA season/stage; MIATOR raw correspondence is reviewed independently'] if cell['sport']=='NBA' and entry['exact_bindings'] else ['Actual supported game listing within a fresh bounded window; empty pages are not provider absence'])
                if cell['sport'] == 'NCAAB':
                    entry['missing'][:0] = ['Exact men\'s Division I game/membership and native CBB participant bindings; native CBB league family alone is insufficient']
            if cell['sport'] == 'MLB' and source in SOURCES[:2] and cell['period'] == 'full_game':
                entry['missing'][:0] = ['Same-event native counterpart; US BOS/NYY and retained Kalshi PHI/ATL are different games']
            if source in SOURCES[2:] and (cell['period'] in ('first_6', 'regulation_9') or cell['category']):
                entry['catalog_review'] = deepcopy(catalog_research['findings'][
                    'mlb_six_nine' if cell['period'] in ('first_6', 'regulation_9')
                    else 'conference' if cell['category'] == 'conference_champion' else 'league'])
                # A missing published key is a precise external schema gap,
                # not proof that a venue can never offer the market.
                entry['engineering_status'] = 'blocked_by_external_fact'
            observed=live.get('cells',{}).get(cell['cell_id'],{}).get(source) if live else None
            if observed:
                entry['captured_live_facts']=deepcopy(observed)
                entry['dimensions']['metadata']=_dimension('COMPLETE_CAPTURED_RECORDS','Whole finite provider responses retained; selection, identity, state, books and economics remain independent',records=observed['complete_metadata_records'])
                predicates=observed.get('predicates',[])
                if predicates:
                    entry['dimensions']['source_predicate']=_dimension('EXPLICIT_PREDICATE_ONLY','Structured strike/primary rule or literal winner/award facts bound through ordinary normalization; effective descriptor and payouts incomplete',policy='native-score-predicate-1')
                    entry['missing'][:1]=list(dict.fromkeys(m for p in predicates for m in p['missing']))
                    entry['engineering_status']='blocked_by_external_fact'
                elif source in SOURCES[2:] and not entry['exact_bindings']:
                    entry['engineering_status']='implemented_and_evidenced'
                if cell['sport']=='MLB' and source in SOURCES[:2]:
                    entry['missing']=[m for m in entry['missing'] if not m.startswith('Same-event native counterpart; US BOS/NYY')]
                    entry['missing'][:0]=['Exact same-session eligible MLB counterpart, game number, original/rescheduled identity and pitcher/action conditions']
            for association in entry.get('event_only_associations',[]):
                matches=[r for r in entry['exact_bindings'] if r.get('event_id')==association['events'][source]]
                if matches:
                    association['current_status']='selected_market_outcomes_reviewed'
                    association['current_review_sha256s']=sorted({r['review_sha256'] for r in matches})
                    association['historical_missing']=association.pop('missing')
                    association['missing']=['Contemporaneous eligible state/books and independent effective economics']
            if live and source=='kalshi' and cell['cell_id']=='NFL/full_game/moneyline':
                contexts=[r for r in live.get('fee_contexts',[]) if r.get('status')=='scoped_current_terms_bound']
                entry['captured_fee_contexts']=deepcopy(contexts)
                if contexts:entry['dimensions']['fees']=_dimension('SCOPED_TERMS_BOUND_PRECISION_UNKNOWN','Current series and selected-event override history bound into existing as-of engine; account balance_precision, applicable rounding and mandatory charges unestablished')
    value = dict(schema=SCHEMA, evidence_mode='retained_observations', as_of='2026-09-30',
        required_cells=63, source_cell_count=252, collection_authorized=False,
        interpretation='Native review v4 with explicitly indexed live-engineering source reviews and predicates; response-scoped aggregate mappings; exact dated evidence only',
        cells=cells, summary={
            'groups': {'full_game': 18, 'first_half': 12, 'mlb_segments': 12, 'nhl_periods': 9, 'championships': 12},
            'by_source': {s: dict(cells_with_exact_records=sum(bool(c['sources'][s]['exact_bindings']) for c in cells),
                                  engineering_statuses=dict(Counter(c['sources'][s]['engineering_status'] for c in cells)),
                                  qualified_economics_cells=0) for s in SOURCES},
            'retained_native_corpus': accounting['summary'],
            'retained_kalshi_typed_series': {'keys':len(native_catalog['bindings']), 'cells':len(native_bindings),
                'unestablished_cells':sorted(c['cell_id'] for c in cells if c['cell_id'] not in native_bindings),
                'qualification':'Exact retained catalog selectors integrated under native-scope-bindings-v1; no contract predicate, current listing, state or economics inferred'},
            'unassigned_native_markets': len(unresolved),
            'unassigned_native_reason': 'Unsupported native types/periods, including futures, lack evidenced sport/season/award/field predicates; not assigned to required cells by title or type',
            'unassigned_native_ledger': NATIVE_EVIDENCE + 'native-object-ledger.json',
        }, evidence_manifest=dict(sorted(manifest.items())),
        limitations=['63 requirements are 252 source cells, not 252 qualified instruments',
                    'Complete metadata, exact identity, eligible state, admitted books and economics are independent',
                    'No current availability, provider absence, acquisition authority, beta signoff or fair probabilities are inferred'])
    value['sha256'] = digest(value)
    return validate_ledger(value)


def validate_ledger(value):
    value = deepcopy(value)
    expected = value.pop('sha256', None)
    if expected != digest(value) or value.get('schema') != SCHEMA:
        raise ValueError('Source-binding ledger hash/schema mismatch')
    expected_cells = {c['cell_id'] for c in required_cells()}
    cells = value.get('cells', [])
    if len(cells) != 63 or {c['cell_id'] for c in cells} != expected_cells or any(set(c['sources']) != set(SOURCES) for c in cells):
        raise ValueError('Source-binding ledger must contain all 63 cells and four sources')
    if value.get('collection_authorized') is not False or value.get('source_cell_count') != 252:
        raise ValueError('Source-binding ledger cannot confer collection authority')
    if any(entry.get('engineering_status') not in ENGINEERING_STATES for c in cells for entry in c['sources'].values()):
        raise ValueError('Source-binding engineering status missing')
    if len(json.dumps(value).encode()) > LIMIT:
        raise ValueError('Source-binding ledger exceeds byte bound')
    value['sha256'] = expected
    return value


def load_ledger(path=PATH):
    path = Path(path)
    if path.stat().st_size > LIMIT:
        raise ValueError('Source-binding ledger exceeds byte bound')
    return validate_ledger(json.loads(path.read_text()))


def ledger_for_snapshot(snapshot):
    """Add bounded cutoff-scoped disclosure; never mutate saved projections.

    Static evidence is deliberately not promoted to a new session. Metadata and
    quote counts below describe only the selected projection's own catalog.
    """
    ledger = load_ledger()
    cells = {c['cell_id']: {s: dict(metadata_rows=0, quote_rows=0, aggregate_rows=0,
                                    market_ids=[], exclusion_reasons=[])
                            for s in SOURCES} for c in ledger['cells']}
    count = 0
    for row in snapshot.get('market_catalog', []):
        if row.get('scope_only'):
            continue
        i = row.get('identity') or {}; source = row.get('source_id')
        key = _key(i.get('competition'), i.get('period'), i.get('family'), i.get('category'))
        if key not in cells or source not in SOURCES:
            continue
        count += 1
        if count > 4096:
            raise ValueError('Selected source-binding catalog row bound')
        target = cells[key][source]
        target['metadata_rows'] += 1
        target['aggregate_rows'] += bool(row.get('aggregate'))
        target['quote_rows'] += bool(row.get('quotes'))
        mid = str(row.get('market_id') or '')
        if mid and mid not in target['market_ids'] and len(target['market_ids']) < 64:
            target['market_ids'].append(mid)
        reason = row.get('reason')
        if reason and reason not in target['exclusion_reasons'] and len(target['exclusion_reasons']) < 8:
            target['exclusion_reasons'].append(str(reason)[:512])
    selected = dict(session_id=snapshot.get('session_id'), cutoff=snapshot.get('durable_cursor'),
        data_mode=snapshot.get('data_mode'), status=snapshot.get('state'),
        started_at=snapshot.get('started_at'), stopped_at=snapshot.get('stopped_at'),
        cells=[dict(cell_id=k, sources=v) for k, v in cells.items()],
        source_health=[dict(source_id=s.get('source_id'), state=s.get('state'))
                       for s in snapshot.get('sources', []) if s.get('source_id') in SOURCES],
        limitation='Selected projection only. A quote or connected source does not establish eligible state, executable depth, current economics or acquisition authority')
    ledger.pop('sha256')
    ledger['selected_session'] = selected
    ledger['sha256'] = digest(ledger)
    return ledger


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PATH)
    args = parser.parse_args()
    args.output.write_text(json.dumps(build_ledger(), sort_keys=True, separators=(',', ':')) + '\n')
