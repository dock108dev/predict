"""Sample the local read-only desk census without starting provider acquisition."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def read(base, route, *, timeout=20):
    with urlopen(base + route, timeout=timeout) as response:
        return json.load(response)


def payoff_summary(value):
    payoffs = [pair['retail_payoff'] for group in value.get('rows', ()) for pair in group.get('pairs', ())]
    return dict(read_at=value.get('publication', {}).get('read_at'), state=value.get('state'),
        groups=value.get('total'), inspected_groups=len(value.get('rows', ())),
        eligible_pair_count=value.get('eligible_pair_count'), inspected_pairs=len(payoffs),
        sized_payoff_available=sum(bool(payoff.get('available')) for payoff in payoffs),
        unavailable_reasons=dict(Counter(payoff.get('reason', 'unknown')
            for payoff in payoffs if not payoff.get('available'))))


def sample(base, *, independent_finance=False, arb_payoff=False, phase=''):
    result = {'sample_started_at': datetime.now(timezone.utc).isoformat()}
    desk_route = '/api/comparison-current/fee-coverage?funnel=1'
    if phase:
        desk_route += '&phase=' + phase
    if independent_finance:
        desk_route += '&independent=1'
    routes = [
        ('desk', desk_route),
        ('coverage', '/api/coverage'),
        ('runtime', '/api/admin/status'),
    ]
    if arb_payoff:
        route = '/api/comparison-current?layout=desk&view=arbs&limit=100'
        routes.append(('arb_payoff', route + ('&phase=' + phase if phase else '')))
    for key, route in routes:
        try:
            value = read(base, route, timeout=135 if key == 'desk' and independent_finance else 20)
        except HTTPError as error:
            result[key] = {'error': 'HTTPError', 'status': error.code}
            try:
                reason = json.loads(error.read(4096)).get('reason')
            except (AttributeError, ValueError):
                reason = None
            if reason in ('current_read_memory_capacity', 'current_read_busy', 'current_read_stopped',
                          'current_inputs_unavailable', 'database_unavailable'):
                result[key]['reason'] = reason
            continue
        except (OSError, URLError, ValueError) as error:
            result[key] = {'error': type(error).__name__}
            continue
        if key == 'desk':
            fields = ('read_at', 'generation', 'state', 'phase', 'total', 'by_provider', 'pair_coverage',
                      'missing_reasons', 'retained_price_gap_reasons', 'published_working_prices',
                      'unpublished_working_prices', 'synchronized_funnel')
            result[key] = {field: value[field] for field in fields if field in value}
        elif key == 'coverage':
            fields = ('captured_at', 'read_at', 'publication_state', 'publication_reasons',
                      'global_totals', 'aggregate_acquisition')
            result[key] = {field: value[field] for field in fields if field in value}
        elif key == 'arb_payoff':
            result[key] = payoff_summary(value)
        else:
            result[key] = {field: value.get(field) for field in
                           ('observed_at', 'runtime_id', 'candidate_digest', 'data_runtime',
                            'source_status', 'background_calculations')}
            result[key]['metrics'] = {
                provider: {field: metrics[field] for field in (
                    'catalog_markets', 'selected_markets', 'subscription_priority', 'derived_roster_unserved',
                    'resyncs', 'pending_books', 'state', 'reason_code', 'next_refresh_at', 'pages', 'events',
                    'records', 'reference_rows', 'last_clock_sample_admitted_at', 'resolved_objects_hour_ended_at',
                    'subscription_rotations', 'source_receipt_ms', 'receipt_projection_ms', 'raw_roster_unserved',
                    'complete_images_received', 'raw_images_persisted', 'derived_images_published',
                    'connections', 'retries', 'priority_rotations_in_place', 'priority_transition_fallbacks',
                    'priority_last_rotation', 'priority_last_fallback', 'priority_rotation_catalog_waits', 'synchronization',
                    'sporting_state_refresh',
                ) if field in metrics}
                for provider, metrics in value.get('metrics', {}).items()
            }
            result[key]['public_sportsbook'] = value.get('metrics', {}).get('public_sportsbook')
            for panel in value.get('sources', ()):
                provider = panel.get('provider')
                metrics = panel.get('metrics', {})
                if provider in ('kalshi', 'polymarket_us'):
                    result[key]['metrics'].setdefault(provider, {}).update({field: metrics[field] for field in (
                        'connections', 'retries', 'resyncs', 'subscription_priority', 'subscription_rotations',
                        'priority_rotations_in_place', 'priority_transition_fallbacks', 'priority_last_rotation',
                        'priority_last_fallback', 'priority_rotation_catalog_waits', 'synchronization',
                        'sporting_state_refresh',
                    ) if field in metrics})
                if provider != 'sportsgameodds':
                    continue
                result[key]['sgo_collection'] = {field: metrics[field] for field in (
                    'state', 'reason_code', 'objects', 'daily_pacing', 'schedule_budget', 'resolved_objects_last_hour',
                    'resolved_objects_hour_ended_at', 'discovery_complete', 'discovery_unstable',
                    'discovery_restored', 'completed_refresh_polls', 'admitted_quote_clock_samples',
                    'last_clock_sample_admitted_at', 'next_refresh_at', 'provider_usage', 'reset_basis',
                    'last_admission_ms', 'retained_schedule_events', 'retained_schedule_truncated', 'alternate_refresh',
                ) if field in metrics}
    result['sample_finished_at'] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8784)
    parser.add_argument('--samples', type=int, default=1, help='number of one-minute samples')
    parser.add_argument('--start-at', type=datetime.fromisoformat,
                        help='start at an ISO 8601 timestamp with a time zone')
    parser.add_argument('--independent-finance', action='store_true',
                        help='also recapture retained inputs to audit EV and arb eligibility')
    parser.add_argument('--independent-every', type=int,
                        help='recapture independent financial inputs on every Nth sample')
    parser.add_argument('--phase', choices=('pregame', 'live'), default='')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.samples < 1:
        parser.error('use a valid loopback port and a positive number of samples')
    if args.start_at and args.start_at.utcoffset() is None:
        parser.error('--start-at requires a time zone')
    if args.independent_every is not None and args.independent_every < 1:
        parser.error('--independent-every must be a positive number of samples')
    base = f'http://127.0.0.1:{args.port}'
    started = args.start_at or datetime.now(timezone.utc)
    for index in range(args.samples):
        slot = started + timedelta(minutes=index)
        while (remaining := (slot - datetime.now(timezone.utc)).total_seconds()) > 0:
            time.sleep(min(remaining, 60))
        if datetime.now(timezone.utc) >= slot + timedelta(minutes=1):
            result = {'sample_scheduled_at': slot.isoformat(), 'skipped': 'sampling_slot_elapsed'}
        else:
            independent = args.independent_finance or bool(args.independent_every and index % args.independent_every == 0)
            result = sample(base, independent_finance=independent, arb_payoff=index % 10 == 0, phase=args.phase)
            result['sample_scheduled_at'] = slot.isoformat()
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
