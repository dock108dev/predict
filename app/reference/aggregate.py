"""Versioned offline aggregate ingestion into the ordinary durable product view.

A response-scoped identity is deliberately not a native contract binding.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from app.dashboard.session_projection import stable, identity
from app.normalization.college_registry import aggregate_registry
from app.reference.product import probability, time, SPORT_KEYS

VERSION = 'odds-aggregate-1'
VENUES = ('novig', 'prophetx')
REFERENCES = ('pinnacle', 'draftkings', 'betmgm')
LIMITATION = ('Historical aggregated odds via The Odds API. 1 / decimal odds is raw implied probability, '
              'not fair probability, model EV or an executable contract price. Fees, settlement, quantity, '
              'execution and provider delay unknown; published bet limits are not available depth.')


def bind(records, registry=None):
    registry = registry or aggregate_registry()
    result = []
    seen = set()
    for raw in records:
        if raw.get('market')=='outrights':
            from .outrights import bind as award_bind
            result.append(award_bind(raw,registry));continue
        rid = stable(raw)
        if rid in seen:
            continue
        seen.add(rid)
        r = deepcopy(raw)
        reasons = []
        book = r.get('bookmaker')
        role = 'aggregated_venue_observation' if book in VENUES else 'bookmaker_reference'
        if book not in VENUES + REFERENCES or r.get('provider') != 'the_odds_api':
            reasons.append('Unsupported provider or bookmaker')
        if r.get('role') != role:
            reasons.append('Source role mismatch')
        sport = r.get('sport')
        participants = {}
        mapping_notes = []
        for field in ('home_team', 'away_team'):
            resolved = registry.resolve('team', r.get(field), league=sport, venue='the_odds_api') if sport in SPORT_KEYS else None
            participants[field] = resolved.canonical_id if resolved else None
            if resolved and resolved.status == 'unknown' and r.get(field) and r.get('source_event_id'):
                # Provider event + home/away slot is an explicit local identity, not
                # a guessed canonical team or a join to another source's event.
                participants[field] = 'the_odds_api:'+str(sport)+':'+r['source_event_id']+':'+field
                mapping_notes.append('Canonical '+field+' unmatched; provider event participant only: '+r[field])
            elif not resolved or resolved.status != 'resolved':
                reasons.append('Unresolved or ambiguous '+field+': '+str(r.get(field)))
        if participants['home_team'] == participants['away_team'] or r.get('home_team') == r.get('away_team'):
            reasons.append('Participants are not distinct')
        for field in ('received_at', 'scheduled_start'):
            try: time(r.get(field))
            except (ValueError, TypeError, AttributeError): reasons.append('Invalid '+field+' timestamp')
        timing_issue = None
        try:
            if time(r.get('source_at')) > time(r['received_at']):
                timing_issue = 'Source timestamp is after receipt; clock semantics unverified'
        except (ValueError, TypeError, AttributeError): timing_issue = 'Missing or invalid source timestamp'
        if not r.get('source_event_id') or not r.get('receipt_sha256'):
            reasons.append('Missing provider event or response identity')
        market = r.get('market')
        from app.reference.odds_bindings import period_binding
        binding = period_binding(sport, market)
        base_market = binding['base'] if binding else market
        period = binding['period'] if binding else 'full_game'
        family = {'h2h':'moneyline','h2h_3_way':'moneyline','spreads':'spread','totals':'total'}.get(base_market) if binding or market in ('h2h','spreads','totals') else None
        if not family or r.get('period', period) != period:
            reasons.append('Unsupported aggregate period or championship binding')
        if binding:
            try:
                if time(r['received_at']) >= time(r['scheduled_start']):
                    reasons.append('Period market not observed pregame')
            except (ValueError, KeyError, TypeError, AttributeError):
                reasons.append('Pregame period timing unverified')
        line = None
        if base_market in ('spreads', 'totals'):
            try:
                value = Decimal(r['point'])
                if not value.is_finite(): raise ValueError()
                # Each spread belongs to its named participant; never flip a sign to force a match.
                line = str(value.normalize())
            except (ValueError, TypeError, ArithmeticError): reasons.append('Invalid line')
        participant = None
        predicate = None
        if base_market == 'totals':
            if r.get('outcome') not in ('Over','Under'): reasons.append('Unsupported total outcome')
            participant = 'total'; predicate = str(r.get('outcome')).lower()
        elif base_market == 'h2h_3_way' and r.get('outcome') == 'Draw':
            participant = 'draw'; predicate = 'draw'
        else:
            matching = [field for field in participants if r.get(field) == r.get('outcome')]
            if len(matching) != 1: reasons.append('Outcome is not an exact event participant')
            else: participant = participants[matching[0]]
            predicate = 'win' if family == 'moneyline' else 'spread'
        try: implied = probability(r['decimal_odds'], 'decimal_odds'); price_issue = None
        except (ValueError, KeyError, TypeError, ArithmeticError):
            implied = None; price_issue = 'Invalid decimal odds; retained as source data only'
        event = dict(id=r.get('source_event_id'), canonical_key=['the_odds_api', sport, r.get('source_event_id'),
                     r.get('scheduled_start'), participants], sport={'NFL':'american_football','NCAAF':'american_football','NBA':'basketball','NCAAB':'basketball','MLB':'baseball','NHL':'ice_hockey'}.get(sport),
                     competition=sport, scheduled_start=r.get('scheduled_start'), season=None)
        ident = identity(event, dict(market_type=family, period=period, line=line,
                         subject=participant if base_market=='spreads' else None, rules_revision='aggregate-settlement-unverified'+(':'+market if binding else '')))
        result.append(dict(id=rid, version='odds-aggregate-period-1' if binding else VERSION, registry_version=registry.version, registry_sha256=registry.fingerprint,
                           original=r, role=role, identity=ident, participant=participant, predicate=predicate,
                           reasons=reasons, mapping_notes=mapping_notes, timing_issue=timing_issue, price_issue=price_issue, implied=implied,
                           response=r.get('receipt_sha256')))
    # A provider event ID must have one identity inside its response, not merely similar names.
    events = defaultdict(set)
    for r in result: events[(r['response'],r['original'].get('source_event_id'))].add(stable(r['identity']['event']))
    for r in result:
        if len(events[(r['response'],r['original'].get('source_event_id'))]) != 1:
            r['reasons'].append('Conflicting identity for provider event ID')
    return result


def augment(snapshot, records):
    """Shared projection extension. Does not supply order books to the net engine."""
    snapshot['aggregate_version'] = VERSION
    groups = defaultdict(list)
    for record in records:
        r = record['original']; ident = record['identity']
        title = (str(r['award_association']['season'])+' '+str(r['award_association']['award']) if r.get('market')=='outrights' else str(r.get('away_team'))+' at '+str(r.get('home_team')))
        reason = '; '.join(record['reasons']) or record['price_issue']
        catalog = dict(source_id=r.get('bookmaker'), market_id=record['id'], title=title, identity=ident,
                       reason=reason, usable=False, received_at=r.get('received_at'), update_path='retained aggregate response',
                       aggregate=dict(id=record['id'],version=record['version'],response=record['response'],mapping_notes=record.get('mapping_notes',[]),original=r))
        if record['role']=='bookmaker_reference':
            snapshot['references'].append(dict(id=record['id'], role='bookmaker_reference', provider_id='the_odds_api',
                origin_id=r.get('bookmaker'), market_identity=ident, participant=record['participant'], predicate=record['predicate'],
                value_kind='raw_implied_probability', value=record['implied'], availability='unqualified',
                conversion_method='1 / decimal odds; no de-vig or fair-probability conversion', original_value=r,
                source_event_id=r.get('source_event_id'), source_at=r.get('source_at'), received_at=r.get('received_at'),
                delay_seconds=None, delay_basis='Unknown source delay', dependency='Betting market input, not independent model',
                provenance=record['response'], mapping=dict(version=record['version'],registry_version=record['registry_version'],registry_sha256=record['registry_sha256'],notes=record.get('mapping_notes',[])), evidence_mode='observation', freshness='historical', reason=reason or LIMITATION))
            continue
        snapshot['market_catalog'].append(catalog)
        if record['reasons']: continue
        key = stable([record['response'], r.get('received_at'), ident, record['participant'], record['predicate']])
        groups[key].append((record, catalog))
    snapshot['aggregate_comparisons'] = []
    for key, values in groups.items():
        books = [r['original']['bookmaker'] for r,c in values]
        if sorted(books) != sorted(VENUES):
            for r,c in values: c['reason'] = c['reason'] or ('Conflicting duplicate book/outcome observations' if len(set(books))!=len(books) else 'Matching ProphetX/Novig outcome and line absent in this response')
            continue
        first = values[0][0]; ident=first['identity']; gid='aggregate-'+key
        title=values[0][1]['title']; at=first['original']['received_at']
        legs=[]; sides={}; sources={}
        for record,catalog in sorted(values,key=lambda pair:pair[0]['original']['bookmaker']):
            r=record['original']; book=r['bookmaker']; cid=record['id']
            try: source_age=str((time(r['received_at'])-time(r.get('source_at'))).total_seconds())
            except (ValueError,TypeError,AttributeError): source_age=None
            if source_age is not None and Decimal(source_age)<0:source_age=None
            native=dict(event_id=r['source_event_id'],market_id=stable([r['source_event_id'],r['market'],r['point'],r['outcome']]),provider_id='the_odds_api',origin_id=book,identity_scope='Aggregator event/outcome key; no native contract binding')
            side=dict(participant=record['participant'],predicate=record['predicate'],native_id=r['outcome'])
            sides[cid]=side; sources[book]=native
            legs.append(dict(id=cid,contract=r['outcome'],venue=book,label={'novig':'Novig','prophetx':'ProphetX'}[book]+' via The Odds API',
                native_identity=native,native_outcome=side,ask=record['implied'],decimal_odds=r['decimal_odds'],
                top_size=None,visible_size=None,levels=[],book_id=cid,received_at=r['received_at'],source_at=r.get('source_at'),
                age_seconds='0',source_age_seconds=source_age,source_to_receipt_seconds=source_age,connection='historical',status='historical aggregate',
                market_state='unknown',url=None,depth_limit=LIMITATION,transformation=LIMITATION,
                warnings=[x for x in (record['price_issue'],record['timing_issue']) if x],provenance=record,
                entry=dict(lower=None,upper=None,net=None,notional=None,quantity='100',reason='Aggregate fees, execution and depth unknown',basis=LIMITATION)))
        prices=[Decimal(l['ask']) if l['ask'] is not None else None for l in legs]
        gap=None if None in prices else abs(prices[0]-prices[1])
        row=dict(id=gid,game_id=gid,event_key=stable(ident['event']),game_title=title,outcome=first['original']['outcome'],identity=ident,
                 session=snapshot['session_id']+'~'+gid,hash=snapshot['session_id'],cutoff=snapshot['durable_cursor'],at=at,
                 contract=legs[0]['id'],candidate='',legs=legs,alternatives=[],raw_difference=None if gap is None else str(gap),
                 lower_raw=None if gap is None else 'Equal' if gap==0 else legs[prices.index(min(prices))]['label'],
                 entry_lower=None,timing=dict(receipt_skew_seconds='0',receipt_limits_pass=False,synchronized=False,reason='Historical response; book update times and upstream lag differ or are unknown'),
                 settlement_audit=None,settlement_status='UNKNOWN',settlement=LIMITATION,net=None,ev=None,mode='observation',historical=True,aggregated=True)
        snapshot['aggregate_comparisons'].append(row)
        snapshot['games'].append(dict(id=gid,title=title,scheduled_start=ident['scheduled_start'],teams=[first['original']['away_team'],first['original']['home_team']],
            sides=sides,sources=sources,candidates=[],product_identity=ident,aggregated=True))
        snapshot['points'][gid]=dict(id=snapshot['durable_cursor'],at=at,label='Historical aggregate response',cards=[])
        snapshot['rows_by_game'][gid]=[]
    add_coverage(snapshot,records)
    for source in snapshot['sources']:
        if source['source_id'] in VENUES:
            source.update(provider_id='the_odds_api',origin_id=source['source_id'],state='historical',environment='retained observations',update_path='The Odds API aggregate (native integration preserved)')


def comparisons(snapshot, query):
    rows=[]
    for original in snapshot.get('aggregate_comparisons',[]):
        row=deepcopy(original)
        if any(query.get(k) and row['identity'].get(k)!=query[k] for k in ('competition','season','period','family')): continue
        if query.get('search','').lower() not in row['game_title'].lower(): continue
        if query.get('venue') and not set(query['venue'].split('+')) <= set(VENUES): continue
        if query.get('positive')=='true' or query.get('freshness')=='usable': continue
        for leg in row['legs']: leg['entry']['quantity']=query.get('quantity','100')
        from app.reference.aggregate_assessment import enrich, VERSION as RULE_VERSION
        rows.append(enrich(row, query.get('rule_version', RULE_VERSION)))
    return rows


def add_coverage(snapshot, records):
    """All 63 required cells stay explicit; sample absence never removes scope."""
    from app.normalization.score_periods import PERIODS
    coverage=[]
    for sport in SPORT_KEYS:
        periods=['full_game']+(['first_half'] if sport in ('NFL','NCAAF','NBA','NCAAB') else list(PERIODS.get(sport,[])))
        cells=[(p,f,None) for p in periods for f in ('moneyline','spread','total')]
        cells += [('season','futures',category) for category in ('conference_champion','league_champion')]
        for period,family,category in cells:
            bound=[c for c in snapshot['aggregate_comparisons'] if c['identity']['competition']==sport and c['identity']['family']==family and c['identity']['period']==period and c['identity'].get('category')==category]
            reason=('Aggregate period / championship mapping unsupported: no retained source records, exact period rules or season/category identity' if period!='full_game' and not bound
                    else 'No ProphetX/Novig observations in this retained sport response' if not any(r['original']['sport']==sport and r['role']=='aggregated_venue_observation' for r in records)
                    else None if bound else 'No unambiguous same-outcome, same-line aggregate pair in this retained response')
            period_records = [r for r in records if r.get('version') == 'odds-aggregate-period-1'
                              and r['original'].get('sport') == sport and r['identity']['period'] == period
                              and r['identity']['family'] == family]
            if period_records and not bound:
                reason = 'Period records retained; no unambiguous pregame same-outcome, same-line ProphetX/Novig pair in this response'
            coverage.append(dict(source_id='the_odds_api',market_id='scope-'+sport+'-'+period+'-'+(category or family),
                title=sport+' required '+(category or family)+' / '+period,identity=dict(competition=sport,family=family,period=period,category=category),
                reason=reason,usable=False,comparison_count=len(bound),scope_only=True))
    snapshot['aggregate_coverage']=coverage
    snapshot['market_catalog'].extend(coverage)
