"""Bounded retained coverage. Collection, source clocks and finance are separate.

Every count uses the same detached current-price cohort. Exact-query diagnostics
describe their own earlier window and never supply a provider-universe denominator.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
from itertools import islice
import json

from .capabilities import SPORTS, SOURCES as VENUES
from app.dashboard.current_contract import stamp

VERSION = 'predict-broad-coverage-1'
MAX_RECORDS = 32768
MAX_EXAMPLES = 3
MAX_CELLS = 4096
COUNT_KEYS = ('retained_observations', 'displayed_observations', 'current_observations',
    'retained_comparison_observations', 'retained_reference_observations',
    'displayed_comparison_directions', 'displayed_current_comparison_directions',
    'last_known_observations', 'unknown_age_observations', 'pending_observations',
    'matched_occurrences', 'supported_comparison_observations', 'current_comparison_observations',
    'comparable_outcomes', 'underlying_pairs', 'signed_comparison_directions', 'gap_observations',
    'identity_matched_observations','meaning_supported_observations','input_supported_observations',
    'input_current_peer_observations','eligible_current_pairs','supported_noncurrent_pairs',
    'eligible_current_directions','publication_pending_directions','display_disagreement_directions','published_current_pairs',
    'retained_peer_candidate_observations','no_retained_peer_observations')
REASONS = {
    'not_configured': ('Not configured', 'configuration', 'This sport and market are outside the configured collection scope.'),
    'source_disabled': ('Source disabled', 'configuration', 'Collection is disabled by the current configuration.'),
    'source_paused': ('Source paused', 'operational', 'The source is paused; retained prices keep their original clocks.'),
    'source_held': ('Aggregate acquisition held', 'operational', 'The upstream aggregate provider is held; supplied venues are not separate acquisition requests.'),
    'not_checked': ('Not checked', 'measurement', 'No retained query measurement exists for this exact cell.'),
    'partial_listing': ('Partial listing', 'operational', 'The bounded query or selected metadata does not cover the provider market universe.'),
    'query_capacity': ('Discovery capacity reached', 'operational', 'Shared discovery capacity deferred records; offered totals remain unknown where unmeasured.'),
    'query_empty': ('No offerings in this query', 'source', 'The exact captured query returned no offerings; this is not a provider-wide absence claim.'),
    'source_failed': ('Query failed', 'source', 'Transport failed; offered totals are unknown.'),
    'payload_rejected': ('Payload unavailable', 'source', 'The captured payload could not be admitted; offered totals are unknown.'),
    'market_type_unsupported': ('Market type unsupported', 'implementation', 'This encountered market family has no implemented comparison contract.'),
    'period_unsupported': ('Period unsupported', 'implementation', 'This encountered period has no implemented comparison contract.'),
    'participant_identity_unresolved': ('Participant identity unresolved', 'identity', 'One or more source participants have no unique canonical identity.'),
    'occurrence_identity_unresolved': ('Game identity unresolved', 'identity', 'The captured source game cannot yet be bound to a supported sporting occurrence.'),
    'schedule_conflict': ('Conflicting schedule', 'identity', 'Captured schedule witnesses conflict; the affected group is withheld.'),
    'comparison_context_missing': ('Comparison context missing', 'identity', 'Required captured season, stage or occurrence facts are missing.'),
    'predicate_missing_or_conflicting': ('Predicate or line unresolved', 'meaning', 'The exact predicate, signed line, subject or inequality is missing or conflicting.'),
    'equality_missing_or_conflicting': ('Equality treatment unresolved', 'meaning', 'The captured equality, push or refund treatment is missing or conflicting.'),
    'scoring_scope_missing_or_conflicting': ('Scoring scope unresolved', 'meaning', 'Required overtime, extra innings or shootout scoring facts are missing or conflicting.'),
    'cross_source_peer_missing': ('No supported cross-source peer', 'matching', 'No retained other-source observation has the same supported outcome identity.'),
    'retained_peer_absent': ('No retained other-source input', 'matching', 'This resolved occurrence and market family/period has no retained observation from another comparison venue.'),
    'retained_peer_meaning_unresolved': ('Other-source inputs need compatible meaning', 'meaning', 'Other-source observations exist for this resolved occurrence and market family/period, but none supplies a supported same-outcome peer.'),
    'native_price_or_binding_unsupported': ('Price or selection cannot be compared', 'meaning', 'The original native price, normal payout or captured selection binding does not support the ordinary gross-price comparison.'),
    'stale_inputs': ('Last-known prices', 'freshness', 'Original source clocks or source health prevent a current comparison.'),
    'unknown_source_clock': ('Unknown price age', 'freshness', 'A valid original source clock is absent or contradictory.'),
    'waiting_for_publication': ('Waiting for publication', 'publication', 'The retained input has no matching valid background publication yet.'),
    'current_inputs_publication_pending': ('Current compatible inputs await publication', 'publication', 'Current compatible retained inputs exist; their current comparison is pending or refused.'),
    'published_display_disagrees': ('Comparison reporting disagrees', 'display', 'A published current comparison disagrees with current retained compatible inputs.'),
    'hidden_by_filter': ('Hidden by display filter', 'display', 'The retained observation is outside the current local display filter.'),
    'reference_only': ('Reference data', 'reference', 'Pinnacle remains reference data and is excluded from comparison-peer counts.'),
}
PRIMARY_ORDER = tuple(REASONS)


def family(value):
    return {'winner': 'moneyline', 'team_binary': 'moneyline', 'h2h': 'moneyline',
            'spreads': 'spread', 'totals': 'total'}.get(value, value or 'unknown')


def native_key(quote):
    source = quote.get('source', {})
    return tuple([quote.get('venue')] + [source.get(k) for k in
        ('provider', 'native_event_id', 'native_market_id', 'native_outcome_id', 'native_side')])


def cell_id(sport, venue, market, period):
    return '|'.join((sport, venue, market, period))


def _ratio(numerator, denominator, label, scope):
    return dict(numerator=numerator, denominator=denominator,
        value=None if denominator == 0 else numerator / denominator, label=label, scope=scope)


def ratios(counts, scope):
    denominator = counts['retained_observations']
    comparison_denominator = counts['retained_comparison_observations']
    return dict(supported_peer=_ratio(counts['supported_comparison_observations'], comparison_denominator,
        'Observations with a supported cross-source peer / retained comparison-source observations', scope+'; reference data excluded'),
        current_peer=_ratio(counts['current_comparison_observations'], comparison_denominator,
        'Observations with a current cross-source peer / retained comparison-source observations', scope+'; reference data excluded'),
        current=_ratio(counts['current_observations'], denominator,
        'Current observations / retained observations', scope))


def _mapped_reason(code):
    code = str(code or '')
    if code.endswith('_supported'):return None
    if 'schedule' in code and any(k in code for k in ('conflict','invalid','unverified','mismatch')): return 'schedule_conflict'
    if 'equality' in code or 'push' in code or 'refund' in code: return 'equality_missing_or_conflicting'
    if any(k in code for k in ('scoring', 'overtime', 'extra_innings', 'shootout', 'scope_')): return 'scoring_scope_missing_or_conflicting'
    if 'period_unsupported' in code: return 'period_unsupported'
    if 'market_type_unsupported' in code: return 'market_type_unsupported'
    if any(k in code for k in ('predicate', 'line_', 'subject')): return 'predicate_missing_or_conflicting'
    if 'participant' in code or 'mapping_unresolved' in code: return 'participant_identity_unresolved'
    if code=='comparison_mapping_unavailable': return 'occurrence_identity_unresolved'
    if code=='comparison_native_unsupported': return 'native_price_or_binding_unsupported'
    if 'context' in code or 'season' in code or 'stage' in code: return 'comparison_context_missing'
    if 'occurrence' in code: return 'occurrence_identity_unresolved'
    return None


def _freshness(quote, event, at, states, published=None):
    try:
        from .source_clock import assess
        clocks=assess(quote,stamp(at))
        if any(code!='source_expired' for code in clocks['reasons']):
            return 'unknown'
        start = event.get('scheduled_start', event.get('start_at'))
        current = (not clocks['reasons']
            and (not start or stamp(at)<stamp(start)))
        state = states.get(quote.get('venue'), {}).get('state', quote.get('state', quote.get('source_state', 'unknown')))
        captured=quote.get('state',quote.get('source_state','unknown'))
        published=published or {}
        captured_available=(captured in ('available','budget_delayed')
            and published.get('captured_source_state',captured) in ('available','budget_delayed')
            and 'captured_source_unavailable' not in published.get('observation_display',{}).get('source_reason_codes',[]))
        return 'current' if current and captured_available and state in ('available', 'budget_delayed') else 'last_known'
    except (ValueError, TypeError):
        return 'unknown'


def _gross_eligibility(quote, published, at):
    """Same price, binding and effective-link gates as ordinary gross inspection.

    A matching predicate alone does not establish a comparable native price.
    The published gross decision also witnesses the resolver's captured verified
    binding; raw source-local ``verified`` can legitimately be promoted there.
    """
    from app.dashboard.u0_display import quote_display
    from .current_dependencies import link_reasons
    original=quote.get('original',{})
    if (original.get('payout_units')!='USD' or not quote_display(original.get('value'),original.get('units'),original.get('payout'))['supported']
            or quote.get('binding',{}).get('verified') is False):
        return False,'comparison_native_unsupported'
    try:
        if any(link_reasons(item,stamp(at)) for item in (quote,published or {})):return False,'comparison_mapping_unavailable'
    except (ValueError,KeyError,TypeError):return False,'comparison_mapping_unavailable'
    gross=(published or {}).get('gross_comparison',{})
    if gross.get('available') or gross.get('reason_code') in ('comparison_peer_missing','comparison_peer_matching_unsupported'):
        return True,None
    return False,gross.get('reason_code') or 'comparison_publication_eligibility_unmeasured'


def _example(item):
    q = item['quote']; p = item.get('published') or {}; record = item['record']
    return dict(quote_id=p.get('quote_id') or item['id'], event=dict(title=record['event'].get('title'),
        start_at=record['event'].get('scheduled_start'), native_event_id=q.get('source', {}).get('native_event_id')),
        source=deepcopy(q.get('source', {})), venue=q.get('venue'), original=deepcopy(q.get('original', {})),
        times=deepcopy(q.get('times', {})), freshness=item['freshness'],
        clock_evidence=deepcopy(item.get('clock_evidence')),book_confirmation=deepcopy(q.get('book_confirmation')),
        missing_fields=deepcopy(p.get('same_outcome', {}).get('missing_fields',
            record.get('comparison_source_metadata', {}).get('comparison_admission', {}).get('missing_fields', []))),
        diagnostic_codes=item['diagnostic_codes'], reasons=item['reasons'],
        failed_conditions=deepcopy(item.get('failed_conditions',[])),
        captured_inputs=deepcopy(p.get('inputs_identity')), provider_requests=0)


def _held(owner):
    quota = owner.get('status', {}).get('quota') or {}
    # Presence of a historical issue alone is not a current hold.
    return bool(quota.get('hold') or quota.get('holds') or quota.get('held') or quota.get('pause')
        or quota.get('blocking_reason') in ('ambiguous_dispatch_unresolved','quota_unknown','clock_continuity_unknown','quota_ledger_unavailable')
        or quota.get('state') in ('held', 'blocked') or owner.get('status', {}).get('recovery', {}).get('reason') in
        ('ambiguous_dispatch_unresolved', 'quota_unknown', 'clock_continuity_unknown', 'restart_accounting_refresh_required'))


def _discovery(query):
    latest = deepcopy((query or {}).get('latest'))
    if not latest:
        return dict(checked_at=None,status='not_checked',completeness='unmeasured',games=None,markets=None,
            native_outcomes=None,scope='exact_query',unique_counts_measured=False,last_success=None)
    failed = latest['status'] in ('failed_source', 'rejected_payload')
    unique = latest.get('unique_offered')
    counts = {} if failed or unique is None else unique
    return dict(checked_at=latest['checked_at'],status=latest['status'],completeness=latest['completeness'],
        games=counts.get('games'),markets=counts.get('markets'),native_outcomes=counts.get('quotes'),
        reported_counts=None if failed else latest.get('offered'),unique_counts_measured=unique is not None and not failed,
        inventory=deepcopy(latest.get('inventory')),
        scope=latest.get('offered_scope','exact_query'),query_sha256=latest.get('query_sha256'),
        reason=latest.get('reason'),admission_code=latest.get('admission_code'),last_success=deepcopy(query.get('last_success')),
        window_note='Exact captured query and selected metadata window; independent of the retained-price cohort. Provider-universe totals are unknown.')


def merge_queries(current, previous=()):
    """Keep bounded latest query evidence across runtime restarts, without aging it.

    A new empty in-memory ledger is not evidence that an older check vanished.
    Successful query clocks and failure clocks remain separate and unchanged.
    """
    values={}
    def merge(a,b):
        result={}
        for key in ('latest','last_success'):
            candidates=[v[key] for v in (a,b) if v and v.get(key)]
            result[key]=deepcopy(max(candidates,key=lambda v:stamp(v['checked_at']))) if candidates else None
        return result
    for row in [*previous,*current]:
        key=(row['sport'],row.get('venue',row.get('source')))
        if key[0] not in SPORTS or key[1] not in VENUES:continue
        old=values.get(key,{})
        families={f['family']:deepcopy(f) for f in old.get('family_queries',[])}
        for f in row.get('family_queries',[]):
            families[f['family']]=dict(family=f['family'],**merge(families.get(f['family']),f))
        values[key]=dict(sport=key[0],venue=key[1],**merge(old,row),family_queries=list(families.values()))
    return [values[key] for key in sorted(values)]


def _pair_count(values):
    values=tuple(values)
    total = sum(values)
    return (total * total - sum(n * n for n in values)) // 2


def totals(cells, groups, occurrences=None,inputs=None,publications=None):
    out = {k: sum(c['counts'][k] for c in cells) if all(c['counts'].get(k) is not None for c in cells) else None for k in COUNT_KEYS}
    selected = {c['id'] for c in cells}
    # Each canonical outcome is local to one league/family/period, with one
    # membership count per source. Pairs are undirected distinct native inputs.
    out['comparable_outcomes'] = sum(bool(selected.intersection(g['cells'])) for g in groups)
    out['underlying_pairs'] = sum(_pair_count(g['cells'].values()) -
        _pair_count(n for key,n in g['cells'].items() if key not in selected) for g in groups)
    if occurrences is not None:
        out['matched_occurrences'] = sum(bool(selected.intersection(ids)) for ids in occurrences)
    def incident(group):
        return _pair_count(group.values())-_pair_count(n for key,n in group.items() if key not in selected)
    out['eligible_current_pairs']=None if inputs is None else sum(incident(g['current_cells']) for g in inputs)
    out['supported_noncurrent_pairs']=None if inputs is None else sum(incident(g['cells'])-incident(g['current_cells']) for g in inputs)
    out['published_current_pairs']=None if publications is None else sum(bool(selected.intersection(ids)) for ids in publications)
    return out


def build(records, published, *, config, owner, at, queries=(), encountered=(), exclusions=(), publication_at=None,resolve_inputs=False):
    """Build once in the background from one repeatable-read database capture."""
    from .capabilities import inventory
    from .calculation_control import checkpoint
    from .source_clock import assess
    records = list(records); published = list(published)
    if len(records)>MAX_RECORDS or len(published)>MAX_RECORDS: raise ValueError('coverage_record_capacity')
    published_by_native = defaultdict(list)
    for q in published:published_by_native[native_key(q)].append(q)
    input_facts={}
    if resolve_inputs:
        from .occurrence_matching import OccurrenceResolver
        from app.storage.comparison_board import _records
        from .same_outcome import record_identity
        def project(row):
            return (native_key(row['quote']), dict(verified=row.get('verified'),
                quote=dict(occurrence_match={k:row['quote']['occurrence_match'].get(k)
                    for k in ('status','occurrence_id')})), record_identity(row))
        # Preserve the ordinary resolver and its complete global membership,
        # but release each detached audit graph after extracting metrics facts.
        for key,row,identity in OccurrenceResolver().resolve(_records(records,at),clock=at,result_projector=project):
            input_facts[key]=(row,identity)
    query_map = {(c['sport'],c.get('venue',c.get('source')),f['family']):f for c in queries for f in c.get('family_queries', [])}
    # A source-wide query cannot become family-specific counts.
    source_queries = {(c['sport'],c.get('venue',c.get('source'))):c for c in queries}
    states = deepcopy(owner.get('states', {}))
    for source in VENUES:
        provider='the_odds_api' if source in ('novig','prophetx','pinnacle') else source
        if not owner.get('healthy',True) or not owner.get('active',True) or owner.get('global_stopped') or provider in owner.get('paused_sources',[]):
            states[source]=dict(states.get(source,{}),state='stopped')
    items = []; seen = set(); scope = list(encountered)
    for record in records:
        checkpoint()
        q = record['quote']; key = native_key(q)
        if key in seen: continue
        seen.add(key)
        sport = record['event'].get('competition', record['event'].get('league'))
        venue = q.get('venue'); market = record.get('market_identity', {})
        fam = family(market.get('family')); period = market.get('period') or 'unknown'
        if sport not in SPORTS or venue not in VENUES: continue
        cid = cell_id(sport,venue,fam,period)
        scope.append(dict(league=sport,source=venue,family=fam,period=period))
        def exact_publication(p):
            return (p.get('original')==q.get('original') and p.get('times',{}).get('source_at')==q.get('times',{}).get('source_at')
                and p.get('book_confirmation')==q.get('book_confirmation'))
        copies=published_by_native.get(key,[])
        p=max(copies,key=lambda p:(exact_publication(p),
            not p.get('observation_display',{}).get('publication_reason_codes'),
            bool(p.get('same_outcome',{}).get('supported')),p.get('times',{}).get('received_at') or '',p.get('quote_id') or '')) if copies else None
        structural_publication=p
        # Receipt-only duplicates do not change the original book or renew its
        # source evidence. Display retains its frozen earlier receipt exactly.
        if p and not exact_publication(p):p=None
        meta = record.get('comparison_source_metadata', {})
        codes = set()
        if p:
            for name in ('same_outcome', 'gross_comparison', 'current_comparison'):
                detail = p.get(name, {})
                codes.update(detail.get('reason_codes', []))
                if detail.get('reason_code') or detail.get('reason'): codes.add(detail.get('reason_code') or detail.get('reason'))
        for name in ('comparison_admission', 'same_outcome', 'scoring_scope'):
            detail=meta.get(name,{})
            if detail.get('reason') and detail.get('status')!='supported' and detail.get('supported') is not True:
                codes.add(detail['reason'])
        failed_conditions=[]
        for exclusion in exclusions:
            members={tuple(m) for m in exclusion.get('members',[])}
            source=q.get('source',{})
            if members:
                related=(source.get('provider'),source.get('native_event_id')) in members
            else:
                related=(exclusion.get('source',exclusion.get('venue')) in (venue,source.get('provider'))
                    and exclusion.get('market_id',source.get('native_market_id'))==source.get('native_market_id')
                    and exclusion.get('event_id',source.get('native_event_id'))==source.get('native_event_id')
                    and exclusion.get('sport',sport)==sport)
            if related:
                failure=exclusion.get('reason',exclusion.get('reason_code'))
                if failure:codes.add(failure)
                failed_conditions.extend(exclusion.get('schedule_conflicts',[])[:3])
        reasons = {_mapped_reason(code) for code in codes} - {None}
        if record['event'].get('schedule_conflict'): reasons.add('schedule_conflict')
        if record['event'].get('identity') not in ('resolved', None): reasons.add('participant_identity_unresolved')
        if not p and venue!='pinnacle': reasons.add('waiting_for_publication')
        match = (p or {}).get('occurrence_match', {})
        if venue != 'pinnacle' and match.get('status') != 'matched': reasons.add('occurrence_identity_unresolved')
        identity = (p or {}).get('same_outcome', {})
        # Stop, a paused runtime or a dead heartbeat withdraw current authority,
        # while the exact retained outcome meaning can remain supported.
        publication_codes=set((p or {}).get('observation_display', {}).get('publication_reason_codes',[]))
        published_valid = not (publication_codes-{'runtime_authority_changed','background_observations_unavailable',
            'updates_stopped','data_runtime_unhealthy'})
        eligible,eligibility_code=_gross_eligibility(q,p,at) if venue!='pinnacle' else (False,None)
        if eligibility_code:
            codes.add(eligibility_code)
            mapped=_mapped_reason(eligibility_code)
            if mapped:reasons.add(mapped)
        supported = bool(identity.get('supported') and identity.get('key') is not None and published_valid and eligible and venue!='pinnacle')
        canonical = json.dumps(identity.get('key'),sort_keys=True,separators=(',',':')) if supported else None
        resolved,raw_identity=input_facts.get(key,(None,{}))
        raw_supported=bool(raw_identity.get('supported') and resolved.get('verified') is True) if resolved else False
        raw_key=raw_identity.get('key') if raw_supported else None
        if resolved and raw_supported:
            from app.dashboard.u0_display import quote_display
            original=q.get('original',{})
            raw_supported=bool(original.get('payout_units')=='USD' and quote_display(original.get('value'),original.get('units'),original.get('payout'))['supported'])
        if not raw_supported and structural_publication and structural_publication.get('same_outcome',{}).get('supported'):
            # Only an exact captured input may supply the legacy projection.
            raw_supported=supported;raw_key=identity.get('key') if supported else None
        input_canonical=json.dumps(raw_key,sort_keys=True,separators=(',',':')) if raw_supported and venue!='pinnacle' else canonical
        if not published_valid: reasons.add('waiting_for_publication')
        fresh = _freshness(q, record['event'], at, states,published=p)
        if fresh == 'unknown': reasons.add('unknown_source_clock')
        elif fresh == 'last_known': reasons.add('stale_inputs')
        if venue == 'pinnacle': reasons.add('reference_only')
        items.append(dict(id=sha256(json.dumps(key).encode()).hexdigest(),cell=cid,quote=q,record=record,
            published=p,canonical=canonical,occurrence=match.get('occurrence_id') if match.get('status')=='matched' else None,
            input_canonical=input_canonical,input_matched=(resolved['quote'].get('occurrence_match',{}).get('status')=='matched') if resolved else match.get('status')=='matched',
            input_occurrence=(resolved['quote'].get('occurrence_match',{}).get('occurrence_id') if resolved else match.get('occurrence_id')),
            clock_evidence=assess(q,stamp(at)),
            freshness=fresh,reasons=reasons,diagnostic_codes=sorted(codes),failed_conditions=failed_conditions))
    specs = inventory(config=config,encountered=scope)
    if len(specs)>MAX_CELLS: raise ValueError('coverage_cell_capacity')
    by_cell = defaultdict(list); by_outcome = defaultdict(list); occurrences = defaultdict(set)
    for item in items:
        by_cell[item['cell']].append(item)
        if item['canonical']: by_outcome[item['canonical']].append(item)
        if item['occurrence']: occurrences[item['occurrence']].add(item['cell'])
    input_groups=defaultdict(list);published_pairs={}
    candidate_groups=defaultdict(list)
    for item in items:
        if item['input_matched'] and item['quote']['venue']!='pinnacle':
            market=item['record']['market_identity']
            candidate_groups[(item['input_occurrence'],family(market.get('family')),market.get('period'))].append(item)
    for group in candidate_groups.values():
        for item in group:
            item['retained_candidates']=sum(i['quote']['venue']!=item['quote']['venue'] for i in group)
            if not item['retained_candidates']:item['reasons'].add('retained_peer_absent')
    for item in items:
        if item['input_canonical']:input_groups[item['input_canonical']].append(item)
    input_aggregation=[]
    for group in input_groups.values():
        if len({i['quote']['venue'] for i in group})<2:continue
        input_aggregation.append(dict(cells=dict(Counter(i['cell'] for i in group)),
            current_cells=dict(Counter(i['cell'] for i in group if i['freshness']=='current'))))
        for item in group:
            peers=[i for i in group if i['quote']['venue']!=item['quote']['venue']]
            item['input_peers']=len(peers)
            item['input_current_peers']=sum(i['freshness']=='current' for i in peers) if item['freshness']=='current' else 0
            displayed=(item['published'] or {}).get('current_comparison',{})
            if item['input_current_peers'] and not (displayed.get('available') and displayed.get('display_status')=='current'):
                item['reasons'].add('current_inputs_publication_pending')
    published_cells={(i['published'] or {}).get('quote_id'):i['cell'] for i in items if i['published']}
    for item in items:
        if item.get('retained_candidates') and not item.get('input_peers'):
            item['reasons'].add('retained_peer_meaning_unresolved')
        p=item['published'] or {};displayed=p.get('current_comparison',{})
        if displayed.get('available') and displayed.get('display_status')=='current':
            if not item.get('input_current_peers'):item['reasons'].add('published_display_disagrees')
            peer=displayed.get('comparison_quote_id')
            if peer and p.get('quote_id'):
                membership=published_pairs.setdefault(tuple(sorted((p['quote_id'],peer))),set())
                membership.add(item['cell'])
                if peer in published_cells:membership.add(published_cells[peer])
    comparable_groups = []
    for group in by_outcome.values():
        checkpoint()
        counts = Counter(i['cell'] for i in group)
        if len({i['quote']['venue'] for i in group})<2: continue
        comparable_groups.append(dict(cells=dict(counts)))
        current_counts=Counter(i['quote']['venue'] for i in group if i['freshness']=='current')
        venue_counts=Counter(i['quote']['venue'] for i in group)
        for item in group:
            source=item['quote']['venue']
            item['peers'] = len(group)-venue_counts[source]
            item['current_peers'] = sum(current_counts.values())-current_counts[source] if item['freshness']=='current' else 0
    cells = []
    aggregate_held = _held(owner)
    for spec in specs:
        checkpoint()
        sport,venue,fam,period = spec['league'],spec['source'],spec['family'],spec['period']
        cid = cell_id(sport,venue,fam,period); local = by_cell[cid]
        configured = spec['configured']; provider = spec['acquisition_provider']
        state = ('not_configured' if not configured else 'disabled' if not spec['acquisition_enabled'] else
            'held' if provider=='the_odds_api' and aggregate_held else 'paused' if owner.get('global_stopped') or provider in owner.get('paused_sources', []) else 'enabled')
        query = query_map.get((sport,venue,fam)) if period=='full_game' else None
        discovery = _discovery(query)
        discovery['source_query'] = _discovery(source_queries.get((sport,venue)))
        contextual = set()
        if state!='enabled': contextual.add({'not_configured':'not_configured','disabled':'source_disabled','held':'source_held','paused':'source_paused'}[state])
        if not spec['comparison_supported'] and venue!='pinnacle': contextual.add('period_unsupported' if period!='full_game' else 'market_type_unsupported')
        if discovery['status']=='not_checked': contextual.add('not_checked')
        if discovery['completeness']=='partial': contextual.add('partial_listing')
        if discovery.get('reason') in ('query_capacity','query_empty','source_failed','payload_rejected'): contextual.add(discovery['reason'])
        if discovery['status']=='failed_source': contextual.add('source_failed')
        if discovery['status']=='rejected_payload': contextual.add('payload_rejected')
        if venue=='pinnacle': contextual.add('reference_only')
        for item in local:
            if not item.get('peers') and not item.get('input_peers') and venue!='pinnacle': item['reasons'].add('cross_source_peer_missing')
            item['reasons'].update(contextual-{'not_checked','partial_listing','query_empty'})
            item['reasons']=sorted(item['reasons'],key=lambda r:PRIMARY_ORDER.index(r))
        counts = {k:0 for k in COUNT_KEYS}
        counts.update(retained_observations=len(local),displayed_observations=sum(i['published'] is not None for i in local),
            identity_matched_observations=sum(bool(i['input_matched']) for i in local if venue!='pinnacle'),
            meaning_supported_observations=sum(bool(i['input_canonical']) for i in local if venue!='pinnacle'),
            input_supported_observations=sum(bool(i.get('input_peers')) for i in local),
            input_current_peer_observations=sum(bool(i.get('input_current_peers')) for i in local),
            eligible_current_directions=sum(i.get('input_current_peers',0) for i in local),
            publication_pending_directions=sum('current_inputs_publication_pending' in i['reasons'] for i in local),
            retained_peer_candidate_observations=sum(bool(i.get('retained_candidates')) for i in local),
            no_retained_peer_observations=sum('retained_peer_absent' in i['reasons'] for i in local),
            display_disagreement_directions=sum('published_display_disagrees' in i['reasons'] for i in local),
            retained_comparison_observations=len(local) if venue!='pinnacle' else 0,
            retained_reference_observations=len(local) if venue=='pinnacle' else 0,
            displayed_comparison_directions=sum(bool((i['published'] or {}).get('gross_comparison',{}).get('available')) for i in local) if venue!='pinnacle' else 0,
            displayed_current_comparison_directions=sum(bool((i['published'] or {}).get('current_comparison',{}).get('available'))
                and (i['published'] or {})['current_comparison'].get('display_status')=='current' and bool(i.get('current_peers')) for i in local) if venue!='pinnacle' else 0,
            current_observations=sum(i['freshness']=='current' for i in local),
            last_known_observations=sum(i['freshness']=='last_known' for i in local),
            unknown_age_observations=sum(i['freshness']=='unknown' for i in local),
            pending_observations=sum('waiting_for_publication' in i['reasons'] for i in local),
            matched_occurrences=len({i['occurrence'] for i in local if i['occurrence']}),
            supported_comparison_observations=sum(bool(i.get('peers')) for i in local),
            current_comparison_observations=sum(bool(i.get('current_peers')) for i in local),
            comparable_outcomes=len({i['canonical'] for i in local if i.get('peers')}),
            underlying_pairs=sum(i.get('peers',0) for i in local),signed_comparison_directions=sum(i.get('peers',0) for i in local),
            gap_observations=sum(not i.get('current_peers') for i in local if venue!='pinnacle'))
        cause_counts = Counter(r for i in local for r in i['reasons'])
        primary = Counter(i['reasons'][0] for i in local if i['reasons'])
        reasons = []
        for code in PRIMARY_ORDER:
            if code not in cause_counts and code not in contextual: continue
            label,category,condition = REASONS[code]
            reasons.append(dict(code=code,label=label,category=category,condition=condition,count=cause_counts[code],
                primary_count=primary[code],overlapping=True,
                examples=[_example(i) for i in islice((i for i in local if code in i['reasons']),MAX_EXAMPLES)]))
        cells.append(dict(id=cid,sport=sport,league=sport,venue=venue,source=venue,provider=provider,
            role='reference' if venue=='pinnacle' else 'comparison',family=fam,period=period,configured=configured,
            configuration_state=state,capability=dict(state=spec['capability_state'],reason=spec['capability_reasons'],
                discovery_supported=spec['discovery_supported'],normalization_supported=spec['normalization_supported'],comparison_supported=spec['comparison_supported']),
            discovery=discovery,counts=counts,ratios=ratios(counts,'captured cell retained observations'),reasons=reasons,
            examples=[_example(i) for i in local[:MAX_EXAMPLES]],
            odds_scope=dict(league=sport,venue=venue,market='winner' if fam=='moneyline' else fam,period=period)))
    occurrence_groups = [sorted(ids) for ids in occurrences.values()]
    publication_groups=[sorted(ids) for ids in published_pairs.values()]
    for cell in cells:
        updated=totals([cell],comparable_groups,None,input_aggregation,publication_groups)
        for key in ('eligible_current_pairs','supported_noncurrent_pairs','published_current_pairs'):cell['counts'][key]=updated[key]
    global_counts = totals(cells,comparable_groups,occurrence_groups,input_aggregation,publication_groups)
    return dict(schema=VERSION,version=VERSION,captured_at=at,publication_at=publication_at or at,
        publication_state='published',runtime_id=owner.get('runtime_id'),provider_requests=0,acquisition_requests=0,
        evidence_class='retained current rows and exact query diagnostics; authored capability is separate',
        dimensions=dict(sports=list(SPORTS),sources=list(VENUES),families=sorted({c['family'] for c in cells}),periods=sorted({c['period'] for c in cells})),
        cells=cells,total_cells=len(cells),filtered_cells=len(cells),global_totals=global_counts,filtered_totals=deepcopy(global_counts),
        ratios=ratios(global_counts,'all captured retained observations'),filtered_ratios=ratios(global_counts,'all captured retained observations'),
        aggregation=dict(outcomes=comparable_groups,occurrences=occurrence_groups,inputs=input_aggregation,publications=publication_groups),
        aggregate_acquisition=dict(provider='the_odds_api',held=aggregate_held,
            pause=(owner.get('status',{}).get('quota') or {}).get('pause'),
            blocking_reason=(owner.get('status',{}).get('quota') or {}).get('blocking_reason'),
            unresolved_attempts=(owner.get('status',{}).get('quota') or {}).get('unresolved_attempts'),
            reserved_credits=(owner.get('status',{}).get('quota') or {}).get('reserved')),
        definitions=dict(cohort='One repeatable-read capture of unexpired retained native price inputs; one observation per source/native side.',
            discovery='Separate exact-query window; reported row counts are distinct from measured unique discovered counts. Unknown provider-universe totals.',
            displayed='Exact retained native inputs with a corresponding ordinary Odds publication, before local display filters.',
            displayed_comparison_directions='Available lowest-observed gross differences actually present in ordinary Odds; current, last-known, unknown and pending labels remain separate from availability.',
            displayed_current_comparison_directions='Available current-peer differences actually present in ordinary Odds whose captured display_status is current.',
            comparable_outcomes='Unique canonical outcomes with at least two comparison venues; Pinnacle is excluded.',
            supported_comparison_observations='Exact retained native inputs with a supported peer and valid published matching authority. Material runtime/source-health revocation can withhold this authority pending publication; source-clock aging alone does not erase supported meaning.',
            underlying_pairs='Undirected distinct native observation pairs across venues; global and filtered totals deduplicate source-cell overlap.',
            signed_comparison_directions='Directed eligible native input to other-venue peer comparisons; kept separate from underlying pairs.',
            reasons='Reason counts overlap. primary_count uses deterministic listed reason precedence; primary counts reconcile affected observations.',
            ratios='Numerator and denominator use the same captured retained cohort. Zero denominators are N/A; metric refresh never renews a price clock.'),
        limits=dict(maximum_records=MAX_RECORDS,maximum_cells=MAX_CELLS,examples_per_reason=MAX_EXAMPLES),
        retained_exclusion_count=len(exclusions))


def select(snapshot, *, league=None, venue=None, market=None, period=None):
    """Filter a compact detached publication; never hydrate a current-price store."""
    value = deepcopy(snapshot)
    filters = dict(sport=league,venue=venue,family=family(market) if market else None,period=period)
    for key,dimension in (('sport','sports'),('venue','sources'),('family','families'),('period','periods')):
        if filters[key] and filters[key] not in value['dimensions'][dimension]: raise ValueError('Unsupported coverage filter')
    cells = [c for c in value['cells'] if all(not wanted or c[key]==wanted for key,wanted in filters.items())]
    selected_counts = totals(cells,value['aggregation']['outcomes'],value['aggregation']['occurrences'],value['aggregation'].get('inputs'),value['aggregation'].get('publications'))
    value.update(cells=cells,filtered_cells=len(cells),filtered_totals=selected_counts,
        filtered_ratios=ratios(selected_counts,'filtered cells from the same captured retained cohort'),filters=filters)
    value['hidden_by_filter_observations']=value['global_totals']['retained_observations']-selected_counts['retained_observations']
    return value
