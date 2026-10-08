"""Explicit local handoff; inert on import. Never include credentials in evidence."""
import os
import sys
from pathlib import Path
import re
import stat
import subprocess
import tempfile

ASSIGN = re.compile(r'^\s*(?:export\s+)?ODDS_API_KEY\s*=')
KEY = re.compile(r'[A-Za-z0-9_-]{1,256}')

def git_executable():
    # The ordinary launcher has a minimal PATH. Prefer the installed standalone
    # Git, whose ignore checks do not depend on Xcode's first-run license state.
    import shutil
    for candidate in ('/opt/homebrew/bin/git','/usr/local/bin/git'):
        if Path(candidate).is_file() and os.access(candidate,os.X_OK):return candidate
    return shutil.which('git') or 'git'

def existing_key(root, supplied=None):
    """Read an existing approved credential at Start; never rewrite its file."""
    if supplied is not None:
        if not isinstance(supplied,str) or not KEY.fullmatch(supplied):
            raise ValueError('Existing credential format unavailable')
        return supplied
    root=Path(root);path=root/'.env'
    ignored=subprocess.run([git_executable(),'check-ignore','--quiet','--no-index','.env'],cwd=root)
    tracked=subprocess.run([git_executable(),'ls-files','--error-unmatch','.env'],cwd=root,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if ignored.returncode or tracked.returncode==0 or path.is_symlink() or not path.is_file():
        raise ValueError('Existing ignored local credential file unavailable')
    if path.stat().st_size>65536:raise ValueError('Existing credential file bound')
    lines=[line for line in path.read_text().splitlines() if ASSIGN.match(line)]
    if len(lines)!=1:raise ValueError('Unique existing credential setting unavailable')
    key=lines[0].split('=',1)[1].strip().strip('"\'')
    if not KEY.fullmatch(key):raise ValueError('Existing credential format unavailable')
    return key


def handoff(root, supplied=None):
    """Save a supplied key or reuse .env, preserving unrelated settings verbatim.

    Caller must validate exact approval before invoking this real credential I/O.
    Tests pass only temporary repositories and dummy values.
    """
    root=Path(root); path=root/'.env'
    check=subprocess.run([git_executable(),'check-ignore','--quiet','--no-index','.env'],cwd=root)
    tracked=subprocess.run([git_executable(),'ls-files','--error-unmatch','.env'],cwd=root,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if check.returncode or tracked.returncode==0:
        raise ValueError('Credential file must be ignored and untracked')
    if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.stat().st_mode)):
        raise ValueError('Credential file must be a regular local file')
    original=path.read_text() if path.exists() else ''
    matches=[line for line in original.splitlines() if ASSIGN.match(line)]
    if len(matches)>1:raise ValueError('Duplicate credential setting; no file changed')
    key=supplied if supplied is not None else (matches[0].split('=',1)[1].strip().strip('"\'') if matches else None)
    if not isinstance(key,str) or not KEY.fullmatch(key):
        raise ValueError('Credential unavailable or unsupported format; no file changed')
    lines=original.splitlines(keepends=True)
    replacement='ODDS_API_KEY='+key+'\n'
    updated=''.join(replacement if ASSIGN.match(line) else line for line in lines)
    if not matches:updated+=('' if not updated or updated.endswith('\n') else '\n')+replacement
    fd,name=tempfile.mkstemp(prefix='.env.',dir=root)
    try:
        with os.fdopen(fd,'w') as f:
            f.write(updated);f.flush();os.fsync(f.fileno())
        os.replace(name,path);path.chmod(0o600)
    finally:
        Path(name).unlink(missing_ok=True)
    return key


def candidate_files(root):
    """Explicit public source allowlist for manifests and source archives."""
    root=Path(root)
    for base in ('app','tests','integration_tests','scripts','docs'):
        for path in sorted((root/base).rglob('*')):
            relative=path.relative_to(root)
            if (path.is_file() and not path.is_symlink()
                and not any(part.startswith('.') or part=='__pycache__' for part in relative.parts)
                and path.suffix in ('.py','.js','.cjs','.html','.css','.json','.md','.sh')):
                yield path


def paid_prompt():
    """Local hidden macOS prompt (or interactive terminal); atomic .env handoff."""
    import json
    from uuid import uuid4
    from datetime import datetime, timezone
    root=Path(__file__).resolve().parents[2]
    if sys.platform == 'darwin':
        script='text returned of (display dialog "Enter your paid Odds API key. Input is hidden and saved only in this project’s private local settings." default answer "" with hidden answer buttons {"Cancel", "Save"} default button "Save" with title "Predict — paid account")'
        response=subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,text=True)
        if response.returncode:
            print('Key entry cancelled. No settings changed.');return
        key=response.stdout.strip()
    else:
        import getpass
        if not sys.stdin.isatty():raise SystemExit('Use an owner-local interactive terminal.')
        key=getpass.getpass('Paid Odds API key (hidden): ').strip()
    if not KEY.fullmatch(key):raise SystemExit('Unsupported key format. Nothing saved.')
    from .current_quota import QuotaLedger
    from .current_aggregate_policy import POLICY
    ledger=QuotaLedger()
    # Refuse migration before changing a credential if consumption is uncertain.
    if ledger.snapshot().get('unresolved_attempts') != 0:
        raise SystemExit('Unresolved accounting: key unchanged. Resolve the retained attempt first.')
    handoff(root,key)
    metadata=root/'.local/predict-odds-account.json'
    metadata.parent.mkdir(mode=0o700,exist_ok=True)
    account=dict(schema='predict-paid-account-1',account_id=str(uuid4()),plan='paid',monthly_credits=POLICY.monthly_ceiling,
                 monthly_price_usd=59,credential_path='.env',confirmed_at=datetime.now(timezone.utc).isoformat(),
                 confirmation='owner-local paid key entry')
    # This record carries no secret or secret-derived identifier.
    ledger.transition_account(account)
    fd,name=tempfile.mkstemp(prefix='account-',dir=metadata.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(account,f);f.flush();os.fsync(f.fileno())
        os.replace(name,metadata);metadata.chmod(0o600)
    finally:Path(name).unlink(missing_ok=True)
    print('Paid key saved privately in .env; account transition retained. Balance awaits a normal response.')
