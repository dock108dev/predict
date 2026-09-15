"""Read-only logical fingerprint; no venue credentials or database writes."""
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from app.storage.store import connect
from psycopg import sql
with connect() as db:
    db.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
    tables=db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    result={}
    for item in tables:
        table=item['tablename'];digest=hashlib.sha256();count=0
        with db.cursor(name='fingerprint') as cursor:
            cursor.execute(sql.SQL('SELECT md5(row_to_json(t)::text) AS h FROM {} t ORDER BY h').format(sql.Identifier(table)))
            for row in cursor:
                digest.update(row['h'].encode());count+=1
        result[table]={'rows':count,'row_digest_sha256':digest.hexdigest()}
    db.execute('ROLLBACK')
Path(sys.argv[1]).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print({k:v['rows'] for k,v in result.items()})
