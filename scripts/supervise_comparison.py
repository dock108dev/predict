#!/usr/bin/env python3
"""Bounded localhost supervision, independent of browser navigation/lifetime.

Never opens or closes a browser, resolves credentials, or starts collection.
The approved app/collector remain responsible for provider access and hard cutoff.
"""
import argparse
from datetime import datetime, timezone
import gzip
import http.client
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class LocalApp:
    def __init__(self, url='http://127.0.0.1:8820', timeout=2):
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Only the local app is permitted')
        self.port = parsed.port or 80
        self.origin = f'http://127.0.0.1:{self.port}'
        self.timeout = timeout

    def request(self, route, *, stop=False):
        if route not in ('/api/status', '/api/dashboard?view=feed', '/api/stop') or (route == '/api/stop') != stop:
            raise ValueError('Observer route not permitted')
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout)
        try:
            connection.request('POST' if stop else 'GET', route, body=b'{}' if stop else None,
                               headers={'Origin': self.origin, 'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f'Local app returned HTTP {response.status}; redirects are not followed')
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise RuntimeError('Local response exceeds 4 MiB')
            return json.loads(body)
        finally:
            connection.close()


class Evidence:
    def __init__(self, folder, limit=32 * 1024 * 1024):
        self.folder = Path(folder)
        self.folder.mkdir(exist_ok=False)
        self.limit = limit
        self.used = 0
        self.sizes = {}

    def save(self, name, value):
        body = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
        # Preserve full responses losslessly without repeated multi-MiB JSON files.
        if name.startswith('dashboard-') or name == 'saved-dashboard.json':
            body = gzip.compress(body, mtime=0)
            name += '.gz'
        # Include separately retained browser checkpoints in the same observer cap.
        self.used = sum(p.stat().st_size for p in self.folder.iterdir() if p.is_file())
        target = self.folder / name
        previous = target.stat().st_size if target.exists() else 0
        next_used = self.used - previous + len(body)
        # Reserve 64 KiB for failure/stop evidence even when observations hit the cap.
        maximum = self.limit if name in ('failure.json', 'safety-stop.json', 'result.json') else self.limit - 65536
        if next_used > maximum:
            raise RuntimeError('Observer evidence cap reached')
        temporary = self.folder / (name + '.tmp')
        temporary.write_bytes(body)
        temporary.replace(self.folder / name)
        self.used = next_used
        self.sizes[name] = len(body)


class Supervisor:
    def __init__(self, app, output, attempt, evidence, *, clock=time.monotonic,
                 wall=lambda: datetime.now(timezone.utc).isoformat(), announce=print,
                 start_before=None):
        self.app, self.output, self.attempt, self.evidence = app, Path(output), attempt, evidence
        self.clock, self.wall, self.announce = clock, wall, announce
        self.start_before = start_before
        self.started = None
        self.safety = None
        self.samples, self.guidance = [], []
        self.sent = set()
        self.last_dashboard = -float('inf')
        self.finished = False
        self.ready_passed = False
        self.bound_session = False

    def record(self, name, value):
        self.evidence.save(name, value)

    def ready(self):
        if (self.output / 'b3-attempt.json').exists():
            raise ValueError('Attempt already consumed; no late observer restart')
        status = self.app.request('/api/status')
        if status.get('active') or not status.get('start_available') or status.get('session'):
            raise ValueError('Expected unused idle app before Start')
        self.record('monitor-ready.json', dict(attempt=self.attempt, at=self.wall(), status=status,
                    evidence_kind='Local backend supervision only; browser visibility must be verified separately'))
        self.ready_passed = True
        self.announce('Monitor ready. Verify the visible browser and record observer-ready.json before Start. Stop manually at 120 seconds.', flush=True)

    def bind_start(self):
        marker = self.output / 'b3-attempt.json'
        if self.started is None and marker.exists():
            value = json.loads(marker.read_text())
            if value.get('attempt_id') != self.attempt:
                raise ValueError('Consumed attempt identity mismatch')
            self.started = float(value['started_monotonic'])
            if self.started > self.clock():
                raise ValueError('Invalid monotonic Start marker')
            self.record('start-observed.json', dict(at=self.wall(), marker=value,
                                                  detected_after_seconds=self.clock() - self.started))
            self.announce('Start consumed. Manual Stop is due at 120 seconds from the recorded Start.', flush=True)

    def safety_stop(self, reason):
        """Automatic failure/overrun stop is never counted as manual Stop evidence."""
        if self.safety is not None:
            return
        self.safety = dict(reason=reason, kind='automatic observer safety stop; NOT manual Stop', at=self.wall(), attempts=[])
        for _ in range(2):  # two local attempts only, never provider requests or restarts
            try:
                try:
                    status = self.app.request('/api/status')
                except Exception:
                    if not self.bound_session:
                        raise
                    status = dict(session=self.attempt, active=True)
                if status.get('session') != self.attempt:
                    self.safety['attempts'].append(dict(error='Local session identity mismatch; no Stop sent'))
                    break
                if not status.get('active'):
                    self.safety['attempts'].append(dict(already_inactive=True))
                    break
                response = self.app.request('/api/stop', stop=True)
                self.safety['attempts'].append(dict(response=response))
                break
            except Exception as exc:
                self.safety['attempts'].append(dict(error=str(exc)))
        try:
            self.record('safety-stop.json', self.safety)
        except Exception as exc:
            self.announce(f'Could not retain safety Stop: {exc}', flush=True)
        self.announce('Safety Stop requested automatically. This does NOT demonstrate manual Stop. Verify cleanup; the independent hard guard remains in force.', flush=True)

    def tick(self):
        self.bind_start()
        status = self.app.request('/api/status')
        now = self.clock()
        if self.started is None:
            if status.get('active'):
                raise ValueError('Active app without matching consumed Start marker')
            if self.start_before and datetime.now(timezone.utc) > datetime.fromisoformat(self.start_before):
                self.record('result.json', dict(state='unused Start window expired', at=self.wall()))
                self.finished = True
            return
        if status.get('session') != self.attempt:
            # Start consumes its marker before credential lookup/session construction.
            # Briefly tolerate that initial transition, never a different session.
            if not self.bound_session and status.get('session') is None and now-self.started <= 5:
                return
            raise ValueError('Running app identity changed')
        elapsed = now - self.started
        self.bound_session = True
        if status.get('active'):
            for due, message in [(90, 'Prepare to click Stop at two minutes.'), (110, 'Click Stop in ten seconds.'),
                                 (120, 'Click Stop now in the ordinary app.')]:
                if elapsed >= due and due not in self.sent:
                    self.sent.add(due)
                    self.guidance.append(dict(due_seconds=due, delivered_seconds=elapsed, at=self.wall(), message=message))
                    self.record('guidance.json', self.guidance)
                    self.announce(message, flush=True)
            if elapsed >= 140:
                self.safety_stop('Manual stopping point missed at 140 seconds')
        self.samples.append(dict(at=self.wall(), elapsed_seconds=elapsed, status=status))
        self.record('status-samples.json', self.samples)
        if now - self.last_dashboard >= 5 or not status.get('active'):
            dashboard = self.app.request('/api/dashboard?view=feed')
            self.record(f'dashboard-{len(self.samples):03d}.json', dashboard)
            self.last_dashboard = now
        if not status.get('active') and status.get('cleanup_complete'):
            first = self.app.request('/api/dashboard?view=feed')
            second = self.app.request('/api/dashboard?view=feed')
            if first.get('state') != 'saved' or second.get('state') != 'saved':
                raise ValueError('Stopped session did not reopen as saved')
            exact = first.get('comparisons') == second.get('comparisons')
            if not exact:
                raise ValueError('Saved comparison mismatch')
            closed = json.loads((self.output / 'network-closed.json').read_text())
            if closed.get('attempt_id') != self.attempt or closed['monotonic'] > self.started + 180:
                raise ValueError('Network closure absent or outside approved ceiling')
            self.record('saved-dashboard.json', second)
            self.record('result.json', dict(at=self.wall(), state='stopped', status=status,
                        network_closed=closed, network_seconds=closed['monotonic']-self.started,
                        saved_comparisons_exact=exact, browser_reopening='Separate visible check required',
                        stop_classification=self.safety['kind'] if self.safety else 'ordinary Stop; verify operator action separately',
                        timing='Backend samples only; no visible-paint or upstream freshness claim'))
            self.finished = True
            self.announce('Collection stopped and saved comparisons match. Browser remains open for visible reopening and review.', flush=True)
        elif elapsed > 190:
            raise RuntimeError('Cleanup not verified after independent cutoff; preserve incomplete evidence')

    def run(self, *, sleep=time.sleep):
        try:
            self.ready()
            while not self.finished:
                self.tick()
                if not self.finished:
                    sleep(1)
        except BaseException as exc:
            # Stop first, even if evidence writing failed. Never close a browser.
            try:
                self.bind_start()
            except Exception:
                pass
            if self.ready_passed and (self.started is not None or (self.output / 'b3-attempt.json').exists()):
                self.safety_stop('Observer failed: ' + str(exc))
            try:
                self.record('failure.json', dict(at=self.wall(), error=str(exc), started=self.started is not None,
                            browser='Not owned or closed by this monitor', manual_stop_demonstrated=False))
            except Exception:
                pass
            raise


def current_status(app, attempt, evidence, *, wall_clock=time.time):
    """Always query the running app; retained samples are never current status."""
    state = app.request('/api/status')
    if state.get('session') not in (None, attempt):
        raise ValueError('Current local app belongs to a different attempt')
    folder = Path(evidence)
    sample = folder / 'status-samples.json'
    age = wall_clock() - sample.stat().st_mtime if sample.exists() else None
    failed = (folder / 'failure.json').exists()
    safety = (folder / 'safety-stop.json').exists()
    healthy = age is not None and 0 <= age <= 4 and not failed and not safety
    return dict(at=datetime.now(timezone.utc).isoformat(), current_app_status=state,
                monitor_sample_age_seconds=age, monitor_failed=failed, automatic_safety_stop=safety,
                guidance_allowed=bool(state.get('active') and healthy),
                instruction=('Manual Stop guidance allowed; app is active and monitor healthy' if state.get('active') and healthy
                             else 'Do not issue timed Stop guidance from retained samples; verify current state and any failure'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--status', action='store_true', help='Read current localhost status, even after a consumed attempt')
    args = parser.parse_args()
    if args.status:
        draft = json.loads((args.package / 'approval.draft.json').read_text())
        attempt = draft['attempt_id']
        print(json.dumps(current_status(LocalApp(), attempt, args.package.parent / ('supervised-observation-' + attempt)), indent=2))
        return
    from app.collection.two_source_package import verify
    from app.dashboard.two_source_preview import check_package
    _, _, seal = verify(args.package)
    spec = json.loads((args.package / 'activation/run-spec.json').read_text())
    approval = json.loads((args.package / 'activation/approval.json').read_text())
    check_package(spec, approval, approval['output'])
    if approval.get('package_seal_sha256') != seal:
        raise ValueError('Activation does not bind this sealed package')
    attempt = spec['two_source_qualification']['attempt_id']
    evidence = Evidence(args.package.parent / ('supervised-observation-' + attempt))
    supervisor = Supervisor(LocalApp(), approval['output'], attempt, evidence, start_before=spec['start_before'])
    supervisor.run()


if __name__ == '__main__':
    main()
