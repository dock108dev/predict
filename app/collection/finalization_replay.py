"""Offline native replay in a fresh bounded process after transports close."""
import json
from pathlib import Path
import subprocess
import sys


def isolated(path):
    path=Path(path).resolve()
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,'-m','app.collection.finalization_replay',str(path)],
        cwd=root,capture_output=True,text=True,timeout=25,check=True)
    if len(result.stdout.encode())>65536:raise ValueError('replay result bound')
    value=json.loads(result.stdout)
    if value.get('journal_complete') is not True:raise ValueError('replay journal incomplete')
    from app.collection.continuous import LIMITS
    if value['sampled_peak_rss']>=LIMITS['rss_bytes']:raise ValueError('replay memory cap')
    return value['replay'],dict(method='fresh offline process',timeout_seconds=25,
        sampled_peak_rss=value['sampled_peak_rss'],journal_chain=value['journal_chain'])


def main(path):
    import socket
    def offline(*args,**kwargs):raise ValueError('Replay network forbidden')
    socket.socket.connect=offline
    from app.collection.continuous import LIMITS,rss
    from app.collection.transport_session import reopen
    from app.dashboard.coverage_owner import replay_groups
    saved=reopen(path)
    if saved['state']!='complete' or rss()>=LIMITS['rss_bytes']:raise ValueError('bounded complete replay required')
    replay=replay_groups(saved)
    if rss()>=LIMITS['rss_bytes']:raise ValueError('replay memory cap')
    print(json.dumps(dict(replay=replay,journal_complete=True,journal_chain=saved['sha256'],sampled_peak_rss=rss())))


if __name__=='__main__':main(sys.argv[1])
