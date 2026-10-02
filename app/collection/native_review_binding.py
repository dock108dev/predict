"""Current receipt binding for explicitly configured ordinary native sessions.

This policy reuses a selected review's identity and semantic terms. It cannot
discover a contract, alter outcomes, extend fee evidence or qualify economics.
Older acquisition slices and historical interpretations do not select it.
"""
from copy import deepcopy
from datetime import timedelta
from app.dashboard.session_projection import stable, stamp
from app.dashboard.native_reviews import validate
from .native_payload import exact_transport
from .native_review_contract import contract, eligibility, valid_observations

POLICY = 'native-current-review-binding-1'
SOURCE_POLICY = 'native-current-source-binding-1'
CURRENT_POLICIES = (POLICY, SOURCE_POLICY)
VENUES = ('kalshi', 'polymarket_us')


def enabled(spec):
    return bool(exact_transport(spec.get('native_transport')) and spec.get('native_sources')
                and 'native_review_records' in spec and not any(spec.get(k) for k in
                    ('native_discovery', 'two_source_qualification', 'supervised_profile')))


def revalidated_sources(record):
    policy = record.get('current_session_revalidation', {}).get('policy')
    if policy == POLICY:
        return set(VENUES)
    if policy == SOURCE_POLICY:
        values = record.get('current_revalidated_sources')
        if isinstance(values, list) and values and values == sorted(set(values)) and set(values) <= set(VENUES):
            return set(values)
        raise ValueError('Exact nonempty current source subset required')
    return set()


def _template_applicability(template):
    return deepcopy(template.get('source_template_applicability') or {
        venue: source.get('fee_review', {}).get('applicability', template['applicability'])
        for venue, source in template['sources'].items()})


def assess(record, venue, catalog, at, receipts):
    """Keep delivery, normalized identity, terms and current eligibility separate."""
    source = record['sources'][venue]
    result = dict(event_id=source['event_id'], market_id=source['market_id'],
                  complete_metadata=False, identity=False, material_terms=False,
                  current_state=False, pregame=False, admitted=False)
    events = [e for e in catalog.get('events', []) if e['id'] == source['event_id']]
    markets = [m for m in catalog.get('markets', []) if m['id'] == source['market_id']]
    if len(events) != 1 or len(markets) != 1:
        result['reason'] = ('conflicting_duplicate_native_identity' if len(events) > 1 or len(markets) > 1
                            else 'complete_selected_metadata_unavailable')
        return result
    event, market = events[0], markets[0]
    en, mn = event.get('_native'), market.get('_native')
    proofs = event.get('provenance', []) + market.get('provenance', [])
    result['complete_metadata'] = bool(isinstance(en, dict) and isinstance(mn, dict) and proofs
        and all((venue, p.get('body_sha256')) in receipts
                and stamp(receipts[venue, p['body_sha256']]) <= at for p in proofs))
    if not result['complete_metadata']:
        result['reason'] = 'selected_metadata_lacks_complete_current_receipt'
        return result
    ident = record['identity']
    normalized = record.get('normalized_event', {})
    result['identity'] = bool(catalog.get('role', 'prediction') == 'prediction'
        and event.get('identity') == 'resolved' and event.get('canonical_key') == record['event']
        and not event.get('conflicting_duplicate') and not market.get('conflicting_duplicate')
        and market['event_id'] == event['id'] and event.get('competition') == ident['competition']
        and {'hockey': 'ice_hockey'}.get(event.get('sport'), event.get('sport')) == ident['sport']
        and not any(event.get(k) is not None and event.get(k) != ident.get(k)
                    for k in ('season', 'stage'))
        and market.get('market_type') == ident['family'] and market.get('period') == ident['period']
        and market.get('line') == source.get('descriptor', ident).get('line')
        and set(event.get('participants', {}).values() or event.get('field', [])) == set(record['participants'])
        and set(source['outcomes']) == ({s['id'] for s in market.get('sides', [])}
                                    or {s['native_id'] for s in market.get('product_outcomes', [])})
        and not any(s.get('native_direction') and s['native_direction'] != next(
            (x.get('role', '').lower() for x in market.get('sides', []) if x['id'] == n), None)
                    for n, s in source['outcomes'].items())
        and not any(k in normalized and event.get(k) != normalized[k] for k in
                    ('competition', 'season', 'stage', 'home', 'away', 'game_id',
                     'schedule_status', 'original_start', 'field', 'states', 'category', 'horizon')))
    semantic = source.get('semantic_review_contract')
    try:
        result['material_terms'] = (contract(venue, en, mn,policy=semantic['policy']) == semantic if semantic else
            stable(en) == source['event_metadata_sha256'] and stable(mn) == source['native_metadata_sha256'])
    except (ValueError, TypeError, KeyError):
        # A malformed current observation rejects this selected market, rather
        # than interrupting discovery for independent healthy sources.
        result['material_terms'] = False
    result['current_state'] = bool(not eligibility(venue, en, event=True)
        and not eligibility(venue, mn) and valid_observations(venue, en, event=True)
        and valid_observations(venue, mn) and market.get('status') == 'active')
    try:
        result['pregame'] = bool(event.get('scheduled_start')
                                and at + timedelta(minutes=5) < stamp(event['scheduled_start']))
    except (ValueError, TypeError):
        pass
    result['admitted'] = all(result[k] for k in
        ('complete_metadata', 'identity', 'material_terms', 'current_state', 'pregame')) and not (event.get('exclusion') or market.get('exclusion'))
    result['review_applicability'] = bool(record['applicability']['status'] == 'SUPPORTED'
        and stamp(record['applicability']['start']) <= at)
    result['admitted'] = result['admitted'] and result['review_applicability']
    result['reason'] = ('current_review_metadata_admitted' if result['admitted'] else
        'unsupported_selected_identity' if not result['identity'] else
        'changed_missing_unknown_or_conflicting_terms_require_review' if not result['material_terms'] else
        'unsupported_current_eligibility' if not result['current_state'] else
        'target_outside_prestart_applicability' if not result['pregame'] else
        'selected_template_applicability_not_supported_yet' if not result['review_applicability'] else
        str(event.get('exclusion') or market.get('exclusion')))
    return result


