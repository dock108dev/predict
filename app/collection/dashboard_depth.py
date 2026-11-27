"""Collector-owned pregame books. Dashboard HTTP only reads committed rows."""
import asyncio
from collections import Counter, defaultdict
from datetime import timedelta
from fractions import Fraction

from app.comparison.current_pregame import COMPARISON_USD
from app.comparison.sgo_native_binding import SIDES, fresh_pregame_witness, outcome_link_id
from app.fees.product_schedules import read_all
from app.research.experiment import utc
from app.storage import sgo_native_catalog
from app.storage.current_rows import project_contract, project_quote
from app.storage.store import connect, stamp
from .current_policy import aggregate_scope
from .dashboard_pmus import BookSelector, read as pmus
from .experiment_depth import _binding
from .native_experiment_depth import synchronized_kalshi
from .novig_experiment_depth import book_depth, catalog_depth

HORIZON = timedelta(hours=24)
SLOT = timedelta(minutes=30)
READ_BUDGET = timedelta(seconds=6)
MAX_DETAIL_BOOKS = 4
MAX_EVENT_RECOVERIES = 2
REFRESH_MINIMUM = timedelta(seconds=5)


def slots(db, at, leagues):
    return [(row['league'], row['slot']) for row in db.execute('''
        SELECT e.facts->>'competition' league,
          date_bin(interval '30 minutes',e.scheduled_start::timestamptz,'2000-01-01'::timestamptz) slot
        FROM public.current_event e
        WHERE e.provider='sportsgameodds' AND e.facts->>'competition'=ANY(%s)
          AND e.scheduled_start::timestamptz>%s AND e.scheduled_start::timestamptz<%s
          AND e.expires_order>extract(epoch FROM %s::timestamptz)
        GROUP BY 1,2 ORDER BY 2,1''', (list(leagues), at, at+HORIZON, at))]


def candidates(db, league, start, at):
    """Join only the requested event window, including negative aggregate quotes."""
    rows = db.execute('''SELECT c.id,c.revision,c.facts contract,e.native_event_id,e.facts event,
          o.facts quote,o.source_at,o.received_at
        FROM public.current_event e JOIN public.current_contract c ON c.event_id=e.id
        JOIN public.current_offer o ON o.contract_id=c.id
        WHERE e.provider='sportsgameodds' AND e.facts->>'competition'=%s AND e.scheduled_start::timestamptz>=%s
          AND e.scheduled_start::timestamptz<%s AND e.scheduled_start::timestamptz>%s
          AND e.expires_order>extract(epoch FROM %s::timestamptz)
          AND c.venue IN ('novig','kalshi','polymarket_us','prophetx')
          AND o.facts->>'state'='available'
          AND c.facts#>>'{market_identity,period}'='full_game'
          AND c.facts#>>'{market_identity,family}' IN ('moneyline','spread','total')
        ORDER BY e.native_event_id,c.id''', (league, start, start+SLOT, at, at)).fetchall()
    events = defaultdict(list)
    for row in rows:
        record = dict(project_contract(row['event'], row['contract'], row['received_at']),
                      event=row['event'], quote=project_quote(row))
        events[row['native_event_id']].append((row['id'], row['revision'], record))
    return dict(events), sgo_native_catalog.read(db, events)


def novig_bindings(events, witnesses, inventory, *, at):
    grouped = {}
    for event_id, rows in events.items():
        market_rows = inventory.get(event_id, {})
        for contract_id, revision, record in rows:
            if record['quote']['venue'] != 'novig':
                continue
            binding = _binding(record, witnesses.get(event_id), at=at, inventory=market_rows)
            grouped[contract_id] = revision, record, binding
    return grouped


def _detailed(observation):
    if observation['reason'] or not observation['levels']:
        return False
    top = observation['levels'][0]
    top_stake = Fraction(top['price']) * Fraction(top['quantity']) * Fraction(observation['payout_usd'])
    fee = observation['fee'].get('coefficient')
    return top_stake < COMPARISON_USD or (fee is not None and Fraction(fee) > 0)


