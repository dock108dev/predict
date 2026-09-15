"""Twelfth example requires the dedicated real PostgreSQL database."""
import json
from app.storage import Store, connect
from app.storage.workflow import import_default

if __name__=='__main__':
    with connect() as db:
        store=Store(db); store.migrate()
        print(json.dumps(import_default(store),indent=2,default=str))
