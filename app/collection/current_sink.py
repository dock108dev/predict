"""Atomic ephemeral admission, using the journal projection's shared reducer.

No cursor, hash chain, journal acknowledgment or reconstruction fallback. A
candidate reducer and normalized catalog swap only after CurrentStore commits.
"""
from copy import deepcopy, copy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from time import perf_counter
from app.dashboard.session_projection import SessionProjection, stable
from app.dashboard.current_contract import packed, serialize, quotes_of
from app.dashboard.current_normalized import catalog_from_normalized


def utc():
    return datetime.now(timezone.utc).isoformat()


def selected_market_observation(market, material):
    """Retain bounded exact-present Kalshi metadata, without execution authority.

    These fields already belong to the selected market discovery response. A
    book receipt cannot date the metadata, and representation/face values do not
    establish a legal quantity grid, settlement, participant channel or costs.
    """
    fields = ('price_ranges', 'price_level_structure', 'notional_value_dollars')
    values = {key: deepcopy(material[key]) for key in fields if key in material}
    proof = (market.get('provenance') or [{}])[-1]
    value = dict(version='selected-market-observation-1',
                 native_event_id=market['event_id'], native_market_id=market['id'],
                 material_sha256=stable(material),
                 source={key: deepcopy(proof[key]) for key in
                         ('path', 'params', 'received_at', 'body_sha256', 'inventory_row') if key in proof},
                 present_fields=list(values),
                 qualification='unreviewed_source_metadata_only_no_execution_authority')
    if len(packed(values)) > 16*1024:
        return dict(value, status='metadata_capacity_excluded', values={})
    return dict(value, status='observed' if values else 'absent', values=values)


def _missing_comparison_context(event):
    """Missing comparison context never becomes an invented source-local fact."""
    fields = ['season', 'stage']
    if event.get('competition') == 'MLB':
        fields.extend(('game_id', 'game_number', 'original_start', 'schedule_status'))
    return [field for field in fields if event.get(field) in (None, '', 'unknown', 'unverified')]


def _source_local_event(event, venue):
    """Validate the smaller durable native identity without joining occurrences."""
    from app.comparison.domain import LEAGUES
    from app.comparison.event_links import instant, provider_key
    participants = event.get('participants', {})
    roles = event.get('source_participant_roles', {})
    if (venue not in ('kalshi', 'polymarket_us') or event.get('identity') != 'resolved'
            or event.get('competition') not in LEAGUES
            or not isinstance(event.get('id'), str) or not event['id']
            or event.get('occurrence_conflict') or event.get('conflicting_duplicate')
            or len(participants) != 2 or len(set(participants.values())) != 2
            or any(not isinstance(value, str) or not value for value in participants.values())
            or set(roles) != {'home', 'away'} or set(roles.values()) != set(participants.values())
            or any(event.get(role) != roles[role] for role in ('home', 'away'))):
        raise ValueError('Exact source-local event identity unavailable or conflicting')
    instant(event['scheduled_start'])
    if event['competition'] == 'MLB':
        original = event.get('original_start'); status = event.get('schedule_status')
        if (original is not None and status == 'original'
                and instant(original) != instant(event['scheduled_start'])):
            raise ValueError('Conflicting original source-local MLB schedule')
        if event.get('game_number') is not None and (type(event['game_number']) is not int or event['game_number'] < 1):
            raise ValueError('Conflicting source-local MLB game number')
        if status is not None and status not in ('original', 'rescheduled'):
            raise ValueError('Conflicting source-local MLB schedule status')
    return provider_key(venue, event)


def _context_display_binding(event, market, binding, venue):
    """Reuse exact typed sides while retaining strict comparison refusal.

    Only the known missing-context blockers are eligible. This detached display
    binding never changes the catalog's BOUND_RAW_PREDICATE decision.
    """
    from .v1_comparison import predicates
    missing = _missing_comparison_context(event)
    if not missing or binding.get('status') != 'IDENTITY_BLOCKED':
        return None
    _source_local_event(event, venue)
    blockers = binding.get('blockers', [])
    prefixes = ('Exact game identity facts unavailable:',
                'Exact schedule, sport season and stage unavailable',
                'Exact MLB game/number/original/rescheduled identity unavailable')
    def contextual(reason):
        return isinstance(reason, str) and (reason.startswith(prefixes)
            or reason == 'Conflicting or incomplete exact MLB occurrence/home/away identity'
            and event['competition'] == 'MLB' and bool(missing))
    if (not blockers or not all(contextual(reason) for reason in blockers)
            or market.get('conflicting_duplicate') or binding.get('source') != venue
            or binding.get('event_id') != event['id'] or binding.get('market_id') != market['id']
            or binding.get('sha256') != stable({k:v for k,v in binding.items() if k != 'sha256'})):
        return None
    identity = binding.get('identity') or {}
    if (identity.get('competition') != event['competition']
            or identity.get('family') != market.get('market_type')
            or identity.get('period') != market.get('period')
            or any(identity.get(field) is not None and event.get(field) is not None
                   and identity[field] != event[field] for field in ('season', 'stage'))):
        return None
    sides = market.get('sides', [])
    values = list(predicates(binding))
    if (not values or len(sides) != len(values)
            or len({side['id'] for side in sides}) != len(sides)
            or {side['id'] for side in sides} != {native for native, _, _ in values}):
        return None
    out = deepcopy(binding)
    out['status'] = 'DISPLAY_ORIGINAL_ONLY'
    out['comparison_admission'] = dict(supported=False, reason='comparison_context_missing',
        missing_fields=missing, detail=deepcopy(blockers))
    return out


