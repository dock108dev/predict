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


def normalized_records(projection, states, previous):
    from app.comparison.event_links import current_event_key as event_key, provider_key
    from .v1_comparison import predicates
    records = []
    excluded = []
    for venue, cat in sorted(projection.inventory.items()):
        if venue in ('kalshi','polymarket_us'):
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
                if reason or binding['status'] != 'BOUND_RAW_PREDICATE':
                    raise ValueError('Native identity or predicate incomplete')
                event=deepcopy(event)
                roles=event.get('source_participant_roles',{})
                for role in ('home','away'):
                    if event.get(role) is None and roles.get(role) is not None:event[role]=roles[role]
                event_scope=None
                try:key = event_key(event)
                except (ValueError,KeyError):
                    if any(not event.get(k) for k in ('season','stage','scheduled_start','home','away')) or event['home']==event['away'] or set(event['participants'].values())!={event['home'],event['away']}:
                        raise ValueError('Complete source-local event identity unavailable')
                    event_scope=dict(policy='native-event-unverified-2',source=venue,native_event_id=event['id'])
                    key=provider_key(venue,event)
                ident = binding['identity']
                if ident['period'] != 'full_game' or ident['family'] not in ('moneyline', 'spread', 'total'):
                    raise ValueError('Outside common full-game scope')
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
                    anchor = fact['participant']
                native_predicates=list(predicates(binding))
                selections={}
                for native,predicate,meaning in native_predicates:
                    participant=meaning['participant'];kind=meaning['predicate'];signed=None
                    if fact:
                        op=meaning['operator']
                        if op not in ('gt','le','lt','ge') or abs(Decimal(canonical_line)%1)!=Decimal('.5'):raise ValueError('Exact score outcome requires supported half-point orientation')
                        if ident['family']=='total':
                            if op not in ('gt','le'):raise ValueError('Unsupported combined-score direction')
                            participant=None;kind='over' if op=='gt' else 'under';signed=canonical_line
                        else:
                            participant=event['home'] if op in ('gt','ge') else event['away']
                            kind='cover';signed=canonical_line if participant==anchor else str(-Decimal(canonical_line))
                    name=next((n for n,cid in event['participants'].items() if cid==participant),None)
                    selections[native]=dict(participant=participant,predicate=kind,signed_line=signed,
                        label=kind.capitalize() if name is None else name+(' does not win' if kind=='not_win' else ''))
                for native, predicate, meaning in native_predicates:
                    ladder = ladders.get(native)
                    if not ladder or not ladder['asks']:
                        continue
                    selection=selections[native]
                    participant=selection['participant'];kind=selection['predicate'];signed=selection['signed_line']
                    levels = sorted(ladder['asks']['levels'], key=lambda x: Decimal(x['price']['value']))
                    if not levels:continue  # known empty side remains an outcome without a price
                    if len(levels) > 4096 or any(Decimal(l['quantity']['value']) <= 0 for l in levels):
                        raise ValueError('Invalid bounded book depth')
                    value = str(levels[0]['price']['value'])
                    side = sides[native]
                    original = dict(value=value, units='usd_per_contract', payout='1', payout_units='USD',
                                    quantity_units='contracts', role='comparison')
                    # The reused purchase_book conversion supplies the original
                    # opposite bid and preserves native liquidity independently.
                    if venue=='kalshi' or venue == 'polymarket_us' and side.get('role') == 'Short':
                        with localcontext() as ctx:
                            ctx.prec=600
                            original.update(native_value=str(Decimal(1)-Decimal(value)), native_units='usd_per_contract', transformation='one_minus_native_bid')
                    state = 'resyncing' if (venue, market['event_id'], market['id']) in projection.invalid else states[venue]['state']
                    source = dict(provider=venue, native_event_id=event['id'], native_market_id=market['id'],
                        native_outcome_id=native, native_side=side.get('role') or native,
                        binding_id=stable([venue, event['id'], market['id'], native, predicate]),
                        binding_version=binding['version'], native_line=market.get('line'), quote_side='buy')
                    q = dict(id='', revision=1, venue=venue, source=source, original=original,
                        times=dict(source_at=book['raw'].get('exchange_at'), received_at=book['raw']['received_at'],
                                   projected_at=utc(), source_time_kind='provider_book' if book['raw'].get('exchange_at') else 'unknown'),
                        state=state if state != 'connecting' else 'resyncing',
                        rule_note='Native predicate reviewed; exceptional settlement and costs remain unqualified.',
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
                        period_boundary='All regulation and applicable overtime; exceptional payouts separately unqualified',
                        anchor_participant=anchor, selection=selection, quote=q,
                        orientation_evidence=[binding['version']+':'+binding['sha256']], verified=event_scope is None,
                        outcome_cardinality=2, outcome_selections=list(selections.values()),
                        result_policy='native-'+ident['family']+'-normal-predicate-1:'+stable([p for _,p,_ in native_predicates]))
                    from .current_occurrence import direct, VERSION as DIRECT_VERSION
                    if event_scope is None and direct(normalized, market, native, selection):
                        if market['direct_win_binding'].get('prospective_only'):
                            # Only the reviewed direct-win instrument shares this
                            # reference basis. An unreviewed Short stays separate.
                            normalized['market_identity']['rules']=DIRECT_VERSION+':prospective-reviewed-direct-win'
                        normalized['result_policy']=DIRECT_VERSION+':normal-full-game-win'
                        normalized['period_boundary']='Full game including applicable overtime; direct win only; exceptional cashflows differ'
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
                        rules_primary=binding.get('settlement',{}).get('native_clauses',{}).get('rules_primary'),
                        rules_secondary=binding.get('settlement',{}).get('native_clauses',{}).get('rules_secondary'),
                        series_id=event_material.get('series_ticker'),
                        phase=('pregame' if event_material.get('period')=='NS' and event_material.get('active') is True and event_material.get('closed') is False else
                               'live' if event_material.get('live') is True and event_material.get('ended') is False else 'unknown'))
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
                    instrument = stable([source, selection, key])
                    # Metadata changes invalidate the shared input dependency
                    # revision. They do not manufacture a quote/price revision.
                    fingerprint = stable([{k: q[k] for k in ('source', 'original', 'state', 'rule_note', 'cost_note', 'depth', 'freshness_policy')},binding['sha256'],q.get('native_predicate')])
                    prior = previous.get(instrument)
                    if prior:
                        q['revision'] = prior['revision'] + (fingerprint != prior['fingerprint'])
                        if fingerprint == prior['fingerprint'] or q['original']==prior.get('original'):
                            q['times'] = deepcopy(prior['times'])
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
        if len(packed({k:v.decode() if isinstance(v,bytes) else v for k,v in row.items()})) > self.config['ingress_bytes']:
            raise ValueError('Current ingress observation capacity')
        tick = perf_counter()
        if row['type'] in ('prediction_book','prediction_books','source_health','current_aggregate'):
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
        if row['type']=='current_aggregate':
            from .current_aggregate_admission import admit_venues, admit
            sport=row['sport']
            aggregate_states[sport]=deepcopy(row.get('venue_states',states))
            if aggregate_receipts.get(sport) and row['received_at']<=aggregate_receipts[sport]:
                raise ValueError('Stale aggregate response')
            accepted,rejected=admit_venues(row['body'],sport,row['received_at'])
            if len(rejected)==2:raise ValueError('Malformed aggregate response')
            prior=aggregate_records.get(sport,[])
            aggregate_records[sport]=[r for r in prior if r['quote']['venue'] in rejected]+[r for batch in accepted.values() for r in batch]
            try:references=admit(row['body'],sport,row['received_at'],venue='pinnacle')
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
            aggregate_receipts[sport]=row['received_at']
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
            if observation['type']!='current_aggregate':candidate.reduce_observation(observation)
        record_count = len(candidate.books)+len(candidate.metadata)+sum(len(r) for r in aggregate_records.values())+sum(len(c['events'])+len(c['markets']) for c in candidate.inventory.values())
        if record_count > self.config['ingress_records']:
            raise ValueError('Current retained record capacity')
        retained = len(packed(dict(inventory=candidate.inventory, books={str(k):v for k,v in candidate.books.items()},
                                  metadata={str(k):v for k,v in candidate.metadata.items()},aggregate=aggregate_records)))
        if retained > 16*1024*1024:
            raise ValueError('Current reducer retained capacity')
        records, excluded = normalized_records(candidate, states, self.revisions)
        from .current_overlap import associate
        native_records=list(records)
        reference_records=[]
        native_signature=stable([[r['event'],r['market_identity'],r['orientation_evidence'],r['result_policy'],r['quote']['source']] for r in native_records])
        for sport,batch in aggregate_records.items():
            signature=stable([native_signature,aggregate_receipts.get(sport),
                {v:[states[v]['state'],aggregate_states.get(sport,states)[v]['state']] for v in ('novig','prophetx')}])
            cached=associated_cache.get(sport)
            if cached and cached[0]==signature:batch=cached[1]
            else:
                batch=associate(native_records,batch)
                associated_cache[sport]=(signature,batch)
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
        from .current_benchmark import attach
        attach(records,reference_records)
        for r in records:
            prior=self.revisions.get(r['_instrument'])
            if prior and r['quote'].get('sharp_reference')!=prior.get('sharp_reference'):
                r['quote']['revision']=max(r['quote']['revision'],prior['revision']+1)
        revisions = {r.pop('_instrument'): dict(fingerprint=r.pop('_fingerprint'), revision=r['quote']['revision'], times=deepcopy(r['quote']['times']),
            original=deepcopy(r['quote']['original']),source=r['quote']['venue'],sharp_reference=deepcopy(r['quote'].get('sharp_reference'))) for r in records}
        raw = deepcopy(self.envelope)
        raw.update(state_revision=self.store._state['state_revision']+1, clock_at=utc(), projected_at=utc(),
                   source_status=deepcopy(states), state='available' if records else 'degraded' if any(s['state']=='error' for s in states.values()) else 'empty')
        raw = catalog_from_normalized(raw, records, reference_records=reference_records)
        encoded = len(packed(raw))
        if not self.store.commit(raw):
            raise ValueError('Current commit sequence rejected')
        self.reducer, self.revisions, self.exclusions = candidate, revisions, excluded
        self.aggregate_records,self.aggregate_receipts,self.aggregate_states=aggregate_records,aggregate_receipts,aggregate_states
        self.associated_cache=associated_cache
        self.sequence += 1
        elapsed = (perf_counter()-tick)*1000
        self.metrics.update(admitted_records=len(records),identity_excluded_records=len(excluded),last_commit_ms=elapsed, max_commit_ms=max(elapsed, self.metrics['max_commit_ms']),
            retained_bytes=retained, max_transient_encoded_bytes=max(self.metrics['max_transient_encoded_bytes'], 2*retained+3*encoded))
        return dict(acknowledgment=self.acknowledgment, service_sequence=self.sequence)
