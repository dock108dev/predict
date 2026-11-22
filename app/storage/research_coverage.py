"""Read-only research coverage; process health never establishes collection.

Working SQL bounds describe retained rows, not an all-time collection census.
Archive counters describe verified exports and recorded skips, not everything
missed while dispatch was down. Full file verification is an explicit CLI job.
"""
from datetime import datetime, timezone
import json

from app.collection.current_policy import DEFAULT, aggregate_provider, price_routes
from app.collection.runtime_status import read_runtime
from .odds_archive import FEEDS
from .odds_archive_export import status as archive_status
from .store import ROOT, stamp

VERSION = 'predict-research-coverage-1'
CENSUS_FILE = 'predict-odds-archive-census.json'


def archive_census_snapshot(path=None):
    """A saved explicit file scan, never a scan or export on a browser read."""
    path = path or ROOT/'.local'/CENSUS_FILE
    try:
        with path.open('rb') as file:
            raw = file.read(2*1024*1024+1)
        if len(raw) > 2*1024*1024:raise ValueError('archive_census_snapshot_capacity')
        value = json.loads(raw)
        if (not isinstance(value,dict) or value.get('version') != 'predict-odds-archive-census-1'
                or not isinstance(value.get('feeds'),dict)
                or set(value['feeds'])-set(FEEDS)
                or any(not isinstance(feed,dict)for feed in value['feeds'].values())):
            raise ValueError('archive_census_snapshot_format')
        return dict(state='available', **value)
    except FileNotFoundError:
        return dict(state='not_recorded', reason='run_explicit_file_census')
    except (OSError, ValueError, TypeError):
        return dict(state='unavailable', reason='saved_file_census_unavailable')


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def report(db, at=None):
    """Use the caller's bounded read-only transaction; performs zero acquisition."""
    now = stamp(at) if at is not None else datetime.now(timezone.utc)
    owner = read_runtime(db, now)
    config = owner.get('config') or DEFAULT
    received = {r['provider']: dict(r, count_unit='retained_representation_rows') for r in db.execute('''
        WITH retained AS (
        SELECT source AS provider,event_id,received_at FROM current_acquisition_image_parts
        UNION ALL SELECT 'sportsgameodds',event_id,to_timestamp(received_order)
        FROM current_sgo_event_frame
        UNION ALL SELECT 'sportsgameodds',event_id,(facts->>'received_at')::timestamptz
        FROM current_sgo_history
        UNION ALL SELECT source,NULLIF(event_id,''),received_at
        FROM acquisition_receipt WHERE received_at IS NOT NULL AND kind<>'failure'
        ) SELECT provider,count(*) records,count(DISTINCT event_id) events,
            count(*) FILTER(WHERE event_id IS NULL) records_without_event_identity,
            min(received_at) first_received_at,max(received_at) last_received_at
        FROM retained GROUP BY provider''').fetchall()}
    rejected = {r['provider']: r for r in db.execute('''
        SELECT source provider,count(*) records,max(received_at) last_received_at
        FROM acquisition_receipt WHERE kind='failure' GROUP BY source''').fetchall()}
    admitted = {r['provider']: r for r in db.execute('''
        SELECT e.provider,count(*) records,count(DISTINCT e.id) events,
            to_timestamp(min(o.received_order)) first_received_at,
            to_timestamp(max(o.received_order)) last_received_at
        FROM current_offer_storage o JOIN current_contract_storage c ON c.id=o.contract_id
        JOIN current_event e ON e.id=c.event_id GROUP BY e.provider''').fetchall()}
    calculated = {r['provider']: r for r in db.execute('''
        SELECT e.provider,count(*) records,count(DISTINCT p.game_key) events,
            count(*) FILTER(WHERE p.net_ev>0) positive,
            count(*) FILTER(WHERE p.net_ev<0) negative,
            count(*) FILTER(WHERE p.net_ev=0) zero,
            count(*) FILTER(WHERE p.net_ev IS NULL) unavailable,
            count(*) FILTER(WHERE p.valid_until<=%s) expired,
            max(p.calculated_at) last_calculated_at
        FROM current_pregame_calculation p JOIN current_contract_storage c ON c.id=p.contract_id
        JOIN current_event e ON e.id=c.event_id GROUP BY e.provider''', (now,)).fetchall()}
    reasons = db.execute('''SELECT e.provider,p.reason,count(*) records
        FROM current_pregame_calculation p JOIN current_contract_storage c ON c.id=p.contract_id
        JOIN current_event e ON e.id=c.event_id WHERE p.reason IS NOT NULL
        GROUP BY e.provider,p.reason ORDER BY e.provider,p.reason''').fetchall()
    for row in reasons:
        calculated[row['provider']].setdefault('unavailable_reasons', {})[row['reason']] = row['records']
    archive = archive_status(db)
    archives = {r['feed']: r for r in archive['feeds']}
    content = archive_census_snapshot()
    sources = sorted(set(FEEDS) | set(received) | set(admitted) | set(archives) |
                     {'the_odds_api', 'novig', 'oddslink_public_board'})
    panels = {p['provider']: p for p in owner.get('status', {}).get('sources', [])}
    source_rows = []
    for provider in sources:
        raw, normalized = received.get(provider), admitted.get(provider)
        last = [r['last_received_at'] for r in (raw, normalized) if r and r.get('last_received_at')]
        last_at = max(last) if last else None
        paused = provider in owner.get('paused_sources', [])
        enabled = bool(config.get('enabled')) and (
            config.get('aggregate_enabled') and provider == aggregate_provider(config)
            or provider in ('kalshi', 'polymarket_us') and config.get('direct_'+provider+'_enabled', True)
            or provider == 'novig' and config.get('direct_novig_enabled', True)
            or provider == 'oddslink_public_board' and config.get('aggregate_enabled')
                and aggregate_provider(config) == 'sportsgameodds')
        state = ('stopped' if owner.get('global_stopped') or paused else
                 'disabled' if not enabled else 'runtime_unavailable' if not owner.get('healthy') else
                 'no_retained_receipt' if last_at is None else 'last_receipt_observed')
        archived = dict(archives.get(provider) or {}) if provider in FEEDS else None
        panel = panels.get(provider) or {}
        mode = panel.get('metrics', {}).get('activity_mode') or {}
        schedule = ({k:mode.get(k) for k in ('mode','next_monitor_at','settings','monitor_schedule')}
                    if mode else None)
        source_rows.append(dict(provider=provider, configured=bool(enabled), paused=paused,
            acquisition_state=state,
            collection_schedule=schedule, processing_phase=panel.get('processing_phase'),
            worker_done=panel.get('worker_done'),
            source_state=owner.get('states', {}).get(provider) or panels.get(provider, {}).get('state'),
            last_received_at=_iso(last_at),
            receipt_age_seconds=None if last_at is None else (now-stamp(last_at)).total_seconds(),
            received=raw, rejected=rejected.get(provider),
            admitted=normalized, calculated=calculated.get(provider),
            archive_supported=provider in FEEDS, archive=archived,
            archive_reason=None if provider in FEEDS else 'unsupported_archive_route',
            collection_outage=None if owner.get('healthy') or not enabled or paused or owner.get('global_stopped') else
                dict(after_last_retained_receipt=_iso(last_at), observed_through=now.isoformat(),
                     exact_outage_start=None, missed_observations=None),
            archive_content=(content.get('feeds') or {}).get(provider),
            archive_first_received_at=((content.get('feeds') or {}).get(provider) or {}).get('first_received_at'),
            archive_last_received_at=((content.get('feeds') or {}).get(provider) or {}).get('last_received_at'),
            archive_census_observed_at=content.get('observed_at'),
            archive_receipt_bounds_reason=None if content['state']=='available' and provider in FEEDS else
                'run_explicit_file_census; counters do not retain receipt bounds'))
    runtime = {key: owner.get(key) for key in ('healthy', 'active', 'service_state', 'heartbeat_at',
               'reason_code', 'global_stopped', 'paused_sources')}
    return dict(version=VERSION, observed_at=now.isoformat(), runtime=runtime,
                sources=source_rows, price_routes=price_routes(config),
                archive_backlog={k: v for k, v in archive.items() if k != 'feeds'},
                archive_census={k:v for k,v in content.items()if k!='feeds'},
                startup_maintenance=owner.get('status', {}).get('background_work', {}).get('startup_storage_maintenance'),
                limitations=[
                    'SQL receipt bounds cover retained working rows, not all historical receipts.',
                    'Received, admitted and calculated counts have different units and are not a funnel.',
                    'Recorded archive skips do not count observations missed during a collection outage.',
                    'Verified local archive files are not an off-host backup.',
                    'Native archive retains top levels, not complete historical depth.'
                ], provider_requests=0)


def main():
    import argparse
    import json
    from .store import connect
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--at')
    args = parser.parse_args()
    with connect() as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        db.execute("SET LOCAL statement_timeout='10s'")
        print(json.dumps(report(db, args.at), default=_iso, indent=2))


if __name__ == '__main__':
    main()
