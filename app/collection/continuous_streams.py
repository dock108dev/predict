"""Finite native stream groups: subscription reconciliation, health and closure.

Session ownership and discovery stay in continuous. Dependencies are explicit so
this module never imports its owner or creates a circular dependency.
"""
import asyncio
import base64
from copy import deepcopy
from dataclasses import asdict
import json

from .acquisition_policy import isolated_native
from .odds_http import BudgetStop
from .prediction_producer import PredictionBudget
from app.reference.records import packed


class GroupBudget:
    def __init__(self, shared):
        self.shared = shared
        self.connections = 0
    def remaining_bytes(self):
        return self.shared.budget.remaining_bytes()
    def charge_bytes(self, n):
        try:
            self.shared.budget.charge_bytes(n)
        except BudgetStop:
            if isolated_native(self.shared.session.spec):
                self.shared.session.discovery.stop_source(self.shared.venue,'prediction_session_byte_cap')
            else:self.shared.session.request_stop('prediction_session_byte_cap')
            raise
    @property
    def bytes(self):
        return self.shared.budget.bytes
    @bytes.setter
    def bytes(self, value):
        self.shared.budget.bytes = value
    def reserve(self, kind):
        if self.shared.session.connection_attempts >= (self.shared.session.profile['connections'] if self.shared.session.profile else 12):
            self.shared.session.request_stop('connection_attempt_cap')
            raise BudgetStop('connection_attempt_cap')
        from .native_books import enabled as book_slice
        if book_slice(self.shared.session.spec) and self.shared.budget.connections >= 2:
            raise BudgetStop('prediction_connection_cap')
        self.shared.session.connection_attempts += 1
        self.connections += 1
        self.shared.budget.reserve(kind)


