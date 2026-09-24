"""Retained reference-input adapters. No network, credential discovery or startup hooks.

Annotated published-page extraction is a local import format, NOT a provider API.
Every extraction retains the entire bounded original plus exact literal offsets.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from urllib.parse import urlsplit

VERSION = 'b4-reference-1'
MAX_BODY = 256 * 1024
SOURCES = {
    'synthetic_partition': dict(scopes=[('ice_hockey','NHL'),('baseball','MLB'),('basketball','NBA'),('basketball','NCAAB'),('american_football','NFL'),('american_football','NCAAF')], dependency='Synthetic test table only; no model provider or independence qualification', refresh=86400),
    'moneypuck': dict(scopes=[('ice_hockey','NHL')], dependency='Sporting inputs documented; betting-market independence not established', refresh=86400),
    'fangraphs': dict(scopes=[('baseball','MLB')], dependency='Player projections and playing-time dependencies; independence not established', refresh=86400),
    'espn_fpi': dict(scopes=[('american_football','NFL'),('american_football','NCAAF')], dependency='Market-informed NFL preseason model; not an independent betting-market signal', refresh=86400),
    'espn_bpi': dict(scopes=[('basketball','NBA'),('basketball','NCAAB')], dependency='Model inputs incompletely verified; independence not established', refresh=86400),
    'kenpom': dict(scopes=[('basketball','NCAAB')], dependency='Efficiency-model estimate; independence not established; web subscription is not API entitlement', refresh=86400),
    'the_odds_api': dict(scopes=[('american_football','NFL'),('american_football','NCAAF'),('basketball','NBA'),('basketball','NCAAB'),('baseball','MLB'),('ice_hockey','NHL')], dependency='Pinnacle betting-market input; not independent of betting markets', refresh=3600),
}
SPORT_KEYS={'NFL':'americanfootball_nfl','NCAAF':'americanfootball_ncaaf','NBA':'basketball_nba','NCAAB':'basketball_ncaab','MLB':'baseball_mlb','NHL':'icehockey_nhl'}

def packed(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str)
def digest(x):return sha256(packed(x).encode()).hexdigest()
def time(x):
    t=datetime.fromisoformat(x.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('Timezone required')
    return t

def number(x):
    d=Decimal(str(x))
    if not d.is_finite():raise ValueError('Nonfinite value')
    return d

def probability(value, convention):
    d=number(value)
    with localcontext() as ctx:
        ctx.prec=40
        if convention=='percent':d/=100
        elif convention=='decimal_odds':
            if d<=1:raise ValueError('Decimal odds must exceed 1')
            d=1/d
        elif convention=='american_odds':
            if abs(d)<100:raise ValueError('Invalid American odds')
            d=100/(d+100) if d>0 else -d/(-d+100)
        elif convention!='probability':raise ValueError('Unknown probability convention')
        if not 0<=d<=1:raise ValueError('Probability outside [0,1]')
        return str(d)

def receipt(body, *, provider, url, received_at, mode, status=200, headers=None):
    if provider not in SOURCES or mode not in ('synthetic','observation'):raise ValueError('Unknown source or evidence mode')
    if provider=='synthetic_partition' and mode!='synthetic':raise ValueError('Synthetic partition fixture cannot qualify observations')
    if not isinstance(body,str) or len(body.encode())>MAX_BODY:raise ValueError('Reference body bound')
    if not url.startswith('https://') or '?' in url or '#' in url:raise ValueError('Use a credential-free source URL; query stored separately')
    parsed=urlsplit(url)
    hosts={'moneypuck':('moneypuck.com','www.moneypuck.com'),'fangraphs':('fangraphs.com','www.fangraphs.com'),'espn_fpi':('www.espn.com','espn.com'),'espn_bpi':('www.espn.com','espn.com'),'kenpom':('kenpom.com','www.kenpom.com'),'the_odds_api':('api.the-odds-api.com',)}
    if parsed.username or parsed.password or (mode=='observation' and parsed.hostname not in hosts[provider]):raise ValueError('Source URL origin mismatch')
    time(received_at)
    r=dict(body=body,provider_id=provider,url=url,received_at=received_at,evidence_mode=mode,status=status,
           headers={k.lower():str(v) for k,v in (headers or {}).items() if k.lower() in ('x-requests-last','x-requests-used','x-requests-remaining','date')})
    return dict(r,id=digest(r))

def base(r, binding, *, source_at=None, model_version=None):
    expected=receipt(r['body'],provider=r['provider_id'],url=r['url'],received_at=r['received_at'],mode=r['evidence_mode'],status=r['status'],headers=r['headers'])
    if r!=expected:raise ValueError('Receipt digest or contract mismatch')
    if r['status']!=200:raise ValueError('Unsuccessful source receipt')
    i=deepcopy(binding['market_identity']);p=r['provider_id']
    required={'version','event','sport','competition','season','stage','scheduled_start','family','period','line','subject','outcome_set','rules','category','horizon'}
    if set(i)!=required or i['version']!=1:raise ValueError('Complete canonical market identity required')
    if i['scheduled_start']:time(i['scheduled_start'])
    if not isinstance(binding['participant'],str) or not binding['participant'] or not binding['source_event_id']:raise ValueError('Explicit source event and outcome required')
    if (i['sport'],i['competition']) not in SOURCES[p]['scopes']:raise ValueError('Source competition mismatch')
    if source_at:time(source_at)
    return dict(schema_version=VERSION,role='bookmaker_reference' if p=='the_odds_api' else 'model_reference',
        provider_id=p,origin_id='pinnacle' if p=='the_odds_api' else p,market_identity=i,
        participant=binding['participant'],source_event_id=binding['source_event_id'],binding=deepcopy(binding),
        source_at=source_at,model_as_of=source_at,model_version=model_version or 'unknown',received_at=r['received_at'],
        delay_seconds=None,delay_basis='Unknown; receipt age is not publication delay',dependency=('College-football model inputs not independently verified; betting-market independence not established' if p=='espn_fpi' and i['competition']=='NCAAF' else SOURCES[p]['dependency']),
        independence='not_established',receipt=deepcopy(r),provenance=r['url'],evidence_mode=r['evidence_mode'],
        exceptional_probabilities=None,unconditional_ev=None,refresh_after_seconds=SOURCES[p]['refresh'])

def finish(x):return dict(x,id=digest(x))

def published_value(r,binding,*,start,end,kind,convention,source_at=None,model_version=None):
    """Explicit annotated page-text import; offsets and identity literals are audited.

    Capturer supplies source as-of only when published; never substitutes receipt.
    A game/date/outcome literal must appear in the retained page. No rank conversion.
    """
    x=base(r,binding,source_at=source_at,model_version=model_version)
    if r['provider_id']=='the_odds_api':raise ValueError('Use native Pinnacle parser')
    for field in ('event_literal','outcome_literal','date_literal'):
        if not binding.get(field) or binding[field] not in r['body']:raise ValueError('Missing source identity evidence')
    if not isinstance(start,int) or not isinstance(end,int) or not 0<=start<end<=len(r['body']):raise ValueError('Invalid extraction span')
    literal=r['body'][start:end];raw=literal.strip().removesuffix('%').strip()
    x.update(original_value=literal,source_value_kind=kind,extraction=dict(method='annotated published text literal',start=start,end=end),value_kind=kind,convention=convention,
             value=None,conversion_method=None,state='unsupported',reason='Only explicit full-game winner probabilities support conditional EV')
    if kind not in ('game_probability','season_probability','rating','rank','projected_margin','projected_total'):raise ValueError('Unknown source output type')
    number(raw)
    if kind=='game_probability' and convention in ('percent','probability'):
        x.update(value=probability(raw,convention),value_kind='probability',conversion_method='percent / 100' if convention=='percent' else 'identity probability',state='available',reason=None)
    else:x['value']=str(number(raw))
    return finish(x)

def kenpom_fanmatch(r,binding,*,game_id,convention,source_at=None):
    """Documented JSON shape; caller must establish HomeWP units, never infer them."""
    if r['provider_id']!='kenpom':raise ValueError('Wrong provider')
    if convention not in ('percent','probability'):raise ValueError('Explicit HomeWP probability units required')
    rows=json.loads(r['body'],parse_float=str)
    matches=[v for v in rows if str(v['GameID'])==str(game_id)]
    if len(matches)!=1:raise ValueError('Missing or conflicting FanMatch game')
    v=matches[0]
    if str(binding['source_event_id'])!=str(game_id) or binding['participant']!=v['Home'] or str(v['Season'])!=str(binding['market_identity']['season']) or v['DateOfGame']!=binding['source_date']:raise ValueError('FanMatch identity mismatch')
    x=base(r,binding,source_at=source_at)
    x.update(original_value=v['HomeWP'],native_record=v,value_kind='probability',convention=convention,
        value=probability(v['HomeWP'],convention),conversion_method='explicit HomeWP '+convention,state='available',reason=None,
        acquisition_limitation='API entitlement required separately; archived/current-date output is not evidence of availability at an earlier cutoff')
    return finish(x)

def pinnacle(r,binding,*,odds_format='decimal'):
    if r['provider_id']!='the_odds_api':raise ValueError('Wrong provider')
    payload=json.loads(r['body'],parse_float=str);events=payload if isinstance(payload,list) else [payload]
    events=[e for e in events if e['id']==binding['source_event_id']]
    if len(events)!=1:raise ValueError('Missing or conflicting event')
    e=events[0];i=binding['market_identity']
    if e['sport_key']!=SPORT_KEYS[i['competition']] or time(e['commence_time'])!=time(i['scheduled_start']):raise ValueError('Event scope mismatch')
    if set(binding['source_participants'])!={e['home_team'],e['away_team']} or binding['participant'] not in binding['source_participants']:raise ValueError('Participant binding mismatch')
    books=[b for b in e['bookmakers'] if b['key']=='pinnacle']
    if len(books)!=1:raise ValueError('Pinnacle missing or conflicting; no substitute')
    markets=[m for m in books[0]['markets'] if m['key']=='h2h']
    if len(markets)!=1:raise ValueError('Pinnacle h2h missing or conflicting')
    m=markets[0];out=m['outcomes'];conv={'decimal':'decimal_odds','american':'american_odds'}[odds_format]
    if len(out)!=2 or {o['name'] for o in out}!=set(binding['source_participants']) or any(o.get('point') is not None for o in out):raise ValueError('Only two-way unlined h2h supported')
    x=base(r,binding,source_at=m.get('last_update') or books[0].get('last_update'),model_version='proportional-no-vig-1')
    with localcontext() as ctx:
        ctx.prec=40
        inverse=[number(probability(o['price'],conv)) for o in out];total=sum(inverse)
        idx=next(n for n,o in enumerate(out) if o['name']==binding['participant'])
        x.update(value=str(inverse[idx]/total),original_value=deepcopy(out),value_kind='probability',convention=conv,
             conversion_method='proportional no-vig: inverse odds / sum of both inverse odds (Decimal precision 40)',
             state='available',reason=None,implied_probability_sum=str(total),native_market=deepcopy(m),
             delay_basis='Public Pinnacle website odds may be delayed; duration unknown')
    return finish(x)

def validate(r):
    core={k:v for k,v in r.items() if k not in ('id','observation_id','observed_at','availability','age_seconds','freshness')}
    if r['id']!=digest(core):raise ValueError('Immutable reference digest mismatch')
    if r['receipt']['id']!=digest({k:v for k,v in r['receipt'].items() if k!='id'}):raise ValueError('Receipt digest mismatch')
    if r['received_at']!=r['receipt']['received_at']:raise ValueError('Receipt time changed')
    if r['value_kind']=='probability':probability(r['value'],'probability')
    if r.get('parser')=='score_distribution':
        from app.reference.score_lines import score_distribution
        expected=score_distribution(r['receipt'],r['binding'],source_at=r['source_at'],model_version=r['model_version'])
    elif 'extraction' in r:
        expected=published_value(r['receipt'],r['binding'],start=r['extraction']['start'],end=r['extraction']['end'],kind=r['source_value_kind'],convention=r['convention'],source_at=r['source_at'],model_version=r['model_version'])
    elif r['provider_id']=='the_odds_api':
        expected=pinnacle(r['receipt'],r['binding'],odds_format='decimal' if r['convention']=='decimal_odds' else 'american')
    elif r['provider_id']=='kenpom':
        expected=kenpom_fanmatch(r['receipt'],r['binding'],game_id=r['source_event_id'],convention=r['convention'],source_at=r['source_at'])
    else:raise ValueError('Unknown reference parser')
    if expected['id']!=r['id']:raise ValueError('Reference does not reproduce from original source input')

def at_cutoff(refs,at):
    result=[]
    for r in refs:
        if any(r.get(k) and time(r[k])>time(at) for k in ('received_at','source_at','model_as_of','observed_at')):continue
        x=deepcopy(r)
        if x.get('schema_version')==VERSION:
            i=x['market_identity'];x['availability']=x['state']
            score_line=x.get('parser')=='score_distribution'
            if score_line:
                from app.reference.score_lines import cutoff_reason
                reason=cutoff_reason(x)
                if reason:x.update(availability='unsupported',reason=reason)
            if not score_line and (i['family']!='moneyline' or i['period']!='full_game' or i.get('line') is not None or i.get('horizon') or i.get('category')):
                x.update(availability='unsupported',reason='Reference does not describe an unlined full-game winner')
            if i.get('scheduled_start') and time(x['received_at'])>=time(i['scheduled_start']):
                x.update(availability='unsupported',reason='First received after scheduled start; retrospective reference only')
            if i['competition']=='NHL' and not score_line:
                from app.normalization.nhl import model_reason
                reason=model_reason(x['binding'],x['receipt']['body']) if x['role']=='model_reference' else 'NHL Pinnacle native winner settlement evidence unavailable'
                if x['source_at'] and time(x['source_at'])>time(x['received_at']):reason='Source publication time is later than receipt'
                if reason:x.update(availability='unsupported',reason=reason)
            if i['competition']=='MLB' and not score_line:
                from app.normalization.mlb import model_reason
                reason=model_reason(x['binding'],x['receipt']['body']) if x['role']=='model_reference' else 'MLB Pinnacle native winner settlement evidence unavailable'
                if x['source_at'] and time(x['source_at'])>time(x['received_at']):reason='Source publication time is later than receipt'
                if reason:x.update(availability='unsupported',reason=reason)
            if i['competition']=='NBA' and not score_line:
                from app.normalization.nba import model_reason
                reason=model_reason(x['binding'],x['receipt']['body']) if x['role']=='model_reference' else 'NBA Pinnacle native winner settlement evidence unavailable'
                if x['source_at'] and time(x['source_at'])>time(x['received_at']):reason='Source publication time is later than receipt'
                if reason:x.update(availability='unsupported',reason=reason)
            if i['competition']=='NCAAB' and not score_line:
                from app.normalization.ncaab import model_reason
                reason=model_reason(x['binding'],x['receipt']['body']) if x['role']=='model_reference' else 'NCAAB Pinnacle native winner settlement evidence unavailable'
                if x['source_at'] and time(x['source_at'])>time(x['received_at']):reason='Source publication time is later than receipt'
                if reason:x.update(availability='unsupported',reason=reason)
            if i['competition']=='NCAAF' and not score_line:
                from app.normalization.ncaaf import model_reason
                reason=model_reason(x['binding'],x['receipt']['body']) if x['role']=='model_reference' else 'NCAAF Pinnacle native winner settlement evidence unavailable'
                if x['source_at'] and time(x['source_at'])>time(x['received_at']):reason='Source publication time is later than receipt'
                if reason:x.update(availability='unsupported',reason=reason)
            age=(time(at)-time(x['source_at'] or x['received_at'])).total_seconds()
            x.update(age_seconds=str(age),freshness='refresh_due' if age>x['refresh_after_seconds'] else 'within_refresh_plan')
        elif (x.get('market_identity',{}).get('competition')=='NHL' and x.get('market_identity',{}).get('family') in ('spread','total')) or x.get('market_identity',{}).get('competition') in ('MLB','NBA','NCAAF','NCAAB') or (x.get('market_identity',{}).get('competition')=='NFL' and (x.get('market_identity',{}).get('family') in ('spread','total') or x.get('market_identity',{}).get('period')=='first_half')):
            x.update(availability='unsupported',reason=x['market_identity']['competition']+' reference requires an original-input reference receipt and reviewed game binding')
        result.append(x)
    # Same source revision with conflicting values is never resolved by insertion order.
    groups={}
    for x in result:
        if x.get('schema_version')==VERSION:
            key=packed([x['provider_id'],x['origin_id'],x['market_identity'],x['participant'],x['source_at'],x['model_version'],x['value_kind']])
            groups.setdefault(key,[]).append(x)
    for xs in groups.values():
        if len({packed([x['value'],x['original_value']]) for x in xs})>1:
            for x in xs:x.update(availability='conflicting',reason='Conflicting retained values for the same source revision')
    return result

def emit_references(collector, references):
    """Existing collector owns acknowledgement, Stop, journal and projection."""
    if collector.stop_event.is_set():raise ValueError('Collector stopped')
    if not isinstance(references,list) or not 1<=len(references)<=16:raise ValueError('Import bound: 1 to 16 references')
    for r in references:
        validate(r)
        if collector.spec.get('mode')!='mock' and r['evidence_mode']=='synthetic':raise ValueError('Synthetic reference in real session')
    if len(set(collector.projection.references)|{r['id'] for r in references})>128:raise ValueError('Reference bound')
    for r in references:
        collector.emit('reference',dict(type='product_reference',reference=r))


def prepare(entries):
    """Prepare bounded local capture annotations for the ordinary Import control."""
    if not isinstance(entries,list) or not 1<=len(entries)<=16:raise ValueError('Preparation bound')
    result=[]
    for entry in entries:
        r=receipt(**entry['receipt']);binding=entry['binding'];options=entry.get('options',{})
        from app.reference.score_lines import score_distribution
        parser={'score_distribution':score_distribution,'published_value':published_value,'pinnacle':pinnacle,'kenpom_fanmatch':kenpom_fanmatch}.get(entry['parser'])
        if parser is None:raise ValueError('Unknown retained-input parser')
        ref=parser(r,binding,**options);validate(ref);result.append(ref)
    return result

if __name__=='__main__':
    import argparse
    from pathlib import Path
    cli=argparse.ArgumentParser(description='Prepare local retained-reference inputs; no provider access')
    cli.add_argument('input',type=Path);cli.add_argument('output',type=Path);args=cli.parse_args()
    if args.input.stat().st_size>1024*1024:raise ValueError('Local input byte bound')
    data=prepare(json.loads(args.input.read_text()))
    encoded=json.dumps(data,indent=2)
    if len(encoded.encode())>1024*1024:raise ValueError('Prepared import byte bound')
    with args.output.open('x') as f:f.write(encoded+'\n')
