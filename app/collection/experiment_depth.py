"""Independent public-book lane for prospective Win $25 paper decisions."""
import asyncio
from collections import defaultdict
from datetime import timedelta
from fractions import Fraction

from app.comparison.sgo_native_binding import (
    bind, bind_pregame_line, event_link_id, outcome_link_id, pregame_inventory_bindings,
)
from app.diagnostics import failure
from app.research import experiment
from app.storage import experiment_depth as storage, sgo_native_catalog
from app.storage.store import connect, hashed, stamp

# Prepare catalog identity early, then leave a bounded budget for the cached
# markets request and selective second-tier reads before the decision itself.
PREPARE_AHEAD = timedelta(seconds=25)
READ_AHEAD = timedelta(seconds=6)
BOOK_AHEAD = timedelta(seconds=4)
ASSEMBLY_RESERVE = timedelta(milliseconds=350)
MANUAL_DELAY = timedelta(seconds=30)
# Allows a common kickoff cluster across leagues while network clients
# independently bound concurrent requests and snapshots per venue.
MAX_GAMES_IN_FLIGHT = 16
MAX_PENDING_BUNDLES = 48


def targets(db, at, *, exclude=()):
    from .current_policy import SPORTS

    games, schedules = zip(*exclude, strict=True) if exclude else ((), ())
    return list(db.execute('''SELECT t.game_id,t.schedule_id,t.target_at,t.deadline_at,
            g.source_event_id,g.event,g.early_id,
            EXISTS (SELECT 1 FROM public.ev_experiment_depth d
                WHERE (d.game_id,d.schedule_id,d.target_at,d.kind)=
                      (t.game_id,t.schedule_id,t.target_at,'decision')) AS observed,
            campaigns.all_sports
        FROM public.ev_experiment_task t JOIN public.ev_experiment_game g ON g.id=t.game_id
        JOIN LATERAL (SELECT bool_or(c.payload->>'depth_policy'=%s) AS all_sports
             FROM public.paper_campaign c
             JOIN public.paper_campaign_day d ON d.campaign_id=c.id
             LEFT JOIN public.paper_campaign_retirement retired ON retired.campaign_id=c.id
             WHERE (c.payload->>'depth_policy'=%s AND g.event->>'league'='NCAAB'
                 OR c.payload->>'depth_policy'=%s AND t.target_at>=(c.payload->>'prospective_start_at')::timestamptz)
             AND c.created_at<=%s
             AND (retired.cutoff_at IS NULL OR t.target_at<retired.cutoff_at)
             AND d.game_date=((g.event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date
             AND NOT EXISTS (SELECT 1 FROM public.paper_campaign revision WHERE revision.payload->>'supersedes'=c.id)
        ) AS campaigns ON campaigns.all_sports IS NOT NULL
        WHERE t.checkpoint='late' AND t.state='pending' AND g.early_id IS NOT NULL
          AND t.target_at>%s AND t.target_at<=%s AND g.event->>'league'=ANY(%s)
          AND NOT EXISTS (SELECT 1 FROM unnest(%s::text[],%s::text[]) AS x(game_id,schedule_id)
              WHERE (x.game_id,x.schedule_id)=(t.game_id,t.schedule_id))
        ORDER BY t.target_at,t.game_id LIMIT %s''',
        (storage.ALL_SPORTS_POLICY, storage.POLICY, storage.ALL_SPORTS_POLICY, at,
         at, at + PREPARE_AHEAD, SPORTS, list(games), list(schedules), MAX_GAMES_IN_FLIGHT)))


def supports(record, *, moneyline=False):
    market = record['market_identity']
    return (record['quote']['venue'] == 'novig' and market['period'] == 'full_game'
            and (market['family'] in ('spread', 'total') or moneyline and market['family'] == 'moneyline')
            and record['quote']['state'] == 'available')


def _binding(record, witness, *, at, inventory=None):
    result = (bind(record, witness, at=at) if inventory is None
              else bind_pregame_line(record, witness, inventory, at=at))
    if not result['available'] or result.get('phase') != 'scheduled' or not result.get('phase_verified'):
        return dict(venue='novig', reason=result.get('reason') or 'unmatched_pregame_phase',
                    levels=[], complete=False)
    return dict(result, family=record['market_identity']['family'],
                league=record['event']['competition'],
                starts_at=record['event']['scheduled_start'])


