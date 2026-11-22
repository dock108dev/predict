"""Explicit, single-page existing-source result capture for declared research.

No browser read calls this owner. It uses the running collector's existing
account partition, operational budget, reservations, rate/hold and Stop guards.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import json

from app.storage.store import ROOT, connect, stamp
from .current_policy import aggregate_provider, aggregate_scope
from .runtime_status import read_runtime


def eligible(owner, cases, event_ids, *, at):
    config = owner.get('config') or {}
    if (not owner.get('active') or owner.get('global_stopped') or
            'sportsgameodds' in owner.get('paused_sources', ()) or not config.get('enabled') or
            not config.get('aggregate_enabled') or aggregate_provider(config) != 'sportsgameodds'):
        return False
    for identity in event_ids:
        matches = [case for case in cases if identity in case.get('source_event_ids', ())]
        if not matches or any(case.get('league') not in aggregate_scope(config) or
                              stamp(case['starts_at']) > at for case in matches):
            return False
    return True


async def collect(event_ids, *, connector=connect):
    if not isinstance(event_ids, list) or not 1 <= len(event_ids) <= 2 or len(set(event_ids)) != len(event_ids):
        raise ValueError('one_or_two_declared_result_event_ids_required')
    from app.research.records import list_cohorts, import_sporting
    from .sportsgameodds_collector import GuardedPageCollector
    from .sportsgameodds_ledger import ObjectLedger
    from .sportsgameodds_transport import SportsgameoddsTransport, ODD_IDS
    from .sportsgameodds_worker import credential, pacing_reset
    from .sportsgameodds_usage import read_usage
    from .sportsgameodds_schedule import response_object_charge
    from .activity_collector import budget_admit
    from .current_storage_policy import require_disk_space, SQL_BYTE_CAP, sql_usage
    from .original_receipts import capture
    from .sgo_game_results import observations
    from .bulk_checkpoint import owned_thread

    def authority():
        with connector() as db, db.transaction():
            db.execute('SET TRANSACTION READ ONLY')
            db.execute("SET LOCAL statement_timeout='5s'")
            owner = read_runtime(db)
            cases = [case for cohort in list_cohorts(db, limit=100) for case in cohort['population']]
            if sql_usage(db) >= SQL_BYTE_CAP:
                raise ValueError('research_result_sql_storage_guard')
        require_disk_space(ROOT / '.local/postgres')
        return owner, cases

    owner, cases = await owned_thread(authority)
    now = datetime.now(timezone.utc)
    if not eligible(owner, cases, event_ids, at=now):
        raise ValueError('research_results_not_declared_started_or_source_authorized')
    key = credential()
    ledger_path = ROOT / '.local/predict-odds/sportsgameodds-ledger.sqlite3'
    if not ledger_path.is_file():
        raise ValueError('existing_sgo_account_ledger_required')
    ledger = ObjectLedger(ledger_path)
    initial = await read_usage(key)
    reset, basis = pacing_reset(initial, now)
    window = ledger.account_identity() + ':' + reset.isoformat()
    # An explicit research action cannot manufacture a new account window.
    before = ledger.status(window)
    budget_admit(ledger, window, len(event_ids), now)

    async def usage():
        value = await read_usage(key)
        current_reset, current_basis = pacing_reset(value, datetime.now(timezone.utc))
        if current_basis != basis or current_reset != reset:
            raise ValueError('sgo_account_reset_evidence_changed')
        return dict(value, reset_at=current_reset)

    async def check(params):
        current, population = await owned_thread(authority)
        # Recheck the same recorded operating limits immediately before dispatch;
        # an in-flight reservation is counted conservatively by the existing owner.
        budget_admit(ledger, window, len(event_ids), datetime.now(timezone.utc))
        return eligible(current, population, event_ids, at=datetime.now(timezone.utc))

    def controls():
        # GuardedPageCollector invokes this again after awaited eligibility.
        with connector() as db:
            current = read_runtime(db)
        return dict(stopped=not current.get('active') or current.get('global_stopped', False),
                    source_paused='sportsgameodds' in current.get('paused_sources', ()))

    async def retain(params, response):
        return await owned_thread(capture, params, response)

    transport = SportsgameoddsTransport()
    collector = GuardedPageCollector(ledger, window, transport, controls=controls,
                                    account_usage=usage, eligible=check, receipt_retainer=retain)
    try:
        page = await collector.fetch(dict(eventIDs=','.join(event_ids), oddID=','.join(sorted(ODD_IDS)),
                                          limit=len(event_ids), includeOpposingOdds=True), key)
    finally:
        await transport.close()
    if any(event['event_id'] not in event_ids for event in page.events):
        raise ValueError('research_result_returned_unrequested_event')
    items = observations(page, known_at=datetime.now(timezone.utc).isoformat())
    with connector() as db:
        imported = import_sporting(db, items)
    after = ledger.status(window)
    return dict(source='sportsgameodds', requested_events=event_ids, returned_events=len(page.events),
                result_observations=len(items), receipt_sha256=page.receipt_sha256,
                charged_objects=response_object_charge(len(page.events)),
                account_window_charge_delta=after['charged']-before['charged'],
                account_window_delta_attribution='may_include_concurrent_ordinary_collection',
                hold_objects_after=after['held'], imported=imported,
                sporting_results=items, paid_event_requests=1, exempt_usage_reads=2,
                note='Explicit declared sporting-result capture; no venue settlement or actual fills inferred.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('event_id', nargs='+')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(collect(args.event_id)), sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
