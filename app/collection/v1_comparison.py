"""Versioned manual-trading admission. Payoff qualification stays independent.

Only exact evidenced identities/predicates enter raw comparison. Missing fees,
positions, probabilities and exceptional payouts never erase those predicates.
This policy is opt-in so original retained projections stay reproducible.
"""
from copy import deepcopy
from decimal import Decimal
from app.dashboard.session_projection import stable, stamp

POLICY = 'manual-comparison-1'
REPAIR_POLICY = 'manual-comparison-2'


def us_selectors(cell, game_id=None):
    from .public_contracts import load
    keys = sorted(k for k, r in load()['us_types'].items()
                  if cell['sport'] in r['competitions'] and r['period'] == cell['period']
                  and r['family'] == cell['family'])
    # A coarse documented FUTURE filter locates records, never an award identity.
    if cell['family'] == 'futures': keys = ['SPORTS_MARKET_TYPE_FUTURE']
    return [dict(path='/v1/markets', params=dict(sportsMarketTypes=k,
                 **({'gameId':str(game_id)} if game_id is not None else {}))) for k in keys]


def _bind_v1(event, market, venue, *, revised=False):
    """A predicate binding may exist without a counterpart or a current quote."""
    from .public_contracts import award_identity, event_identity, us_type
    native = market.get('_native') or market.get('native_metadata') or {}
    scope = market.get('native_scope_binding')
    result = dict(version=POLICY, source=venue, event_id=market['event_id'], market_id=market['id'],
                  native_metadata_sha256=stable(native), predicate=None, identity=None, blockers=[],
                  settlement=dict(status='UNKNOWN', terms=deepcopy(market.get('terms',{})),
                                  native_clauses={k:deepcopy(native[k]) for k in ('rules_primary','rules_secondary','description','resolutionCriteria','settlementSource') if k in native},
                                  reason='Raw predicate correspondence does not establish identical payout treatment'),
                  net=None, ev=None, collection_authorized=False)
    if venue == 'kalshi' and market.get('market_type')=='moneyline' and market.get('period')=='full_game':
        from app.normalization.native_registry import native_registry
        team=native.get('yes_sub_title'); text=native.get('rules_primary','')
        resolved=native_registry(live=True).resolve('team',team,league=event.get('competition'),venue=venue)
        if resolved.status=='resolved' and text.startswith('If '+str(team)+' wins ') and text.endswith(', then the market resolves to Yes.'):
            result['predicate']=[dict(native_id='yes',participant=resolved.canonical_id,predicate='win'),
                                 dict(native_id='no',participant=resolved.canonical_id,predicate='not_win')]
        else: result['blockers'].append('Exact full-game native winner literal unavailable')
    elif venue == 'kalshi' and scope:
        from .native_score_binding import bind as score
        fact = score(native, scope, revised=revised)
        if scope['family'] == 'futures':
            try:
                award = award_identity(native, scope)
                result['award_binding'] = award
                if award['association'] and award['participant'] is None:
                    entrant=award_entrant(native,award)
                    if entrant:
                        award=deepcopy(award);award['participant']=entrant['canonical_id']
                        result['award_binding']=award;result['entrant_enrichment']=entrant
                if not award['association'] or not award['participant']:
                    raise ValueError('Exact award/season/entrant crosswalk unavailable')
                if award['field'] and award['participant'] not in award['field']:raise ValueError('Award entrant is outside documented field')
                a = award['association']
                result['identity'] = dict(competition=scope['sport'], season=award['season'], stage='championship',
                    period='season', family='futures', category=scope['category'], conference_id=scope['conference_id'],
                    award=award['predicate']['source_award'], event=[scope['sport'],award['season'],scope['category'],scope['conference_id'],award['predicate']['source_award']],
                    scheduled_start=a['expected_expiration_time'])
                result['predicate'] = ['wins_award',award['participant']]
                result['settlement']['reason'] += '; field revisions and exceptional payouts remain unknown'
            except (ValueError, KeyError) as exc: result['blockers'].append(str(exc))
        elif fact and fact.get('participant') is not None:
            result['source_predicate'] = fact
            result['predicate'] = [fact['participant'],fact['line'],fact['outcomes']]
        else: result['blockers'].append('Exact literal score/outcome predicate or canonical participant unavailable')
    elif venue == 'polymarket_us':
        locator = us_type(native,competition=event.get('competition'))
        result['locator'] = locator
        if locator['status'] != 'DOCUMENTED_LOCATOR': result['blockers'].append(locator['reason'])
        elif locator['family'] != 'moneyline' or revised and locator['period']=='first_half':
            from .admission_enrichment import us_score
            fact=us_score(native,locator,event) if revised else None
            if fact:
                result['source_predicate']=fact;result['predicate']=[fact['participant'],fact['line'],fact['outcomes']]
            else:result['blockers'].append('Exact signed line, native side inequality and combined/team total scope unavailable')
    if result['identity'] is None:
        participants = list(set(event.get('participants',{}).values()))
        if None not in participants:participants.sort()
        if len(participants)!=2 or None in participants or event.get('identity')!='resolved':
            result['blockers'].append('Exact distinct canonical participants unavailable')
        start=event.get('scheduled_start'); season=event.get('season'); stage=event.get('stage')
        if start and len(participants)==2 and None not in participants:
            public=event_identity(source=venue,event_id=event['id'],competition=event.get('competition'),
                participants=participants,scheduled_start=start,provider_season=season,provider_stage=stage)
            if public.get('enrichment'):
                result['public_identity']=public
                if season is not None and season!=public['enrichment']['season'] or stage is not None and stage!=public['enrichment']['stage']:
                    result['blockers'].append('Explicit provider season/stage conflicts with authoritative event crosswalk')
                season=public['enrichment']['season'];stage=public['enrichment']['stage']
        if not start or not season or not stage:
            missing=[k for k,v in [('schedule',start),('season',season),('stage',stage)] if not v]
            result['blockers'].append('Exact game identity facts unavailable: '+', '.join(missing) if revised else 'Exact schedule, sport season and stage unavailable')
        if event.get('competition')=='MLB':
            required=('game_id','game_number','original_start','schedule_status')
            if any(event.get(k) is None for k in required):
                missing=[k for k in required if event.get(k) is None]
                result['blockers'].append('Exact MLB game/number/original/rescheduled identity unavailable'+(': '+', '.join(missing) if revised else ''))
            else:
                from app.normalization.comparison_identity import baseball
                try:baseball(event)
                except (ValueError,KeyError,TypeError):result['blockers'].append('Conflicting or incomplete exact MLB occurrence/home/away identity')
        result['identity']=dict(competition=event.get('competition'),season=season,stage=stage,
            period=result.get('locator',{}).get('period',market.get('period')),family=result.get('locator',{}).get('family',market.get('market_type')),category=market.get('category'),
            event=event.get('canonical_key'),participants=participants,scheduled_start=start,line=result.get('source_predicate',{}).get('line',market.get('line')),
            game_identity={k:event.get(k) for k in ('game_id','game_number','original_start','schedule_status')})
        if venue=='polymarket_us' and result.get('locator',{}).get('family')=='moneyline' and not result.get('source_predicate'):
            sides=native.get('marketSides',[])
            mapped=[]
            for side in sides:
                team=(side.get('team') or {}).get('name')
                participant=event.get('participants',{}).get(team)
                if revised:
                    from .admission_enrichment import resolve_team
                    participant=resolve_team(side.get('team') or {},event.get('competition'),venue)
                if participant is None or type(side.get('long')) is not bool or str(side.get('marketId'))!=market['id']:
                    mapped=[];break
                mapped.append(dict(native_id=str(side['id']),participant=participant,predicate='win',native_direction='long' if side['long'] else 'short'))
            if len(mapped)==2 and {s['participant'] for s in mapped}==set(participants):result['predicate']=mapped
            else:result['blockers'].append('Exact US Long/Short outcome orientation unavailable')
    if isinstance(result['predicate'],list) and result['predicate'] and isinstance(result['predicate'][0],dict):
        if any(s['participant'] not in event.get('participants',{}).values() for s in result['predicate']):
            result['blockers'].append('Native winner participant is outside event')
    if result.get('source_predicate') and result['identity']['family'] in ('spread','moneyline'):
        roles=event.get('source_participant_roles') or {k:event.get(k) for k in ('home','away')}
        if set(roles)!={'home','away'} or None in roles.values() or set(roles.values())!=set(event.get('participants',{}).values()):
            result['blockers'].append('Exact home/away roles for score predicate unavailable')
        else:result['identity']['roles']=roles
    if result['predicate'] is None and not result['blockers']:result['blockers'].append('Exact outcome predicate unavailable')
    if market.get('conflicting_duplicate') or event.get('conflicting_duplicate'):result['blockers'].append('Conflicting duplicate native identity')
    result['status']='BOUND_RAW_PREDICATE' if not result['blockers'] else 'IDENTITY_BLOCKED'
    result['sha256']=stable(result)
    return result


