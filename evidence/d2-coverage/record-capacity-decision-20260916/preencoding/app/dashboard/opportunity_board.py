"""Opportunity board entry point and retained-capture presentation helpers."""
import argparse
from aiohttp import web
from app.dashboard import e6_real as historical
from app.dashboard.e6_live import validate_saved
from app.collection.transport_session import reopen
from app.opportunities.board import display

ROOT=historical.ROOT
SECOND='2a1fa76c-46a3-4fb8-9d55-403b3b5313b7'

def load_sessions():
    first=historical.load_package()
    folder=ROOT/'evidence/e6/live-watch/sessions'/SECOND
    second=validate_saved(folder)
    return {first['session']:(first,reopen(ROOT/historical.JOURNAL)['rows']),
            second['session']:(second,reopen(folder/'observations.jsonl')['rows'])}

def present(result):
    for c in result['candidates']:
        c['display']={k:display(c[k],4 if k in ('raw_gap','raw_combined_price') else 2) for k in ('profit','return_pct','cash','notional','fees','raw_gap','raw_combined_price')}
        for leg in c['legs']:leg['display']={k:display(leg[k],4 if k=='ask' else 2) for k in ('ask','cash','fee','notional','top_size','visible_size')}
    ev=result['ev'];ev['display']={k:display(ev[k]) for k in ('expected_payout','expected_profit','return_pct','break_even_pct')}
    ev['leg']['display']={k:display(ev['leg'][k],4 if k=='ask' else 2) for k in ('ask','cash','fee','notional','top_size','visible_size')}
    return result

def create_app(sessions=None, **kwargs):
    """Keep the public entry point on the authoritative multi-game routes."""
    from app.dashboard.multi_game_server import create_app as multi_app
    return multi_app(sessions=sessions, **kwargs)

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8783);a=p.parse_args()
    import psycopg
    def deny(*args,**kwargs):raise PermissionError('File-only board forbids database connections')
    psycopg.connect=psycopg.Connection.connect=psycopg.AsyncConnection.connect=deny
    web.run_app(create_app(),host='127.0.0.1',port=a.port,access_log=None)

if __name__=='__main__':main()