class DashboardDepth:
    def __init__(self, owner, *, connector=connect, now=utc):
        self.owner, self.connector, self.now = owner, connector, now
        self.last = {}
        self.kalshi = owner.kalshi_catalog
        self.pmus_books = BookSelector()
        self.progress = dict(state='starting', public_requests=0, slots=0)

    def _next(self, at):
        with self.connector() as db:
            upcoming = slots(db, at, aggregate_scope(self.owner.service.config))
            self.last = {key: self.last[key] for key in upcoming if key in self.last}
            if not upcoming:
                return None
            league, start = min(upcoming, key=lambda key: (self.last.get(key, at-HORIZON), key[1], key[0]))
            if at-self.last.get((league, start), at-HORIZON) < REFRESH_MINIMUM:
                return None
            self.last[league, start] = at
            return (league, start), candidates(db, league, start, at), read_all(db)

    def _write(self, items, at):
        from app.collection.mens_d1_jobs import _late_capture_due
        from app.storage.current_pregame_depth import publish

        with self.connector() as db:
            if self.owner._near_checkpoint() or _late_capture_due(db, at):
                return 0
            return publish(db, items, at=at)

    async def _novig(self, client, scope, events, witnesses):
        league, start = scope
        cutoff = self.now()+READ_BUDGET
        inventory = await client.read_slate(league, after=start-timedelta(milliseconds=1),
                                           before=start+SLOT, cutoff=cutoff)
        self.progress['public_requests'] += len(inventory.receipts)
        by_event = defaultdict(dict)
        for mid, row in inventory.markets.items():
            by_event[row['eventId']][mid] = row
        witnesses = dict(witnesses)
        exact = {}
        recoveries = 0
        for source_id, rows in events.items():
            if inventory.reason:
                break
            e = rows[0][2]['event']
            native_id = (e.get('shared_provider_ids') or {}).get('novig_event')
            if not native_id or not by_event[native_id]:
                continue
            exact[source_id] = market_rows = by_event[native_id]
            if source_id in witnesses or recoveries >= MAX_EVENT_RECOVERIES or self.owner._near_checkpoint():
                continue
            desired = {}
            for _, _, r in rows:
                q = r['quote']
                meta = r.get('comparison_source_metadata') or {}
                link = outcome_link_id(meta.get('bookmaker_market_link'))
                side = SIDES.get(q['source']['native_outcome_id'])
                if q['venue'] == 'novig' and link and side:
                    desired[link] = dict(side=side, family=r['market_identity']['family'],
                                         line=q['source'].get('native_line'))
            if not desired:
                continue
            recoveries += 1
            event, proof, reason = await client.read_event_metadata(native_id, cutoff)
            self.progress['public_requests'] += proof is not None
            if not reason:
                try:
                    witnesses[source_id] = fresh_pregame_witness(source_id, event, proof, market_rows, desired)
                except (KeyError, TypeError, ValueError):
                    continue
        planned = await asyncio.to_thread(novig_bindings, events, witnesses, exact, at=self.now())
        observations, deeper = {}, defaultdict(list)
        for cid, (revision, record, binding) in planned.items():
            observation = catalog_depth(binding, inventory, self.now())
            if binding.get('available'):
                observation['identity_receipts'] = [binding['event_receipt'], binding['market_receipt']]
                observation['binding_method'] = binding.get('binding_method', 'aggregate_outcome_link')
                if observation.get('contract'):
                    observation['contract']['contract_id'] = cid
            elif not observation.get('reason'):
                observation['reason'] = inventory.reason or 'unmatched'
            observations[cid] = revision, observation
            if _detailed(observation):
                role = (record.get('comparison_source_metadata') or {}).get('alternate')
                deeper[binding['market_id']].append((cid, binding, role is not False))
        priority = sorted(deeper, key=lambda mid: (all(side[2] for side in deeper[mid]), mid))
        for mid in priority[:MAX_DETAIL_BOOKS]:
            if self.owner._near_checkpoint() or not self.owner.venue_enabled('novig') or self.now()>=cutoff:
                break
            detail = await client.read_book(mid, cutoff)
            self.progress['public_requests'] += detail.receipt is not None
            for cid, binding, _ in deeper[mid]:
                revision, original = observations[cid]
                current = book_depth(binding, detail, self.now(), catalog=original)
                if current.get('contract'):
                    current['contract']['contract_id'] = cid
                observations[cid] = revision, current if not current.get('reason') else original
        return observations

    async def _native(self, client, scope, events, products):
        league, _ = scope
        cutoff = self.now()+READ_BUDGET
        venue_reads = []
        if self.owner.venue_enabled('kalshi'):
            venue_reads.append(self.kalshi.read(client, league, events, cutoff=cutoff, products=products))
        if self.owner.venue_enabled('polymarket_us'):
            venue_reads.append(pmus(client, league, events, at=self.now(), cutoff=cutoff, products=products))
        bindings = {}
        for result in await asyncio.gather(*venue_reads, return_exceptions=True):
            if isinstance(result, Exception):
                from app.diagnostics import failure
                failure(__name__, 'dashboard_native_discovery', result)
            else:
                bindings.update(result)
        if self.owner._near_checkpoint():
            return {}
        bindings = self.pmus_books.select(scope, bindings, events)
        results = await asyncio.to_thread(self._synchronized, bindings, cutoff)
        results.update(await client.read_native({cid:b for cid,b in bindings.items() if cid not in results},
                                                cutoff, batch=True))
        self.progress['public_requests'] += len({r['sha256'] for b in results.values()
                                                for r in b.get('receipts', ()) if r.get('sha256')})
        output = {}
        for rows in events.values():
            for cid, revision, record in rows:
                venue = record['quote']['venue']
                if cid in results:
                    output[cid] = revision, results[cid]
                elif venue != 'novig':
                    reason = ('source_paused' if not self.owner.venue_enabled(venue) else
                              'prophetx_depth_entitlement_unavailable' if venue == 'prophetx' else
                              'native_identity_unmatched')
                    output[cid] = revision, dict(venue=venue, reason=reason, complete=False, levels=[])
        return output

    def _synchronized(self, bindings, cutoff):
        with self.connector() as db:
            return synchronized_kalshi(db, bindings, at=self.now(), cutoff=cutoff)

    async def tick(self, novig, native):
        if not self.owner.enabled() or self.owner._near_checkpoint():
            return
        at = self.now()
        plan = await asyncio.to_thread(self._next, at)
        if plan is None:
            return
        scope, (events, witnesses), products = plan
        reads = [self._native(native, scope, events, products)]
        if self.owner.venue_enabled('novig'):
            reads.append(self._novig(novig, scope, events, witnesses))
        async def publish_read(read):
            try:
                result = await read
                await self._publish(result)
                return Counter(row[1].get('reason') or 'book' for row in result.values())
            except Exception as result:
                from app.diagnostics import failure
                failure(__name__, 'dashboard_depth_read', result)
                return Counter({type(result).__name__: 1})

        dispositions = await asyncio.gather(*(publish_read(read) for read in reads))
        self.progress.update(state='ready', slots=self.progress['slots']+1,
                             last_league=scope[0], last_dispositions=dict(sum(dispositions, Counter())),
                             native_session_requests=dict(native.requests))

    async def _publish(self, observations):
        at = self.now()
        items = []
        for contract_id, (revision, receipt) in observations.items():
            valid_until = stamp(receipt['valid_until']) if receipt.get('valid_until') else at+SLOT
            if valid_until <= at:
                continue
            receipt.update(contract_id=contract_id,
                           source_health='observed' if not receipt.get('reason') else receipt['reason'])
            items.append(dict(contract_id=contract_id, contract_revision=revision, receipt=receipt,
                              known_at=at, valid_until=valid_until))
        if items and self.owner.enabled():
            await asyncio.to_thread(self._write, items, at)

    async def run(self, novig, native):
        from app.diagnostics import failure

        while True:
            try:
                await self.tick(novig, native)
            except Exception as exc:
                failure(__name__, 'dashboard_public_depth_poll', exc)
                self.progress.update(state='degraded', reason=type(exc).__name__)
            await asyncio.sleep(1)
