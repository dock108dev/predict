"""Offline evidence summary; keeps wire observations distinct from reconstructed books."""
import base64
from collections import Counter
import json
from .native_books import enabled


def summarize(rows):
    sources = {}
    for row in rows:
        if row['type'] == 'session_started' and not enabled(row['spec']):
            raise ValueError('Native book slice report requires its exact versioned session')
        venue = row.get('source')
        if venue not in ('kalshi', 'polymarket_us'):
            continue
        source = sources.setdefault(venue, dict(selection=None, wire=Counter(), accepted=Counter(),
            source_time=Counter(), price_level_changes=0, quantity_changes=0,
            recovery_comparisons=Counter(), health=Counter(), stream_diagnostics=[], observations=[]))
        if row['type'] == 'native_book_selection':
            source['selection'] = {k: row.get(k) for k in ('event_id','market_ids','selection_basis','metadata','separate_slug_delivery','reason','error')}
        elif row['type'] == 'prediction_frame':
            data = json.loads(base64.b64decode(row['body_b64']))
            kind = data.get('type') if venue == 'kalshi' else 'full_window_image' if 'marketData' in data else 'control_or_heartbeat'
            source['wire'][kind or 'unknown'] += 1
        elif row['type'] == 'source_health':
            source['health'][row['state']] += 1
        elif row['type'] == 'native_stream_finished':
            source['stream_diagnostics'].extend(row['diagnostics'])
        elif row['type'] == 'prediction_book' and row.get('native_observation'):
            obs = row['native_observation']; label = obs['classification']
            source['accepted'][label] += 1
            source['source_time'][obs['source_time_progress']] += 1
            if label == 'price_or_quantity_change':
                source['price_level_changes'] += int(obs['price_levels_changed'])
                source['quantity_changes'] += int(obs['quantities_changed'])
            if label == 'recovery_snapshot':
                source['recovery_comparisons'][obs['comparison_to_previous']] += 1
            source['observations'].append(dict(obs, ingress_id=row.get('ingress_id'),
                wire_sha256=row.get('local_timing',{}).get('wire_sha256')))
    return dict(version='native-book-evidence-1', sources=sources,
        limitation='Wire counts include rejected messages. Accepted snapshots, identical repeats, within-connection changes and recovery comparisons are separate. No fresh-price, latency, execution, fee, settlement, arbitrage or EV qualification. Original values/timestamps remain in the immutable wire journal.')


def main():
    import argparse
    from pathlib import Path
    from app.dashboard.session_history import verified
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path)
    args=parser.parse_args()
    print(json.dumps(summarize(verified(args.session)['rows']),indent=2))


if __name__ == '__main__':
    main()