def source_local_display_binding(event, market, binding, venue):
    """Exact native display fallback for discovery and sink; never comparison authority."""
    try:
        return _context_display_binding(event, market, binding, venue)
    except (ValueError, KeyError, TypeError, ArithmeticError):
        return None


def _raw_display_binding(event,market,binding):
    """Retain a typed native quote when only comparison interpretation is missing.

    These are display labels from the original sides and source line. The explicit
    comparison_admission block prevents them from becoming score predicates.
    """
    from .admission_enrichment import resolve_team
    if (event.get('identity')!='resolved' or market.get('period')!='full_game'
            or market.get('market_type') not in ('moneyline','spread','total')):return None
    native=market.get('_native') or market.get('native_metadata') or {}
    family=market['market_type'];venue=binding.get('source')
    if venue!='polymarket_us':return None
    sides=native.get('marketSides',[])
    if (len(sides)!=2 or {s.get('long') for s in sides}!={True,False}
            or any(str(s.get('marketId'))!=market['id'] or type(s.get('long')) is not bool for s in sides)):return None
    line=None
    if family!='moneyline':
        try:
            line=Decimal(str(native.get('line')))
            if not line.is_finite() or abs(line)>10000:return None
        except (ValueError,TypeError,ArithmeticError):return None
    selections=[];anchor=None
    for side in sides:
        participant=None;signed=None
        if family=='total':
            label=side.get('description')
            if label not in ('Over','Under'):return None
            kind=label.lower();signed=str(line)
        else:
            participant=resolve_team(side.get('team') or {},event.get('competition'),venue)
            if participant not in event.get('participants',{}).values():return None
            kind='win' if family=='moneyline' else 'cover'
            if family=='spread':
                try:signed=Decimal(str(side.get('description')))
                except (ValueError,TypeError,ArithmeticError):return None
                if signed!=(line if side['long'] else -line):return None
                signed=str(signed)
                if side['long']:anchor=participant
        selections.append(dict(native_id=str(side['id']),participant=participant,predicate=kind,signed_line=signed))
    out=deepcopy(binding)
    out.update(status='DISPLAY_ORIGINAL_ONLY',predicate=selections,source_predicate=None,display_anchor=anchor)
    out['identity']=dict(binding.get('identity') or {},family=family,period='full_game',line=None if line is None else str(line))
    conflict=any('conflict' in str(reason).lower() for reason in binding.get('blockers',[]))
    out['comparison_admission']=dict(supported=False,reason='comparison_predicate_conflict' if conflict else 'comparison_predicate_missing',
        missing_fields=['native_inequality','native_contract_wording'],detail=deepcopy(binding.get('blockers',[])))
    return out


