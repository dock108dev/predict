"""D2 mode of the existing single owner; saved calculation catalog stays intact."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from app.dashboard.multi_game import MultiOwner, configuration
from app.dashboard.e6_live import save_json, digest, ROOT
from app.collection.continuous import ContinuousSession, LIMITS, MIB, rss
from app.collection.transport_session import reopen
from app.collection.native_replay import verify_native_saved

OUTPUT = ROOT/'evidence/d2-coverage'


def spec():
    value = configuration()
    value.pop('multi_game_limits')
    value.update(duration=180, discovery_cadence=60,
        capture_authorization='D2: one explicitly authorized pilot, <=180 seconds from Start including discovery; zero spend')
    value['prediction'].update(discovery_requests=100, frame_bytes=MIB, connections=2)
    return value


def replay_groups(saved):
    groups = sorted({r['stream_group'] for r in saved['rows'] if r['type']=='prediction_command'})
    result = {}
    for group in groups:
        rows = [saved['rows'][0]]+[r for r in saved['rows'] if r.get('stream_group')==group]
        result[group] = verify_native_saved(dict(saved,rows=rows))
    if saved['rows'][0].get('spec',{}).get('native_sources'):
        from app.collection.native_rest_replay import verify
        result['native_rest']=verify(saved['rows'])
    return result


class CoverageOwner(MultiOwner):
    def __init__(self, *args, pilot_output=OUTPUT, session_factory=ContinuousSession, mock_segmented=False, profile_name=None, supervised_live=False, product_mode=False, native_approval_path=None, **kwargs):
        from app.collection.supervised import profile
        self.profile=profile(profile_name) if profile_name else None
        self.cutoffs={}
        self.product_mode=product_mode
        self.native_approval_path=native_approval_path
        if product_mode and (supervised_live or profile_name): raise ValueError('product mode cannot consume supervised allowances')
        self.supervised_live = supervised_live
        self.segmented_history = mock_segmented or supervised_live
        if supervised_live:
            from app.collection.supervised_live import validate_live_endpoints
            if mock_segmented or not self.profile or Path(pilot_output).resolve()==OUTPUT.resolve():
                raise ValueError('live profile requires exclusive isolated selection')
            validate_live_endpoints(kwargs.get('endpoints', {}))
        if self.profile and not self.segmented_history: raise ValueError('supervised profile requires isolated fixture path')
        self.mock_segmented = mock_segmented
        if mock_segmented:
            from app.collection.mock_history import validate_mock
            if Path(pilot_output).resolve() == OUTPUT.resolve() or 'endpoints' not in kwargs:
                raise ValueError('mock integration requires an explicit isolated output and fixture endpoints')
            validate_mock(dict(mode='mock',reference_enabled=False), kwargs['endpoints'])
        super().__init__(*args, personal_beta=True, session_factory=session_factory, **kwargs)
        self.pilot_output = Path(pilot_output)
        self.pilot_output.mkdir(parents=True,exist_ok=True)
        self.owner_lock = None
        self.previous_pilot = None
        if (self.pilot_output/'attempt.json').exists():
            attempt = json.loads((self.pilot_output/'attempt.json').read_text())
            report = self.pilot_output/attempt['session']/'report.json'
            if report.exists():
                retained = json.loads(report.read_text())
                self.previous_pilot = {k:retained[k] for k in ('session','reason','collection_seconds','cleanup_complete')}

    async def start(self, max_games=None, duration=180):
        if type(duration) is not int or not 1 <= duration <= (300 if self.profile else 180):
            raise ValueError('Duration must be 1 to 180 seconds')
        async with self.lock:
            if self.active():
                raise ValueError('Collector already running or finalizing')
            if not self.product_mode and (self.pilot_output/'attempt.json').exists():
                raise ValueError('D2 pilot consumed; no automatic or second live run authorized')
            self.owner_lock = ((OUTPUT if self.supervised_live else self.pilot_output)/'collector.lock').open('a')
            try:
                fcntl.flock(self.owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:
                self.owner_lock.close()
                self.owner_lock = None
                raise ValueError('Another collector owns the pilot') from None
            self.starting = True
            try:
                value = self.spec_factory() if self.product_mode else spec(); value.pop('multi_game_limits',None); value['duration'] = duration
                if self.product_mode:
                    from app.collection.mock_history import validate_mock
                    if value.get('native_sources') and value['mode']=='real':
                        from app.collection.native_approval import validate_approval
                        validate_approval(value,self.endpoints,self.native_approval_path,self.pilot_output,consume=True)
                    else:
                        validate_mock(value,self.endpoints)
                        value['capture_authorization']='B2 explicit product fixture session; no real-source allowance'
                    self.error=None
                options = {}
                if self.supervised_live:
                    value.update(mode='real',reference_enabled=False,capture_authorization='One explicitly authorized supervised live session; 300s maximum; direct Stop at 240s; zero spend')
                    options['supervised_live'] = True
                if self.mock_segmented:
                    value.update(mode='mock', reference_enabled=False,
                        capture_authorization='Isolated local mock collector; synthetic observations only; finite D3a policy')
                    options['mock_segmented'] = True
                if self.profile:
                    value.update(supervised_profile=self.profile['name'],discovery_cadence=120)
                    value['prediction'].update(messages=self.profile['group_messages'],session_bytes=self.profile['body_bytes'],discovery_requests=self.profile['requests'])
                self.session = self.session_factory(value,self.pilot_output/'pending',self.endpoints,**options)
                if isinstance(self.session,ContinuousSession):
                    from app.dashboard.session_projection import SessionProjection
                    self.session.product_session=self.product_mode
                    self.session.native_authorized=bool(self.product_mode and value.get('native_sources') and value['mode']=='real')
                    self.session.projection=SessionProjection()
                    self.session.acknowledged_observer=self.session.projection.apply
                folder = self.pilot_output/self.session.sid
                folder.mkdir()
                self.session.output = folder
                save_json(folder/'product-run.json' if self.product_mode else self.pilot_output/'attempt.json',dict(session=self.session.sid,at=datetime.now(timezone.utc).isoformat(),duration=duration))
                save_json(folder/'run-spec.json',value)
                limits = dict(LIMITS,
                    effective_ingress_bytes=16*MIB,effective_ingress_records=2048,
                    per_venue_body_bytes=16*MIB,per_group_messages=600,
                    journal_terminal_reserve_bytes=65536,journal_terminal_reserve_records=64)
                if self.mock_segmented:
                    from app.collection.segmented import POLICY
                    limits = dict(POLICY, per_group_messages=600,
                        rest_per_venue=100, connection_attempts=12, mode='isolated-mock-segmented')
                if self.profile: limits=dict(self.profile)
                save_json(folder/'aggregate-limits.json',limits)
                await self.session.start()
                fd = os.open(folder, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self.finalizer = asyncio.create_task(self.finish(folder))
                return self.session.sid
            except Exception:
                if self.session and self.session.task:
                    await self.session.stop()
                self.error = 'Product fixture Start failed; run retained' if self.product_mode else 'D2 Start failed; attempt retained, no retry authorized'
                self.release()
                raise
            finally:
                self.starting = False

    def release(self):
        if self.owner_lock:
            self.owner_lock.close()
            self.owner_lock = None

    async def finish(self, folder):
        if self.segmented_history:
            return await self.finish_mock_segmented(folder)
        try:
            await self.session.task
            session = self.session
            # Both transports close before export/replay. No duplicate raw export:
            # D3 segmentation remains deferred, primary journal remains authoritative.
            if session.persistence_error or session.cleanup_errors:
                raise ValueError('collector cleanup or persistence incomplete')
            # Reserve expansion before materializing a JSON journal for native replay.
            replay_allowed = rss()+max(session.journal.bytes, session.journal.expanded_bytes)*6 < LIMITS['rss_bytes']
            saved = None
            replay_error = None
            if replay_allowed:
                try:
                    saved = reopen(session.journal.path)
                    replay = replay_groups(saved)
                except Exception as exc:
                    replay_error = type(exc).__name__
                    replay = dict(verified=False,reason=replay_error)
            else:
                replay_error = 'replay_memory_reservation'
                replay = dict(verified=False,reason=replay_error)
            save_json(folder/'replay.json',replay)
            if replay_error:
                self.error = 'D2 native replay unverified: '+replay_error
            summary = dict(session=session.sid,state=session.state,reason=session.reason,
                cleanup_complete=session.cleanup_complete,health=session.health,
                coverage=session.status_coverage(),resources=session.resources(),
                inventory=session.discovery.inventory,discovery=session.discovery.status(),snapshots=session.snapshots,
                journal_chain=session.journal.previous,journal_state='complete' if session.journal.terminal_acknowledged else 'interrupted',accounting=session.accounting(),
                collection_seconds=session.collection_seconds,
                ever_market_ids={v:{k:sorted(ids) for k,ids in p.ever.items()} for v,p in session.producers.items()},
                limitations=['Filtered open/active catalogs; hidden/unopened/closed universe not claimed',
                    'US gameId filtering and short-page exhaustion do not guarantee upstream atomic snapshot or all listings',
                    'US Short depth derived only from supplied Long bids; completeness unverified' if session.spec.get('native_sources') else 'US Short purchase depth unavailable',
                    'Usable means synchronized and receipt-recent, not economic or settlement qualification'])
            save_json(folder/'report.json',summary)
            names = ['run-spec.json','aggregate-limits.json',session.journal.path.name,'replay.json','report.json']
            save_json(folder/'manifest.json',dict(session=session.sid,journal_chain=session.journal.previous,files={n:digest(folder/n) for n in names}))
            if sum(p.stat().st_size for p in folder.iterdir() if p.is_file())>LIMITS['output_bytes']:
                raise ValueError('output cap exceeded')
        except Exception as exc:
            self.error = 'D2 finalization incomplete: '+type(exc).__name__
            # Sanitized report; retain original journal in place.
            from app.diagnostics import failure
            failure(__name__,'d2_finalization',exc)
        finally:
            self.release()

    def status(self):
        value = super().status()
        value.update(operating_mode='d2-bounded-inventory',
            start_available=not self.active() and not (self.pilot_output/'attempt.json').exists(),
            pilot_allowance='one pilot; idle startup; no autoresume',
            stop_reason=self.session.reason if self.session else None,
            previous_pilot=self.previous_pilot,
            coverage=self.session.status_coverage() if self.session and hasattr(self.session,'discovery') else None,
            discovery=self.session.discovery.status() if self.session and hasattr(self.session,'discovery') else None,
            resources=self.session.resources() if self.session and hasattr(self.session,'resources') else None)
        if self.segmented_history:
            value.update(operating_mode='isolated-supervised-live' if self.supervised_live else 'isolated-mock-segmented',
                finalization=getattr(self, 'mock_result', None))
        if self.product_mode:
            configured=self.spec_factory().get('mode')=='mock'
            if self.native_approval_path and not configured:
                try:
                    from app.collection.native_approval import validate_approval
                    validate_approval(self.spec_factory(),self.endpoints,self.native_approval_path,self.pilot_output)
                    configured=True
                except (ValueError,OSError):pass
            value.update(operating_mode='product-session',start_available=configured and not self.active() and not getattr(self.session,'cleanup_errors',[]),pilot_allowance='One approved B3 qualification; no automatic repeat' if self.native_approval_path else 'Explicit bounded fixture sessions; real source Start not authorized')
        return value

    def history_paths(self):
        from app.dashboard.session_history import list_sessions
        return list_sessions([self.output,self.pilot_output])

    def current_snapshot(self):
        s=self.session
        if not s or not hasattr(s,'projection'): return None
        if s.persistence_error: raise ValueError('Current projection unavailable: persistence failed')
        if getattr(s,'projection_error',None):
            if s.segmented_history: raise ValueError('Projection unavailable until verified saved reconciliation')
            from app.dashboard.session_projection import SessionProjection
            rebuilt=SessionProjection()
            for row in reopen(s.journal.path)['rows'][:s.journal.count]: rebuilt.apply(row)
            s.projection=rebuilt;s.acknowledged_observer=rebuilt.apply;s.projection_error=None
        state=self.status()['state']
        frozen=s.projection.snapshot(mode='saved')
        self.cutoffs[frozen['durable_cursor']]=frozen
        from app.dashboard.bounds import retained_bytes
        while len(self.cutoffs)>8 or retained_bytes(self.cutoffs)>32*1024*1024:self.cutoffs.pop(next(iter(self.cutoffs)))
        return s.projection.snapshot(mode='current' if state=='running' else 'saved',state='saving' if self.active() and state!='running' else 'current' if state=='running' else 'incomplete' if self.error else 'saved')

    async def finish_mock_segmented(self, folder):
        # Same collector/task owner; only persistence finalization is substituted.
        import time
        import tracemalloc
        from collections import Counter
        from hashlib import sha256
        from app.reference.records import packed
        from app.collection.segmented import SegmentedReader, POLICY, fsync_dir
        from app.collection.native_replay import GroupedNativeVerifier
        started = time.monotonic(); baseline = rss(); own_trace = not tracemalloc.is_tracing() and not self.profile
        replay_samples=[]
        def save_metadata(path, value):
            self.session.journal.history._guard(len(json.dumps(value,indent=2).encode()))
            save_json(path,value)

        outcome = dict(status='failed', operator_stop=False, native_verified=False)
        try:
            await self.session.task
            s = self.session
            if s.persistence_error or s.cleanup_errors:
                raise ValueError('collector cleanup or persistence incomplete')
            if own_trace: tracemalloc.start()
            replay_started = time.monotonic(); replay_baseline = rss()
            replay_traced_start = tracemalloc.get_traced_memory()[0]
            if own_trace: tracemalloc.reset_peak()
            verifier = GroupedNativeVerifier(self.profile['name'] if self.profile else None); counts = Counter(); ids = set(); sequence = sha256()
            if self.profile:
                from app.collection.supervised import ExactIdentities
                ids=ExactIdentities(folder/'identities')
                deadline=time.monotonic()+self.profile['finalization_seconds']
                s.journal.history.finalizing=True
            published = {}; applied = {}; last_at = None
            for row in SegmentedReader(folder/'history').rows():
                if row['session_id'] != s.sid: raise ValueError('source session identity mismatch')
                if last_at and row['observed_at'] < last_at: raise ValueError('observation time order changed')
                last_at = row['observed_at']
                if 'ingress_id' in row:
                    if not self.profile and row['ingress_id'] in ids: raise ValueError('duplicate observation identity')
                    ids.add(row['ingress_id'])
                sequence.update(packed(row).encode()); counts[row['type']] += 1
                if row['type'] == 'coverage_inventory':
                    generation = row['generation']
                    if row['previous_generation'] != (max(published) if published else None):
                        raise ValueError('catalog generation dependency mismatch')
                    published[generation] = {v:cat['selection']['ids'] for v,cat in row['inventory'].items()}
                if row['type'] == 'coverage_applied':
                    if row['generation'] not in published or not set(row['selected_ids']).issubset(published[row['generation']][row['source']]):
                        raise ValueError('applied plan lacks published catalog')
                    applied[row['source']] = row['generation']
                verifier.feed(row)
                if self.profile:
                    if time.monotonic()>deadline: raise ValueError('supervised_finalization_deadline')
                    if sum(counts.values())%1024==0:
                        from app.collection.supervised import native_state
                        from app.dashboard.bounds import retained_bytes
                        size=retained_bytes(dict(groups={k:native_state(v) for k,v in verifier.groups.items()},previous=verifier.previous_books,identities=ids.chunk,published=published))
                        replay_samples.append(dict(rows=sum(counts.values()),bytes=size,rss=rss()))
                        if size>self.profile['state_bytes'] or rss()>=self.profile['rss']: raise ValueError('supervised_replay_memory_cap')
            identity_count=ids.finish() if self.profile else len(ids)
            if counts['session_finished'] != 1 or identity_count != s.delivered:
                raise ValueError('terminal or admission accounting mismatch')
            result = verifier.result(state='complete',sha256=digest(folder/'history'/'manifest.json'))
            save_metadata(folder/'replay.json',dict(groups=result,derived_health_books=verifier.derived_health_books,
                counts=dict(counts),sequence_sha256=sequence.hexdigest(),published_generations=sorted(published),
                applied_generations=applied,incremental=True))
            outcome.update(status='complete',operator_stop=s.reason=='manual_stop',native_verified=True,
                replay_seconds=time.monotonic()-replay_started, replay_baseline_rss=replay_baseline,
                counts=dict(counts),published_generations=sorted(published),applied_generations=applied,
                replay_traced_start=replay_traced_start,replay_traced_peak=tracemalloc.get_traced_memory()[1])
        except Exception as exc:
            self.error = 'Mock segmented finalization incomplete: '+type(exc).__name__
            outcome['error'] = type(exc).__name__
        finally:
            s = self.session
            current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (0,0)
            if own_trace and tracemalloc.is_tracing(): tracemalloc.stop()
            outcome.update(reason=s.reason,cleanup_complete=s.cleanup_complete,cleanup_errors=s.cleanup_errors,
                persistence_error=s.persistence_error,seconds=time.monotonic()-started,
                baseline_rss=baseline,peak_rss=rss(),traced_peak=peak,traced_current=current)
            if self.profile:
                outcome.update(profile=self.profile['name'],replay_state_samples=replay_samples,live_state_samples=s.state_samples,rate_peaks=s.rate_budget.peak,frames_received=s.rate_budget.frame_count,
                    stop_to_closed_seconds=(s.closed_at-s.stop_requested_at if hasattr(s,'stop_requested_at') else None))
            self.mock_result = outcome
            try:
                history = s.journal.history
                history._guard(65536)
                save_metadata(folder/'report.json',dict(session=s.sid,reason=s.reason,collection_seconds=s.collection_seconds,
                    cleanup_complete=s.cleanup_complete,outcome=outcome,accounting=s.accounting(),
                    resources=s.resources(),coverage=s.status_coverage(),discovery=s.discovery.status(),
                    producer_tasks_done=all(g['task'].done() for p in s.producers.values() for g in p.groups.values() if 'task' in g),
                    streams_closed=all(g['producer'].stream is None or g['producer'].stream.closed for p in s.producers.values() for g in p.groups.values())))
                if outcome['status']=='complete':
                    names=['run-spec.json','aggregate-limits.json','history/manifest.json','replay.json','report.json']
                    save_metadata(folder/'manifest.pending.json',dict(session=s.sid,mode='isolated-supervised-live' if self.supervised_live else 'isolated-mock-segmented',
                        files={n:digest(folder/n) for n in names}))
                    os.replace(folder/'manifest.pending.json',folder/'manifest.json');fsync_dir(folder)
                outcome['disk_bytes'] = history.disk_bytes()
                if outcome['disk_bytes'] > (self.profile or POLICY)['output']: raise ValueError('segmented output cap')
            except Exception as exc:
                outcome.update(status='failed',operator_stop=False,finalization_error=type(exc).__name__)
                self.error = 'Mock segmented finalization incomplete: '+type(exc).__name__
                try: save_metadata(folder/'finalization-failure.json',outcome)
                except Exception: pass
            finally:
                self.release()


class OfflineHistoryOwner:
    """D3a retained-input owner. Deliberately has no Start, credentials or transport.

    Call admit with unmodified retained observations, drain the bounded work queue,
    then await Stop. Feed/task handles may only be isolated offline fixtures here.
    This is not selected by the application factory or CoverageOwner.
    """
    def __init__(self, folder, *, label, fault=None):
        from app.collection.segmented import SegmentedJournal
        from app.dashboard.bounds import CaptureQueue
        self.journal = SegmentedJournal(folder, label=label, fault=fault)
        self.queue = CaptureQueue(48, 4*MIB)
        self.received = self.accepted = self.durable = self.rejected = self.drained = 0
        self.intake_closed = False; self.reason = None; self.cleanup_errors = []
        self.feeds = {}; self.tasks = []; self.stopped = False

    def admit(self, row):
        from app.collection.odds_http import BudgetStop
        self.received += 1
        if self.intake_closed:
            self.rejected += 1
            return False
        before = self.journal.observations
        attempts = self.journal.admission_attempts
        try:
            self.journal.save(row)
        except BudgetStop:
            self.rejected += 1; self.intake_closed = True; self.reason = 'resource_stop'
            raise
        except BaseException:
            self.accepted += self.journal.admission_attempts-attempts
            self.rejected += int(self.journal.admission_attempts == attempts)
            self.intake_closed = True; self.reason = 'storage_failure'
            raise
        self.accepted += 1; self.durable += self.journal.observations-before
        try:
            self.queue.put_nowait(row)
        except asyncio.QueueFull:
            self.intake_closed = True; self.reason = 'queue_capacity'
            raise
        return True

    def drain(self):
        while not self.queue.empty():
            self.queue.get_nowait(); self.queue.task_done(); self.drained += 1

    async def stop(self, reason='manual_stop'):
        if self.stopped: return
        self.intake_closed = True; self.reason = self.reason or reason
        for task in self.tasks: task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        results = await asyncio.gather(*(feed.aclose() for feed in self.feeds.values()), return_exceptions=True)
        self.cleanup_errors = [type(r).__name__ for r in results if isinstance(r, BaseException)]
        self.drain()
        try:
            if self.journal.failed: self.journal.abort()
            else: self.journal.finish(cleanup_complete=not self.cleanup_errors)
        finally:
            self.stopped = True
            if not self.journal.closed: self.journal.abort()

    def accounting(self):
        return dict(received=self.received, accepted=self.accepted, rejected=self.rejected,
            durable=self.durable, unresolved=self.accepted-self.durable,
            queue_drained=self.drained, queue_pending=self.queue.qsize(),
            durable_not_queued=self.durable-self.drained-self.queue.qsize(),
            queue_peak_objects=self.queue.high_items, queue_peak_expanded_bytes=self.queue.high_bytes,
            cleanup_errors=self.cleanup_errors, reason=self.reason, **self.journal.accounting())


def replay_segmented(folder):
    """Exact native books and packets without whole-run materialization."""
    from app.collection.segmented import SegmentedReader
    from app.collection.native_replay import GroupedNativeVerifier
    verifier = GroupedNativeVerifier()
    reader = SegmentedReader(folder)
    for row in reader.rows(): verifier.feed(row)
    from app.collection.segmented import digest_file
    return verifier.result(state='complete', sha256=digest_file(Path(folder)/'manifest.json'))
