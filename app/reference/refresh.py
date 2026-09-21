"""Explicit, injected, bounded reference refresh. No default transport or key access."""
from copy import deepcopy
from app.reference.product import MAX_BODY, SOURCES, digest, time

class Refresh:
    def __init__(self, *, max_requests=1, max_credits=1, max_entries=8):
        if not 1<=max_requests<=10 or not 0<=max_credits<=10 or not 1<=max_entries<=32:raise ValueError('Refresh bounds')
        self.max_requests=max_requests;self.max_credits=max_credits;self.max_entries=max_entries
        self.requests=0;self.credits=0;self.cache={};self.ledger=[];self.stopped=False

    def stop(self):self.stopped=True

    async def acquire(self, plan, *, at, transport, retain, approved=False):
        if not approved:raise ValueError('Explicit acquisition approval required')
        if self.stopped:raise ValueError('Refresh stopped')
        p=deepcopy(plan)
        if set(p)-{'provider','bookmakers','markets','max_credits','oddsFormat','sport','eventIds'}:raise ValueError('Unknown plan field; credentials and URLs must not enter retained plan')
        provider=p['provider'];cost=p['max_credits']
        if provider not in SOURCES or not isinstance(cost,int) or cost<0:raise ValueError('Invalid plan')
        if provider=='the_odds_api':
            if p.get('sport') not in ('americanfootball_nfl','americanfootball_ncaaf','basketball_nba','basketball_ncaab','baseball_mlb','icehockey_nhl') or p.get('bookmakers')!='pinnacle' or p.get('markets')!=['h2h'] or cost!=1 or p.get('oddsFormat') not in ('decimal','american'):raise ValueError('Only bounded Pinnacle h2h plan supported')
        else:raise ValueError('Model sources use explicit retained-file import; no approved automated acquisition contract')
        key=digest(p);cached=self.cache.get(key)
        if cached and 0<=(time(at)-time(cached['at'])).total_seconds()<SOURCES[provider]['refresh']:
            return deepcopy(cached['value']) # Original receipt/time retained; never restamped.
        if self.requests>=self.max_requests or self.credits+cost>self.max_credits:raise ValueError('Request or credit bound reached')
        if key not in self.cache and len(self.cache)>=self.max_entries:raise ValueError('Cache bound reached')
        self.requests+=1;self.credits+=cost
        entry=dict(plan=p,at=at,reserved_credits=cost,actual_credits=None,state='reserved',request=self.requests)
        self.ledger.append(entry)
        try:
            retain(deepcopy(entry)) # durable intent BEFORE transport
            value=await transport(deepcopy(p))
            if not isinstance(value['body'],str) or len(value['body'].encode())>MAX_BODY:raise ValueError('Response byte bound')
            headers={k.lower():v for k,v in value.get('headers',{}).items() if k.lower() in ('x-requests-last','x-requests-used','x-requests-remaining','date')}
            value=dict(body=value['body'],status=value['status'],headers=headers,received_at=at)
            last=headers.get('x-requests-last')
            if last is not None:
                actual=int(last)
                if actual<0:raise ValueError('Invalid credit header')
                entry['actual_credits']=actual
                # A failure or missing header never refunds the conservative reservation.
                self.credits+=max(0,actual-cost)
                if actual>cost:self.stopped=True;raise ValueError('Provider exceeded planned credit cost')
            entry.update(state='received',status=value['status'])
            if value['status']!=200:self.stopped=True;raise ValueError('Source response failed; no retry')
            if self.stopped:raise ValueError('Stopped before publication')
            retain(deepcopy(dict(entry,response=value)))
            self.cache[key]=dict(at=at,value=deepcopy(value));return deepcopy(value)
        except Exception:
            entry['state']='failed';self.stopped=True;retain(deepcopy(entry));raise
