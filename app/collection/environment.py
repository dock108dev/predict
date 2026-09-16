"""Fresh socket-only PostgreSQL; every connection verifies exact local identity."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import psycopg
from psycopg.rows import dict_row
from app.storage.store import Store


class Environment:
    def __init__(self,root):
        self.root=Path(root).resolve();self.data=self.root/'data';self.socket=self.root/'socket'
        self.user='e6_disposable';self.port=55486
        marker=json.loads((self.root/'e6-environment.json').read_text())
        if marker!={'root':str(self.root),'purpose':'E6 disposable synthetic only'}:raise ValueError('environment identity mismatch')
    @classmethod
    def create(cls):
        root=Path(tempfile.mkdtemp(prefix='e6pg-',dir='/tmp')).resolve()
        (root/'socket').mkdir(mode=0o700)
        (root/'e6-environment.json').write_text(json.dumps(dict(root=str(root),purpose='E6 disposable synthetic only')))
        env=cls(root)
        env.command(['initdb','-D',str(env.data),'-U',env.user,'--auth-local=trust','--auth-host=reject','--encoding=UTF8','--no-locale'])
        env.command(['pg_ctl','-D',str(env.data),'-l',str(root/'postgres.log'),'-o',f"-k {env.socket} -p {env.port} -c listen_addresses='' -c unix_socket_permissions=0700 -c shared_buffers=32MB -c max_connections=10 -c max_wal_size=128MB",'start'])
        with env.connect('postgres') as db:db.execute('CREATE DATABASE e6_synthetic')
        with env.connect() as db:Store(db).migrate()
        return env
    def command(self,args):
        with (self.root/'commands.log').open('a') as log:subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,check=True)
    def connect(self,database='e6_synthetic'):
        if database not in ('e6_synthetic','postgres'):raise ValueError('explicit disposable database required')
        db=psycopg.connect(host=str(self.socket),port=self.port,user=self.user,dbname=database,autocommit=True,row_factory=dict_row,
            connect_timeout=3,options='-c statement_timeout=5000 -c lock_timeout=1000')
        row=db.execute("SELECT current_database() AS database,current_user AS username,current_setting('data_directory') AS data_directory,current_setting('unix_socket_directories') AS sockets,current_setting('listen_addresses') AS listen_addresses,current_setting('port') AS port").fetchone()
        if row!=dict(database=database,username=self.user,data_directory=str(self.data),sockets=str(self.socket),listen_addresses='',port=str(self.port)):
            db.close();raise ValueError('database identity mismatch')
        with (self.root/'identities.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        return db
    def remove(self,evidence):
        self.command(['pg_ctl','-D',str(self.data),'-m','fast','-w','stop'])
        destination=Path(evidence);destination.mkdir(parents=True,exist_ok=True)
        for name in ('commands.log','postgres.log','identities.jsonl','e6-environment.json'):shutil.copyfile(self.root/name,destination/name)
        shutil.rmtree(self.root)
        (destination/'cleanup.json').write_text(json.dumps(dict(root=str(self.root),removed=not self.root.exists(),stopped=True)))
