"""Ordinary selected native Original/Details read with exact captured equality."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.storage.store import connect
from app.dashboard.comparison_board import expand_financial
from scripts.pipeline_recovered_reads import read,release

cohort=json.loads(Path('test-results/d02-native-delivery/original-68.json').read_text())
ids=[r['source_event_id'] for r in cohort['rows']];tokens=[];out=dict(at=time.time(),attempts=[])
try:
    with connect() as db:
        games=db.execute("SELECT game_key FROM latest_board WHERE publication_events ?| %s AND calculated_at IS NOT NULL ORDER BY jsonb_array_length(facts#>'{boards,ev,rows}') LIMIT 3",(ids,)).fetchall()
    for game in games:
        r=read('/api/boards/ev',dict(game=game['game_key'],filter='all'));b=r.pop('data',{});tokens.append(b.get('read_token'))
        item=dict(game=game['game_key'],board=r);out['attempts'].append(item)
        if r.get('status')!=200:continue
        b=expand_financial(b)
        row=next((r for r in b.get('rows',[]) if r.get('venue') in ('kalshi','polymarket_us') and r.get('details')),None)
        if row is None:item['reason']='native_financial_selection_not_available';continue
        selected=row['details'];query=dict(game=game['game_key'],quote=selected['quote_id'],context_id=selected['context_id'],read_token=selected.get('read_token') or b.get('read_token'))
        details=read('/api/boards/details',query);d=details.pop('data',{});tokens.append(d.get('read_token'))
        query['read_token']=d.get('read_token') or query['read_token']
        original=read('/api/boards/inputs',query);o=original.pop('data',{});tokens.append(o.get('read_token'))
        item.update(details=details,original=original,details_value=d,original_value=o)
        if details.get('status')==original.get('status')==200:
            item['exact_original_equal']=d['quote']['original']==o['evidence']['original']
            item['exact_clocks_equal']=d['quote']['times']==o['evidence']['times']
            item['board_original_equal']=row.get('original')==d['quote']['original']
            break
    Path(sys.argv[1]).write_text(json.dumps(out,indent=2,default=str)+'\n')
    print(json.dumps([ {k:v for k,v in a.items() if k not in ('details_value','original_value')} for a in out['attempts']],indent=2))
finally:release(tokens)