def bind(event,market,venue,*,policy=POLICY):
    if policy==POLICY:return _bind_v1(event,market,venue)
    if policy!=REPAIR_POLICY:raise ValueError('Unknown manual admission policy')
    from .admission_enrichment import enrich_game,award
    if market.get('market_type')=='futures' or (market.get('native_scope_binding') or {}).get('family')=='futures':return award(event,market,venue)
    e=enrich_game(dict(event,source=venue));r=_bind_v1(e,market,venue,revised=True)
    if e.get('identity_conflicts'):
        r['blockers']+=list(e['identity_conflicts']);r['status']='IDENTITY_BLOCKED'
    r['version']=policy;r['sha256']=stable({k:v for k,v in r.items() if k!='sha256'});return r


def annotate(catalog, venue, templates=(), *, policy=POLICY):
    """Attach separately versioned bindings; admission clears only payout gates."""
    events={e['id']:e for e in catalog['events']}
    for market in catalog['markets']:
        event=events.get(market['event_id'])
        if not event:continue
        # Reuse exact reviewed event identity, never unrelated event/capture titles.
        enriched=deepcopy(event)
        if policy==REPAIR_POLICY and market.get('market_type')!='futures' and (market.get('native_scope_binding') or {}).get('family')!='futures':
            from .admission_enrichment import enrich_game
            enriched=enrich_game(dict(enriched,source=venue))
            event.update({k:v for k,v in enriched.items() if k not in ('_native','provenance')})
        for review in templates:
            source=review['sources'].get(venue,{})
            if source.get('event_id') in (event['id'],event.get('related_game_event_id')) and review.get('event')==event.get('canonical_key'):
                ident=review['identity']
                if any(event.get(k) is not None and event[k]!=ident[k] for k in ('season','stage')):
                    enriched['conflicting_duplicate']=True
                enriched.update(season=ident['season'],stage=ident['stage'])
                enriched.update({k:v for k,v in review.get('normalized_event',{}).items()
                                 if k in ('game_id','game_number','original_start','schedule_status')})
        if venue=='polymarket_us':
            from .public_contracts import us_type
            locator=us_type(market.get('_native') or market.get('native_metadata') or {},competition=enriched.get('competition'))
            if locator['status']=='DOCUMENTED_LOCATOR':
                market.update(market_type=locator['family'],period=locator['period'])
        binding=bind(enriched,market,venue,policy=policy);market['v1_raw_binding']=binding
        if binding['status']=='BOUND_RAW_PREDICATE' and binding['identity']['family']=='futures':
            event.update(identity='resolved',competition=binding['identity']['competition'],season=binding['identity']['season'],stage='championship',
                scheduled_start=binding['identity']['scheduled_start'],canonical_key=binding['identity']['event'])
            if event.get('exclusion') in ('unknown_schedule','event_parse_error'):event['exclusion']=None
        if policy==REPAIR_POLICY and venue=='polymarket_us' and binding['status']=='BOUND_RAW_PREDICATE' and market.get('subscription_evidence_exclusion')=='unresolved_native_sides':
            native=market.get('_native') or market.get('native_metadata') or {}
            sides=native.get('marketSides',[])
            exact_ids={n for n,p,s in predicates(binding)}
            if (len(sides)==2 and len(exact_ids)==2 and {str(s.get('id')) for s in sides}==exact_ids
                and all(type(s.get('long')) is bool and str(s.get('marketId'))==market['id'] for s in sides)
                and {s['long'] for s in sides}=={True,False}):
                market['subscription_evidence_exclusion']=None
                market['subscription_evidence_basis']='Exact admitted native predicate sides and Long/Short roles; score predicates do not require each side to be a team'
        if binding['status']=='BOUND_RAW_PREDICATE' and market.get('exclusion') in (
                'native_scope_effective_descriptor_facts_missing','native_scope_predicate_review_required','unsupported_market_type_or_period'):
            market['qualified_exclusion']=market['exclusion'];market['exclusion']=None
    return catalog