def successor(template, catalogs, sid, at, end, revision, sources=None):
    """A new raw-correspondence record anchored to this session's whole receipts."""
    selected = set(VENUES if sources is None else sources)
    if not selected or not selected <= set(VENUES):
        raise ValueError('Exact nonempty current source subset required')
    end = min(end, *(stamp(next(e for e in catalogs[venue]['events']
        if e['id'] == source['event_id'])['scheduled_start']) - timedelta(minutes=5)
        for venue, source in template['sources'].items() if venue in selected))
    record = deepcopy(template)
    record.pop('sha256')
    record['revision'] = revision
    record['historical_session_id'] = sid
    partial = selected != set(VENUES) or template.get('current_session_revalidation', {}).get('policy') == SOURCE_POLICY
    record['current_session_revalidation'] = dict(policy=SOURCE_POLICY if partial else POLICY, template_sha256=template['sha256'])
    if partial:
        record['current_revalidated_sources'] = sorted(selected)
        record['source_template_applicability'] = _template_applicability(template)
    record['applicability'] = dict(status='SUPPORTED', start=at.isoformat(), end=end.isoformat(),
        basis='Current complete receipts match explicitly selected identity and semantic terms; this session raw correspondence only')
    for venue, source in record['sources'].items():
        if venue not in selected:
            continue
        event = next(e for e in catalogs[venue]['events'] if e['id'] == source['event_id'])
        market = next(m for m in catalogs[venue]['markets'] if m['id'] == source['market_id'])
        source.pop('catalog_evidence', None)
        source.pop('base_native_metadata_sha256', None)
        source['reviewed_template_raw_hashes'] = dict(event=source['event_metadata_sha256'],
                                                     market=source['native_metadata_sha256'])
        source['metadata'] = deepcopy(market['_native'])
        source['native_metadata_sha256'] = stable(market['_native'])
        source['event_metadata_sha256'] = stable(event['_native'])
        source['semantic_review_contract'] = contract(venue, event['_native'], market['_native'],
            policy=source.get('semantic_review_contract',{}).get('policy','native-semantic-review-v1'))
        source['provenance'] = deepcopy(event['provenance'] + market['provenance'])
        if template.get('current_session_revalidation', {}).get('policy') in CURRENT_POLICIES and template.get('historical_session_id') == sid and venue in revalidated_sources(template):
            # An unchanged subscription still uses its earlier selected metadata
            # receipt. Only validated predecessors from this session may anchor
            # that metadata; historical preparation receipts never carry over.
            for proof in template['sources'][venue]['provenance']:
                if proof not in source['provenance']:
                    source['provenance'].append(deepcopy(proof))
        # Raw correspondence has a new interval. Historical economics does not.
        if source.get('fee_review'):
            source['fee_review'].setdefault('applicability', deepcopy(
                record.get('source_template_applicability', {}).get(venue, template['applicability'])))
    record['sha256'] = stable(record)
    return validate(record)


