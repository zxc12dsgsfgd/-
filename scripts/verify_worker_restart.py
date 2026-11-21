"""Verify real worker restart and same-day deduplication in a disposable schema."""
import os,secrets,subprocess,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sqlalchemy import create_engine,func,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import User,Paper,Workflow,Notification,WorkflowRun,WorkflowEvent

root=Path.cwd();name='zhiyan_test_worker_'+secrets.token_hex(6)
base=make_url(get_settings().database_url);user=base.username.replace("'","''")
created=granted=False;process=None;engine=None
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def mysql(sql):
 r=subprocess.run(['docker','compose','exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root'],input=sql,text=True,capture_output=True)
 if r.returncode:raise RuntimeError('Temporary schema operation failed')

def start(env):
 return subprocess.Popen([sys.executable,'-m','app.worker'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)

def stop(p):
 if p and p.poll() is None:
  if os.name=='nt':subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
  else:p.terminate()
  try:p.wait(timeout=10)
  except subprocess.TimeoutExpired:p.kill();p.wait()

def counts():
 with Session(engine) as db:
  return tuple(db.scalar(select(func.count()).select_from(m)) for m in (Notification,WorkflowRun,WorkflowEvent))

def wait_counts(expected,p):
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  if p.poll() is not None:raise RuntimeError('worker stopped unexpectedly')
  if counts()==expected:return
  time.sleep(.2)
 raise RuntimeError(f'worker did not produce expected counts; got {counts()}')

try:
 mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;');created=True
 mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';");granted=True
 url=base.set(database=name);env=os.environ.copy();env['DATABASE_URL']=url.render_as_string(hide_password=False);env['PYTHONPATH']=str(root/'backend')
 r=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,capture_output=True)
 if r.returncode:raise RuntimeError('migration failed')
 engine=create_engine(url)
 today=datetime.now(timezone.utc).date()
 with Session(engine) as db:
  u=User(email='worker-test@example.org',email_norm='worker-test@example.org',password_hash='test',display_name='test');db.add(u);db.flush();uid=u.id
  db.add(Workflow(owner_id=uid,name='overdue test',enabled=True,trigger='scheduled_check',filter_value='1',message='test reminder',action_type='notify'))
  db.add(Paper(owner_id=uid,title='first',authors=[],status='unread',created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=3)));db.commit()
 process=start(env);wait_counts((1,1,1),process);stop(process);process=None
 with Session(engine) as db:
  db.add(Paper(owner_id=uid,title='second',authors=[],status='unread',created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=3)));db.commit()
 process=start(env);wait_counts((2,2,2),process)
 if datetime.now(timezone.utc).date()!=today:raise RuntimeError('UTC day changed; same-day test inconclusive')
 with Session(engine) as db:
  events=db.scalars(select(WorkflowEvent).where(WorkflowEvent.trigger=='scheduled_check')).all()
  assert len({e.object_id for e in events})==2
 print('PASS: real worker scanned, restarted, processed new item and did not duplicate first item')
finally:
 stop(process)
 if engine:engine.dispose()
 if granted:mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
 if created:mysql(f'DROP DATABASE `{name}`;')
 if created:print('Temporary schema, grant and worker cleaned')