class Venue:
    def __init__(self, session, venue, *, clock, inventory_selector, endpoints, producer_factory):
        self.session, self.venue = session, venue
        self.clock = clock
        self.inventory_selector = inventory_selector
        self.endpoints = endpoints
        self.producer_factory = producer_factory
        self.budget = PredictionBudget(session.spec['prediction'])
        self.groups = {}
        self.serial = 0
        self.records = {}
        self.ever = {k:set() for k in ('requested','acknowledged','receiving','usable')}
        self.peak = {k:0 for k in self.ever}
        self.eligible = 0
        self.selected = []
        self.applied_generation = None

    async def discover(self):
        return (await self.session.discovery.discover())[self.venue]

    def health(self, group, state):
        g = self.groups[group]
        g['health'] = state
        if state in ('disconnected','awaiting_snapshot','ineligible'):
            g['usable'].clear()
            if state != 'ineligible':
                g['acknowledged'].clear()
                g['receiving'].clear()
        self.session.health[self.venue] = 'connected' if any(x['health']=='connected' for x in self.groups.values()) else state
        self.session.emit(self.venue, dict(type='source_health', state=state, stream_group=group,
            market_ids=list(g['ids']), gap_reason='fresh synchronization required' if state!='connected' else None))

    def emit(self, group, source, row):
        guard = getattr(self.session, 'guard_scope', None)
        if guard: guard(source, row)  # Before acknowledgement, books or usable-state mutation.
        if getattr(self.session, 'spec', {}).get('future_qualification_policy')=='native-prerequisites-1':
            g=self.groups[group]
            if row['type']=='prediction_command':g['qualification_epoch']=g.get('qualification_epoch',0)+1
            row=dict(row,connection_epoch=str(group)+':'+str(g.get('qualification_epoch',0)))
        segmented = getattr(self.session, 'segmented_history', False)
        error = None; result = None
        if segmented:
            before = self.session.counts['durably_acknowledged']
            try: result = self.session.emit(source, dict(row, stream_group=group))
            except BaseException as exc:
                if self.session.counts['durably_acknowledged'] == before: raise
                error = exc  # Retained despite a later queue rejection.
            if result is False: return False
        g = self.groups[group]
        if row['type']=='prediction_command':
            command = json.loads(row['body'])
            g['request'] = command.get('id') if self.venue=='kalshi' else command['subscribe']['requestId']
            g['requested'].update(g['ids'])
        elif row['type']=='prediction_frame' and self.venue=='kalshi':
            data = json.loads(base64.b64decode(row['body_b64']))
            if (data.get('type')=='subscribed' and data.get('id')==g.get('request')
                    and data.get('msg',{}).get('channel')=='orderbook_delta'
                    and type(data.get('msg',{}).get('sid')) is int and data['msg']['sid']>0):
                g['acknowledged'].update(g['ids'])
        elif row['type']=='prediction_book':
            book = row['book']; mid = book['raw']['ref']['market_id']
            if book['sync']=='synchronized' and book['receipt_freshness']=='recent':
                g['receiving'].add(mid)
                if self.venue=='polymarket_us':
                    g['acknowledged'].add(mid)  # valid matching subscription data; no separate ack
                if not g.get('invalidated') and mid not in self.safety_exclusions():
                    g['usable'].add(mid)
                self.records[mid] = dict(received_at=book['raw']['received_at'],
                    exchange_at=book['raw'].get('exchange_at'), sync=book['sync'],
                    source_time_progress=book['source_time_progress'])
            else:
                g['usable'].discard(mid)
        for key in self.ever:
            self.ever[key].update(g[key])
        if not segmented: result = self.session.emit(source, dict(row, stream_group=group))
        self.snapshot()
        if error: raise error
        return result

    def safety_exclusions(self):
        d = getattr(self.session, 'discovery', None)
        if not d or not d.inventory:
            return set()
        cat = (dict(d.inventory[self.venue],markets=[dict(m) for m in d.inventory[self.venue]['markets']])
               if self.session.profile else deepcopy(d.inventory[self.venue]))
        ids, _ = self.inventory_selector(cat, self.clock())
        return ({m['id'] for m in cat['markets']} - set(ids)) | set(getattr(d, 'blocked', {}).get(self.venue, {}))

    def snapshot(self):
        for group in self.groups.values():
            if group.get('invalidated'):
                group['usable'].clear()
            group['usable'].difference_update(self.safety_exclusions())
        counts = {}
        for key in self.ever:
            ids = set().union(*(g[key] for g in self.groups.values())) if self.groups else set()
            counts[key] = len(ids)
            self.peak[key] = max(self.peak[key], len(ids))
        return dict(**(dict(applying_generation=getattr(self,'applying_generation',None)) if getattr(self.session,'segmented_history',False) else {}), applied_generation=self.applied_generation, applied_eligible=self.eligible, applied_selected=len(self.selected), **counts,
                    ever={k:len(v) for k,v in self.ever.items()}, peak_simultaneous=dict(self.peak),
                    requests=self.budget.requests, connection_attempts=self.budget.connections,
                    body_bytes_charged=self.budget.bytes,
                    acknowledgement_basis='explicit channel acknowledgement' if self.venue=='kalshi' else 'valid current-request market image; no separate acknowledgement',
                    latest_receipts=deepcopy(self.records))

    async def reconcile(self):
        inventory = deepcopy(self.session.discovery.inventory[self.venue])
        ids, eligible = self.inventory_selector(inventory, self.clock())
        if self.session.spec.get('native_discovery',{}).get('discovery_only'):
            ids=[]  # Reconciliation must not re-enable subscriptions from catalog eligibility.
        ids = [m for m in ids if m in self.session.discovery.markets[self.venue] and m not in self.safety_exclusions()]
        from .native_books import enabled as book_slice
        if book_slice(self.session.spec) and self.session.spec['mode']=='real' and ids and self.venue not in self.session.credentials:
            if getattr(self,'credential_failed',False):return
            from .venue_access import load_credentials
            try:self.session.credentials.update(load_credentials([self.venue]))
            except Exception:
                self.credential_failed=True
                self.session.discovery.stop_source(self.venue,'dedicated_credential_unavailable')
                return
        generation = getattr(self.session.discovery, 'published_generation', None)
        segmented = getattr(self.session, 'segmented_history', False)
        market_objects = self.session.discovery.markets[self.venue]
        if not segmented:
            self.applied_generation = generation
            self.selected, self.eligible = ids, eligible
        else:
            self.applying_generation = generation
        size = 20 if self.venue=='kalshi' else 100
        desired = [tuple(ids[i:i+size]) for i in range(0,len(ids),size)]
        # Reschedules/metadata revisions require a new synchronized subscription too.
        rows = {r['id']:r for r in inventory['markets']}
        events = {r['id']:r for r in inventory['events']}
        signatures = {group: tuple(packed([rows[m]['event_id'], events[rows[m]['event_id']]['scheduled_start'],
                            rows[m]['status'], rows[m]['sides'], rows[m]['terms'],
                            (rows[m].get('v1_raw_binding') or {}).get('identity'),(rows[m].get('v1_raw_binding') or {}).get('predicate')]) for m in group) for group in desired}
        for name, group in list(self.groups.items()):
            if group.get('invalidated') or group['ids'] not in desired or group['signature']!=signatures.get(group['ids']):
                self.health(name, 'disconnected')
                self.session.emit(self.venue, dict(type='subscription_departure',stream_group=name,market_ids=list(group['ids']),reason='inventory_or_schedule_changed'))
                group['task'].cancel()
                await asyncio.gather(group['task'], return_exceptions=True)
                await group['producer'].aclose()
                del self.groups[name]
                if self.session.profile:
                    self.records={mid:record for mid,record in self.records.items() if mid in ids}
        for group in desired:
            if any(g['ids']==group for g in self.groups.values()):
                continue
            if self.session.profile:
                if sum(v.serial for v in self.session.producers.values())>=self.session.profile['groups']: raise BudgetStop('supervised_group_cap')
                if sum(len(v.groups) for v in self.session.producers.values())>=self.session.profile['sockets']: raise BudgetStop('supervised_socket_cap')
                if len(self.ever['requested']|set(ids))>256: raise BudgetStop('supervised_market_union_cap')
            self.serial += 1
            name = self.venue+'-'+str(self.serial)
            spec = deepcopy(self.session.spec)
            spec['prediction']['connections'] = 2
            producer = self.producer_factory(self.venue, spec, self.endpoints(self.session)[self.venue]['rest'], self.endpoints(self.session)[self.venue]['ws'],
                lambda source,row,n=name:self.emit(n,source,row), lambda source,state,n=name:self.health(n,state),
                credential=(self.session.credentials or {}).get(self.venue), budget=GroupBudget(self))
            producer.payload_rejected=lambda reason:self.session.discovery.stop_source(self.venue,reason)
            producer.mock_segmented = getattr(self.session, 'mock_segmented', False)
            self.groups[name] = dict(ids=group, signature=signatures[group], producer=producer, health='idle',
                **{k:set() for k in self.ever})
            if hasattr(self.session, 'queue'):
                producer.after_book = self.session.queue.join
            markets = [(market_objects if segmented else self.session.discovery.markets[self.venue])[m] for m in group]
            for market in markets:
                self.session.emit(self.venue, dict(type='market_selected',stream_group=name,market=json.loads(json.dumps(asdict(market),default=str))))
                await asyncio.sleep(0)
                if segmented and self.session.stop_event.is_set(): return
            self.groups[name]['task'] = asyncio.create_task(producer.run(markets))
        if segmented and self.applied_generation != generation:
            admitted = self.session.emit(self.venue, dict(type='coverage_applied', generation=generation,
                selected_ids=list(ids), stream_groups=list(self.groups), usable=self.snapshot()['usable']))
            if admitted is not False:
                self.applied_generation = generation
                self.selected, self.eligible = ids, eligible
        if segmented: self.applying_generation = None
        self.snapshot()

    async def run(self, markets):
        while not self.session.stop_event.is_set():
            if self.venue in self.session.discovery.source_stops:
                await self.aclose()
                return
            await self.reconcile()
            if getattr(self.session,'segmented_history',False) and self.session.stop_event.is_set(): return
            for group in list(self.groups.values()):
                if group['task'].done():
                    if self.session.spec.get('source_session'):
                        name=next(n for n,g in self.groups.items() if g is group)
                        self.health(name,'disconnected')
                        await asyncio.gather(group['task'],return_exceptions=True)
                        await group['producer'].aclose()
                        del self.groups[name]
                        if self.budget.connections>=self.session.spec['prediction']['connections']:
                            await self.session.stop_event.wait()
                            return
                        await self.session.pause(1)
                        continue
                    if self.session.spec.get('native_sources'):
                        self.health(next(n for n,g in self.groups.items() if g is group), 'disconnected')
                        try: await group['task']
                        except Exception as exc:
                            from app.diagnostics import failure
                            failure('app.collection.continuous', 'native_stream_task', exc)
                        self.session.discovery.stop_source(self.venue,'native_stream_terminal')
                        await self.aclose()
                        return
                    await group['task']
                    self.session.request_stop('native_stream_ended')
                    return
            await self.session.pause(.25)

    async def aclose(self):
        tasks = [g['task'] for g in self.groups.values() if 'task' in g]
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        from app.cleanup import close_all
        resources = [group['producer'] for group in self.groups.values()]
        client = self.session.discovery.clients.get(self.venue)
        if client:
            resources.append(client)
        await close_all(resources)