def bindings(db, task, at):
    view = experiment._checkpoint_view(db, dict(id=task['game_id'], early_id=task['early_id']), 'early')
    snapshot = view.get('snapshot') or {}
    if (not snapshot.get('event')
            or stamp(snapshot['event']['scheduled_start']) != stamp(task['event']['starts_at'])):
        snapshot = {}
    source_id = task['source_event_id']
    witness = sgo_native_catalog.read(db, [source_id]).get(source_id)
    if witness and stamp(witness['observed_at']) > at:
        witness = None
    result, unresolved = plan_from_snapshot(snapshot, witness, at)
    event = _inventory_event(db, task, snapshot, witness, at)
    prices = _current_prices(db, source_id, event, at) if event else {}
    return result, witness, unresolved, event, prices, snapshot.get('offers', ())


def _inventory_event(db, task, snapshot, witness, at):
    if not witness:
        return None
    from app.storage.sportsgameodds_reference import read_event_frame

    source_id, declared = task['source_event_id'], task['event']
    expected = witness['event']['eventId']
    frame = (read_event_frame(db, source_id) or {}).get('facts')
    if frame and stamp(frame['received_at']) <= at and stamp(frame['starts_at']) == stamp(declared['starts_at']):
        context = frame['event_context']
        link = event_link_id((context.get('bookmaker_event_links') or {}).get('novig'))
        if not link or link != expected or context.get('phase') != 'pregame':
            return None
        from app.collection.experiment_acquisition import event_metadata

        normalized = event_metadata(dict(event_id=source_id, starts_at=frame['starts_at'],
            received_at=frame['received_at'], aliases=[], **context), frame['receipt_sha256'])
        if not all(normalized[k] == declared[k] for k in ('league', 'home', 'away')):
            return None
    elif ((snapshot.get('event') or {}).get('shared_provider_ids') or {}).get('novig_event') != expected:
        return None
    return dict(id=source_id, competition=declared['league'], home=declared['home'], away=declared['away'],
                scheduled_start=declared['starts_at'], shared_provider_ids={'novig_event': expected})


def _current_prices(db, source_id, event, at):
    rows = db.execute('''SELECT facts FROM public.current_sgo_reference
        WHERE event_id=%s AND bookmaker_id='novig'
        ORDER BY received_order DESC LIMIT 256''', (source_id,)).fetchall()
    prices = {}
    for row in rows:
        value = row['facts']
        if (value.get('line') is None or not value.get('available')
                or stamp(value['received_at']) > at or stamp(value['starts_at']) != stamp(event['scheduled_start'])):
            continue
        odds = Fraction(value['price_american'])
        price = 100 / (odds + 100) if odds > 0 else -odds / (100 - odds)
        prices.setdefault((value['market'], value['side'], Fraction(value['line'])), price)
    return prices


def plan_from_snapshot(snapshot, witness, at, *, moneyline=False):
    result, unresolved = {}, []
    for offer in snapshot.get('offers', ()):
        record = offer['record']
        if not supports(record, moneyline=moneyline):
            continue
        original = record['quote']['original']
        odds = Fraction(original['value'])
        price = 100 / (odds + 100) if odds > 0 else -odds / (100 - odds)
        key = storage.offer_key(record)
        result[key] = (_binding(record, witness, at=at), price)
        if result[key][0].get('reason') in ('sgo_native_outcome_link_unavailable',
                                            'sgo_native_outcome_absent_from_catalog'):
            unresolved.append((key, record, price))
    return result, unresolved


def _reconcile(plan, witness, unresolved, catalog, at, *, event=None, prices=None):
    # Without a direct outcome link, complete inventory is needed to prove
    # that the event, side and signed line identify a single contract.
    for key, record, price in unresolved:
        if catalog.reason:
            plan[key] = (dict(plan[key][0], reason=catalog.reason,
                              receipts=list(catalog.receipts)), price)
            continue
        plan[key] = (_binding(record, witness, at=at, inventory=catalog.markets), price)
    if event and not catalog.reason:
        entries = defaultdict(list)
        for record, binding in pregame_inventory_bindings(event, witness, catalog.markets, at=at):
            key = storage.offer_key(record)
            scope = (record['market_identity']['family'], binding['selected_side'], Fraction(binding['signed_line']))
            price = (prices or {}).get(scope, plan.get(key, (None, None))[1])
            entries[key].append((dict(binding, family=scope[0], league=event['competition'],
                                      starts_at=event['scheduled_start']), price))
        for key, matches in entries.items():
            if len(matches) > 1:
                existing, _ = plan.get(key, ({}, None))
                # A positively verified direct outcome link resolves a
                # duplicate game/side/line only for the same later quote.
                if outcome_link_id(existing.get('original_link')) and existing.get('available'):
                    existing['explicit_link_required'] = True
                else:
                    plan[key] = (dict(venue='novig', reason='unmatched_ambiguous_native_contract',
                                      complete=False, levels=[]), None)
            elif not plan.get(key, ({}, None))[0].get('available'):
                plan[key] = matches[0]
    return plan


