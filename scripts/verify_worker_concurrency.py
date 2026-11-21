"""Concurrent real workers tested against a disposable MySQL schema."""
import os,secrets,subprocess,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sqlalchemy import create_engine,func,select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import User,Paper,Workflow,Notification,WorkflowRun,WorkflowEvent,SchedulerFailure
root=Path.cwd();name='zhiyan_test_concurrent_'+secrets.token_hex(6)
base=make_url(get_settings().database_url);user=base.username.replace("'","''")
created=granted=False;workers=[];engine=None;locked=None
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

def mysql(sql):
 r=subprocess.run(['docker','compose','exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N'],input=sql,text=True,capture_output=True)
 if r.returncode:raise RuntimeError('MySQL administrative operation failed')
 return r.stdout.strip()

def stop(p):
 if p.poll() is None:
  if os.name=='nt':subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False)
  else:p.terminate()
  try:p.wait(timeout=10)
  except subprocess.TimeoutExpired:p.kill();p.wait()

def counts():
 with Session(engine) as db:return tuple(db.scalar(select(func.count()).select_from(m)) for m in (Notification,WorkflowRun,WorkflowEvent,SchedulerFailure))

try:
 mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;');created=True
 mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';");granted=True
 url=base.set(database=name);env=os.environ.copy();env['DATABASE_URL']=url.render_as_string(hide_password=False);env['PYTHONPATH']=str(root/'backend')
 if subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,capture_output=True).returncode:raise RuntimeError('migration failed')
 engine=create_engine(url)
 with Session(engine) as db:
  u=User(email='concurrent-worker@example.org',email_norm='concurrent-worker@example.org',password_hash='test',display_name='test');db.add(u);db.flush()
  rule=Workflow(owner_id=u.id,name='concurrent',enabled=True,trigger='scheduled_check',filter_value='1',message='reminder',action_type='notify');db.add(rule);db.flush();rid=rule.id
  for i in range(5):db.add(Paper(owner_id=u.id,title=f'paper-{i}',authors=[],status='unread',created_at=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=3)))
  db.commit()
 locked=Session(engine);locked.scalar(select(Workflow).where(Workflow.id==rid).with_for_update())
 for i in range(2):workers.append(subprocess.Popen([sys.executable,'-m','app.worker'],cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags))
 deadline=time.monotonic()+25;waiters=0
 while time.monotonic()<deadline:
  if any(p.poll() is not None for p in workers):raise RuntimeError('worker exited unexpectedly')
  waiters=int(mysql('SELECT COUNT(*) FROM performance_schema.data_lock_waits;') or '0')
  if waiters>=2:break
  time.sleep(.25)
 if waiters<2:raise RuntimeError(f'could not confirm two workers waiting for the held rule lock; got {waiters}')
 locked.commit();locked.close();locked=None
 deadline=time.monotonic()+30
 while time.monotonic()<deadline:
  if any(p.poll() is not None for p in workers):raise RuntimeError('worker exited unexpectedly')
  current=counts()
  if current[:3]==(5,5,5):break
  time.sleep(.2)
 else:raise RuntimeError(f'concurrent scan incomplete: {counts()}')
 time.sleep(2)
 assert counts()==(5,5,5,0),counts()
 with Session(engine) as db:
  events=db.scalars(select(WorkflowEvent).where(WorkflowEvent.trigger=='scheduled_check')).all();assert len({e.object_id for e in events})==5
 print('PASS: two real workers simultaneously waited on held rule lock; five items produced exactly five events, runs and notifications; zero failures')
finally:
 if locked:locked.rollback();locked.close()
 for p in workers:stop(p)
 if engine:engine.dispose()
 if granted:mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
 if created:mysql(f'DROP DATABASE `{name}`;')
 if created:print('Temporary schema, grant and workers cleaned')
