"""Owner-operated hidden entry into macOS Keychain; never makes an API request."""
import getpass
import json
import sys

SERVICE='prediction-arb.the-odds-api.free'
ACCOUNT='nfl-pinnacle-readonly'
REFERENCE='keychain:'+SERVICE+'/'+ACCOUNT

def main():
    if not sys.stdin.isatty():raise SystemExit('Use an owner-local interactive terminal.')
    print('Check your existing Odds API account plan locally. Do not make a test API request.')
    if input('Type FREE only if the account shows the free 500-credit monthly plan: ').strip()!='FREE':
        raise SystemExit('Not confirmed. Nothing saved; no request made.')
    key=getpass.getpass('Odds API key (hidden; paste here, never in chat): ').strip()
    if not key or not key.isascii() or not key.isalnum():raise SystemExit('Invalid key format; nothing saved.')
    from keyring.backends.macOS import Keyring
    Keyring().set_password(SERVICE,ACCOUNT,json.dumps(dict(api_key=key,plan='free',monthly_credits=500,confirmation='owner-local account-plan check')))
    print('Saved '+REFERENCE+'. No provider request made.')

if __name__=='__main__':main()
