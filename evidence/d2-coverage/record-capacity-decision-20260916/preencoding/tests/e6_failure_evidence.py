"""Retain one bounded actual disconnected-DB journal and restart reconstruction."""
import asyncio
import json
from pathlib import Path
from app.collection.environment import Environment
from app.collection.session import Session,checked
from app.collection.storage import Repository
from app.collection.synthetic import WallClock

async def main():
    out=Path('evidence/e6/primary-storage-failure');out.mkdir(exist_ok=False)
    env=Environment.create();db=env.connect()
    try:
        limits=checked(dict(seconds=6,prediction_poll=.5,reference_poll=1,calculation_poll=1,discovery_poll=1))
        s=Session(Repository(db,out,limits),WallClock(),out,limits);await s.start();await asyncio.sleep(.8)
        db.close();await s.task
        assert s.state=='failed'
        with env.connect() as fresh:
            recovered=Repository(fresh,out,limits).recover()
            assert recovered[0]['state']=='interrupted' and recovered[0]['crash_at'] is None
        (out/'verification.json').write_text(json.dumps(dict(state=s.state,delivered=s.delivered,persisted=s.persisted,
            fallback_records=s.delivered-s.persisted,recovered=recovered),indent=2))
    finally:
        db.close();env.remove(out/'cleanup')
if __name__=='__main__':asyncio.run(main())
