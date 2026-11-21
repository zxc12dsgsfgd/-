"""Host-local cross-process lock; lock files live on application-controlled storage."""
from contextlib import contextmanager
import os
import re
from pathlib import Path


@contextmanager
def batch_process_lock(root: Path, batch_id: str):
    if not re.fullmatch(r'[0-9a-f]{32}', batch_id):
        raise ValueError('invalid batch')
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or os.path.isjunction(root) or not root.is_dir():
        raise ValueError('invalid lock directory')
    with (root / (batch_id + '.lock')).open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            import time
            while True:
                try:
                    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.1)
            try:
                yield
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
