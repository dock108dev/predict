"""Ordinary API probes for independent units and exact captured Originals."""
import json,sys,time,gzip
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.pipeline_recovered_reads import read,release
from app.dashboard.comparison_board import expand_financial

def run(folder,path):
    sample=json.loads(gzip.decompress(sorted(Path(folder).glob('sample-*.json.gz'))[-1].read_bytes()))
    cohort={r['source_event_id'] for r in json.loads(Path('test-results/d02-native-delivery/original-68.json').read_text())['rows']}
    changed={u['game_key'] for u in sample['units'] if not u['current'] and ('result_candidate_input_changed' in u['reasons'] or 'current_dependencies_changed' in u['reasons'])}
    current=sorted((u for u in sample['units'] if u['current']),key=lambda u:(not (u['game_key'] in changed and bool(set(u['events'])&cohort)),u['game_key'] not in changed,not bool(set(u['events'])&cohort)))
    keys=list(dict.fromkeys(u['game_key'] for u in current))
    out=dict(at=time.time(),sample_at=sample['at'],attempts=[]);tokens=[]
    try:
        for key in keys[:8]:
            r=read('/api/boards/ev',dict(game=key,filter='all'));b=r.pop('data',{});tokens.append(b.get('read_token'))
            item=dict(game=key,board=r,read_at=b.get('read_at'),coverage=b.get('result_unit_coverage'),units=b.get('result_units'));out['attempts'].append(item)
            if r.get('status')!=200:continue
            b=expand_financial(b);states={u['unit_id']:u for u in b.get('result_units',[])}
            rows=[row for row in b.get('rows',[]) if row.get('details') and states.get(row.get('result_unit_id'),{}).get('state')=='current']
            rows.sort(key=lambda row:row.get('venue') not in ('kalshi','polymarket_us'))
            historical=next((row for row in b.get('rows',[]) if row.get('details') and states.get(row.get('result_unit_id'),{}).get('state')=='historical'),None)
            item['selected']=[]
            for row in rows[:1]+([historical] if historical else []):
                choice=row['details'];query=dict(game=key,quote=choice['quote_id'],context_id=choice['context_id'],read_token=choice.get('read_token') or b.get('read_token'))
                details=read('/api/boards/details',query);d=details.pop('data',{});tokens.append(d.get('read_token'));query['read_token']=d.get('read_token') or query['read_token']
                original=read('/api/boards/inputs',query);o=original.pop('data',{});tokens.append(o.get('read_token'))
                chosen=dict(unit=row['result_unit_id'],unit_state=states[row['result_unit_id']],row_freshness=row.get('freshness'),row_availability=row.get('availability'),details=details,original=original,details_value=d,original_value=o)
                if details.get('status')==original.get('status')==200:
                    chosen.update(exact_original_equal=d['quote']['original']==o['evidence']['original'],exact_clocks_equal=d['quote']['times']==o['evidence']['times'],board_original_equal=row.get('original')==d['quote']['original'])
                item['selected'].append(chosen)
            release(tokens);tokens=[]
            if rows and historical and any(s.get('exact_clocks_equal') for s in item['selected']):break
        for endpoint in ('/api/boards/dashboard','/api/admin/status','/api/scanner'):
            response=read(endpoint);data=response.pop('data',{})
            out[endpoint]=dict(response,data=data)
        Path(path).write_text(json.dumps(out,indent=2)+'\n')
        print(json.dumps([dict(game=a['game'],board=a['board'],coverage=a.get('coverage'),selected=[{k:v for k,v in s.items() if k not in ('details_value','original_value','row_availability')} for s in a.get('selected',[])]) for a in out['attempts']],indent=2))
    finally:release(tokens)
if __name__=='__main__':run(*sys.argv[1:])
