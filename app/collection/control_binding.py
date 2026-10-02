"""Bounded public identity only: preserve its values without relaxing secret redaction."""
import json,re
from pathlib import PurePosixPath
from uuid import UUID
SCHEMA_VERSION='native-control-binding-v1'
BODY_CAP=65536
KEYS=frozenset(('implementation_sha256','spec_sha256','attempt_id','output','file_hashes'))
HASH=re.compile(r'[0-9a-f]{64}\Z')
NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')

def validate_identity(value):
    if type(value) is not dict or set(value)!=KEYS:raise ValueError('binding_schema_keys')
    for key in ('implementation_sha256','spec_sha256'):
        if type(value[key]) is not str or not HASH.fullmatch(value[key]):raise ValueError('binding_hash')
    attempt=value['attempt_id']
    if type(attempt) is not str or len(attempt)!=36:raise ValueError('binding_attempt')
    try:
        if str(UUID(attempt))!=attempt:raise ValueError('binding_attempt')
    except (ValueError,AttributeError):raise ValueError('binding_attempt') from None
    output=value['output']
    if type(output) is not str or not 1<=len(output)<=4096 or not PurePosixPath(output).is_absolute() or any(ord(c)<32 for c in output) or '..' in PurePosixPath(output).parts:raise ValueError('binding_output')
    hashes=value['file_hashes']
    if type(hashes) is not dict or not 1<=len(hashes)<=64:raise ValueError('binding_files')
    for name,hashed in hashes.items():
        if not NAME.fullmatch(name) or type(hashed) is not str or not HASH.fullmatch(hashed):raise ValueError('binding_file_hash')
    if 'AUTHORIZATION.txt' not in hashes:raise ValueError('binding_authorization_hash_missing')
    return value

def parse_identity(raw):
    if not raw or len(raw)>BODY_CAP:raise ValueError('binding_response_size')
    def pairs(items):
        value={}
        for k,v in items:
            if k in value:raise ValueError('binding_duplicate_key')
            value[k]=v
        return value
    def constant(value):raise ValueError('binding_nonfinite')
    try:value=json.loads(raw.decode('utf-8',errors='strict'),object_pairs_hook=pairs,parse_constant=constant)
    except (UnicodeError,RecursionError,json.JSONDecodeError):raise ValueError('binding_malformed_json') from None
    return validate_identity(value)
