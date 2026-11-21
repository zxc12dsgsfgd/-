"""Verify retry of a persisted scheduled failure after a real worker restart."""
import os,secrets,subprocess,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sqlalchemy import create_engine,func,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import User,Paper,Workflow,Notification,WorkflowRun,WorkflowEvent,SchedulerFailure

root=Path.cwd();name='zhiyan_test_retry_'+secrets.token_hex(6)
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

def wait_for(predicate,p):
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  if p.poll() is not None:raise RuntimeError('worker exited unexpectedly')
  with Session(engine) as db:
   if predicate(db):return
  time.sleep(.2)
 raise RuntimeError('worker did not reach expected state')

try:
 mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;');created=True
 mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';");granted=True
 url=base.set(database=name);env=os.environ.copy();env['DATABASE_URL']=url.render_as_string(hide_password=False);env['PYTHONPATH']=str(root/'backend')
 if subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,capture_output=True).returncode:raise RuntimeError('migration failed')
 engine=create_engine(url)
 with Session(engine) as db:
  u=User(email='worker-retry@example.org',email_norm='worker-retry@example.org',password_hash='test',display_name='test');db.add(u);db.flush()
  # Deliberately invalid tag reference models a rule whose target has become unavailable.
  rule=Workflow(owner_id=u.id,name='retry-test',enabled=True,trigger='scheduled_check',filter_value='1',message='recovered',action_type='add_tag',action_value='999999');db.add(rule);db.flush();rid=rule.id
  db.add(Paper(owner_id=u.id,title='overdue',authors=[],status='unread',created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=3)));db.commit()
 process=start(env)
 wait_for(lambda db:db.scalar(select(func.count()).select_from(SchedulerFailure))==1,process)
 stop(process);process=None
 with Session(engine) as db:
  failure=db.scalar(select(SchedulerFailure));assert failure.error_code=='tag_missing' and failure.attempts==1 and failure.resolved_at is None
  assert failure.next_retry_at>failure.updated_at
  assert db.scalar(select(func.count()).select_from(WorkflowEvent))==0
  assert db.scalar(select(func.count()).select_from(Notification))==0
  # Test-only adjustment avoids waiting a full minute; runtime honors normal backoff.
  failure.next_retry_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(seconds=1)
  rule=db.get(Workflow,rid);rule.action_type='notify';rule.action_value=None;db.commit()
 process=start(env)
 wait_for(lambda db:db.scalar(select(SchedulerFailure.resolved_at)) is not None,process)
 with Session(engine) as db:
  failure=db.scalar(select(SchedulerFailure));assert failure.attempts==1 and failure.resolved_at is not None
  assert all(db.scalar(select(func.count()).select_from(m))==1 for m in (WorkflowEvent,WorkflowRun,Notification))
 print('PASS: failure persisted with backoff; restarted worker retried corrected rule and recorded one recovery')
finally:
 stop(process)
 if engine:engine.dispose()
 if granted:mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
 if created:mysql(f'DROP DATABASE `{name}`;')
 if created:print('Temporary schema, grant and worker cleaned')