def admission(binding, book, at, *, connected=True):
    """Quote/state/receipt gates; optional economics inputs are deliberately absent."""
    if binding.get('sha256')!=stable({k:v for k,v in binding.items() if k!='sha256'}):return False,'Raw binding digest conflict'
    if binding['status']!='BOUND_RAW_PREDICATE':return False,'; '.join(binding['blockers'])
    if not book:return False,'Exact selected book unavailable'
    raw=book['raw']
    if raw['ref']!={'venue':binding['source'],'event_id':binding['event_id'],'market_id':binding['market_id']}:
        return False,'Book instrument identity conflict'
    if book.get('state')!='active' or book.get('sync')!='synchronized' or not connected:
        return False,'Inactive, disconnected or unsynchronized book'
    if raw.get('exchange_at'):
        source_age=(stamp(at)-stamp(raw['exchange_at'])).total_seconds()
        if not 0<=source_age<=15:return False,'Stale or future source timestamp'
    age=Decimal(str((stamp(at)-stamp(raw['received_at'])).total_seconds()))
    if not 0<=age<=15:return False,'Stale or future receipt'
    if not binding['identity'].get('scheduled_start'):return False,'Exact game start or award deadline unavailable'
    if stamp(at)>=stamp(binding['identity']['scheduled_start']):return False,'Scheduled start/deadline reached'
    return True,None