def _reuse(before, after):
    """A repeated sequence is not evidence of either cache reuse or freshness."""
    original = {(r.get('path'), r.get('date'), r.get('sha256'))
                for r in before.get('receipts', ()) if r.get('date') and r.get('sha256')}
    return any((r.get('path'), r.get('date'), r.get('sha256')) in original
               for r in after.get('receipts', ()))


class ExperimentDepth:
    def __init__(self, service, *, connector=connect, client_factory=None, now=experiment.utc):
        from .dashboard_kalshi import Catalog

        self.service = service
        self.connector = connector
        self.client_factory = client_factory
        self.now = now
        self.task = None
        self.running = {}
        self.pending = {}
        self.kalshi_catalog = Catalog()
        self.progress = dict(state='starting', version=storage.VERSION)

    def enabled(self):
        service = self.service
        worker = service.workers.get('sportsgameodds')
        return (service.dispatch and not service.globally_stopped and worker is not None
                and 'sportsgameodds' not in service.paused_sources
                and not any(worker.controls().values()))

    def venue_enabled(self, venue):
        return self.enabled() and venue not in self.service.paused_sources

    def _near_checkpoint(self):
        from .experiment_acquisition import late_protection_active

        worker = self.service.workers.get('sportsgameodds')
        return worker is not None and late_protection_active(worker)

    def _targets(self, at, exclude):
        with self.connector() as db:
            return [task for task in targets(db, at, exclude=exclude) if not task['observed']]

    def _bindings(self, task, at):
        from .native_experiment_depth import VENUES, native_bindings
        from app.fees.product_schedules import read_all

        with self.connector() as db:
            plan, witness, unresolved, event, prices, source_offers = bindings(db, task, at)
            native = native_bindings(db, task, at, source_offers,
                                     venues=[venue for venue in VENUES if self.venue_enabled(venue)])
            products = read_all(db) if task.get('all_sports') else {}
        return plan, witness, unresolved, event, prices, native, source_offers, products

    def _still_targeted(self, task):
        identity = (task['game_id'], task['schedule_id'], task['target_at'])
        at = self.now()
        with self.connector() as db:
            return any((row['game_id'], row['schedule_id'], row['target_at']) == identity and not row['observed']
                       for row in targets(db, at))

    async def _prospective_native(self, client, task, offers, cutoff, products):
        """Bind the frozen strategy's quote to an independently listed instrument."""
        from .dashboard_pmus import read as pmus

        league = task['event']['league']
        records = {task['source_event_id']: [(storage.offer_key(r), None, r) for r in
            (offer.get('record', offer) for offer in offers)
            if r['market_identity']['family'] in ('spread', 'total')
            and r['market_identity']['period'] == 'full_game']}
        reads = []
        if self.venue_enabled('kalshi'):
            reads.append(self.kalshi_catalog.read(client, league, records, cutoff=cutoff, products=products))
        if self.venue_enabled('polymarket_us'):
            reads.append(pmus(client, league, records, at=self.now(), cutoff=cutoff, products=products))
        result = {}
        for group in await asyncio.gather(*reads, return_exceptions=True):
            if isinstance(group, Exception):
                failure(__name__, 'experiment_native_discovery', group)
            else:
                result.update(group)
        for key, _, record in records[task['source_event_id']]:
            binding = result.get(key)
            if not binding or record['quote']['venue'] != 'polymarket_us':
                continue
            if record['quote']['source']['provider'] == 'polymarket_us':
                continue
            link = (record.get('comparison_source_metadata') or {}).get('bookmaker_market_link') or {}
            if (link.get('host') not in ('polymarket.us', 'www.polymarket.us', 'gateway.polymarket.us')
                    or binding.get('route') not in link.get('path', '').split('/')):
                result.pop(key)
        return result

    async def _market_reads(self, client, plan, cutoff, *, slate=None):
        from .novig_experiment_depth import book_depth, catalog_depth
        from app.comparison.experiment_depth_execution import needs_book

        observations, events = {}, defaultdict(list)
        network_cutoff = cutoff - ASSEMBLY_RESERVE
        for key, (binding, quote_price) in plan.items():
            if binding.get('reason'):
                observations[key] = binding
            else:
                events[binding['event_id']].append((key, binding, quote_price))

        async def read_event(event_id, entries):
            if not self.venue_enabled('novig') or self.now() >= network_cutoff:
                return
            catalog = (await client.read_checkpoint_slate(*slate, network_cutoff) if slate is not None
                       else await client.read_event(event_id, network_cutoff))
            deeper = defaultdict(list)
            for key, binding, quote_price in entries:
                observation = catalog_depth(binding, catalog, cutoff)
                observation['identity_receipts'] = [binding['event_receipt'], binding['market_receipt']]
                observation['binding_revision'] = binding['revision']
                observation['binding_method'] = binding.get('binding_method', 'aggregate_outcome_link')
                if binding.get('explicit_link_required'):
                    observation['explicit_link_required'] = True
                observations[key] = observation
                hint = quote_price if quote_price is not None else next(
                    (level['price'] for level in observation['levels']), None)
                if hint is not None and needs_book(observation, quote_price=hint):
                    deeper[binding['market_id']].append((key, binding))

            async def read_market(market_id, sides):
                if not self.venue_enabled('novig') or self.now() >= network_cutoff:
                    return
                book = await client.read_book(market_id, network_cutoff)
                for key, binding in sides:
                    existing = observations[key]
                    observation = book_depth(binding, book, cutoff, catalog=existing)
                    observations[key] = observation

            if deeper:
                await asyncio.sleep(max(0, (cutoff - BOOK_AHEAD - self.now()).total_seconds()))
            await asyncio.gather(*(read_market(market_id, sides) for market_id, sides in deeper.items()))

        await asyncio.gather(*(read_event(event_id, entries) for event_id, entries in events.items()))
        return observations

    async def _capture(self, client, task):
        cutoff = task['target_at']
        novig, native_client = client
        plan, witness, unresolved, event, prices, native, offers, products = await asyncio.to_thread(
            self._bindings, task, self.now())
        slate = (task['event']['league'], task['event']['starts_at']) if task.get('all_sports') else None
        preparation_cutoff = cutoff-READ_AHEAD
        preparation, source_gaps = (), {}

        async def prepare_novig():
            if not (witness and (event or unresolved) and self.venue_enabled('novig')
                    and self.now() < preparation_cutoff):
                return None
            if slate:
                return await novig.read_checkpoint_slate(*slate, preparation_cutoff)
            return await novig.read_event(witness['event']['eventId'], preparation_cutoff)

        if slate:
            inventory, extra = await asyncio.gather(prepare_novig(), self._prospective_native(
                native_client, task, offers, preparation_cutoff, products))
            native.update(extra)
        else:
            inventory = await prepare_novig()
        if inventory is not None:
            preparation = inventory.receipts
            if inventory.reason:
                source_gaps['novig'] = inventory.reason
            plan = await asyncio.to_thread(_reconcile, plan, witness, unresolved, inventory, self.now(),
                                           event=event, prices=prices)
        elif not self.venue_enabled('novig'):
            source_gaps['novig'] = 'source_paused'
        elif not plan:
            source_gaps['novig'] = 'unmatched_pregame_event'
        await asyncio.sleep(max(0, (cutoff - READ_AHEAD - self.now()).total_seconds()))
        if (not self.enabled() or self.now() >= cutoff
                or task.get('all_sports') and not await asyncio.to_thread(self._still_targeted, task)):
            return
        observation_options = dict(slate=slate) if slate else {}
        decision, failures = await self._observe(novig, native_client, plan, native, cutoff, **observation_options)
        source_gaps.update(failures)
        known = self.now()
        if known > cutoff or not self.enabled():
            return
        key = (task['game_id'], task['schedule_id'])
        self.pending[key] = dict(task=task, known_at=known, observations=decision,
            reason=None if plan or native else 'unmatched_no_pregame_offer_witness',
            source_gaps=source_gaps, preparation=preparation, followup=None)
        # Stable prospective sampling keeps a follow-up independent of the
        # market result, and keeps its later evidence out of the decision.
        if not decision or int(hashed(key[0])[:8], 16) % 5:
            return
        later = cutoff + MANUAL_DELAY
        await asyncio.sleep(max(0, (later - READ_AHEAD - self.now()).total_seconds()))
        if not self.enabled() or self.now() >= later:
            return
        followup, failures = await self._observe(novig, native_client, plan, native, later, **observation_options)
        known = self.now()
        if known <= later and self.enabled():
            for offer, observation in followup.items():
                if _reuse(decision.get(offer, {}), observation):
                    observation.update(reason='followup_cache_reuse', complete=False)
            self.pending[key]['followup'] = dict(known_at=known, observations=followup,
                cutoff_at=later, source_gaps=failures)

    async def _observe(self, novig, native_client, plan, native, cutoff, *, slate=None):
        from .native_experiment_depth import VENUES

        native_options = dict(batch=True) if any(binding.get('contract') for binding in native.values()) else {}
        novig_options = dict(slate=slate) if slate else {}
        book_sides = await asyncio.gather(
            self._market_reads(novig, plan, cutoff, **novig_options),
            native_client.read_native(native, cutoff - ASSEMBLY_RESERVE, **native_options),
            return_exceptions=True,
        )
        observations, gaps = {}, {}
        for venues, result in zip((('novig',), VENUES), book_sides, strict=True):
            if isinstance(result, Exception):
                failure(__name__, 'experiment_depth_read', result)
                gaps.update(dict.fromkeys(venues, 'unavailable'))
            else:
                observations.update(result)
        return observations, gaps

    def _persist(self, pending):
        with self.connector() as db:
            kwargs = {k: v for k, v in pending.items() if k != 'followup'}
            saved = storage.save(db, protect_checkpoint=True, **kwargs)
            if saved and pending['followup']:
                storage.save(db, pending['task'], kind='followup', origin_id=saved['id'], protect_checkpoint=True,
                             **pending['followup'])
            return saved

    async def tick(self, client):
        for key in list(self.running):
            job = self.running[key]
            if not job.done():
                continue
            del self.running[key]
            if not job.cancelled() and (error := job.exception()):
                failure(__name__, 'experiment_depth_collect', error)
                self.progress = dict(self.progress, state='degraded', reason=type(error).__name__)
        at = self.now()
        if not self.enabled():
            for job in self.running.values():
                job.cancel()
            self.progress = dict(self.progress, state='paused')
            return
        if not self._near_checkpoint():
            for key in list(self.pending):
                pending = self.pending[key]
                if key in self.running or pending['task']['deadline_at'] > at:
                    continue
                try:
                    saved = await asyncio.to_thread(self._persist, pending)
                except BlockingIOError:
                    break
                except Exception as exc:
                    failure(__name__, 'experiment_depth_persist', exc)
                    self.progress = dict(self.progress, state='degraded', reason=str(exc)[:140])
                else:
                    self.progress = dict(self.progress, state='ready',
                        last_saved_id=saved['id'] if saved else None)
                del self.pending[key]
                break  # Yield before pulling another persistence turn.
        capacity = MAX_GAMES_IN_FLIGHT - len(self.running)
        if capacity > 0 and len(self.pending) < MAX_PENDING_BUNDLES:
            excluded = self.running.keys() | self.pending.keys()
            upcoming = await asyncio.to_thread(self._targets, at, excluded)
            for task in upcoming[:capacity]:
                key = (task['game_id'], task['schedule_id'])
                self.running[key] = asyncio.create_task(self._capture(client, task))
        self.progress = dict(self.progress, active=len(self.running), pending=len(self.pending))

    async def run(self):
        from .native_trading import NativeTrading
        from .native_experiment_depth import NativeExperimentDepth
        from .novig_experiment_depth import NovigExperimentDepth

        try:
            async with ((self.client_factory or NovigExperimentDepth)() as novig,
                        NativeExperimentDepth(now=self.now, allowed=lambda venue:
                            self.service.dispatch and not self.service.globally_stopped
                            and venue not in self.service.paused_sources) as native):
                dashboard = NativeTrading(self, connector=self.connector, now=self.now)
                self.dashboard_progress = dashboard.progress
                task = asyncio.create_task(native.dashboard_call(dashboard.run(novig, native), self.service.config),
                                           name='predict-dashboard-public-depth')
                try:
                    while True:
                        try:
                            await self.tick((novig, native))
                        except Exception as exc:
                            failure(__name__, 'experiment_depth_poll', exc)
                            self.progress = dict(self.progress, state='degraded', reason=type(exc).__name__)
                        await asyncio.sleep(2)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        finally:
            for job in self.running.values():
                job.cancel()
            await asyncio.gather(*self.running.values(), return_exceptions=True)

    async def start(self):
        self.task = asyncio.create_task(self.run(), name='predict-experiment-public-depth')

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
