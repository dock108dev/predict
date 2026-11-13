"""One local acquisition owner, shared by current and retained real runtimes."""
import fcntl
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / '.local/predict-native-owner.lock'
REMOTE_OWNER_PATH = ROOT / '.local/predict-remote-collection-owner'


class LocalOwnership:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.file = None

    def acquire(self, runtime):
        if self.file is not None:
            raise ValueError('Acquisition ownership already held')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        stream = os.fdopen(fd, 'r+')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path in (DEFAULT_PATH, ROOT / '.local/predict-data-runtime-owner.lock') and REMOTE_OWNER_PATH.exists():
                raise ValueError('Collection ownership moved to the server')
            stream.seek(0)
            stream.truncate()
            json.dump(dict(pid=os.getpid(), runtime_id=runtime), stream)
            stream.flush()
            os.fsync(stream.fileno())
        except BlockingIOError:
            stream.close()
            raise ValueError('Another local process owns native acquisition') from None
        except BaseException:
            stream.close()
            raise
        self.file = stream

    def release(self):
        if self.file is not None:
            self.file.close()
            self.file = None