def predicates(binding):
    """Canonical predicate keys without calling the payoff/state-space engine."""
    fact=binding.get('source_predicate');ident=binding['identity']
    if fact:
        domain='combined_score' if fact['family']=='total' else 'home_margin'
        roles=ident.get('roles',{});home=roles.get('home')
        threshold=Decimal(fact['line']) if domain=='combined_score' else -Decimal(fact['line']) if fact['participant']==home else Decimal(fact['line'])
        for side in fact['outcomes']:
            op=side['operator']
            if domain=='home_margin' and fact['participant'] not in ('tie',home):op={'gt':'lt','le':'ge','eq':'eq','ne':'ne'}[op]
            yield side['native_id'],[domain,str(threshold.normalize()),op],dict(participant=fact['participant'],predicate='score',operator=op)
    elif isinstance(binding['predicate'],list) and binding['predicate'] and isinstance(binding['predicate'][0],dict):
        for side in binding['predicate']:
            # NO stays not_win; a tie exception is never silently complemented.
            yield side['native_id'],[side['predicate'],side['participant']],side
    elif ident['family']=='futures':
        for side,op in [('yes','wins_award'),('no','does_not_win_award')]:
            yield side,[op,binding['predicate'][1]],dict(participant=binding['predicate'][1],predicate=op)


