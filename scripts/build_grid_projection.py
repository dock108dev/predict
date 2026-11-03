"""Backfill only the derived grid view, with exact-source compare-and-swap.

Original boards and selected evidence stay intact. Normal publication maintains
this projection after backfill. Existing SQL/disk/publication limits still apply.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect,encoded,ROOT
from app.dashboard.grouped_odds import grid_board
from app.storage.latest_board import MAX_BYTES
from app.collection.current_storage_policy import require_disk_space,sql_usage,SQL_BYTE_CAP
from psycopg.types.json import Jsonb
from copy import deepcopy
from app.storage.grid_read_packet import pack
from time import monotonic
s=monotonic();updated=0;skipped=0;before=after=0
with connect() as db:
 db.execute("update latest_board set facts=facts #- '{boards,grid}' where facts#>'{boards,grid}' IS NOT NULL")
 keys=[r['game_key'] for r in db.execute('select game_key from latest_board order by game_key')]
 for key in keys:
  r=db.execute('select game_key,dependency_revision,economic_revision,calculated_at,facts from latest_board where game_key=%s',(key,)).fetchone()
  if not r:continue
  facts=r['facts'];grid=grid_board(deepcopy(facts['boards']['odds']));packet=pack(r,grid)
  selector=facts.get('publication_dependencies',{}).get('selector')
  size=db.execute('SELECT octet_length(%s::jsonb::text)+octet_length(%s::jsonb::text) n',(Jsonb(grid),Jsonb(selector))).fetchone()['n']
  from app.storage import grid_packet_store as packets
  from app.storage.current_rows import LOCK
  with db.transaction():
   db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
   current=db.execute('select facts from latest_board where game_key=%s for update',(key,)).fetchone()
   changed=bool(current and current['facts']==facts)
   if changed:
    packets.cleanup(db);extra=packets.extra_bytes(db,[packet])
    if sql_usage(db)+size+extra>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
    retained=db.execute('SELECT coalesce(sum(n),0) n FROM (SELECT retained_bytes n FROM latest_board UNION ALL SELECT retained_bytes-blob_bytes FROM current_grid_projection WHERE game_key<>%s) r',(key,)).fetchone()['n']
    if retained+size+packets.retained_bytes(db)+extra>MAX_BYTES:raise ValueError('latest_board_capacity')
    require_disk_space(ROOT/'.local/postgres',append_bytes=size+extra)
    blob=packets.put(db,packet)
    db.execute('insert into current_grid_projection(game_key,facts,read_selector,blob_id,blob_bytes) values (%s,%s,%s,%s,%s) on conflict(game_key) do update set facts=EXCLUDED.facts,read_packet=NULL,read_selector=EXCLUDED.read_selector,blob_id=EXCLUDED.blob_id,blob_bytes=EXCLUDED.blob_bytes',(key,Jsonb(grid),Jsonb(selector),blob,len(packet)))
  updated+=changed;skipped+=not changed;before+=len(encoded(facts['boards']['odds']));after+=size
print(dict(updated=updated,concurrently_changed=skipped,odds_bytes=before,grid_bytes=after,seconds=round(monotonic()-s,3),provider_requests=0))
