"""Immutable r2 discovery/credit contract; no I/O or credential access."""
from copy import deepcopy
from decimal import Decimal
from .odds_http import HTTPPolicy, Budget, BudgetStop
from app.reference.product import SPORT_KEYS
from app.reference.odds_bindings import BOOKS

STARTUP='sports-quota-once-v1'
NATIVE='bounded-open-catalog-v1'
NATIVE_REQUEST_CAPS={'kalshi':58,'polymarket_us':54}
NATIVE_V2='bounded-open-catalog-v2'
# Historical v2: smaller pages did not solve single-event payload size.
NATIVE_V2_CAPS={'kalshi':58,'polymarket_us':3*(75+6)*2}
from .native_payload import POLICY as NATIVE_V4, REQUEST_CAPS as NATIVE_V3_CAPS
from .native_selectors import POLICY as DIRECTED, policy as discovery_policy, REQUEST_CAPS as DIRECTED_CAPS
NATIVE_V3='bounded-open-catalog-v3'
def bounded_native(spec):return discovery_policy(spec) in (NATIVE,NATIVE_V2,NATIVE_V3,NATIVE_V4,DIRECTED,'polymarket-us-metadata-delivery-v1')
def isolated_native(spec):return discovery_policy(spec) in (NATIVE_V2,NATIVE_V3,NATIVE_V4,DIRECTED,'polymarket-us-metadata-delivery-v1')
def native_caps(spec):
    if spec.get('source_session',{}).get('coverage_policy')=='v1-counterpart-completion-1':return dict(kalshi=10,polymarket_us=10)
    if spec.get('source_session',{}).get('coverage_policy')=='v1-missing-pairs-1':return dict(kalshi=151,polymarket_us=51)
    if spec.get('native_discovery',{}).get('native_scopes'):
        return dict(kalshi=48,polymarket_us=48)
    if spec.get('native_discovery',{}).get('slice')=='us-event-delivery-diagnostic-v1':
        return dict(kalshi=0,polymarket_us=1,novig=0,prophetx=0)
    from .native_target import enabled as target
    if target(spec):return {v:1 for v in ('kalshi','polymarket_us')}
    from .native_books import enabled, CAPS
    if enabled(spec):return CAPS
    from .native_selectors import gap_enabled,GAP_CAPS
    if gap_enabled(spec):return GAP_CAPS
    if discovery_policy(spec)==DIRECTED:return {'kalshi':36,'polymarket_us':34} if spec.get('native_discovery') else DIRECTED_CAPS
    if discovery_policy(spec)in (NATIVE_V3,NATIVE_V4):return NATIVE_V3_CAPS
    return NATIVE_V2_CAPS if isolated_native(spec) else NATIVE_REQUEST_CAPS


def dynamic(spec):return spec.get('source_session',{}).get('quota_startup')==STARTUP

def policy(settings):
    p=deepcopy(settings['http'])
    if settings.get('quota_startup')==STARTUP:
        if any(p[k] is not None for k in ('initial_used','initial_remaining')):
            raise ValueError('Quota observations belong to execution evidence, not authorization')
        p.update(initial_used=0,initial_remaining=0)
    for k in ('dollars','dollars_per_credit'):p[k]=Decimal(p[k])
    return HTTPPolicy(**p)

def totals(settings):
    cycles=settings['max_cycles'];events=settings['event_limit']
    if settings.get('coverage_policy')=='v1-counterpart-completion-1':
        return dict(startup=1,discovery=2,paid=4,requests=7,credits=8)
    if settings.get('coverage_policy')=='v1-missing-pairs-1':
        return dict(startup=1,discovery=6,paid=24,requests=31,credits=2*sum(len(s['markets']) for s in settings['scopes'])+12)
    return dict(startup=1,discovery=cycles*len(settings['scopes']),
        paid=cycles*len(settings['scopes'])*events,
        requests=1+cycles*len(settings['scopes'])*(1+events),
        credits=cycles*events*sum(len(s['markets']) for s in settings['scopes']))