def connect(projection,snapshot,at):
    """Ordinary projection extension; only its own catalog/books can form pairs."""
    from collections import defaultdict
    from app.dashboard.session_projection import format_book
    from app.opportunities.board import contracts
    from itertools import combinations
    groups=defaultdict(list);snapshot['manual_comparisons']=[];snapshot['manual_comparison_exclusions']=[]
    used={(v,ids['market_id']) for g in snapshot['games'] for v,ids in g['sources'].items()}
    for venue in ('kalshi','polymarket_us'):
        cat=deepcopy(projection.inventory.get(venue,dict(events=[],markets=[])))
        annotate(cat,venue,projection.spec.get('native_review_records',[]),policy=projection.spec.get('v1_comparison_policy',POLICY))
        events={e['id']:e for e in cat['events']}
        for market in cat['markets']:
            binding=market.get('v1_raw_binding');event=events.get(market['event_id'])
            if not binding or not event:continue
            key=(venue,event['id'],market['id']);row=projection.books.get(key)
            health=projection.health.get(key,{}).get('state')
            valid,reason=admission(binding,row['book'] if row else None,at,connected=health=='connected' or snapshot['view_mode']!='current')
            if event.get('exclusion') or market.get('exclusion') or key in projection.invalid or key in projection.safety.get(venue,{}):
                valid=False;reason=event.get('exclusion') or market.get('exclusion') or 'Invalidated native observation'
            if not valid:
                if len(snapshot['manual_comparison_exclusions'])<128:snapshot['manual_comparison_exclusions'].append(dict(source=venue,market_id=market['id'],reason=reason))
                continue
            sides={venue+':'+n:dict(s,native_id=n) for n,p,s in predicates(binding)}
            if venue=='polymarket_us' and any(o['asks'] is None for o in row['book']['outcomes']):
                from .native_semantics import purchase_saved_book
                row=purchase_saved_book(row,{n:s for n,p,s in predicates(binding)})
            formatted=format_book(row,{venue:{n:(s['participant'],n) for n,p,s in predicates(binding)}})
            age=str((stamp(at)-stamp(row['book']['raw']['received_at'])).total_seconds())
            game=dict(sides=sides,teams=list(event.get('participants',{}).values()))
            point=dict(cards=[dict(venue=venue,label={'kalshi':'Kalshi','polymarket_us':'Polymarket US'}[venue],book=formatted,connection=health,age_seconds=age,receipt_stale=False)])
            cs=contracts(point,game)
            ident=binding['identity'];event_key={k:v for k,v in ident.items() if k not in ('line','roles')}
            for n,p,s in predicates(binding):
                leg=cs[venue+':'+n]
                if leg['ask'] is None:continue
                leg.update(native_identity=dict(event_id=event['id'],market_id=market['id']),native_outcome=s,
                    market_state=row['book']['state'],status='recent receipt',source_age_seconds=None,url=None,
                    depth_limit='Retained advertised levels; informational size only',
                    provenance=dict(response=binding['sha256'],registry_sha256=None),
                    entry=dict(lower=None,upper=None,net=None,notional=None,quantity='100',reason='Scoped fee inputs unavailable',basis='Depth notional only; fees/payouts separate'))
                if leg.get('source_at'):
                    leg['source_age_seconds']=str((stamp(at)-stamp(leg['source_at'])).total_seconds())
                else:leg['warnings'].append('Source time unknown; receipt does not establish newly priced input')
                from .counterparts import key as counterpart_key
                groups[counterpart_key(binding,p)].append((binding,leg,p,event))
    # Source-scoped aggregate prices can join exact native predicates without
    # requiring native execution accounts or a complete payout state table.
    from app.reference.source_correspondence import _aggregate_leg, _aggregate_predicate
    for token,values in list(groups.items()):
        original=values[0];ident=original[0]['identity']
        if ident['family']=='futures':continue
        native_roles=ident.get('roles') or original[3].get('source_participant_roles') or {k:original[3].get(k) for k in ('home','away')}
        for record in projection.aggregates.values():
            raw=record['original'];ai=record['identity'];participants=ai['event'][-1]
            if raw['bookmaker'] not in ('novig','prophetx') or record['reasons'] or record['price_issue']:continue
            if (ai['competition'],ai['period'],ai['family'])!=(ident['competition'],ident['period'],ident['family']):continue
            if stamp(raw['scheduled_start'])!=stamp(ident['scheduled_start']) or set(participants.values())!=set(ident.get('participants',[])):continue
            if ident['competition']=='MLB':
                from app.normalization.comparison_identity import baseball
                try:
                    native_event=dict(original[3],**ident['game_identity'])
                    if baseball(native_event)!=baseball(raw.get('v1_event_identity',{})):continue
                except (ValueError,KeyError,TypeError):continue
            if not 0<=(stamp(at)-stamp(raw['received_at'])).total_seconds()<=15:continue
            try:
                if ident['family']=='moneyline' and ident['period']=='full_game':predicate=['win',record['participant']]
                else:
                    canonical=_aggregate_predicate(record,participants,dict(normalized_event=native_roles))
                    predicate=[canonical[0],canonical[3],canonical[4]]
                if predicate!=original[2]:continue
            except (ValueError,KeyError,TypeError,ArithmeticError):continue
            leg=_aggregate_leg(record);leg['age_seconds']=str((stamp(at)-stamp(leg['received_at'])).total_seconds())
            if leg.get('source_at'):
                try:leg['source_age_seconds']=str((stamp(at)-stamp(leg['source_at'])).total_seconds())
                except (ValueError,TypeError):leg['source_age_seconds']=None
                if leg['source_age_seconds'] is None or not 0<=Decimal(leg['source_age_seconds'])<=15:continue
            binding=dict(version=POLICY,source=leg['venue'],identity=ident,aggregate_record=record,settlement=dict(status='UNKNOWN',reason='Aggregate payout/fees/state remain unqualified'))
            groups[token].append((binding,leg,predicate,original[3]))
    combinations_to_build=[]
    for token,values in groups.items():
        by_source={v:[x for x in values if x[1]['venue']==v] for v in sorted({x[1]['venue'] for x in values})}
        unique=[xs[0] for xs in by_source.values() if len(xs)==1]
        for left,right in combinations(unique,2):
            if all(x[1]['venue'] in ('novig','prophetx') for x in (left,right)):continue
            if left[1]['venue'] not in ('kalshi','polymarket_us'):left,right=right,left
            if all((x[1]['venue'],x[1]['native_identity']['market_id']) in used for x in (left,right)):continue
            legs=[left[1],right[1]];skew=abs((stamp(legs[0]['received_at'])-stamp(legs[1]['received_at'])).total_seconds())
            if skew>5:continue
            combinations_to_build.append((stable([token,sorted(by_source_key[1]['venue'] for by_source_key in (left,right))]),left,right,legs,skew))
    for token,left,right,legs,skew in combinations_to_build[:128]:
        gid='manual-'+token;prices=[Decimal(l['ask']) for l in legs];identity=dict(left[0]['identity'],version=5,rules=POLICY)
        binding=dict(version=POLICY,sources=[left[0],right[0]],predicate=left[2],session_id=snapshot['session_id'])
        row=dict(id=gid,game_id=gid,game_title=left[3].get('title'),identity=identity,outcome=outcome_label(left[2],left[3]),event_key=stable(identity['event']),
            session=snapshot['session_id']+'~'+gid,hash=snapshot['session_id'],cutoff=snapshot['durable_cursor'],at=at,contract=legs[0]['id'],candidate='',
            legs=legs,alternatives=[],raw_difference=str(abs(prices[0]-prices[1])),lower_raw='Equal' if prices[0]==prices[1] else legs[prices.index(min(prices))]['label'],
            entry_lower=None,net=None,ev=None,manual_raw=True,aggregated=any(l['venue'] in ('novig','prophetx') for l in legs),manual_binding=binding,manual_units='Native $ per $1 claim versus raw implied odds' if any(l['venue'] in ('novig','prophetx') for l in legs) else 'Native contract prices',
            timing=dict(receipt_skew_seconds=str(skew),receipt_limits_pass=True,synchronized=False,reason='Receipt limits pass; source-clock uncertainty remains visible'),
            settlement_audit=None,settlement_status='UNKNOWN',settlement='Exact predicate only. Native payout clauses and exceptions remain independently unknown or different.',mode=snapshot['data_mode'],historical=snapshot['view_mode']!='current')
        snapshot['manual_comparisons'].append(row)
        snapshot['games'].append(dict(id=gid,title=row['game_title'],scheduled_start=identity['scheduled_start'],aggregated=row['aggregated'],manual_raw=True,product_identity=identity,sides={},sources={l['venue']:l['native_identity'] for l in legs},teams=list(left[3].get('participants',{}).values()),candidates=[]))
        snapshot['points'][gid]=dict(id=snapshot['durable_cursor'],at=at,cards=[],label='Manual raw comparison')
        snapshot['rows_by_game'][gid]=[binding]


