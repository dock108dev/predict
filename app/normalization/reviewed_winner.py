"""Shared native review and settlement plumbing for bounded winner slices."""
from hashlib import sha256
import json
from app.normalization.registry import Registry
from app.reference.product import time

def winner_review(config,event,market,meta,source,mode):
    league=config.LEAGUE; key=config.KEY; FIELDS=config.FIELDS; RULES=config.RULES
    event_key=config.event_key
    event_key(event)
    if market.get('market_type')!='moneyline' or market.get('period')!='full_game' or any(market.get(k) is not None for k in ('line','subject','category','horizon')):
        raise ValueError(f'{league} supports unlined full-game winner only')
    if market.get('outcome_set')!='two_way' or market.get('rules_revision')!=RULES:
        raise ValueError(f'{league} period / three-way / unknown winner semantics unsupported')
    r=market.get(key+'_review')
    if not r or r.get('source')!=source or r.get('event_id')!=event['id'] or r.get('market_id')!=market['id']:
        raise ValueError(f'Source-specific {league} native terms review missing')
    if r.get('evidence_mode') not in ('synthetic','observation') or (r['evidence_mode']=='synthetic' and mode!='mock'):
        raise ValueError(f'Synthetic {league} mapping cannot qualify observations')
    raw=meta['market']['raw'];body=raw['json_text']
    if raw.get('kind')!=r['evidence_mode']:raise ValueError(f'{league} review evidence mode conflicts with native receipt')
    if r.get('raw_sha256')!=sha256(body.encode()).hexdigest():
        raise ValueError(f'{league} native terms receipt changed')
    terms=r.get('terms',{});literals=r.get('literals',{})
    if set(terms)!=set(FIELDS) or set(literals)!=set(FIELDS) or any(not isinstance(literals[k],str) or not literals[k] or literals[k] not in body for k in FIELDS):
        raise ValueError(f'Missing {league} outcome / exceptional settlement evidence')
    if any(not isinstance(terms[k],str) or terms[k].strip().lower() in ('','unknown','unverified','unspecified') for k in FIELDS):
        raise ValueError(f'Unresolved {league} settlement terms')
    if any(terms[k]!=value for k,value in config.REQUIRED_TERMS.items()):
        raise ValueError(f'Conflicting {league} full-game winner semantics')
    binding=r.get('event_binding')
    if binding!=event_key(event):
        raise ValueError(f'{league} native review event / schedule binding conflict')
    evidence=r.get('event_literals',{})
    if set(evidence)!=set(config.EVENT_FIELDS) or any(not isinstance(v,str) or not v or v not in body for v in evidence.values()):
        raise ValueError(f'Missing {league} native event identity evidence')
    native=json.loads(body)
    paths=r.get('event_paths',{})
    if set(paths)!=set(evidence):raise ValueError(f'{league} native identity paths missing')
    for field,path in paths.items():
        value=native
        if not isinstance(path,list) or not path:raise ValueError(f'{league} native identity path invalid')
        for part in path:value=value[part]
        expected=event[field]
        if field in ('scheduled_start','original_start'):
            value=time(value);expected=time(expected)
        if value!=expected:raise ValueError(f'{league} native identity conflicts: '+field)
    if not r.get('scope_literal') or r['scope_literal'] not in body:
        raise ValueError(f'{league} native full-game scope evidence missing')
    if source not in ('kalshi','polymarket_us'):
        raise ValueError(f'{league} native outcome mapping not reviewed for this source')
    sides=market.get('product_outcomes',[])
    if sides!=r.get('outcomes') or len(sides)!=2 or len({s.get('native_id') for s in sides})!=2:
        raise ValueError(f'{league} native outcome orientation missing or conflicting')
    names={Registry.load().entities[c]['name'] for c in event['participants'].values()}
    winners=[]
    for s in sides:
        if s.get('participant') not in names or s.get('predicate') not in ('win','not_win') or not s.get('native_id'):
            raise ValueError(f'{league} native outcome participant / predicate unsupported')
        winners.append(next(n for n in names if n!=s['participant']) if s['predicate']=='not_win' else s['participant'])
    if set(winners)!=names:raise ValueError(f'{league} outcomes do not cover both normal winners')
    native=json.loads(body)
    markets=native.get('markets',[])+[m for e in native.get('events',[]) for m in e.get('markets',[])]
    if source in ('kalshi','polymarket_us'):
        matched=[m for m in markets if str(m.get('ticker' if source=='kalshi' else 'id'))==market['id']]
        if len(matched)!=1:raise ValueError(f'Missing or duplicate native {league} listing')
        nm=matched[0];registry=Registry.load()
        if source=='kalshi' and (nm.get('event_ticker')!=event['id'] or nm.get('series_ticker') not in getattr(config,'NATIVE_SERIES',(config.SERIES,))):
            raise ValueError(f'{league} native series / event association conflict')
        if source=='polymarket_us' and nm.get('eventId')!=event['id']:
            raise ValueError(f'{league} native event association conflict')
        def name(value):
            resolved=registry.resolve('team',value,league=league)
            if resolved.status!='resolved':raise ValueError(f'Ambiguous native {league} outcome')
            return resolved.canonical_name
        if source=='kalshi':
            expected={('yes',name(nm['yes_sub_title']),'win'),('no',name(nm['yes_sub_title']),'not_win')}
        else:
            ns=nm['marketSides']
            if len(ns)!=2 or {s.get('long') for s in ns}!={True,False} or any(type(s.get('long')) is not bool for s in ns):raise ValueError(f'Conflicting native {league} Long/Short orientation')
            expected={(str(s['id']),name(s['team']['name']),'win') for s in ns}
            for side in sides:
                original=next(s for s in ns if str(s['id'])==side['native_id'])
                if side.get('native_label')!=('Long' if original['long'] else 'Short'):raise ValueError(f'{league} Long/Short label conflicts with native side')
        if expected!={(s['native_id'],s['participant'],s['predicate']) for s in sides}:raise ValueError(f'{league} outcome review conflicts with native listing')
    if not r.get('outcome_literal') or r['outcome_literal'] not in body:
        raise ValueError(f'{league} native outcome evidence missing')
    return r