def verify_successor(record, template, sid):
    """Only an explicit unchanged semantic binding can supersede its template."""
    marker = record.get('current_session_revalidation', {})
    if marker.get('policy') not in CURRENT_POLICIES or marker != dict(policy=marker.get('policy'), template_sha256=template['sha256']):
        raise ValueError('Current review template binding differs')
    selected = revalidated_sources(record)
    if marker['policy'] == SOURCE_POLICY:
        expected_scope = _template_applicability(template)
        if record.get('source_template_applicability') != expected_scope:
            raise ValueError('Current review changed original source applicability')
    elif any(k in record for k in ('source_template_applicability', 'current_revalidated_sources')):
        raise ValueError('Paired current policy cannot select a source subset')
    if record.get('historical_session_id') != sid or record['review_id'] != template['review_id'] or record['revision'] <= template['revision']:
        raise ValueError('Current review session or revision differs')
    for key in ('identity', 'event', 'participants', 'normalized_event', 'evidence_mode', 'settlement_assessment'):
        if record.get(key) != template.get(key):
            raise ValueError('Current review changed selected identity or judgment')
    for venue, source in record['sources'].items():
        old = template['sources'][venue]
        if venue not in selected:
            if source != old:
                raise ValueError('Unrenewed source differs from exact selected template')
            continue
        if source.get('reviewed_template_raw_hashes') != dict(event=old['event_metadata_sha256'], market=old['native_metadata_sha256']):
            raise ValueError('Current review template metadata hashes differ')
        if stable(source['metadata']) != source['native_metadata_sha256']:
            raise ValueError('Current review market metadata hash differs')
        for key in ('event_id', 'market_id', 'outcomes', 'orientation_evidence', 'descriptor', 'semantic_review_contract'):
            if source.get(key) != old.get(key):
                raise ValueError('Current review changed selected source terms or outcomes')
        expected_fee = deepcopy(old.get('fee_review'))
        if expected_fee:
            expected_fee.setdefault('applicability', deepcopy(
                record.get('source_template_applicability', {}).get(venue, template['applicability'])))
        if source.get('fee_review') != expected_fee:
            raise ValueError('Current review extended economic evidence')


def apply(discovery, catalogs, at):
    spec = discovery.session.spec
    if not enabled(spec):
        return
    receipts = {(p['source'], p['body_sha256']): p['received_at'] for p in discovery.pages
                if p.get('complete') is True and p.get('status') == 200
                and p.get('usable_metadata', True)}
    started = getattr(getattr(discovery.session, 'projection', None), 'started', None)
    if started:
        receipts = {key: value for key, value in receipts.items() if stamp(value) >= stamp(started)}
    end = stamp(started) + timedelta(seconds=spec['duration']) if started else at + timedelta(seconds=spec['duration'])
    cache = getattr(discovery, 'current_review_bindings', {})
    discovery.current_review_bindings = cache
    for template in spec['native_review_records']:
        template = validate(template)
        if not all('semantic_review_contract' in s for s in template['sources'].values()):
            continue
        findings = {v: assess(template, v, catalogs.get(v, {}), at, receipts) for v in VENUES}
        if at > end:
            for finding in findings.values():
                finding.update(admitted=False, reason='outside_current_session_interval')
        for venue, finding in findings.items():
            catalog = catalogs.get(venue)
            if catalog is None:
                continue
            catalog.setdefault('native_review_admission', []).append(dict(
                policy=POLICY, review_sha256=template['sha256'], **finding))
            if not finding['admitted']:
                for market in catalog.get('markets', []):
                    if market['id'] == finding['market_id']:
                        market['subscription_evidence_exclusion'] = finding['reason']
        selected = {v for v, f in findings.items() if f['admitted']}
        if not selected:
            continue
        # Different source schedules cannot be admitted as the same paired game.
        schedules = {stamp(next(e for e in catalogs[v]['events'] if e['id'] == f['event_id'])['scheduled_start'])
                     for v, f in findings.items() if v in selected}
        if len(schedules) != 1:
            for venue, finding in findings.items():
                for market in catalogs[venue]['markets']:
                    if market['id'] == finding['market_id']:
                        market['subscription_evidence_exclusion'] = 'reviewed_native_schedules_differ'
            continue
        key = stable([template['sha256'], [(v, sorted({p['body_sha256'] for kind in ('events', 'markets')
            for row in catalogs[v][kind] if row['id'] == findings[v]['event_id' if kind == 'events' else 'market_id']
            for p in row['provenance']})) for v in sorted(selected)]])
        prior = [r for r in cache.values() if r['review_id'] == template['review_id']]
        parent = max(prior, key=lambda r: r['revision']) if prior else template
        if key in cache and cache[key]['sha256'] == parent['sha256']:
            continue
        record = successor(parent, catalogs, discovery.session.sid, at, end, parent['revision'] + 1, selected)
        discovery.session.emit('session', dict(type='native_review', review=record))
        cache[key] = record
