import os
import subprocess
import sys
import time
from pathlib import Path

from app.pdf_import_process_lock import batch_process_lock


def test_cross_process_lock_survives_until_holder_exits(tmp_path):
    root=tmp_path/'locks';ready=tmp_path/'ready';acquired=tmp_path/'acquired';batch='a'*32
    program=("import sys,time; from pathlib import Path; "
             "from app.pdf_import_process_lock import batch_process_lock; "
             "ctx=batch_process_lock(Path(sys.argv[1]),sys.argv[2]); ctx.__enter__(); "
             "Path(sys.argv[3]).write_text('ready'); time.sleep(30)")
    env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1])
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    child=subprocess.Popen([sys.executable,'-c',program,str(root),batch,str(ready)],env=env,creationflags=flags)
    contender=None
    try:
        deadline=time.monotonic()+10
        while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.05)
        assert ready.exists()
        program2=("import sys; from pathlib import Path; from app.pdf_import_process_lock import batch_process_lock; "
                  "ctx=batch_process_lock(Path(sys.argv[1]),sys.argv[2]); ctx.__enter__(); "
                  "Path(sys.argv[3]).write_text('acquired'); ctx.__exit__(None,None,None)")
        contender=subprocess.Popen([sys.executable,'-c',program2,str(root),batch,str(acquired)],env=env,creationflags=flags)
        time.sleep(.7)
        assert not acquired.exists() and contender.poll() is None
        child.kill();child.wait(timeout=10)
        assert contender.wait(timeout=10)==0 and acquired.exists()
        with batch_process_lock(root,batch):pass
    finally:
        for process in (child,contender):
            if process and process.poll() is None:process.kill();process.wait(timeout=10)