def comparisons(snapshot,query):
    rows=[]
    for row in snapshot.get('manual_comparisons',[]):
        if any(query.get(k) and row['identity'].get(k)!=query[k] for k in ('competition','season','period','family')):continue
        if query.get('search','').lower() not in row['game_title'].lower():continue
        if query.get('venue') and not set(query['venue'].split('+'))<={l['venue'] for l in row['legs']}:continue
        if query.get('positive')=='true':continue
        if query.get('freshness')=='usable' and (row['aggregated'] or not all(l['source_age_seconds'] is not None and 0<=Decimal(l['source_age_seconds'])<=15 for l in row['legs'])):continue
        value=deepcopy(row)
        for leg in value['legs']:leg['entry']['quantity']=query.get('quantity','100')
        rows.append(value)
    return rows


def size_report(snapshot,game,options):
    """Informational depth walk only, using the shared depth consumer."""
    if any(l['venue'] in ('novig','prophetx') for r in snapshot['manual_comparisons'] if r['game_id']==game['id'] for l in r['legs']):
        raise ValueError('Aggregate quantity and depth unavailable; native depth is informational only')
    from app.dashboard.decision_support import sizes
    from app.depth import consume
    rows=[r for r in snapshot['manual_comparisons'] if r['game_id']==game['id']]
    results=[]
    for quantity in sizes(options.get('sizes',['1','10','100'])):
        legs=[]
        for row in rows:
            for leg in row['legs']:
                value=dict(venue=leg['venue'],quantity=str(quantity),notional=None,net=None,fee=None)
                try:
                    fills=consume(leg['levels'],str(quantity))
                    value.update(fills=fills,notional=str(sum(Decimal(f['price'])*Decimal(f['quantity']) for f in fills)),reason=None)
                except (ValueError,ArithmeticError) as exc:value['reason']=str(exc)
                legs.append(value)
        results.append(dict(quantity=str(quantity),legs=legs,candidates=[],limitation='Informational retained depth; fill availability, complete costs and payout unknown'))
    return dict(version=POLICY,session=options['session'],hash=options['hash'],cutoff=options['cutoff'],sizes=results,
                best=None,ceiling=options.get('ceiling'),mode=snapshot['data_mode'],historical=snapshot['view_mode']!='current',
                search='Supplied sizes only; raw same-outcome alternatives cannot be added as a hedge')


