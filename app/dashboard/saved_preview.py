"""Shared saved-preview formatting and credential/network isolation. No collection."""
from decimal import Decimal, localcontext, Context
from pathlib import Path
import sys

def fixed(value):
    if value is None: return None
    text = format(Decimal(value), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def percent(value):
    if value is None: return None
    with localcontext(Context(prec=110)):
        return fixed((Decimal(value) * 100).quantize(Decimal('0.0001')))


def isolate_process():
    import psycopg
    def no_database(*args, **kwargs):
        raise PermissionError('E5 file-only preview forbids database connections')
    psycopg.connect = no_database
    psycopg.Connection.connect = no_database
    psycopg.AsyncConnection.connect = no_database
    # Audit events are denied before the OS operation, including dependencies.
    def guard(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0])
            if (any(part in {'.ssh', '.aws', '.codex', 'Keychains'} for part in path.parts)
                or path.name.startswith('.env') or path.name in {'auth.json', 'credentials', 'credentials.json'}
                or path.suffix in {'.pem', '.key'}):
                raise PermissionError('E5 preview forbids credential-file reads')
        if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'):
            raise PermissionError('E5 file-only preview forbids outbound connections and child processes')
    sys.addaudithook(guard)
