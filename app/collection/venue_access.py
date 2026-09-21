"""Fixed production read-only destinations; dedicated project credentials at Start."""
import base64
import json
import time
from app.adapters.kalshi_stream import RuntimeSigner as KSigner
from app.adapters.polymarket_us_stream import RuntimeSigner as PSigner

ENDPOINTS = {
    'kalshi': dict(rest='https://external-api.kalshi.com',ws='wss://external-api-ws.kalshi.com/trade-api/ws/v2'),
    'polymarket_us': dict(rest='https://gateway.polymarket.us',ws='wss://api.polymarket.us/v1/ws/markets'),
}
REFERENCES = {'kalshi':'keychain:prediction-arb.kalshi.production/market-data',
              'polymarket_us':'keychain:prediction-arb.polymarket-us/retail-api'}

class Credential:
    def __init__(self, venue, data):
        self.venue=venue
        self.signer=(KSigner(data['key_id'],data['private_key']) if venue=='kalshi' else PSigner(data['key_id'],data['secret_key']))
        self._secrets=tuple(v.encode() for v in data.values() if isinstance(v,str) and v)
    def __repr__(self):return 'Credential(<redacted>)'
    def check(self, raw, headers=None):
        secrets=self._secrets+tuple(str(v).encode() for k,v in (headers or {}).items() if 'key' in k.lower() or 'signature' in k.lower())
        if any(s in raw or base64.b64encode(s) in raw for s in secrets):
            raise ValueError('credential echo suppressed')
    def headers(self, path=None):
        if path is None:return self.signer.headers()
        # Same native signing mechanism, with the actual REST path (no query).
        ts=str(int(time.time()*1000)); payload=(ts+'GET'+path).encode()
        if self.venue=='kalshi':
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding
            sig=self.signer._key.sign(payload,padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=padding.PSS.DIGEST_LENGTH),hashes.SHA256())
            return {'KALSHI-ACCESS-KEY':self.signer._key_id,'KALSHI-ACCESS-TIMESTAMP':ts,'KALSHI-ACCESS-SIGNATURE':base64.b64encode(sig).decode()}
        return self.signer.headers()


def load_credentials(venues=None):
    from keyring.backends.macOS import Keyring
    result={}
    for venue,service,account in [('kalshi','prediction-arb.kalshi.production','market-data'),('polymarket_us','prediction-arb.polymarket-us','retail-api')]:
        if venues is not None and venue not in venues:continue
        try:
            value=Keyring().get_password(service,account)
            if not value:raise ValueError()
            result[venue]=Credential(venue,json.loads(value))
        except Exception:
            raise RuntimeError(venue+': existing dedicated project credential missing or invalid') from None
    return result


def endpoint(venue, kind, value):
    if value!=ENDPOINTS[venue][kind]:raise ValueError('production destination not allowlisted')
    return value
