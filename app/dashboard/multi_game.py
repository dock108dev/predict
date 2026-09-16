"""Multi-game projection and ranking for the existing opportunity board."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
import json
from app.collection.multi_game import MultiSession, native_identity
from app.collection.transport_session import reopen
from app.dashboard.e6_live import Owner, save_json, digest, verify_all_saved
from app.dashboard import e6_real as historical
from app.opportunities.board import evaluate, contracts

OUTPUT=historical.ROOT/'evidence/multi-game/sessions'


def configuration():
    from app.dashboard.e6_live import configuration as original
    spec=original();now=datetime.now(timezone.utc)
    # Bootstrap fields satisfy the existing single-session contract. Actual selected
    # event identities are recorded independently before any subscriptions.
    spec.update(duration=175,scheduled_start=(now+timedelta(days=1)).isoformat(),capture_authorization='One multi-game verification run, maximum 180 seconds including discovery; zero additional spending',mapping_revision='multi-game-native-1')
    spec['prediction']=dict(spec['prediction'],messages=600,connections=2,discovery_requests=64,session_bytes=16*1024*1024)
    spec['multi_game_limits']=dict(max_games=6,minimum_seconds_before_kickoff=300,aggregate_requests=128,aggregate_connections=4,concurrent_sockets=2,aggregate_messages=1200,aggregate_body_bytes=32*1024*1024,ingress_records=2048,ingress_bytes=16*1024*1024,journal_records=4096,journal_bytes=32*1024*1024)
    # run_spec validator only accepts its established top-level fields.
    return spec


class MultiOwner(Owner):
    def __init__(self,*args,personal_beta=False,session_factory=MultiSession,**kwargs):
        super().__init__(*args,**kwargs)
        self.personal_beta=personal_beta;self.session_factory=session_factory;self.starting=False
    def active(self):return self.starting or super().active()
    def saved(self):
        return [p.parent.name for p in sorted(self.output.glob('*/manifest.json'),key=lambda p:(p.parent/'run-spec.json').stat().st_mtime)]
    async def start(self,max_games=6,duration=175):
        if type(max_games) is not int or not 1<=max_games<=6:raise ValueError('Maximum games must be 1 to 6')
        if type(duration) is not int or not 1<=duration<=180:raise ValueError('Duration must be 1 to 180 seconds')
        async with self.lock:
            if self.active():raise ValueError('A scan is already running or saving')
            if not self.personal_beta and (self.session is not None or (self.output/'attempt.json').exists()):raise ValueError('This slice’s one verification scan has been consumed')
            spec=self.spec_factory();limits=spec.pop('multi_game_limits')
            spec['duration']=duration;limits['max_games']=max_games
            if self.personal_beta:spec['capture_authorization']='Personal beta: explicit owner Start; bounded prediction-only scan; zero additional spending'
            self.error=None;self.starting=True
            try:
                self.session=self.session_factory(spec,self.output/'pending',self.endpoints)
                self.session.max_games=max_games
                folder=self.output/self.session.sid;folder.mkdir();self.session.output=folder
                save_json(folder/'run-record.json' if self.personal_beta else self.output/'attempt.json',dict(session=self.session.sid,at=datetime.now(timezone.utc).isoformat(),mode='personal-beta' if self.personal_beta else 'one-attempt',limits=limits))
                save_json(folder/'run-spec.json',spec);save_json(folder/'aggregate-limits.json',limits)
                await self.session.start()
            except Exception:
                self.error='Start unavailable; run record retained. No automatic retry.'
                raise ValueError(self.error) from None
            finally:self.starting=False
            self.finalizer=__import__('asyncio').create_task(self.finish(folder))
            return self.session.sid
    async def finish(self,folder):
        try:
            await self.session.task
            path=self.session.journal.path
            path.rename(folder/'observations.jsonl');self.session.journal.path=folder/'observations.jsonl'
            saved=reopen(self.session.journal.path);save_json(folder/'saved-observations.json',saved)
            # Native replay handles multiplexed subscriptions; health-derived records
            # are counted separately, never passed off as new wire observations.
            from app.collection.native_replay import verify_native_saved
            replay=verify_native_saved(saved);save_json(folder/'replay.json',replay)
            save_json(folder/'manifest.json',dict(journal_chain=saved['sha256'],files={n:digest(folder/n) for n in ('run-spec.json','observations.jsonl','saved-observations.json','replay.json','selection.json','aggregate-limits.json')}))
        except Exception as exc:self.error='Capture retained; saved finalization unavailable: '+type(exc).__name__
    def status(self):
        s=self.session;active=self.active()
        return dict(state=('saving' if active and s and s.state=='stopped' else s.state) if s else 'idle',active=active,operating_mode='personal-beta' if self.personal_beta else 'one-attempt',start_available=not active and (self.personal_beta or s is None and not (self.output/'attempt.json').exists()),error=self.error,saved=self.saved(),session=None if s is None else s.sid,cleanup_complete=not active and (s is None or s.cleanup_complete),coverage=getattr(getattr(s,'discovery',None),'coverage',None))


def saved_rows(folder):
    manifest=json.loads((folder/'manifest.json').read_text())
    for name,sha in manifest['files'].items():
        if name not in ('run-spec.json','observations.jsonl','saved-observations.json','replay.json','selection.json','aggregate-limits.json'):raise ValueError('invalid saved name')
        if digest(folder/name)!=sha:raise ValueError('saved file changed')
    saved=reopen(folder/'observations.jsonl')
    if saved['sha256']!=manifest['journal_chain'] or saved['state']!='complete':raise ValueError('saved identity mismatch')
    return saved


def project_game(rows,game,live=False):
    """Filter by BOTH native event and market before projecting any quote packets."""
    sides={v:{k.split(':',1)[1]:(s['participant'],s.get('native_label',k.split(':',1)[1].upper())) for k,s in game['sides'].items() if k.startswith(v+':')} for v in historical.VENUES}
    health=dict.fromkeys(historical.VENUES,'idle');latest={};previous={};timeline=[];selected=[];metadata={}
    for row in rows:
        typ=row['type'];v=row.get('source');at=row['observed_at']
        if typ in ('market_selected','prediction_book'):
            raw=row['market']['raw'] if typ=='market_selected' else row['book']['raw'];ref=raw['ref']
            if v not in game['sources'] or any(ref[k]!=game['sources'][v][k] for k in ('event_id','market_id')):continue
            if row.get('game_id',game['id'])!=game['id']:raise ValueError('cross-event record')
            selected.append(row)
            if typ=='market_selected':metadata[v]=row
        if typ=='source_health' and v in health:health[v]=row['state']
        if typ=='prediction_book':
            latest[v]=historical.project_book(row,previous.get(v),sides);previous[v]=row
        if typ not in ('session_started','prediction_book','source_health','session_finished'):continue
        cards=[]
        for venue in historical.VENUES:
            b=deepcopy(latest.get(venue))
            if b and b['market_state']=='unknown' and venue in metadata:
                b['market_state']=metadata[venue]['market']['state']
                b['market_state_basis']='Latest retained listing at '+metadata[venue]['observed_at']
            age=None if b is None else historical.fixed(historical.exact_time(at)-historical.exact_time(b['received_at']))
            cards.append(dict(venue=venue,label=historical.LABELS[venue],book=b,connection=health[venue],age_seconds=age,receipt_stale=age is not None and Decimal(age)>30))
        timeline.append(dict(id=row.get('ingress_id','finished'),at=at,cards=cards,label=typ))
    if live and timeline:
        p=deepcopy(timeline[-1]);p['id']='current';p['at']=datetime.now(timezone.utc).isoformat()
        for c in p['cards']:
            if c['book']:
                c['age_seconds']=historical.fixed(historical.exact_time(p['at'])-historical.exact_time(c['book']['received_at']));c['receipt_stale']=Decimal(c['age_seconds'])>30
        timeline.append(p)
    return timeline,selected


def default_point(timeline):
    # Latest simultaneously usable observation, explicitly historical after Stop.
    usable=[p for p in timeline if all(c['book'] and c['connection']=='connected' and not c['receipt_stale'] and c['book']['sync']=='synchronized' for c in p['cards'])]
    return (usable or timeline)[-1]


def game_calculation(point,rows,game,quantity,scenario,probability=None,contract=None):
    selected=contract or next(k for k,s in game['sides'].items() if s.get('native_label')=='Long')
    r=evaluate(point,rows,quantity,scenario,probability,selected,game)
    cs=contracts(point,game);q=Decimal(quantity)
    # One visible requested basis; actual modeled quantity is capped by real depth.
    for c in r['candidates']:
        capacities=[Decimal(cs[l['id']]['visible_size'] or '0') for l in c['legs']]
        actual=min([q,*capacities]).to_integral_value(rounding=ROUND_FLOOR)
        if 0<actual<q:
            adjusted=evaluate(point,rows,str(actual),scenario,None,selected,game)
            c.update(next(x for x in adjusted['candidates'] if x['id']==c['id']))
        c.update(requested_quantity=quantity,modeled_quantity=str(actual),depth_limited=actual<q,usable=actual>0 and not any(l['warnings'] for l in c['legs']) and 'Books more than 5 seconds apart at cutoff' not in c['reasons'])
    cap=Decimal(cs[selected]['visible_size'] or '0');actual=min(q,cap).to_integral_value(rounding=ROUND_FLOOR)
    if 0<actual<q:r['ev']=evaluate(point,rows,str(actual),scenario,probability,selected,game)['ev']
    r['ev'].update(modeled_quantity=str(actual),depth_limited=actual<q,usable=actual>0 and not r['ev']['leg']['warnings'])
    r.update(game=game,coverage=dict(limitation='Bounded native books; selected cutoffs only. No claim of complete upstream history.',completeness='Historical results are never currently executable.'))
    return r


def rank_filter(rows,sort='roi',positive=False,venue='',freshness='',search=''):
    def value(r):return r.get('return_pct' if sort=='roi' else 'profit')
    rows=[r for r in rows if (not positive or r['profit'] is not None and Decimal(r['profit'])>0) and (not venue or venue==r['venue_pair'] or venue in r['venues']) and (not freshness or r['usable']==(freshness=='usable')) and search.casefold() in r['game_title'].casefold()]
    # Unsupported values never receive a numeric zero. Raw gaps have their own class.
    def key(r):
        n=value(r)
        cls=0 if r['status']=='Qualified' else 1 if n is not None else 2
        return (not r['usable'],cls,n is None, Decimal(n).copy_negate() if n is not None else Decimal(0),r['id'])
    return sorted(rows,key=key)