def validate_static(settings):
    if settings.get('quota_startup')!=STARTUP or settings.get('native_discovery') not in (NATIVE,NATIVE_V2,NATIVE_V3,NATIVE_V4,DIRECTED):
        raise ValueError('Unknown acquisition contract')
    if 'quota_observed_at' in settings or 'native_selection' in settings:
        raise ValueError('Execution observations cannot alter the static acquisition contract')
    p=policy(settings);t=totals(settings)
    if settings.get('coverage_policy')=='v1-counterpart-completion-1':
        if settings['max_cycles']!=2 or settings['event_limit']!=1 or settings['scopes']!=[dict(sport=s,markets=['spreads_h1','totals_h1'],event_ids=[]) for s in ('NFL','NCAAF')]:raise ValueError('Exact football H1 counterpart operations required')
    elif settings.get('coverage_policy')=='v1-missing-pairs-1':
        if settings['max_cycles']!=2 or settings['event_limit']!=1 or len(settings['scopes'])!=6 or set(s['sport'] for s in settings['scopes'])!=set(SPORT_KEYS):raise ValueError('Exact six-sport two-cycle coverage required')
    elif settings['max_cycles']!=3 or settings['event_limit']!=1 or len(settings['scopes'])!=6:
        raise ValueError('Integrated acquisition requires six sports and three bounded cycles')
    if (p.requests,p.credits,p.reserve_per_request,p.retries)!=(t['requests'],t['credits'],max(len(s['markets']) for s in settings['scopes']),0):
        raise ValueError('Request matrix and allowance disagree')
    if p.dollars or p.dollars_per_credit or any(s['event_ids'] for s in settings['scopes']):
        raise ValueError('Zero spend and runtime event selection required')

def request_cost(settings,target):
    path,params=target['path'],target['params']
    if path=='/v4/sports' and params=={'all':'true'}:return 0
    for scope in settings['scopes']:
        if settings.get('coverage_policy')=='v1-missing-pairs-1':
            from app.reference.odds_bindings import CHAMPIONSHIPS
            if path=='/v4/sports/'+CHAMPIONSHIPS[scope['sport']]+'/odds' and params==dict(bookmakers=','.join(BOOKS),markets='outrights',oddsFormat='decimal',dateFormat='iso'):return 1
        prefix='/v4/sports/'+SPORT_KEYS[scope['sport']]+'/events'
        if path==prefix and params=={'dateFormat':'iso'}:return 0
        if path.startswith(prefix+'/') and path.endswith('/odds'):
            import re
            if not re.fullmatch('[A-Za-z0-9_-]{1,160}',path[len(prefix)+1:-5]):break
            expected=dict(bookmakers=','.join(BOOKS),markets=','.join(scope['markets']),oddsFormat='decimal',dateFormat='iso',includeSids='true')
            if params!=expected:break
            return len(scope['markets']) # five books => one region; returned unique markets <= requested
    raise ValueError('Request outside approved endpoint/market scope')

class StartupBudget(Budget):
    def __init__(self,policy):super().__init__(policy);self.baseline_pending=True
    def reserve(self,credits=None):
        if self.baseline_pending and (credits!=0 or self.requests):
            raise BudgetStop('fresh_quota_required')
        return super().reserve(credits)
    def reconcile(self,headers):
        if not self.baseline_pending:return super().reconcile(headers)
        values={}
        import re
        for k in ('x-requests-used','x-requests-remaining','x-requests-last'):
            found=[v for name,v in headers if name==k]
            if len(found)!=1 or not re.fullmatch('[0-9]{1,12}',found[0]):
                self.reason='quota_unknown_or_duplicate';return
            values[k]=int(found[0])
        if values['x-requests-last']!=0:
            self.credits+=values['x-requests-last'];self.reason='unexpected_startup_charge';return
        self.used=values['x-requests-used'];self.remaining=self.reported_remaining=values['x-requests-remaining']
        self.baseline_pending=False
        if self.remaining<self.policy.credits:self.reason='insufficient_startup_allowance'
    def snapshot(self):return dict(super().snapshot(),baseline_pending=self.baseline_pending)
