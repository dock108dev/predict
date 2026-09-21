"""python -m app.storage --help"""
import argparse
import json
from .store import Store, connect
from .workflow import import_default


def main():
    p=argparse.ArgumentParser(description='Dedicated local historical storage; no venue/network capture')
    p.add_argument('--database',default='prediction_arb')
    commands=p.add_subparsers(dest='command',required=True)
    for name in ('migrate','ingest-default','replay'): commands.add_parser(name)
    q=commands.add_parser('query'); q.add_argument('--session'); q.add_argument('--limit',type=int,default=100)
    for name in ('export','import'): commands.add_parser(name).add_argument('path')
    h=commands.add_parser('history'); h.add_argument('session'); h.add_argument('candidate')
    r=commands.add_parser('recover'); r.add_argument('session')
    args=p.parse_args()
    with connect(args.database) as db:
        s=Store(db)
        if args.command=='migrate': s.migrate(); result={'migration':'applied'}
        elif args.command=='ingest-default': result=import_default(s)
        elif args.command=='query':
            if not 1<=args.limit<=1000: p.error('--limit must be 1..1000')
            result=s.summary()
            result['query_limit']=args.limit
            result['coverage']=db.execute('SELECT * FROM coverage_event WHERE (%s::text IS NULL OR session_id=%s) ORDER BY observed_at DESC LIMIT %s',(args.session,args.session,args.limit)).fetchall()
            result['candidates']=db.execute('SELECT session_id,candidate_id,engine,state,structural,conditional_positive,qualified,liquidity_families,observed_at FROM candidate_observation WHERE (%s::text IS NULL OR session_id=%s) ORDER BY observed_at DESC LIMIT %s',(args.session,args.session,args.limit)).fetchall()
            result['observations']=db.execute('SELECT r.*,q.side,q.ask,q.ask_size,q.bid,q.bid_size,q.unit,q.state FROM receipt r LEFT JOIN quote_observation q ON (r.session_id=q.session_id AND r.id=q.receipt_id) WHERE (%s::text IS NULL OR r.session_id=%s) ORDER BY r.received_at DESC,r.id LIMIT %s',(args.session,args.session,args.limit)).fetchall()
        elif args.command=='replay': result={'verified_audits':s.replay_all()}
        elif args.command=='export': s.export(args.path); result={'exported':args.path}
        elif args.command=='import': s.import_bundle(args.path); result=s.summary()
        elif args.command=='history': result=s.history(args.session,args.candidate)
        elif args.command=='recover': s.interrupt(args.session); result={'interrupted':args.session,'next':'start a new capture session'}
    print(json.dumps(result,indent=2,default=str))

if __name__=='__main__': main()
