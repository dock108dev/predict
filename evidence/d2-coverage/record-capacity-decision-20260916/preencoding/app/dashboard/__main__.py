import atexit,fcntl,os
from aiohttp import web
from app.storage.store import ROOT
from .server import create_app

if __name__=='__main__':
    local=ROOT/'.local';local.mkdir(exist_ok=True)
    lock=(local/'dashboard.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('The project dashboard is already running.')
    pid=local/'dashboard.pid';pid.write_text(str(os.getpid()))
    atexit.register(lambda:pid.unlink(missing_ok=True))
    web.run_app(create_app(),host='127.0.0.1',port=8765,access_log=None,shutdown_timeout=15)