def normalized_records(projection, states, previous, *, dated_annotations=True, clock=None, include_missing=False):
    from app.comparison.event_links import current_event_key as event_key
    from .v1_comparison import predicates
    records = []
    excluded = []
    for venue, cat in sorted(projection.inventory.items()):
        if dated_annotations and venue in ('kalshi','polymarket_us'):
            from .current_occurrence import annotate as occurrence
            cat = occurrence(deepcopy(cat), venue)
        events = {e['id']: e for e in cat['events']}
        for market in cat['markets']:
            event = events.get(market['event_id'])
            binding = market.get('v1_raw_binding')
            row = projection.books.get((venue, market['event_id'], market['id']))
            if not event or not binding or not row:
                continue
            reason = event.get('exclusion') or market.get('exclusion') or market.get('subscription_evidence_exclusion')
            try:
                event=deepcopy(event)
                roles=event.get('source_participant_roles',{})
                for role in ('home','away'):
                    if event.get(role) is None and roles.get(role) is not None:event[role]=roles[role]
                if binding['status']!='BOUND_RAW_PREDICATE':
                    contextual=source_local_display_binding(event,market,binding,venue)
                    if (_missing_comparison_context(event)
                            and (event.get('occurrence_conflict') or event.get('conflicting_duplicate')
                                 or market.get('conflicting_duplicate')
                                 or contextual is None and any('conflict' in str(value).lower() for value in binding.get('blockers',[])))):
                        raise ValueError('Conflicting source-local identity')
                    if contextual is not None:
                        soft={'native_scope_effective_descriptor_facts_missing', 'native_scope_predicate_review_required',
                              'unsupported_market_type_or_period', 'unresolved_native_sides'}
                        if not event.get('exclusion') and all(not value or value in soft for value in
                                (market.get('exclusion'),market.get('subscription_evidence_exclusion'))):
                            binding=contextual;reason=None
                    elif not reason:
                        binding=_raw_display_binding(event,market,binding) or binding
                # The catalog binding's seal covers its original strict facts.
                # Attach the separate display refusal only after verifying it.
                if market.get('comparison_admission',{}).get('supported') is False:
                    binding=dict(binding,comparison_admission=deepcopy(market['comparison_admission']))
                display_only=binding.get('comparison_admission',{}).get('supported') is False
                if reason or binding['status'] not in ('BOUND_RAW_PREDICATE','DISPLAY_ORIGINAL_ONLY'):
                    raise ValueError('Native identity or predicate incomplete')
                event_scope=None
                try:key = event_key(event)
                except (ValueError,KeyError):
                    event_scope=dict(policy='native-event-unverified-2',source=venue,native_event_id=event['id'])
                    key=_source_local_event(event,venue)
                    for field in ('season','stage'):event.setdefault(field,None)
                missing_context=_missing_comparison_context(event)
                if event_scope is not None and missing_context:
                    admission=deepcopy(binding.get('comparison_admission',{}))
                    binding=dict(binding,comparison_admission=dict(supported=False,reason='comparison_context_missing',
                        missing_fields=list(dict.fromkeys(missing_context+admission.get('missing_fields',[]))),
                        detail=deepcopy(binding.get('blockers',admission.get('detail',[])))))
                    display_only=True
                ident = binding['identity']
                from app.comparison.domain import PERIODS
                if ident['period'] not in PERIODS or ident['family'] not in ('moneyline', 'spread', 'total'):
                    raise ValueError('Outside common sporting scope')
                book = row['book']
                if book['raw']['ref'] != dict(venue=venue, event_id=event['id'], market_id=market['id']):
                    raise ValueError('Book identity conflict')
                if book['sync'] != 'synchronized' or book['state'] != 'active':
                    continue  # incomplete images never replace an admitted complete image
                sides = {s['id']: s for s in market['sides']}
                ladders = {o['outcome_id']: o for o in book['outcomes']}
                fact = binding.get('source_predicate')
                canonical_line = None if ident['family'] == 'moneyline' else str(ident['line'])
                anchor = None
                if ident['family'] == 'spread':
                    anchor = fact['participant'] if fact else binding.get('display_anchor')
                native_predicates=list(predicates(binding))
                selections={}
                for native,predicate,meaning in native_predicates:
                    participant=meaning['participant'];kind=meaning['predicate'];signed=meaning.get('signed_line')
                    if fact:
                        op=meaning['operator']
                        if op not in ('gt','le','lt','ge'):raise ValueError('Exact score outcome requires supported orientation')
                        if ident['family']=='total':
                            participant=None;kind='over' if op in ('gt','ge') else 'under';signed=canonical_line
                        elif ident['family']=='moneyline':
                            participant=fact['participant'];signed=None
                            # A native team-win NO includes its own tie predicate;
                            # it never becomes an opposing team's YES.
                            if participant not in (event['home'],event['away']):
                                raise ValueError('Partial winner requires a named team predicate')
                            kind='win' if op==('gt' if participant==event['home'] else 'lt') else 'not_win'
                        else:
                            participant=event['home'] if op in ('gt','ge') else event['away']
                            kind='cover';signed=canonical_line if participant==anchor else str(-Decimal(canonical_line))
                    name=next((n for n,cid in event['participants'].items() if cid==participant),None)
                    selections[native]=dict(participant=participant,predicate=kind,signed_line=signed,
                        label=kind.capitalize() if name is None else name+(' does not win' if kind=='not_win' else ''))
                for native, predicate, meaning in native_predicates:
                    ladder = ladders.get(native)
                    if (not ladder or not ladder['asks']) and not include_missing:
                        continue
                    selection=selections[native]
                    participant=selection['participant'];kind=selection['predicate'];signed=selection['signed_line']
                    levels = sorted(ladder['asks']['levels'], key=lambda x: Decimal(x['price']['value'])) if ladder and ladder['asks'] else []
                    if not levels and not include_missing:continue  # known empty side remains an outcome without a price
                    if len(levels) > 4096 or any(Decimal(l['quantity']['value']) <= 0 for l in levels):
                        raise ValueError('Invalid bounded book depth')
                    value = str(levels[0]['price']['value']) if levels else None
                    side = sides[native]
                    original = dict(value=value, units='usd_per_contract', payout='1', payout_units='USD',
                                    quantity_units='contracts', role='comparison')
                    # The reused purchase_book conversion supplies the original
                    # opposite bid and preserves native liquidity independently.
                    if value is not None and (venue=='kalshi' or venue == 'polymarket_us' and side.get('role') == 'Short'):
                        with localcontext() as ctx:
                            ctx.prec=600
                            original.update(native_value=str(Decimal(1)-Decimal(value)), native_units='usd_per_contract', transformation='one_minus_native_bid')
                    state = 'resyncing' if (venue, market['event_id'], market['id']) in projection.invalid else states[venue]['state']
                    if market.get('comparison_admission',{}).get('reason')=='native_material_changed_capacity':state='stale'
                    source = dict(provider=venue, native_event_id=event['id'], native_market_id=market['id'],
                        native_outcome_id=native, native_side=side.get('role') or native,
                        binding_id=stable([venue, event['id'], market['id'], native, predicate]),
                        binding_version=binding['version'], native_line=market.get('line'), quote_side='buy')
                    q = dict(id='', revision=1, venue=venue, source=source, original=original,
                        times=dict(source_at=book['raw'].get('exchange_at'), received_at=book['raw']['received_at'],
                                   projected_at=clock or utc(), source_time_kind='provider_book' if book['raw'].get('exchange_at') else 'unknown'),
                        state=state if state != 'connecting' else 'resyncing',
                        rule_note=('Original native price retained; comparison context is incomplete.'
                            if binding.get('comparison_admission',{}).get('reason')=='comparison_context_missing' else
                            'Original native price retained; exact comparison predicate is unavailable.' if display_only else
                            'Native predicate reviewed; exceptional settlement and costs remain unqualified.'),
                        cost_note='Current applicable costs unavailable',
                        depth=[dict(price=str(l['price']['value']), quantity=str(l['quantity']['value'])) for l in levels],
                        freshness_policy=dict(version=venue+'-book-age-engineering-1', maximum_age_seconds=30),
                        provenance=dict(mode='current', real_source=True, sha256=binding['sha256']))
                    if book.get('book_confirmation'):
                        q['book_confirmation']=deepcopy(book['book_confirmation'])
                    name = next((n for n, cid in event['participants'].items() if cid == participant), None)
                    selection = dict(participant=participant, predicate=kind, signed_line=signed,
                                     label=kind.capitalize() if name is None else name+(' does not win' if kind == 'not_win' else ''))
                    normalized = dict(event=deepcopy(event), market_identity=dict(event=key, sport=event['sport'],
                        competition=event['competition'], season=event['season'], stage=event['stage'], scheduled_start=event['scheduled_start'],
                        family=ident['family'], period=ident['period'], line=canonical_line,
                        outcome_set=stable([p for _, p, _ in predicates(binding)]), rules='native-gross-predicate-1'),
                        period_boundary='Original native period; scoring scope recorded separately',
                        anchor_participant=anchor, selection=selection, quote=q,
                        orientation_evidence=[binding['version']+':'+binding['sha256']], verified=event_scope is None and not display_only,
                        outcome_cardinality=2, outcome_selections=list(selections.values()),
                        result_policy='native-'+ident['family']+'-normal-predicate-1:'+stable([p for _,p,_ in native_predicates]))
                    normalized['comparison_scope']=dict(overtime=(market.get('native_scope_binding') or {}).get('overtime','unknown'))
                    from .current_occurrence import direct, VERSION as DIRECT_VERSION
                    if dated_annotations and event_scope is None and direct(normalized, market, native, selection):
                        if market['direct_win_binding'].get('prospective_only'):
                            # Only the reviewed direct-win instrument shares this
                            # reference basis. An unreviewed Short stays separate.
                            normalized['market_identity']['rules']=DIRECT_VERSION+':prospective-reviewed-direct-win'
                        normalized['result_policy']=DIRECT_VERSION+':normal-full-game-win'
                        normalized['period_boundary']='Full game including applicable overtime; direct win only; exceptional cashflows differ'
                        normalized['comparison_scope']=dict(overtime='included')
                        normalized['outcome_selections']=[dict(participant=event[role],predicate='win',signed_line=None,label=next(n for n,c in event['participants'].items() if c==event[role])) for role in ('away','home')]
                        normalized['orientation_evidence'].append(DIRECT_VERSION+':'+market['direct_win_binding']['sha256'])
                        q['native_predicate']=dict(version=DIRECT_VERSION,participant=participant,predicate=kind,
                            native_outcome_id=native,domain=[dict(item,native_outcome_id=side) for side,item in selections.items()],
                            binding_sha256=market['direct_win_binding']['sha256'],
                            original_result_policy='native-'+ident['family']+'-normal-predicate-1:'+stable([p for _,p,_ in native_predicates]))
                        q['rule_note']='Direct full-game win gross quote comparison only. Original native outcome domain is preserved. Tie pays 0.50; Kalshi postponement window is 48 hours, US is two weeks; fair-price/refund/cancellation treatment differs or remains unqualified. Kalshi NO is not opponent YES.'
                        q['rule_note']=market['direct_win_binding'].get('rule_note',q['rule_note'])
                        q['rules_differ']=True
                    material=market.get('_native') or market.get('native_metadata') or {}
                    event_material=event.get('_native') or event.get('native_metadata') or {}
                    normalized['comparison_source_metadata']=dict(
                        native_key=[venue,source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source['native_side']],
                        material_sha256=stable(material),observed_at=q['times']['received_at'],
                        original_wording={k:deepcopy(material[k]) for k in ('title','subtitle','yes_sub_title','no_sub_title','description','rules_primary','rules_secondary') if k in material},
                        rules_primary=binding.get('settlement',{}).get('native_clauses',{}).get('rules_primary'),
                        rules_secondary=binding.get('settlement',{}).get('native_clauses',{}).get('rules_secondary'),
                        series_id=event_material.get('series_ticker'),
                        native_market_type=binding.get('locator',{}).get('native_type'),
                        native_scope_binding=deepcopy(market.get('native_scope_binding')),
                        source_predicate=deepcopy(binding.get('source_predicate')),
                        native_terms=deepcopy(market.get('terms',{})),
                        phase=('pregame' if event_material.get('period')=='NS' and event_material.get('active') is True and event_material.get('closed') is False else
                               'live' if event_material.get('live') is True and event_material.get('ended') is False else 'unknown'))
                    if display_only:
                        normalized['comparison_source_metadata']['comparison_admission']=deepcopy(binding['comparison_admission'])
                        if event_scope is None:
                            event_scope=dict(policy='native-event-unverified-2',source=venue,native_event_id=event['id'])
                    if venue == 'kalshi':
                        normalized['comparison_source_metadata']['selected_market_observation'] = selected_market_observation(market, material)
                    # Preserve only exact selected instrument fields. A neighboring
                    # book/market or displayed face value cannot supply these units.
                    instrument_material=material
                    if venue=='polymarket_us':
                        candidates=material.get('instruments',[])
                        selected=[item for item in candidates if isinstance(item,dict) and str(item.get('id'))==native]
                        instrument_material=selected[0] if len(selected)==1 else material if str(material.get('id'))==native else {}
                    fields=('priceScale','fractionalQtyScale','minimumTradeQty','tickSize')
                    normalized['comparison_source_metadata']['selected_reference_data']=dict(
                        instrument_id=native,market_id=market['id'],
                        present=bool(instrument_material),
                        values={field:deepcopy(instrument_material[field]) for field in fields if field in instrument_material},
                        material_sha256=stable(instrument_material))
                    if venue=='polymarket_us':
                        normalized['comparison_source_metadata']['public_event_occurrence']=dict(
                            event_id=str(event_material.get('id')) if event_material.get('id') is not None else None,
                            game_id=str(event_material.get('gameId')) if event_material.get('gameId') is not None else None,
                            provider_game_id=event_material.get('sportradarGameId'),
                            rescheduled_from_game_id=str(event_material.get('rescheduledFromGameId')) if event_material.get('rescheduledFromGameId') is not None else None)
                        public_sides=[item for item in material.get('marketSides',[]) if
                            isinstance(item,dict) and str(item.get('id'))==native and
                            str(item.get('marketId'))==market['id']]
                        if len(public_sides)==1 and str(material.get('id'))==market['id']:
                            public_side=public_sides[0]
                            normalized['comparison_source_metadata']['public_retail_observation']=dict(
                                market_id=market['id'],instrument_id=native,
                                long=public_side.get('long'),team_id=str(public_side.get('teamId')),
                                values={field:str(material[field]) for field in
                                    ('orderPriceMinTickSize','minimumTradeQty','feeCoefficient') if field in material},
                                description=material.get('description'),
                                updated_at=material.get('updatedAt'),material_sha256=stable(material),
                                applicability='separate_metadata_requires_selected_binding')
                    if event_scope is not None:normalized['event_scope']=event_scope
                    # Comparison metadata remains facet-local: an unknown
                    # equality/scoring fact retains this native price.
                    from app.comparison.same_outcome import descriptor
                    normalized['comparison_source_metadata']['same_outcome']=descriptor(normalized,
                        scoring=dict(overtime=normalized['comparison_scope']['overtime']))
                    instrument = stable([source, selection])
                    # Metadata changes invalidate the shared input dependency
                    # revision. They do not manufacture a quote/price revision.
                    fingerprint = stable([{k: q[k] for k in ('source', 'original', 'state', 'rule_note', 'cost_note', 'depth', 'freshness_policy')},binding['sha256'],q.get('native_predicate')])
                    prior = previous.get(instrument)
                    if prior:
                        q['revision'] = prior['revision'] + (fingerprint != prior['fingerprint'])
                        if fingerprint == prior['fingerprint'] or q['original']==prior.get('original'):
                            q['times'] = deepcopy(prior['times'])
                    if value is None:normalized['offer_missing']=True
                    normalized['_instrument'] = instrument
                    normalized['_fingerprint'] = fingerprint
                    records.append(normalized)
            except (ValueError, KeyError, TypeError, ArithmeticError, StopIteration) as exc:
                excluded.append(dict(source=venue, market_id=market['id'], reason='Exact current binding incomplete or unsupported',
                    sport=event.get('competition') if event else None,family=market.get('family'),reason_code='mapping_unresolved',
                    binding_status=binding.get('status'),binding_blockers=binding.get('blockers',[]),catalog_exclusion=reason))
    return records, excluded[:200]


