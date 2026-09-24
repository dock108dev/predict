"""Moneyline market matching. Native ingestion remains in venue adapters.

update() takes an authoritative complete market snapshot and a current event
Matcher. report() requires that current parent matcher too, so historical linkage
cannot accidentally stand in for confirmation. Revisions retain all input evidence.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from itertools import combinations
from hashlib import sha256
import json
from pathlib import Path
import re

from app.matching import Matcher, VERSION as EVENT_VERSION, clone, digest, packed, expand_raw
from app.normalization import Registry
from app.settlement import (compare_profiles, relationships, validate as validate_profile,
                            VERSION as RULE_VERSION)

VERSION='moneyline-matcher-1'
SCHEMA=1


def rule_binding(native, venue, scope, rule_profile):
    if scope[0]=='synthetic': return True  # Explicit synthetic policy source, no venue claim.
    text=('\n\n'.join(native[k] for k in ('rules_primary','rules_secondary') if native.get(k))
          if venue=='kalshi' else native.get('description',''))
    return bool(text) and any(s.get('priority')=='market-specific' and
        s['sha256']==sha256(text.encode()).hexdigest() and s['text']==text
        for s in rule_profile['sources'])


def observe(market, parent, rule_profile, *, native, context, artifact, registry=None):
    """Enrich one native market with canonical participants and retained evidence.

    Kalshi: KXNFLGAME + Game metadata + anchored listing YES criterion, checked
    against yes_sub_title; default full-game period from FOOTBALLGAMEWIN terms.
    PMUS: exact full-game winner taxonomy + explicit marketSides teamId/long.
    This bounded grammar fails closed. No ticker/title/order/price heuristics.
    """
    registry=registry or Registry.load()
    validate_profile(rule_profile)
    ref=market.raw.ref
    if (ref.venue.value,ref.event_id,market.raw.kind.value)!=(parent['venue'],parent['native_event_id'],parent['scope'][0]):
        raise ValueError('market/parent native scope mismatch')
    def contains(value):
        if isinstance(value,dict):
            return value==native or any(contains(v) for v in value.values() if isinstance(v,(list,dict)))
        if isinstance(value,list): return any(contains(v) for v in value)
        return False
    if not contains(json.loads(market.raw.json_text)):
        raise ValueError('native market does not occur in source payload')
    key=packed([*parent['scope'],ref.venue.value,ref.event_id,ref.market_id])
    reasons=[]; sides=[]; period=None; market_type='unknown'
    if parent['registry'] != [[registry.version,registry.fingerprint]]:
        reasons.append('normalization-registry-disagreement')
    def resolve(name=None,native_id=None):
        r=registry.resolve('team',name,league=parent['league'],venue=ref.venue.value,
                           environment=parent['environment'],native_id=native_id)
        if r.status!='resolved' or r.canonical_id not in parent['participants']:
            raise ValueError('side participant unresolved, conflicting, or outside parent event')
        return r.canonical_id
    try:
        if ref.venue.value=='kalshi':
            if native.get('ticker')!=ref.market_id or native.get('event_ticker')!=ref.event_id:
                raise ValueError('native-market-reference-mismatch')
            if context.get('series_ticker')!='KXNFLGAME' or native.get('market_type')!='binary':
                raise ValueError('unsupported-moneyline-series-or-market-type')
            market_type='moneyline'
            if (context.get('product_metadata',{}).get('competition_scope')!='Game'
                    or context.get('strike_period') not in ('',None)
                    or market.period not in (None,'full_game') or native.get('period') not in (None,'full_game')):
                raise ValueError('non-full-game-or-unknown-period')
            period='full_game'
            criterion=re.fullmatch(r'If (.+) wins the (.+) (?:professional football|Pro Football) game originally scheduled for ([A-Za-z]+ \d{1,2}, \d{4}), then the market resolves to Yes\.',native.get('rules_primary',''))
            if not criterion:
                raise ValueError('unrecognized-authoritative-YES-criterion')
            pair=re.fullmatch(r'(.+) vs\.? (.+)',criterion[2])
            if not pair or {resolve(pair[1]),resolve(pair[2])}!=set(parent['participants']):
                raise ValueError('listing-rule-event-participants-disagree')
            participant=resolve(criterion[1])
            if resolve(native.get('yes_sub_title'))!=participant:
                raise ValueError('YES-label-rule-conflict')
            actual={o.native_id for o in market.outcomes}
            if not actual or actual-{'yes','no'}:
                raise ValueError('unsupported-native-sides')
            sides=[{'native_id':s,'participant':participant,'predicate':'win' if s=='yes' else 'not_win',
                    'representation':s,'evidence':'rules_primary + yes_sub_title; FOOTBALLGAMEWIN binary settlement',
                    'liquidity_key':key} for s in sorted(actual)]
        elif ref.venue.value=='polymarket_us':
            if str(native.get('id'))!=ref.market_id or str(context.get('id'))!=ref.event_id:
                raise ValueError('native-market-reference-mismatch')
            if native.get('marketType')!='moneyline' or native.get('sportsMarketTypeV2') not in (None,'SPORTS_MARKET_TYPE_MONEYLINE'):
                raise ValueError('non-moneyline-market:'+str(native.get('marketType')))
            market_type='moneyline'
            if (native.get('sportsMarketType')!='football_team_full_game_winner'
                    or market.period not in (None,'full_game') or native.get('period') not in (None,'full_game')):
                raise ValueError('non-full-game-or-unknown-period:'+str(native.get('sportsMarketType')))
            period='full_game'; seen=set()
            actual={o.native_id for o in market.outcomes}
            for s in native.get('marketSides',[]):
                if (str(s.get('id')) not in actual or str(s.get('marketId'))!=ref.market_id
                        or type(s.get('long')) is not bool or s['long'] in seen):
                    raise ValueError('ambiguous-native-side-or-market-link')
                seen.add(s['long'])
                team=s.get('team',{})
                if s.get('teamId') is None or str(s['teamId'])!=str(team.get('id')):
                    raise ValueError('native-team-ID-conflict-or-missing')
                participant=resolve(team.get('name'),str(s['teamId']))
                sides.append({'native_id':str(s['id']),'participant':participant,'predicate':'win',
                    'representation':'long' if s['long'] else 'short',
                    'evidence':'marketSides.id, marketId, teamId, team.id/name, long; full-game winner taxonomy',
                    'liquidity_key':key})
            if {s['native_id'] for s in sides}!=actual or not sides:
                raise ValueError('native-side-coverage-mismatch')
            if len({s['participant'] for s in sides})!=len(sides):
                raise ValueError('duplicate-team-side-identity')
        else:
            raise ValueError('venue-native-moneyline-mapping-not-implemented')
    except ValueError as e:
        reasons.append(str(e)); sides=[]
    row={'key':key,'id':'native-market-'+digest(key)[:24], 'parent_key':parent['key'],
         'parent_observation_hash':parent['hash'],'scope':parent['scope'],
         'venue':ref.venue.value,'native_event_id':ref.event_id,'native_market_id':ref.market_id,
         'participants':parent['participants'],'registry':parent['registry'],
         'market_type':market_type,'period':period,'sides':sorted(sides,key=lambda x:x['native_id']),
         'reasons':reasons,'mapping_version':VERSION,'event_matcher_version':EVENT_VERSION,
         'profile':clone(rule_profile),'rule_binding':rule_binding(native,ref.venue.value,parent['scope'],rule_profile),
         'artifact':artifact,'native':clone(native),'context':clone(context),
         'raw':{**json.loads(json.dumps({k:v for k,v in asdict(market.raw).items() if k!='json_text'},default=lambda x:x.isoformat())),
                'source_body_sha256':sha256(market.raw.json_text.encode()).hexdigest()},
         'venue_event_liquidity_family':parent['key'],
         'liquidity_note':'Sides share native instrument liquidity; related venue markets are not independent opportunity claims.'}
    row['hash']=digest(row)
    return row


def validate_market(row):
    if row['hash']!=digest({k:v for k,v in row.items() if k!='hash'}) or row['mapping_version']!=VERSION:
        raise ValueError('invalid market observation/version')
    if row['id']!='native-market-'+digest(row['key'])[:24]: raise ValueError('invalid stable market ID')
    ref=[*row['scope'],row['venue'],row['native_event_id'],row['native_market_id']]
    if row['key']!=packed(ref) or row['parent_key']!=packed(ref[:-1]): raise ValueError('invalid scoped market reference')
    validate_profile(row['profile'])
    if row['rule_binding']!=rule_binding(row['native'],row['venue'],row['scope'],row['profile']):
        raise ValueError('invalid listing-rule binding')


class MoneylineMatcher:
    def __init__(self):
        self._data={'schema_version':SCHEMA,'matcher_version':VERSION,'observations':{},
                    'current':{},'parent_snapshots':{},'decisions':{},'revisions':[],'reviews':[]}

    @property
    def snapshot(self): return clone(self._data)

    def update(self, parents, markets):
        """Replace active inventory, retain history; conflicting batch variants block."""
        incoming={}
        for row in markets:
            row=clone(row); validate_market(row)
            incoming[row['hash']]=row
        current={}
        for h,row in sorted(incoming.items()): current.setdefault(row['key'],[]).append(h)
        self._data['observations'].update(incoming)
        self._data['current']=current
        return self.report(parents)

    def report(self, parents):
        if not isinstance(parents,Matcher): raise ValueError('current event Matcher required')
        p=parents.snapshot
        # Exact source bodies already live in the event store/capture artifacts.
        def source_refs(value):
            if isinstance(value,list): return [source_refs(x) for x in value]
            if not isinstance(value,dict): return value
            return {('source_body_sha256' if k=='json_text' else k):
                    (sha256(v.encode()).hexdigest() if k=='json_text' else source_refs(v))
                    for k,v in value.items()}
        retained=source_refs(p); ph=digest(retained)
        self._data['parent_snapshots'][ph]=retained
        d=self._data; attached={}
        for key,hs in sorted(d['current'].items()):
            row=d['observations'][hs[0]]; reasons=list(row['reasons'])
            mapping=p['mappings'].get(row['parent_key'],{})
            po=p['observations'].get(p['current'].get(row['parent_key']),{})
            if len(hs)>1: reasons.append('conflicting-native-market-observations')
            if mapping.get('status')!='matched' or row['parent_key'] in p['pending']:
                reasons.append('parent-event-not-currently-confirmed:'+mapping.get('status','missing'))
            if not mapping.get('canonical_id'): reasons.append('canonical-event-unavailable')
            if po.get('participants')!=row['participants'] or po.get('registry')!=row['registry']:
                reasons.append('parent-identity-or-registry-changed')
            cid=mapping.get('canonical_id')
            cm=('moneyline-'+digest([cid,'moneyline','full_game'])[:24]
                if cid and row['market_type']=='moneyline' and row['period']=='full_game' else None)
            attached[key]={'native_market_id':row['native_market_id'],'venue':row['venue'],
                'canonical_event_id':cid,'canonical_market_id':cm,'structural_status':'confirmed' if not reasons else 'rejected',
                'reasons':reasons,'sides':row['sides'],'observation_hashes':hs,'parent_mapping':mapping,
                'profile_hash':row['profile']['hash']}
        pairs={}
        for ka,kb in combinations(sorted(attached),2):
            a,b=(d['observations'][d['current'][k][0]] for k in (ka,kb))
            ma,mb=attached[ka],attached[kb]
            # Related listings within one venue are retained above, never new cross-venue opportunities.
            if a['venue']==b['venue'] or a['scope']!=b['scope']: continue
            if not ma['canonical_event_id'] or ma['canonical_event_id']!=mb['canonical_event_id']: continue
            structural=ma['structural_status']==mb['structural_status']=='confirmed'
            settlement=compare_profiles(a['profile'],b['profile'],d['reviews'])
            if not a['rule_binding'] or not b['rule_binding']:
                settlement={**settlement,'status':'UNKNOWN','qualified':False,'conflicts':[],
                    'unknown':[{'condition':'rule_profile_binding','reason':'profile is not bound to current listing rules'}],
                    'reason':'changed or missing listing rules require a new assessment'}
            rel=relationships(a['sides'],b['sides'],a['profile'],b['profile'],a['participants'],settlement)
            eligible=structural and settlement['qualified'] and any(r['complementary_payoffs']=='YES' for r in rel)
            pairid='market-pair-'+digest([ka,kb])[:24]
            row={'id':pairid,'left':ka,'right':kb,'canonical_market_id':ma['canonical_market_id'],
                 'structural_match':structural,'structural_reasons':ma['reasons']+mb['reasons'],
                 'settlement':settlement,'relationships':rel,
                 'qualification':{'eligible_for_fee_arb_evaluation':eligible,
                     'reasons':([] if eligible else ([*ma['reasons'],*mb['reasons']]+
                         ([] if settlement['qualified'] else ['settlement:'+settlement['status']])+
                         ([] if any(r['complementary_payoffs']=='YES' for r in rel) else ['no-proven-complementary-legs']))),
                     'scope':'mapping qualification only; no fees, depth, freshness, ROI or tradability assessment'},
                 'market_hashes':[a['hash'],b['hash']],'parent_snapshot_hash':ph,
                 'matcher_version':VERSION}
            pairs[pairid]=row
        # Explicit withdrawn decisions invalidate formerly qualified pairs as inventory/parents change.
        for pid,old in d['decisions'].items():
            if pid not in pairs:
                pairs[pid]={'id':pid,'structural_match':False,'withdrawn':True,
                    'qualification':{'eligible_for_fee_arb_evaluation':False,'reasons':['current-parent-or-market-pair-unavailable']},
                    'parent_snapshot_hash':ph,'matcher_version':VERSION}
        for pid,row in sorted(pairs.items()):
            old=d['decisions'].get(pid)
            if old and {k:v for k,v in old.items() if k!='revision'}==row: continue
            row['revision']=(old['revision'] if old else 0)+1
            d['revisions'].append({'key':pid,'before':clone(old),'after':clone(row)})
            d['decisions'][pid]=row
        return {'version':VERSION,'parent_snapshot_hash':ph,'markets':clone(attached),
                'pairs':clone(d['decisions']),'reviews':clone(d['reviews'])}

    def approve_compatible(self, left_profile, right_profile, *, actor, reason, source, reviewed_at):
        if not all(isinstance(x,str) and x.strip() for x in (actor,reason,source,reviewed_at)):
            raise ValueError('approval requires actual actor, reason, source and review time')
        dt=datetime.fromisoformat(reviewed_at)
        if dt.utcoffset() is None: raise ValueError('aware review time required')
        profiles={r['profile']['hash']:r['profile'] for r in self._data['observations'].values()}
        status=compare_profiles(profiles[left_profile],profiles[right_profile])['status']
        if status!='COMPATIBLE': raise ValueError('approval cannot override unknown or conflicting rules')
        review={'action':'approve-compatible','profiles':sorted([left_profile,right_profile]),
                'comparator':RULE_VERSION,'actor':actor,'reason':reason,'source':source,'reviewed_at':reviewed_at}
        if review not in self._data['reviews']: self._data['reviews'].append(review)

    # Reuse the established atomic JSON snapshot writer and raw-body deduplication.
    save=Matcher.save
    envelope=Matcher.envelope

    @classmethod
    def load(cls,path):
        def unique(pairs):
            row={}
            for k,v in pairs:
                if k in row: raise ValueError('duplicate store key')
                row[k]=v
            return row
        envelope=json.loads(Path(path).read_text(),object_pairs_hook=unique)
        return cls.from_envelope(envelope)

    @classmethod
    def from_envelope(cls,envelope):
        if digest(envelope['data'])!=envelope['sha256']: raise ValueError('store checksum mismatch')
        d=expand_raw(envelope['data'],envelope.get('raw_payloads',{}))
        if d['schema_version']!=SCHEMA or d['matcher_version']!=VERSION: raise ValueError('unsupported store version')
        for h,r in d['observations'].items():
            validate_market(r)
            if h!=r['hash']: raise ValueError('invalid observation index')
        for k,hs in d['current'].items():
            if not hs or any(d['observations'][h]['key']!=k for h in hs): raise ValueError('invalid current market')
        for h,p in d['parent_snapshots'].items():
            if h!=digest(p) or p['matcher_version']!=EVENT_VERSION: raise ValueError('invalid parent snapshot')
        audit={}
        for rev in d['revisions']:
            k=rev['key']; after=rev['after']
            if rev['before']!=audit.get(k) or after['revision']!=(audit[k]['revision']+1 if k in audit else 1):
                raise ValueError('broken revision history')
            if after['parent_snapshot_hash'] not in d['parent_snapshots']: raise ValueError('missing parent evidence')
            if any(h not in d['observations'] for h in after.get('market_hashes',[])): raise ValueError('missing market evidence')
            audit[k]=after
        if audit!=d['decisions']: raise ValueError('decisions disagree with history')
        result=cls(); result._data=d
        for review in d['reviews']:
            if review['comparator']!=RULE_VERSION: raise ValueError('unsupported review comparator')
            result.approve_compatible(*review['profiles'],**{k:review[k] for k in ('actor','reason','source','reviewed_at')})
        return result
