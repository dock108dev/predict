"""Temporary ordinary UI with numeric-loopback simulated transports; idle until Start."""
import asyncio
from pathlib import Path
from datetime import datetime,timezone
from tests.test_source_session import UnifiedFixture

async def main():
    path=Path('evidence/unified-session-20260929')/('BROWSER-SIMULATED-'+datetime.now(timezone.utc).strftime('%H%M%S'))
    f=UnifiedFixture();await f.boot(path)
    print(str(f.client.make_url('/')),flush=True)
    sid=None
    try:
        while True:
            s=f.owner.session
            if s and s.sid!=sid:
                sid=s.sid;original=s.journal.save
                def saved(row):
                    original(row);f.books+=row['type']=='prediction_book';f.changed.set()
                s.journal.save=saved
            if s and s.state=='running':
                for c in f.active():
                    if not c['images']:await f.send(c)
            await asyncio.sleep(.1)
    finally:await f.close()

if __name__=='__main__':asyncio.run(main())