def outcome_label(predicate,event):
    from app.normalization.native_registry import native_registry
    reg=native_registry(live=True)
    def name(cid):return reg.entities.get(cid,{}).get('name',cid)
    if predicate[0] in ('win','not_win','wins_award','does_not_win_award'):
        return name(predicate[1])+' '+{'win':'wins','not_win':'does not win','wins_award':'wins the award','does_not_win_award':'does not win the award'}[predicate[0]]
    subject='Combined score' if predicate[0]=='combined_score' else name((event.get('source_participant_roles') or {}).get('home',event.get('home','Home team')))+' margin'
    return subject+' '+{'gt':'>','ge':'>=','lt':'<','le':'<=','eq':'=','ne':'!='}[predicate[2]]+' '+predicate[1]


def award_entrant(native,award):
    import json
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'fixtures/manual-award-entrants-v1.json'
    if path.stat().st_size>32768:raise ValueError('Entrant binding byte bound')
    data=json.loads(path.read_text())
    if data.get('version')!='manual-award-entrants-1' or data.get('collection_authorized') is not False or data.get('sha256')!=stable({k:v for k,v in data.items() if k!='sha256'}):
        raise ValueError('Exact entrant binding version/digest conflict')
    matches=[r for r in data['entries'] if r['market_id']==native.get('ticker') and r['native_metadata_sha256']==stable(native)
             and r['native_label']==native.get('yes_sub_title') and r['native_rules_primary']==native.get('rules_primary')
             and r['native_team_id']==native.get('custom_strike',{}).get('football_team') and r['season']==award['season']]
    if len(matches)!=1:return None
    row=matches[0]
    if row['canonical_id'] not in (award.get('field') or []):raise ValueError('Enriched entrant outside documented field')
    return deepcopy(row)
