"""Explicit authored scanner wire workload, never a production authority source."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)


def workload(count=130):
    page = json.loads((ROOT / 'docs/examples/scanner-1/snapshot.json').read_text())
    template = page['rows'][0]
    rows = []
    for i in range(count):
        row = deepcopy(template)
        row.update(id=f'authored-opportunity:{i:04}:covered_outcome_arb', opportunity_id=f'authored-opportunity:{i:04}',
                   pair_id=f'authored-pair:{i:04}', dependency_revision=f'authored-dependency:{i:04}:1', economic_revision=f'authored-economic:{i:04}:1',
                   occurrence_id=f'authored-event:{i % 20:03}', evaluated_at=AT.isoformat(), calculation_started_at=AT.isoformat(),
                   expires_at=(AT + timedelta(minutes=10)).isoformat(),
                   event_context=dict(title=f'{["Seattle at Buffalo", "Dallas at Miami", "Chicago at Detroit", "Denver at Houston"][i % 4]} · {i % 20 + 1}',
                                      participants=['NFL:SEA', 'NFL:BUF'], start_at=(AT + timedelta(hours=5)).isoformat()))
        # Best opportunity is in the last authored event; ties have stable IDs.
        edge = (i // 2 + 1) / 10
        row['metric'] = dict(value=str(edge), display=f'+{edge:.2f}')
        row['supported_capital_usd'] = str(100 + i)
        for j, position in enumerate(row['positions']):
            venue = ('kalshi', 'polymarket_us')[j]
            side = ('YES', 'NO', 'Long', 'Short')[(i + j) % 4]
            position['native_key'] = [venue, f'authored-event:{i % 20}', f'contract:{i}', f'outcome:{j}', side]
            position['predicate'].update(participant=('NFL:SEA', 'NFL:BUF')[j], predicate='not_win' if side in ('NO', 'Short') else 'win')
            position['original_price'] = dict(value='0.45', units='usd_per_contract', payout='1')
            position['common_odds'] = dict(supported=True, american='+122', cents='45.0', equivalent=False, reason=None)
        row['source_clocks'] = [dict(c, source_at=AT.isoformat(), book_at=AT.isoformat(), received_at=AT.isoformat()) for c in row['source_clocks']]
        rows.append(row)
    rows.sort(key=lambda r: (-float(r['metric']['value']), r['occurrence_id'], r['id']))
    page.update(server_id='authored-sc04-server', epoch='authored-sc04-epoch-1', publication_revision=1,
                rows=rows[:100], ranked_ids=[r['id'] for r in rows[:100]], limit=100, offset=0, next_offset=100 if count > 100 else None,
                total_matching=count, expires_at=(AT + timedelta(minutes=10)).isoformat(), published_at=AT.isoformat())
    page['coverage'].update(compatible_pairs=count, evaluated_pairs=count, qualifying_pairs=count)
    return page, rows


if __name__ == '__main__':
    page, rows = workload()
    (ROOT / 'tests/fixtures/sc04/workload.json').write_text(json.dumps(dict(evidence_class='Authored schema-valid scanner UI workload, no current financial/source/link authority', page=page, rows=rows), separators=(',', ':')) + '\n')