class LatestStateSink:
    acknowledgment = 'validated-in-memory-commit'

    def __init__(self, store, envelope, config=None):
        from .current_policy import DEFAULT
        self.config = config or DEFAULT
        self.store = store
        self.envelope = envelope
        self.reducer = SessionProjection()
        self.reducer.sid = envelope['runtime_id']
        self.reducer.spec = dict(mode='real', v1_comparison_policy='manual-comparison-2')
        self.sequence = 0
        self.revisions = {}
        self.exclusions = []
        self.aggregate_records = {}
        self.aggregate_receipts = {}
        self.aggregate_states = {}
        self.associated_cache = {}
        from app.comparison.occurrence_matching import OccurrenceResolver
        self.occurrence_resolver = OccurrenceResolver()
        self.metrics = dict(admitted_observations=0, rejected_observations=0, last_commit_ms=0, max_commit_ms=0, retained_bytes=0, max_transient_encoded_bytes=0)

    def commit(self, row, states):
        try:
            result=self._commit(row,states)
        except Exception:
            self.metrics["rejected_observations"]+=1
            raise
        self.metrics["admitted_observations"]+=1
        return result

    def _commit(self, row, states):
        ingress = {k:v.decode() if isinstance(v,bytes) else v for k,v in row.items()}
        if row['type']=='current_aggregate_batches':
            if not row['batches'] or len(row['batches'])>6 or len({r['sport'] for r in row['batches']})!=len(row['batches']):
                raise ValueError('Retained aggregate batch capacity')
            ingress['batches']=[{k:v.decode() if isinstance(v,bytes) else v for k,v in r.items()} for r in row['batches']]
        if len(packed(ingress)) > self.config['ingress_bytes']:
            raise ValueError('Current ingress observation capacity')
        tick = perf_counter()
        if row['type'] in ('prediction_book','prediction_books','source_health','current_aggregate','current_aggregate_batches'):
            # These observations replace book/health values, never inventory or
            # metadata. Detach just their mutable maps for atomic admission.
            candidate=copy(self.reducer)
            for name in ('books','health','sizes'):setattr(candidate,name,dict(getattr(self.reducer,name)))
            candidate.invalid=set(self.reducer.invalid)
            candidate.book_evidence=deepcopy(self.reducer.book_evidence)
        else:candidate=deepcopy(self.reducer)
        # Retained batches are read-only; association returns detached records.
        aggregate_records = dict(self.aggregate_records)
        aggregate_receipts = deepcopy(self.aggregate_receipts)
        aggregate_states = deepcopy(self.aggregate_states)
        associated_cache=dict(self.associated_cache)
        if row['type'] in ('current_aggregate','current_aggregate_batches'):
            batches = row['batches'] if row['type']=='current_aggregate_batches' else [row]
            for batch_row in batches:
                from .current_aggregate_admission import admit_venues, admit
                sport=batch_row['sport']
                aggregate_states[sport]=deepcopy(batch_row.get('venue_states',states))
                if aggregate_receipts.get(sport) and batch_row['received_at']<=aggregate_receipts[sport]:
                    raise ValueError('Stale aggregate response')
                accepted,rejected=admit_venues(batch_row['body'],sport,batch_row['received_at'])
                if len(rejected)==2:raise ValueError('Malformed aggregate response')
                prior=aggregate_records.get(sport,[])
                incoming={r['_instrument'] for batch in accepted.values() for r in batch}
                aggregate_records[sport]=[r for r in prior if r['quote']['venue'] in rejected and r.get('_instrument') not in incoming]+[r for batch in accepted.values() for r in batch]
                try:references=admit(batch_row['body'],sport,batch_row['received_at'],venue='pinnacle')
                except (ValueError,KeyError,TypeError,ArithmeticError,StopIteration):references=[]
                # Reference records need identity, originals and clocks, not venue
                # presentation fields or duplicated outcome descriptors.
                for r in references:
                    q=r['quote']
                    aggregate_records[sport].append({
                        **{k:r[k] for k in ('event','market_identity','selection','verified','orientation_evidence')},
                        'quote':dict(venue='pinnacle',source=q['source'],rule_note='',
                            original={'value':q['original']['value']},
                            times={k:q['times'][k] for k in ('source_at','received_at')},
                            revision=q['revision'],provider_clocks=deepcopy(q.get('provider_clocks',{})),
                            provenance=deepcopy(q['provenance']))})
                aggregate_receipts[sport]=batch_row['received_at']
        observations=row['observations'] if row['type']=='prediction_books' else [row]
        if not observations or len(observations)>self.config['markets_per_source']:
            raise ValueError('Current native batch capacity')
        if row['type']=='prediction_books':
            if any(o['type']!='prediction_book' or o['source']!=row['source'] for o in observations):
                raise ValueError('Exact single-source native batch required')
            identities=[tuple(o['book']['raw']['ref'][k] for k in ('venue','event_id','market_id')) for o in observations]
            if len(set(identities))!=len(identities):raise ValueError('Duplicate native batch identity')
        for observation in observations:
            if observation['type']=='prediction_book' and observation['book']['sync']=='synchronized':
                from app.dashboard.current_contract import bounded_decimal, stamp
                book=observation['book'];ref=book['raw']['ref'];source=observation['source']
                cat=candidate.inventory.get(source,{})
                market=next((m for m in cat.get('markets',[]) if m['id']==ref['market_id'] and m['event_id']==ref['event_id']),None)
                if source!=ref['venue'] or market is None or book['quantity_unit']!='contracts':raise ValueError('Unadmitted current book identity or units')
                if {o['outcome_id'] for o in book['outcomes']}!={s['id'] for s in market['sides']}:raise ValueError('Incomplete current outcome set')
                stamp(book['raw']['received_at']);stamp(book['raw'].get('exchange_at'),True)
                if book.get('book_confirmation'):
                    from .current_confirmation import validate
                    validate(book['book_confirmation'],ref,book)
                for outcome in book['outcomes']:
                    for name in ('asks','bids'):
                        ladder=outcome[name]
                        if ladder is None:continue
                        levels=ladder['levels']
                        if len(levels)>4096:raise ValueError('Current book level bound')
                        prices=set()
                        for level in levels:
                            price=bounded_decimal(level['price']['value']);quantity=bounded_decimal(level['quantity']['value'])
                            if not 0<=price<=1 or quantity<=0 or level['quantity']['unit']!='contracts' or price in prices:raise ValueError('Invalid current native level')
                            prices.add(price)
                candidate.reduce_observation(dict(observation,type='source_health',state='connected',market_ids=[observation['book']['raw']['ref']['market_id']]))
            elif observation['type']=='prediction_book':raise ValueError('Incomplete native image requires resynchronization')
            if observation['type'] not in ('current_aggregate','current_aggregate_batches'):candidate.reduce_observation(observation)
        if (getattr(self.store,'_stopping',False) is True or getattr(self.store,'_source_stopping',False) is True) and row['type']=='source_health':
            # Stop health is a separate synchronous admission after financial
            # publication authority has been revoked. No price/resolver/revision
            # or accounting candidate is acknowledged through this path.
            self.store.admit_shutdown_health(states)
            self.reducer=candidate;self.sequence+=1
            elapsed=(perf_counter()-tick)*1000
            self.metrics.update(last_commit_ms=elapsed,max_commit_ms=max(elapsed,self.metrics['max_commit_ms']))
            return dict(acknowledgment='validated-shutdown-health-commit',service_sequence=self.sequence)
        record_count = len(candidate.books)+len(candidate.metadata)+sum(len(r) for r in aggregate_records.values())+sum(len(c['events'])+len(c['markets']) for c in candidate.inventory.values())
        if record_count > self.config['ingress_records']:
            raise ValueError('Current retained record capacity')
        retained = len(packed(dict(inventory=candidate.inventory, books={str(k):v for k,v in candidate.books.items()},
                                  metadata={str(k):v for k,v in candidate.metadata.items()},aggregate=aggregate_records)))
        if retained > 16*1024*1024:
            raise ValueError('Current reducer retained capacity')
        records, excluded = normalized_records(candidate, states, self.revisions)
        # Exact dated proof readers retain their sealed projection semantics.
        # The ordinary reusable path below has no dependency on those fixtures.
        sealed={r['event']['game_id'] for r in records
                if r['result_policy'].startswith('predict-direct-win-1:')}
        native_records=list(records)
        reference_records=[]
        for sport,batch in aggregate_records.items():
            if sealed:
                from .current_overlap import associate
                from app.comparison.event_links import instant
                batch=associate(native_records,batch,clock=instant(utc()))
            reference_records.extend(r for r in batch if r['quote']['venue']=='pinnacle')
            batch=[r for r in batch if r['quote']['venue']!='pinnacle']
            for record in batch:
                r=dict(record);q=dict(record['quote']);r['quote']=q
                global_state=states[q['venue']]['state']
                state=global_state if global_state in ('stopped','error') else aggregate_states.get(sport,states)[q['venue']]['state']
                q['state']=state if state in ('stopped','error','unavailable') else 'budget_delayed'
                # Admission and native association can change the binding evidence
                # without changing the price. Publish that change coherently too.
                r['_fingerprint']=stable([record['_fingerprint'],q['state'],
                    r['market_identity'],r['orientation_evidence'],q['rule_note']])
                prior=self.revisions.get(r['_instrument'])
                if prior:
                    from app.dashboard.current_contract import stamp
                    old_time=prior['times']['source_at'];new_time=q['times']['source_at']
                    if old_time and (new_time is None or stamp(new_time)<stamp(old_time)):raise ValueError('Aggregate source time regressed')
                    q['revision']=prior['revision']+(r['_fingerprint']!=prior['fingerprint'])
                    if q['original']==prior['original'] and new_time==old_time:
                        q['times']=deepcopy(prior['times'])
                records.append(r)
        resolver=deepcopy(self.occurrence_resolver)
        from .current_overlap import resolve_current
        combined=records+reference_records
        legacy=[r for r in combined if r['event'].get('game_id') in sealed]
        ordinary=[r for r in combined if r['event'].get('game_id') not in sealed]
        joined=legacy+resolve_current(ordinary,clock=utc(),resolver=resolver)
        records=[r for r in joined if r['quote']['venue']!='pinnacle']
        reference_records=[r for r in joined if r['quote']['venue']=='pinnacle']
        from .current_benchmark import attach
        attach(records,reference_records)
        for r in records:
            prior=self.revisions.get(r['_instrument'])
            if prior and (r['quote'].get('sharp_reference')!=prior.get('sharp_reference') or
                          r['quote'].get('occurrence_link')!=prior.get('occurrence_link') or
                          r['verified']!=prior.get('binding_verified')):
                r['quote']['revision']=max(r['quote']['revision'],prior['revision']+1)
        revisions = {r.pop('_instrument'): dict(fingerprint=r.pop('_fingerprint'), revision=r['quote']['revision'], times=deepcopy(r['quote']['times']),
            original=deepcopy(r['quote']['original']),source=r['quote']['venue'],sharp_reference=deepcopy(r['quote'].get('sharp_reference')),
            occurrence_link=deepcopy(r['quote'].get('occurrence_link')),binding_verified=r['verified']) for r in records}
        raw = deepcopy(self.envelope)
        raw.update(state_revision=self.store._state['state_revision']+1, clock_at=utc(), projected_at=utc(),
                   source_status=deepcopy(states), state='available' if records else 'degraded' if any(s['state']=='error' for s in states.values()) else 'empty')
        raw = catalog_from_normalized(raw, records, reference_records=reference_records)
        encoded = len(packed(raw))
        if not self.store.commit(raw):
            raise ValueError('Current commit sequence rejected')
        self.reducer, self.revisions, self.exclusions = candidate, revisions, excluded
        self.occurrence_resolver=resolver
        self.aggregate_records,self.aggregate_receipts,self.aggregate_states=aggregate_records,aggregate_receipts,aggregate_states
        self.associated_cache=associated_cache
        self.sequence += 1
        elapsed = (perf_counter()-tick)*1000
        self.metrics.update(admitted_records=len(records),identity_excluded_records=len(excluded),last_commit_ms=elapsed, max_commit_ms=max(elapsed, self.metrics['max_commit_ms']),
            retained_bytes=retained, max_transient_encoded_bytes=max(self.metrics['max_transient_encoded_bytes'], 2*retained+3*encoded))
        return dict(acknowledgment=self.acknowledgment, service_sequence=self.sequence)
