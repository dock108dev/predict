"""Bounded current provider, commit/update and immutable lease interfaces.

No source workers, durable cursor, history load, credential access or archive.
All state transitions occur synchronously on the server event loop, including
lease validation/admission; a notification follows the committed state swap.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import time
from uuid import uuid4
from aiohttp import web
from .current_contract import VERSION, VENUES, serialize, packed, quotes_of, manual_scenario, stamp, snapshot_inputs
from .local_security import HEADERS, read_json, PublicRequestError
from .current_response import CurrentResponse

CURRENT_KEY=web.AppKey('current',object)
MAX_STREAMS=8
STREAM_WRITE_SECONDS=2


def unavailable():
    now=datetime.now(timezone.utc).isoformat()
    return dict(schema=VERSION,mode='current',runtime_id=str(uuid4()),state_revision=1,projected_at=now,clock_at=now,
                state='unavailable',events=[],source_status={v:dict(state='unavailable',reason_code='current_provider_pending',
                reason='Automatic current prices are not connected yet.',next_due_at=None) for v in VENUES})


class CurrentStateProvider:
    """Explicit current-state absence until a normalized provider is injected."""
    allow_synthetic=False

    def initial_state(self):
        return unavailable()

    async def close(self):
        pass


class SelectionError(Exception):
    def __init__(self,status,code,reason,**extra):
        self.status=status; self.body=dict(error=code,reason=reason,**extra)


class CurrentStore:
    def __init__(self,provider=None,*,monotonic=time.monotonic,lease_ttl=300):
        self.provider=provider or CurrentStateProvider()
        self.monotonic=monotonic
        if not 0<lease_ttl<=300:raise ValueError('Lease TTL must be at most 300 seconds')
        self.ttl=lease_ttl;self.leases={};self.clients={};self.subscribers=set();self.closed=False
        initial=self.provider.initial_state()
        retained=initial if getattr(self.provider,'retained_bootstrap',False) else None
        if retained is not None:
            # Opt-in retained restoration does not block listener setup on a
            # financial projection. Ordinary source providers stay synchronous.
            initial=dict(initial,runtime_id='retained-loading:'+str(uuid4()),state_revision=1,state='unavailable',events=[],comparison_profiles={})
        self._state=serialize(initial,allow_synthetic=self.provider.allow_synthetic)
        from .current_incremental import signatures
        self._fingerprints=signatures(initial,self._state['estimate_policy']['revision'])
        self._group_bytes={(e['id'],g['id']):len(packed(g))+256*sum(len(quotes_of(o)) for o in g['outcomes']) for e in self._state['events'] for g in e['groups']}
        self.projection_metrics=dict(projected_groups=0,reused_groups=0)
        self._event_versions={e['id']:self._state['state_revision'] for e in self._state['events']}
        self._removed_events={};self._changes_floor=self._state['state_revision']
        self._age_origin=self.monotonic();self._clock_origin=stamp(self._state['clock_at'])
        self._comparison_body_cache=None
        self._publication_generation=0
        self._current_body_cache=None;self._current_timer=None;self._details_cache=None
        from .current_encoded import EncodedBodies
        self.encoded_bodies=EncodedBodies()
        from .comparison_jobs import ComparisonJobs
        self.comparison_jobs=ComparisonJobs()
        self._calculation_epoch=0;self._input_epoch=0;self._stopping=False;self._source_stopping=False;self._shutdown_health=None
        from .current_temporal import TemporalOwner
        self.temporal=TemporalOwner(self)
        self._comparison_timer=None
        self._index_deadline()
        from .current_admission import AdmissionOwner
        self.admission=AdmissionOwner(self)
        self._retained_startup = retained
        if retained is not None:
            try:asyncio.get_running_loop()
            except RuntimeError:pass  # Ordinary create_app runs before the loop.
            else:self.start_retained()

    def start_retained(self):
        if self._retained_startup is not None:
            self.admission.submit(self._retained_startup)
            self._retained_startup = None

    def _index_deadline(self):
        from .current_deadlines import next_deadline
        self._economic_deadline=next_deadline(self._state)
        self._economic_invalidated=False

    def validation_clock(self):
        return self._clock_origin+timedelta(seconds=max(0,int(self.monotonic()-self._age_origin)))

    def economic_valid(self,epoch):
        # Revoke before expensive reconstruction. Never update captured result
        # clocks or acknowledge a source admission on this validation path.
        from app.comparison.estimated_policy import load
        due=self._economic_deadline is not None and self.validation_clock()>=self._economic_deadline
        if due or load().to_dict()!=self._state.get('estimate_policy'):
            self._revoke_economic()
            return False
        return not self.closed and not self._stopping and not self._source_stopping and not self._economic_invalidated and self._calculation_epoch==epoch

    def _revoke_economic(self):
        if not self._economic_invalidated:
            self._economic_invalidated=True;self._calculation_epoch+=1
            self.comparison_jobs.invalidate();self._clear_comparison_body()
            self.publish()

    def require_economic(self):
        if self.closed or self._stopping or self._source_stopping:
            raise SelectionError(410,'selection_expired','Current runtime is stopping',**self.notice())
        if not self.economic_valid(self._calculation_epoch):
            self.temporal.request()
            failed=self.temporal.failure is not None
            raise SelectionError(503,'temporal_failed' if failed else 'temporal_pending',
                'Temporal reconstruction failed; estimates remain unavailable until a valid new admission' if failed else
                'Inputs crossed an eligibility boundary; estimates are withheld while rebuilding',
                retry_after_seconds=1,**self.notice())

    def _install_temporal(self,result):
        state,fingerprints,bounds,dirty,metrics,deadline,changed=result
        self._clear_comparison_body()
        self._clear_current_body();self._details_cache=None
        versions=dict(self._event_versions)
        for eid in dirty:versions[eid]=state['state_revision']
        self._state,self._fingerprints,self._group_bytes,self._event_versions=state,fingerprints,bounds,versions
        self._publication_generation+=1
        if metrics is not None:self.projection_metrics=metrics
        self._economic_deadline=deadline;self._economic_invalidated=False
        if changed:
            self._calculation_epoch+=1;self.comparison_jobs.invalidate();self.publish()
        elif self.temporal.active is not None and self.temporal.active['previous'] is not state:
            # Ready lifecycle notice also clears conservative pending refusals.
            self.publish()

    def _clear_comparison_body(self):
        timer=getattr(self,'_comparison_timer',None)
        if timer is not None:timer.cancel();self._comparison_timer=None
        cached=self._comparison_body_cache
        self._comparison_body_cache=None
        if cached is not None and hasattr(cached[2],'release'):cached[2].release()

    def encoded_transport_snapshot(self,request=None,*,league=None,search=''):
        self.refresh_age();self.require_economic()
        epoch=self._calculation_epoch
        scope=(self._publication_generation,league,search)
        cached=self._current_body_cache
        if cached is not None and cached[0]==scope and time.monotonic()<cached[1].expires_at:
            owner=cached[1]
        else:
            self._clear_current_body()
            value=self._state
            if league or search:
                events=[e for e in value['events'] if (not league or e['league']==league) and search.lower() in e['title'].lower()]
                value=dict(value,events=events)
                if value.get('comparison_profiles'):
                    from app.comparison.shared_templates import subset
                    value['comparison_profiles']=subset(value['comparison_profiles'],dict(outcomes=[o for e in events for g in e['groups'] for o in g['outcomes']]))
            owner=self.encoded_bodies.encode(value)
            self._current_body_cache=(scope,owner)
            self._current_timer=asyncio.get_running_loop().call_later(self.encoded_bodies.CACHE_SECONDS,self._clear_current_body)
        try:self.require_economic()
        except BaseException:self._clear_current_body();raise
        return self.encoded_bodies.payload(owner,request,**self.delivery_guards(epoch))

    def delivery_guards(self,epoch):
        state=self._state
        return dict(valid=lambda:self.economic_valid(epoch),
            alive=lambda:not (self.closed or self._stopping or self._source_stopping),
            capture={'Runtime':state['runtime_id'],'Revision':state['state_revision'],
                'Epoch':epoch,'Clock':state['clock_at'],
                'Eligibility-Deadline':None if self._economic_deadline is None else self._economic_deadline.isoformat()})

    def _clear_current_body(self):
        if self._current_timer is not None:self._current_timer.cancel();self._current_timer=None
        cached=self._current_body_cache;self._current_body_cache=None
        if cached is not None:cached[1].release()

    def comparison_body(self,key,build):
        """One bounded encoded read, keyed by the entire owned publication.

        Policy/query key includes financial filters and delivery context. The
        immutable state object binds all native/content/profile/clock inputs;
        temporal refresh runs before lookup. No cache crosses a state swap.
        """
        cached=self._comparison_body_cache
        if cached is not None and cached[0]==self._publication_generation and cached[1]==key:
            expiry=getattr(cached[2],'expires_at',None)
            if expiry is None or time.monotonic()<expiry:return cached[2]
        self._clear_comparison_body()
        captured=self._publication_generation;body=build()
        from .current_contract import MAX_BYTES
        if self._publication_generation==captured and len(body)<=MAX_BYTES:
            self._comparison_body_cache=(captured,key,body)
            if hasattr(body,'expires_at'):
                self._comparison_timer=asyncio.get_running_loop().call_later(
                    self.encoded_bodies.CACHE_SECONDS,self._clear_comparison_body)
        return body

    def snapshot(self):
        self.refresh_age();self.require_economic()
        return deepcopy(self._state)

    def encoded_snapshot(self):
        # Encoding is synchronous on the service loop; no caller receives a
        # mutable state reference, and no full defensive snapshot is needed.
        self.refresh_age();self.require_economic()
        return packed(self._state)

    def changed_event_ids(self,runtime_id,revision):
        state=self._state
        if runtime_id!=state['runtime_id'] or revision<self._changes_floor or revision>state['state_revision']:return None
        return {eid for eid,at in self._event_versions.items() if at>revision}|{eid for eid,at in self._removed_events.items() if at>revision}

    def encoded_changes(self,runtime_id,revision):
        return packed(self.changes_value(runtime_id,revision))

    def encoded_transport_changes(self,runtime_id,revision,request=None):
        value=self.changes_value(runtime_id,revision);epoch=self._calculation_epoch
        owner=self.encoded_bodies.encode(value)
        try:self.require_economic()
        except BaseException:owner.release();raise
        return self.encoded_bodies.payload(owner,request,adopt=True,**self.delivery_guards(epoch))

    def changes_value(self,runtime_id,revision):
        self.refresh_age();self.require_economic()
        state=self._state
        if runtime_id!=state['runtime_id'] or revision<self._changes_floor or revision>state['state_revision']:
            return state
        return dict(schema='predict-current-changes-1',base_revision=revision,
            snapshot={k:v for k,v in state.items() if k!='events'},
            events=[e for e in state['events'] if self._event_versions.get(e['id'],0)>revision],
            removed_events=[eid for eid,at in self._removed_events.items() if at>revision])

    def refresh_age(self):
        try:asyncio.get_running_loop()
        except RuntimeError:return self._refresh_age_sync()
        if self.closed or self._stopping or self._source_stopping:return
        self.economic_valid(self._calculation_epoch)
        from app.comparison.estimated_policy import load
        if self.validation_clock()>stamp(self._state['clock_at']) or load().to_dict()!=self._state['estimate_policy']:
            self.temporal.request()

    def _refresh_age_sync(self):
        elapsed=max(0,int(self.monotonic()-self._age_origin))
        clock=self._clock_origin+timedelta(seconds=elapsed)
        from app.comparison.estimated_policy import load
        policy_changed = load().to_dict() != self._state.get('estimate_policy')
        if clock<=stamp(self._state['clock_at']) and not policy_changed:return
        self._clear_comparison_body()
        self._clear_current_body();self._details_cache=None
        # Eligibility transitions and clock-bound financial frames use the same
        # projection policy as the asynchronous temporal owner.
        from .current_incremental import aged, clock_bound
        state=dict(self._state,clock_at=clock.isoformat(),events=[]);changed=policy_changed
        old_clock=stamp(self._state['clock_at'])
        for event in self._state['events']:
            groups=[]
            for group in event['groups']:
                value,transition=aged(group,clock,old_clock,state.get('comparison_profiles'),event)
                groups.append(value);changed=changed or transition
            state['events'].append(dict(event,groups=groups))
        refresh_frames=clock!=old_clock and any(clock_bound(g) for e in state['events'] for g in e['groups'])
        if changed or refresh_frames:
            if changed:
                self._calculation_epoch+=1;self.comparison_jobs.invalidate()
                state['state_revision']+=1
            # Every dependent result is rebuilt from its original bound inputs,
            # including engine legs whose other quote became stale. Leases stay frozen.
            from .current_incremental import project
            state,fingerprints,bounds,dirty,metrics=project(snapshot_inputs(state,copy_graph=False),self._state,self._fingerprints,self._group_bytes,allow_synthetic=self.provider.allow_synthetic,borrow_profiles=True)
            self._fingerprints,self._group_bytes,self.projection_metrics=fingerprints,bounds,metrics
            for eid in dirty:self._event_versions[eid]=state['state_revision']
        self._state=state
        self._publication_generation+=1
        if changed or self._economic_invalidated or (
                self._economic_deadline is not None and clock>=self._economic_deadline):
            self._index_deadline()
        if changed:self.publish()

    def publish(self):
        for queue in self.subscribers:
            if queue.full():queue.get_nowait()
            queue.put_nowait(self.notice())

    def notice(self):
        return dict({k:self._state[k] for k in ('schema','runtime_id','state_revision')},
            input_epoch=self._input_epoch,eligibility='pending' if self._economic_invalidated else 'ready',
            calculation_epoch=self._calculation_epoch)

    def admit_shutdown_health(self,states):
        """Synchronous health-only acknowledgement after publication revocation.

        This admits source safety independently of complete financial Current.
        It cannot admit a packet, change an input epoch, or publish estimates.
        Reducer health swaps only after this strict bounded admission succeeds.
        """
        if not (self._stopping or self._source_stopping) or self.closed:raise ValueError('Shutdown health boundary required')
        envelope=dict({k:v for k,v in self._state.items() if k not in ('events','comparison_profiles','estimate_policy')},
            events=[],source_status=states,state='stopped')
        from app.comparison.estimated_policy import EstimatePolicy
        admitted=serialize(envelope,allow_synthetic=self.provider.allow_synthetic,
            estimate_policy=EstimatePolicy.from_dict(self._state['estimate_policy']))
        self._shutdown_health=admitted['source_status']
        return True

    def commit(self,raw):
        if self.closed or self._stopping or (self._source_stopping and raw.get('runtime_id')==self._state['runtime_id']):
            raise ValueError('Current store is closed or stopping')
        self._clear_comparison_body()
        # serialize owns the defensive deep copy; only the clock changes here.
        raw=dict(raw)
        evaluated=self._clock_origin+timedelta(seconds=max(0,int(self.monotonic()-self._age_origin)))
        if raw.get('runtime_id')==self._state['runtime_id'] and stamp(raw['clock_at'])<evaluated:raw['clock_at']=evaluated.isoformat()
        from .current_incremental import project
        candidate,fingerprints,bounds,dirty,metrics=project(raw,self._state,self._fingerprints,self._group_bytes,allow_synthetic=self.provider.allow_synthetic)
        from .current_deadlines import next_deadline
        deadline=next_deadline(candidate)
        return self._install_admission(candidate,fingerprints,bounds,dirty,metrics,deadline)

    def _install_admission(self,candidate,fingerprints,bounds,dirty,metrics,deadline,*,owned_generation=None):
        """Validate then install one complete admitted graph without an await."""
        old=self._state
        if candidate['runtime_id']==old['runtime_id']:
            if candidate['state_revision']<=old['state_revision']:
                return False  # Duplicate/regressing notices never replace a commit.
            previous={x['quote']['id']:x['quote'] for x in self.index(old).values()}
            for x in self.index(candidate).values():
                q=x['quote'];prev=previous.get(q['id'])
                if prev:
                    if q['revision']<prev['revision']:raise ValueError('Quote revision regressed')
                    # Receipt/projection clocks alone do not reprice a quote.
                    content=lambda v:dict({k:v.get(k) for k in ('original','source','state','rule_note','binding','calculation_inputs','depth','freshness_policy','rules_differ','cost_note','sharp_reference','occurrence_link')},source_time_kind=v['times']['source_time_kind'])
                    if q['revision']==prev['revision'] and content(q)!=content(prev):raise ValueError('Quote changed without a coherent revision')
                    if q['revision']>prev['revision'] and content(q)==content(prev):raise ValueError('Heartbeat cannot reprice a quote')
                    new=q.get('book_confirmation');prior=prev.get('book_confirmation')
                    if new and prior and new!=prior:
                        if new['generation']<prior['generation'] or stamp(new['confirmed_at'])<=stamp(prior['confirmed_at']) or new['payload_sha256']==prior['payload_sha256']:
                            raise ValueError('Replayed or regressed book confirmation')
                    if q['times']['source_at'] is not None and q['times']['source_at']!=prev['times']['source_at'] and q['original']==prev['original'] and q.get('observation_time_evidence') is None:
                        raise ValueError('Identical repeat cannot reset source age without explicit observation-time evidence')
        else:
            self.leases.clear();self.clients.clear()
        if candidate['runtime_id']!=old['runtime_id']:
            self._event_versions={};self._removed_events={};self._changes_floor=candidate['state_revision']
        present={e['id'] for e in candidate['events']}
        for eid in set(self._event_versions)-present:
            self._removed_events[eid]=candidate['state_revision'];self._event_versions.pop(eid,None)
        for eid in dirty| (present-set(self._event_versions)):
            self._event_versions[eid]=candidate['state_revision'];self._removed_events.pop(eid,None)
        if len(self._removed_events)>2000:
            oldest=sorted(self._removed_events,key=self._removed_events.get)[:-2000]
            self._changes_floor=max(self._changes_floor,max(self._removed_events[eid] for eid in oldest))
            for eid in oldest:self._removed_events.pop(eid)
        self._fingerprints,self._group_bytes,self.projection_metrics=fingerprints,bounds,metrics
        if owned_generation is None:self.admission.supersede()
        self.temporal.invalidate();self._input_epoch+=1
        if self._source_stopping:
            # Only a fully admitted new runtime restores publication owners.
            from .current_temporal import TemporalOwner
            from .comparison_jobs import ComparisonJobs
            from .current_encoded import EncodedBodies
            self.temporal=TemporalOwner(self);self.comparison_jobs=ComparisonJobs();self.encoded_bodies=EncodedBodies()
            from .current_admission import AdmissionOwner
            self.admission=AdmissionOwner(self)
            self._source_stopping=False;self._shutdown_health=None
        self._state=candidate
        self._publication_generation+=1
        self._clear_comparison_body()
        self._clear_current_body();self._details_cache=None
        self._economic_deadline=deadline;self._economic_invalidated=False
        self._calculation_epoch+=1;self.comparison_jobs.invalidate()
        if owned_generation is None:
            self._age_origin=self.monotonic();self._clock_origin=stamp(candidate['clock_at'])
        # Owned calculation can take many real clock turns. Its captured
        # financial instant never resets the running validation clock.
        self.publish()
        return True

    @staticmethod
    def index(state):
        result={}
        for e in state['events']:
            for g in e['groups']:
                for o in g['outcomes']:
                    for q in quotes_of(o):
                        if q['id'] in result:raise ValueError('Instrument identity occurs twice')
                        # Hold just this event/group/outcome context, not the catalog.
                        result[q['id']]=dict(event={k:v for k,v in e.items() if k!='groups'},
                            group={k:v for k,v in g.items() if k!='outcomes'},
                            outcome={k:v for k,v in o.items() if k not in ('quotes','alternatives')},
                            quote=q,comparisonQuotes=o['quotes'],alternatives=o.get('alternatives',{}))
        return result

    def details(self, request):
        required={'runtime_id','state_revision','quote_id'}
        if not isinstance(request,dict) or set(request)-required-{'ceiling','buffer','request_generation','quote_revision','pair_id','pair_revision','objective','opposing_quote_id','opposing_quote_revision'} or not required<=set(request):
            raise PublicRequestError('Exact current Details context required')
        if any(not isinstance(request[k],str) or not 1<=len(request[k])<=160 for k in ('runtime_id','quote_id')) or type(request['state_revision']) is not int:
            raise PublicRequestError('Bounded current Details identity required')
        from app.comparison.effective_policy import effective_policy
        try:effective_policy(self._state['estimate_policy'],ceiling=request.get('ceiling'),buffer=request.get('buffer'))
        except ValueError as exc:raise PublicRequestError(str(exc)) from None
        for key in ('quote_revision','opposing_quote_revision','request_generation'):
            if key in request and (not isinstance(request[key],str) or not request[key].isdigit() or not 0<=int(request[key])<=9007199254740991):
                raise PublicRequestError('Bounded exact revision/generation required')
        if request.get('objective') not in (None,'decisive_max_min','all_modeled_states_max_min','requested_funded_net_balance'):
            raise PublicRequestError('Exact funded objective required')
        if any(k in request for k in ('objective','pair_revision','opposing_quote_id','opposing_quote_revision')) and not request.get('pair_id'):
            raise PublicRequestError('Pair identity required')
        self.refresh_age();self.require_economic();state=self._state
        if self.closed or request['runtime_id']!=state['runtime_id']:
            raise SelectionError(410,'selection_expired','Current runtime changed; reselect a current price')
        if request['state_revision']!=state['state_revision']:
            raise SelectionError(409,'selection_changed','Inputs changed before Details; refresh the selected contract',**self.notice())
        from app.comparison.current_details import selected
        try:
            key=tuple(sorted((k,v) for k,v in request.items() if k!='request_generation'))
            cached=self._details_cache
            if cached is not None and cached[0]==self._publication_generation and cached[1]==key:
                value=deepcopy(cached[2]);value['request_generation']=request.get('request_generation')
                return value
            index=self.index(state)
            for id_key,rev_key in (('quote_id','quote_revision'),('opposing_quote_id','opposing_quote_revision')):
                if id_key in request and (request[id_key] not in index or (rev_key in request and str(index[request[id_key]]['quote']['revision'])!=request[rev_key])):
                    raise ValueError('Selected leg changed')
            value=selected(state,request['quote_id'],ceiling=request.get('ceiling'),buffer=request.get('buffer'),
                pair_id=request.get('pair_id'),objective=request.get('objective'),pair_revision=request.get('pair_revision'))
            if request.get('opposing_quote_id') and not any(any(leg['quote_id']==request['opposing_quote_id'] for leg in pair['legs']) for pair in value['funded_pairs']):
                raise ValueError('Opposing leg identity conflict')
            value['request_generation']=request.get('request_generation')
            self.require_economic()
            if len(packed(value))<=2*1024*1024:self._details_cache=(self._publication_generation,key,deepcopy(value))
            return value
        except ValueError:
            raise SelectionError(409,'selection_changed','Selected contract is no longer available',**self.notice()) from None

    def prune(self):
        now=self.monotonic()
        for token,lease in list(self.leases.items()):
            if now>=lease['deadline']:
                self.leases.pop(token)
                if self.clients.get(lease['client'])==token:self.clients.pop(lease['client'])

    def create(self,request):
        expected={'schema','runtime_id','state_revision','quote_id','quote_revision','client_id'}
        if not isinstance(request,dict) or set(request)!=expected or request['schema']!=VERSION:raise PublicRequestError('Exact selection request required')
        for k in ('runtime_id','quote_id','client_id'):
            if not isinstance(request[k],str) or not 1<=len(request[k])<=160:raise PublicRequestError('Bounded selection identity required')
        for k in ('state_revision','quote_revision'):
            if type(request[k]) is not int or request[k]<1:raise PublicRequestError('Positive selection revision required')
        self.prune();self.refresh_age();self.require_economic()
        state=self._state
        if self.closed or request['runtime_id']!=state['runtime_id']:
            raise SelectionError(410,'selection_expired','Current runtime changed; reselect a current price')
        selected=self.index(state).get(request['quote_id'])
        if selected is None or state['state_revision']!=request['state_revision'] or selected['quote']['revision']!=request['quote_revision']:
            latest=None if selected is None else dict(quote_id=selected['quote']['id'],quote_revision=selected['quote']['revision'])
            raise SelectionError(409,'selection_changed','Prices changed before selection; reselect deliberately',latest=latest,**self.notice())
        if selected['quote']['state'] in ('error','unavailable','not_offered','stopped','connecting','resyncing'):
            raise SelectionError(409,'selection_changed','Selected price is no longer available for review',latest=None)
        from app.comparison.shared_templates import shared
        if shared(state.get('comparison_profiles')) or selected['event'].get('funded_pairs'):
            selected=self.details(dict(runtime_id=state['runtime_id'],state_revision=state['state_revision'],quote_id=request['quote_id']))
        selected.update(runtime_id=state['runtime_id'],state_revision=state['state_revision'],clock_at=state['clock_at'],mode=state['mode'])
        size=len(packed(selected));previous=self.clients.get(request['client_id'])
        retained=[l for token,l in self.leases.items() if token!=previous]
        if len(retained)>=8 or sum(l['bytes'] for l in retained)+size>2*1024*1024:
            raise SelectionError(429,'selection_capacity','Reviews are full; close a review or wait for expiry')
        # Capacity and revision validation precede replacement. Failed adoption
        # leaves the previous review untouched.
        token=str(uuid4())
        lease=dict(client=request['client_id'],review=deepcopy(selected),deadline=self.monotonic()+self.ttl,bytes=size)
        if previous:self.leases.pop(previous,None)
        self.leases[token]=lease;self.clients[request['client_id']]=token
        return self.get(token)

    def get(self,token):
        self.prune();lease=self.leases.get(token)
        if self.closed or not lease:
            raise SelectionError(410,'selection_expired','Selection expired, released or runtime restarted')
        review=lease['review'];q=review['quote'];latest=self.index(self._state).get(q['id'])
        newer=self._economic_invalidated or latest is None or latest['quote']['revision']!=q['revision'] or (
            latest['quote'].get('comparison_input_refs')!=q.get('comparison_input_refs') or
            latest['quote'].get('comparison_dependency_reasons')!=q.get('comparison_dependency_reasons') or
            latest['quote'].get('comparison_temporal_revision')!=q.get('comparison_temporal_revision') or
            latest['quote'].get('calculations',{}).get('net_ev',{}).get('estimate_policy')!=q.get('calculations',{}).get('net_ev',{}).get('estimate_policy'))
        if review.get('funded_pairs'):
            current_pairs={pair['id']:pair['revision'] for event in self._state['events']
                if event['id']==review['event']['id'] for pair in event.get('funded_pairs',[])}
            newer=newer or any(current_pairs.get(pair['id'])!=pair['revision'] for pair in review['funded_pairs'])
        return dict(schema=VERSION,selection_id=token,runtime_id=self._state['runtime_id'],status='newer_available' if newer else 'held',
            ttl_remaining=max(0,lease['deadline']-self.monotonic()),review=deepcopy(review),
            latest=None if latest is None else dict(quote_id=q['id'],quote_revision=latest['quote']['revision'],state_revision=self._state['state_revision'],state=latest['quote']['state'],display=deepcopy(latest['quote']['display'])))

    def release(self,token):
        self.get(token)
        lease=self.leases.pop(token)
        if self.clients.get(lease['client'])==token:self.clients.pop(lease['client'])
        return dict(released=True)

    async def revoke_source_publication(self):
        self._source_stopping=True;self._revoke_economic()
        await self.admission.close()
        self._clear_current_body();self._details_cache=None
        await self.temporal.close()
        self.encoded_bodies.close()
        await self.comparison_jobs.close()

    async def close(self):
        if self.closed:return
        # Provider revokes dispatch and establishes source safety before the
        # store expires leases and closes subscriber delivery.
        self._stopping=True;self._revoke_economic()
        await self.admission.close()
        self._clear_current_body();self._details_cache=None
        await self.provider.close()
        await self.temporal.close()
        self.closed=True;self.leases.clear();self.clients.clear();self._clear_comparison_body()
        self.encoded_bodies.close()
        await self.comparison_jobs.close()
        for queue in self.subscribers:
            if queue.full():queue.get_nowait()
            queue.put_nowait(None)


def mount(app,provider=None):
    store=CurrentStore(provider);app[CURRENT_KEY]=store

    def strict_query(req):
        if req.query:raise PublicRequestError('Current endpoints do not accept filters or acquisition controls')

    async def current(req):
        if set(req.query)-{'league','search'} or len(req.query)!=len(set(req.query)):raise PublicRequestError('Unsupported current read scope')
        if req.query.get('league') not in (None,'NFL','NBA','MLB','NHL','NCAAF','NCAAB'):raise PublicRequestError('Unsupported current league')
        search=req.query.get('search','')
        if len(search)>200:raise PublicRequestError('Bounded current search required')
        return CurrentResponse(body=store.encoded_transport_snapshot(req,league=req.query.get('league'),search=search),content_type='application/json')

    async def changes(req):
        try:
            if set(req.query)!={'runtime_id','state_revision'}:raise ValueError()
            runtime=req.query['runtime_id'];revision=int(req.query['state_revision'])
            if not 0<len(runtime)<=128 or not 1<=revision<=9007199254740991:raise ValueError()
        except (ValueError,TypeError):return web.json_response({'error':'invalid_change_cursor'},status=422)
        return CurrentResponse(body=store.encoded_transport_changes(runtime,revision,req),content_type='application/json')

    async def details(req):
        try:
            data=dict(req.query)
            if 'state_revision' in data:
                try:data['state_revision']=int(data['state_revision'])
                except ValueError:raise PublicRequestError('Positive Details revision required') from None
            value=store.details(data);epoch=store._calculation_epoch
            owner=store.encoded_bodies.encode(value)
            return CurrentResponse(body=store.encoded_bodies.payload(owner,req,adopt=True,**store.delivery_guards(epoch)),content_type='application/json')
        except SelectionError as exc:return web.json_response(exc.body,status=exc.status)

    async def prices(req):
        if set(req.query)-{'settings_generation','page','generation_id'}:
            raise PublicRequestError('Unsupported retained price query')
        try:
            settings=int(req.query.get('settings_generation','0'));page=int(req.query.get('page','0'))
            if store.admission.readers>=store.admission.MAX_READERS:
                return web.json_response(dict(error='retained_reader_capacity'),status=429)
            value=store.admission.page(settings_generation=settings,page=page,generation_id=req.query.get('generation_id'))
            if store.admission.closed:return web.Response(body=packed(value),content_type='application/json')
            from .current_admission import PriceReader
            return CurrentResponse(body=PriceReader(store.admission,packed(value),req),content_type='application/json')
        except ValueError as exc:return web.json_response(dict(error='retained_prices_unavailable',reason=str(exc)),status=409)

    async def updates(req):
        strict_query(req)
        if req.method=='HEAD':return web.Response(headers={'Content-Type':'text/event-stream',**HEADERS})
        if len(store.subscribers)>=MAX_STREAMS:return web.json_response({'error':'update_capacity','reason':'Too many connected boards'},status=429,headers={'Retry-After':'2',**HEADERS})
        queue=asyncio.Queue(maxsize=1);store.subscribers.add(queue);queue.put_nowait(store.notice())
        response=web.StreamResponse(headers={'Content-Type':'text/event-stream',**HEADERS})
        try:
            await response.prepare(req)
            while not store.closed and req.transport is not None and not req.transport.is_closing():
                try:
                    notice=await asyncio.wait_for(queue.get(),10)
                    if notice is None:break
                    data=b'data: '+packed(notice)+b'\n\n'
                except TimeoutError:data=b': connection heartbeat\n\n'
                # One tiny latest notice (<1KiB) pending, no journal backlog.
                async with asyncio.timeout(STREAM_WRITE_SECONDS):await response.write(data)
        except (ConnectionError,TimeoutError,asyncio.CancelledError):
            pass
        finally:store.subscribers.discard(queue)
        return response

    async def selection(req):
        strict_query(req)
        try:
            if req.path=='/api/selections':return web.json_response(store.create(await read_json(req)),status=201)
            token=req.match_info['token']
            if req.method=='GET':return web.json_response(store.get(token))
            body=await read_json(req)
            if req.path.endswith('/release'):
                if body!={}:raise PublicRequestError('Release accepts an empty object')
                return web.json_response(store.release(token))
            review=store.get(token)['review']
            return web.json_response(manual_scenario(review,body))
        except SelectionError as exc:return web.json_response(exc.body,status=exc.status)

    app.router.add_get('/api/current',current)
    app.router.add_get('/api/current/changes',changes)
    app.router.add_get('/api/current/details',details)
    app.router.add_get('/api/current/prices',prices)
    app.router.add_get('/api/current/updates',updates)
    app.router.add_post('/api/selections',selection)
    app.router.add_get('/api/selections/{token}',selection)
    app.router.add_post('/api/selections/{token}/release',selection)
    app.router.add_post('/api/selections/{token}/what-if',selection)
    async def aging():
        while not store.closed:
            await asyncio.sleep(1)
            store.refresh_age();store.prune()
    async def startup(app):
        store.start_retained()
        start=getattr(store.provider,'start',None)
        if start:await start(store)
        app[age_key]=asyncio.create_task(aging())
    async def shutdown(app):
        await store.close()
        task=app.get(age_key)
        if task:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
    age_key=web.AppKey('current_age_task',object)
    app.on_startup.append(startup)
    app.on_shutdown.append(shutdown)
    app.on_cleanup.append(shutdown)
    return store
