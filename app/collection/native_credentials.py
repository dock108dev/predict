"""Owner-local, hidden Keychain entry only. Never connects to a venue."""
import argparse
from getpass import getpass
import json
import sys
from .native_product import REFERENCES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('venue',choices=tuple(REFERENCES))
    parser.add_argument('--environment',required=True)
    args=parser.parse_args()
    if args.environment not in REFERENCES[args.venue]:parser.error('unsupported environment')
    if not sys.stdin.isatty():parser.error('run in a local interactive terminal')
    fields=('client_id','client_secret') if args.venue=='novig' else ('access_key','secret_key')
    values={field:getpass(field.replace('_',' ').title()+': ') for field in fields}
    if any(not x.strip() for x in values.values()):parser.error('empty credential; nothing saved')
    service,account=REFERENCES[args.venue][args.environment].removeprefix('keychain:').split('/')
    from keyring.backends.macOS import Keyring
    Keyring().set_password(service,account,json.dumps(values))
    print('Saved locally. No venue request was made.')

if __name__=='__main__':main()
