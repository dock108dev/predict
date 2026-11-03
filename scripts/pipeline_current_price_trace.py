"""Sample exact normalized receipts through ordinary Odds HTTP, without acquisition.

Latency is first-observed HTTP time minus the unchanged source receipt, an upper
bound including polling. Initial retained prices are excluded. This is a sample,
not a coverage denominator or a claim that every intermediate receipt displayed.
"""
import json
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,stamp,hashed
from app.dashboard.comparison_board import expand_odds,expand_price_fields
from scripts.pipeline_recovered_reads import read,release

start=datetime.now(timezone.utc);deadline=time.monotonic()+float(sys.argv[2] if len(sys.argv)>2 else 120)
seen=set();records=[];reads=[]
while time.monotonic()<deadline and len(records)<256:
    with connect() as db:
        games=db.execute('''SELECT b.game_key,max(o.received_at::timestamptz) receipt
            FROM current_offer o JOIN current_contract c ON c.id=o.contract_id
            JOIN latest_board b ON b.publication_events ? c.event_id
            WHERE c.venue IN ('kalshi','polymarket_us') AND o.received_at::timestamptz>=%s
            GROUP BY b.game_key ORDER BY max(o.received_at::timestamptz) DESC LIMIT 4''',(start,)).fetchall()
    for game in games:
        response=read('/api/boards/odds',dict(game=game['game_key'],filter='all'))
        body=response.pop('data',{});reads.append(dict(game=game['game_key'],**response))
        try:
            if response.get('status')!=200:continue
            board=expand_odds(expand_price_fields(body));at=datetime.now(timezone.utc)
            for q in board.get('prices',[]):
                if q['venue'] not in ('kalshi','polymarket_us'):continue
                receipt=q['times']['received_at'];key=(q['quote_id'],receipt)
                if stamp(receipt)<start or key in seen:continue
                seen.add(key);source=q['source'];eid=hashed([source['provider'],source['native_event_id']])
                cid=hashed([q['venue'],source['provider'],source['native_event_id'],source['native_market_id'],source['native_outcome_id'],source.get('native_side','')])
                with connect() as db:
                    normalized=db.execute('SELECT received_at,source_at,price_value,price_units FROM current_offer WHERE contract_id=%s',(cid,)).fetchone()
                    raw=db.execute('SELECT received_at,persisted_at FROM current_acquisition_image WHERE source=%s AND event_id=%s AND market_id=%s',
                        (q['venue'],source['native_event_id'],source['native_market_id'])).fetchone()
                records.append(dict(game=game['game_key'],contract=cid,venue=q['venue'],receipt=receipt,
                    source_at=q['times'].get('source_at'),http_observed_at=at.isoformat(),
                    receipt_to_http_upper_seconds=(at-stamp(receipt)).total_seconds(),
                    original=q['original'],normalized_at_followup=normalized,raw_at_followup=raw))
                if len(records)>=256:break
        finally:release([body.get('read_token')])
    Path(sys.argv[1]).write_text(json.dumps(dict(start=start.isoformat(),records=records,reads=reads),default=str,indent=2))
    time.sleep(2)
print(dict(traced_receipts=len(records),reads=len(reads)))
