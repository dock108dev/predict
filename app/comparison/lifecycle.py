"""Source-owned subscription continuity and bounded latest complete images."""
from copy import deepcopy
from hashlib import sha256
import json
from app.dashboard.current_contract import stamp
from app.collection.current_confirmation import content
from .event_links import EventLinks

VERSION='comparison-lifecycle-1'
MAX_MARKETS=20
MAX_BOOK_BYTES=256*1024


def digest(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()


class LifecycleOwner:
    """One token per selected native market under an immutable runtime attempt.

    Transport remains the existing source-owned batched socket. Reconciliation
    returns exact work deltas; this object never opens a socket or releases outer
    ownership, quota, reservations or consumed authority.
    """
    def __init__(self,venue,runtime_id,*,attempt_id=None,links=None,cap=MAX_MARKETS):
        if venue not in ('kalshi','polymarket_us') or not isinstance(runtime_id,str) or not runtime_id or len(runtime_id)>256:
            raise ValueError('Exact bounded lifecycle owner required')
        if type(cap) is not int or not 1<=cap<=MAX_MARKETS:
            raise ValueError('Lifecycle subscription bound')
        self.venue=venue;self.runtime_id=runtime_id;self.attempt_id=attempt_id or runtime_id
        self.links=links or EventLinks();self.cap=cap
        self.dispatch=True;self.generation=0;self.sequence=0
        self.leases={};self.books={};self.retired=[]

    def reconcile(self,selected,at):
        if not self.dispatch:
            raise ValueError('Lifecycle dispatch revoked')
        if len(selected)>self.cap:
            raise ValueError('Lifecycle subscription bound')
        desired={};rejected=[]
        seen=set()
        for value in selected:
            value=deepcopy(value);mid=value['market_id'];event=value['event']
            if len(json.dumps(value,default=str).encode())>256*1024:
                raise ValueError('Selected lifecycle metadata bound')
            if not isinstance(mid,str) or not mid or len(mid)>256 or mid in seen:
                raise ValueError('Unique exact selected markets required')
            seen.add(mid)
            if not isinstance(event.get('id'),str) or not event['id'] or len(event['id'])>256:
                raise ValueError('Exact native event required')
            if value.get('discovery_eligible') is not True:
                continue
            if not isinstance(value.get('material_revision'),str) or not value['material_revision'] or len(value['material_revision'])>256:
                raise ValueError('Material native selection revision required')
            if value.get('payout_eligible') is not None and type(value['payout_eligible']) is not bool:
                raise ValueError('Payout eligibility is measured or unknown')
            if event.get('scheduled_start') is not None:
                stamp(event['scheduled_start'])
            edge=reason=None
            if all(isinstance(event.get(k),str) and event[k] for k in ('competition','home','away')):
                edge,reason=self.links.resolve(self.venue,event['id'],event['competition'],event['home'],event['away'],at)
            else:
                reason='source_roles_unresolved'
            value['occurrence_id']=edge.occurrence_id if edge else None
            value['occurrence_reference']=self.links.reference(edge).to_dict() if edge else None
            value['occurrence_reason']=reason
            old=self.leases.get(mid)
            if old and old['selection']['event']['id']!=event['id']:
                old['image_current']=False
                self.books.pop(mid,None)
                rejected.append(dict(market_id=mid,reason='market_event_identity_conflict'))
                desired[mid]=deepcopy(old['selection'])
                continue
            desired[mid]=value
        actions=[]
        for mid in sorted(set(self.leases)-set(desired)):
            actions.append(dict(action='close',market_id=mid,owner_token=self.leases[mid]['owner_token']))
            self.retired.append(dict(market_id=mid,retired_at=at.isoformat(),reason='catalog_retired'))
            self.leases.pop(mid);self.books.pop(mid,None)
        self.retired=self.retired[-200:]
        for mid,value in sorted(desired.items()):
            old=self.leases.get(mid)
            if old is None:
                self.sequence+=1
                token=digest([self.runtime_id,self.attempt_id,self.venue,mid,self.sequence])
                self.leases[mid]=dict(owner_token=token,selection=value,image_current=False,generation=self.generation)
                actions.append(dict(action='create',market_id=mid,owner_token=token))
            else:
                if old['selection']['material_revision']!=value['material_revision']:
                    old['image_current']=False;self.books.pop(mid,None)
                    actions.append(dict(action='reimage',market_id=mid,owner_token=old['owner_token']))
                elif old['selection']!=value:
                    actions.append(dict(action='metadata',market_id=mid,owner_token=old['owner_token']))
                old['selection']=value
        return dict(schema=VERSION,actions=actions,rejected=rejected,selected=len(self.leases))

    def begin_connection(self,generation):
        if not self.dispatch or type(generation) is not int or generation<=self.generation:
            raise ValueError('Stale/revoked subscription generation')
        self.generation=generation
        for lease in self.leases.values():
            lease['generation']=generation;lease['image_current']=False
        # A disconnected historical image is retained only as inspection context.
        # It cannot become current until a complete image from this generation.

    def admit_book(self,book,*,generation):
        if not self.dispatch or generation!=self.generation:
            raise ValueError('Stale/revoked native book generation')
        ref=book['raw']['ref'];mid=ref['market_id'];lease=self.leases.get(mid)
        if lease is None or ref['venue']!=self.venue or ref['event_id']!=lease['selection']['event']['id']:
            raise ValueError('Retired/unowned native book')
        if book.get('sync')!='synchronized' or book.get('state')!='active':
            raise ValueError('Complete active native image required')
        if len(json.dumps(book,default=str).encode())>MAX_BOOK_BYTES:
            raise ValueError('Latest native book byte bound')
        received=stamp(book['raw']['received_at']);source=book['raw'].get('exchange_at')
        if source is not None and stamp(source)>received:
            raise ValueError('Future native price clock')
        previous=self.books.get(mid)
        if previous and source is not None and previous['original_source_at'] is not None and stamp(source)<stamp(previous['original_source_at']):
            raise ValueError('Regressed native price clock')
        value=deepcopy(book);fingerprint=content(book)
        # A complete unchanged image may have a new confirmation time, but the
        # price's original exchange clock remains the prior source observation.
        original=previous['original_source_at'] if previous and previous['content_sha256']==fingerprint else source
        value['raw']['exchange_at']=original
        self.books[mid]=dict(book=value,content_sha256=fingerprint,original_source_at=original,
            last_received_at=book['raw']['received_at'],confirmation_source_at=source,generation=generation)
        lease['image_current']=True
        return deepcopy(value)

    def freshness(self,market_id,at,maximum_age_seconds=30):
        book=self.books.get(market_id);lease=self.leases.get(market_id)
        source=book['original_source_at'] if book else None
        age=None if source is None else (at-stamp(source)).total_seconds()
        return dict(original_source_at=source,age_seconds=age,
            current=bool(self.dispatch and lease and lease['image_current'] and age is not None and 0<=age<=maximum_age_seconds),
            discovery_eligible=None if lease is None else lease['selection']['discovery_eligible'],
            payout_eligible=None if lease is None else lease['selection'].get('payout_eligible'))

    def signature(self):
        return digest([(mid,lease['selection']['event']['id'],lease['selection']['material_revision']) for mid,lease in sorted(self.leases.items())])

    def revoke(self):
        self.dispatch=False
        for lease in self.leases.values():lease['image_current']=False

    async def stop(self,close):
        """Revoke synchronously before the first external cleanup await."""
        self.revoke()
        for mid,lease in list(self.leases.items()):
            await close(mid,lease['owner_token'])
            self.leases.pop(mid,None);self.books.pop(mid,None)
        # Immutable attempt/runtime identity is deliberately preserved.


def worker_selections(venue,parsed,catalog):
    """Adapt existing admitted current catalog/markets without new authority."""
    events={e['id']:e for e in catalog['events']}
    markets={m['id']:m for m in catalog['markets']}
    result=[]
    for mid,market in sorted(parsed.items()):
        row=markets[mid];parent=events[market.raw.ref.event_id]
        roles=parent.get('source_participant_roles',{})
        event=dict(id=parent['id'],competition=parent.get('competition'),home=parent.get('home',roles.get('home')),
            away=parent.get('away',roles.get('away')),scheduled_start=parent.get('scheduled_start'),status=deepcopy(parent.get('status',{})))
        binding=row.get('v1_raw_binding',{})
        identity={k:v for k,v in binding.get('identity',{}).items() if k not in ('event','scheduled_start')}
        material=dict(state=market.state.value,identity=identity,predicate=binding.get('predicate'),
            source_predicate=binding.get('source_predicate'),slug=row.get('native_slug'),
            sides=row.get('sides'),terms=row.get('terms'))
        result.append(dict(market_id=mid,event=event,material_revision=digest(material),discovery_eligible=True,payout_eligible=None))
    return result