def assessment(config,rows,cutoff,game):
    league=config.LEAGUE; key=config.KEY
    """Reuse settlement profiles without importing football exceptional terms."""
    from app.settlement import profile,fact
    profiles={};sources={};coefficient=None;fee_bases={}
    for venue,review in game.get(key+'_reviews',{}).items():
        eligible=[r for r in rows if r['source']==venue and time(r['observed_at'])<=time(cutoff)]
        if not eligible:continue
        raw=eligible[-1]['market']['raw']
        if sha256(raw['json_text'].encode()).hexdigest()!=review['raw_sha256']:continue
        terms=review['terms'];h=review['raw_sha256']
        source=dict(url=raw['source'],sha256=h,text=json.dumps(terms,sort_keys=True),priority='market-specific',received_at=raw['received_at'])
        # Unknown exceptional payouts remain unknown; a declared sporting
        # winner never establishes a venue's cancellation payout.
        payouts={}
        if terms['tie']=='fraction-0.50':payouts['tie']=dict(kind='fraction',value='0.5',evidence=h)
        profile_terms=config.settlement_terms(terms) if hasattr(config,'settlement_terms') else terms
        profiles[venue]=profile(sources=[source],actor=f'B5 explicit {league} retained terms review',dimensions={ {'extra_innings':'overtime','suspension':'resumption'}.get(k,k):fact(v,evidence=h) for k,v in profile_terms.items() if k not in ('outcomes','void','refund')},payouts=payouts)
        sources[venue]=dict(source=source,known_at=eligible[-1]['observed_at'],market_id=raw['ref']['market_id'])
        basis=review.get('fee_basis')
        if basis and basis.get('evidence_literal') and basis['evidence_literal'] in raw['json_text']:
            fee_bases[venue]=basis
            if venue=='polymarket_us':coefficient=basis.get('coefficient')
    return dict(assessed_at=game['assessment_at'],observation_cutoff=cutoff,profiles=profiles,sources=sources,pmus_coefficient=coefficient,note=f'Reviewed {league} normal-winner conditional calculation; exceptional probabilities unknown.',**{key+'_fee_bases':fee_bases})


def inventory_gaps(config,inventory):
    league=config.LEAGUE; event_key=config.event_key
    gaps={};buckets={};native={};slots={}
    for source,cat in inventory.items():
        for e in cat.get('events',[]):
            if e.get('competition')!=league:continue
            key=(source,e['id'])
            try:k=event_key(e)
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                gaps[key]=f'{league} identity: '+str(exc);continue
            if key in native:
                gaps[key]=f'Duplicate native {league} event'
            native[key]=key
            buckets.setdefault(e['game_id'],[]).append((key,k))
            # Same opponents/original UTC date with different IDs
            # are a conflicting binding, not two independent games.
            slot=(k[7][:10],tuple(sorted(e['participants'].values())))
            slots.setdefault(slot,[]).append((key,k))
    for entries in [*buckets.values(),*slots.values()]:
        if len({json.dumps(k) for _,k in entries})>1 or len({key[0] for key,_ in entries})!=len(entries):
            for key,_ in entries:gaps[key]=f'Conflicting {league} game ID, stage, season, start or reschedule binding'
    return gaps


def model_reason(config,binding,body):
    league=config.LEAGUE; event_key=config.event_key; RULES=config.RULES
    """Only an annotated, explicit home-win or away-win output with established meaning."""
    r=binding.get(config.KEY+'_model_review',{});e=r.get('event',{})
    try:
        key=event_key(e)
        i=binding['market_identity']
        if key!=i['event'] or any(i[k]!=e[k] for k in ('season','stage','competition')) or time(i['scheduled_start'])!=time(e['scheduled_start']):
            return f'Model {league} event, season or start binding conflicts'
        if any(str(e[k]) not in body for k in ('game_id','scheduled_start','original_start','competition','season','stage')):return f'Model {league} game ID or start evidence missing'
        registry=Registry.load()
        if r.get('published_outcome') not in ('home_win','away_win'):return 'Explicit published home-win or away-win output required'
        for field,cid in [('home_name',e['home']),('away_name',e['away'])]:
            if not r.get(field) or r[field] not in body or registry.resolve('team',r[field],league=league).canonical_id!=cid:
                return f'Model home/away names conflict with reviewed {league} event'
        published=registry.entities[e['home' if r['published_outcome']=='home_win' else 'away']]['name']
        if binding['participant']!=published:return f'{league} probability participant conflicts with explicitly published outcome'
        if i['rules']!=RULES or i['outcome_set']!='two_way':return f'Model {league} outcome meaning does not match two-way full-game winner'
        if r.get('overtime')!='included':return f'Model {league} overtime meaning unestablished'
        if any(not r.get(k) or r[k] not in body for k in ('home_literal','away_literal','semantics_literal')):
            return f'Model {league} home/away or outcome evidence missing'
    except (KeyError,ValueError,TypeError,AttributeError):return f'Reviewed {league} model event binding missing'
    return None

