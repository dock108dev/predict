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
    return result


class CoverageOwner(MultiOwner):
    def __init__(self, *args, pilot_output=OUTPUT, session_factory=ContinuousSession, **kwargs):
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
        if type(duration) is not int or not 1 <= duration <= 180:
            raise ValueError('Duration must be 1 to 180 seconds')
        async with self.lock:
            if self.active():
                raise ValueError('Collector already running or finalizing')
            if (self.pilot_output/'attempt.json').exists():
                raise ValueError('D2 pilot consumed; no automatic or second live run authorized')
            self.owner_lock = (self.pilot_output/'collector.lock').open('a')
            try:
                fcntl.flock(self.owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:
                self.owner_lock.close()
                self.owner_lock = None
                raise ValueError('Another collector owns the pilot') from None
            self.starting = True
            try:
                value = spec(); value['duration'] = duration
                self.session = self.session_factory(value,self.pilot_output/'pending',self.endpoints)
                folder = self.pilot_output/self.session.sid
                folder.mkdir()
                self.session.output = folder
                save_json(self.pilot_output/'attempt.json',dict(session=self.session.sid,at=datetime.now(timezone.utc).isoformat(),duration=duration))
                save_json(folder/'run-spec.json',value)
                save_json(folder/'aggregate-limits.json',dict(LIMITS,
                    effective_ingress_bytes=16*MIB,effective_ingress_records=2048,
                    per_venue_body_bytes=16*MIB,per_group_messages=600,
                    journal_terminal_reserve_bytes=65536,journal_terminal_reserve_records=64))
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
                self.error = 'D2 Start failed; attempt retained, no retry authorized'
                self.release()
                raise
            finally:
                self.starting = False

    def release(self):
        if self.owner_lock:
            self.owner_lock.close()
            self.owner_lock = None

    async def finish(self, folder):
        try:
            await self.session.task
            session = self.session
            # Both transports close before export/replay. No duplicate raw export:
            # D3 segmentation remains deferred, primary journal remains authoritative.
            if session.persistence_error or session.cleanup_errors:
                raise ValueError('collector cleanup or persistence incomplete')
            # Reserve expansion before materializing a JSON journal for native replay.
            replay_allowed = rss()+session.journal.bytes*6 < LIMITS['rss_bytes']
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
                    'US Short purchase depth unavailable',
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
        return value
