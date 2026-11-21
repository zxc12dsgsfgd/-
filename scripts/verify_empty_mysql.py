import os, secrets, subprocess, sys
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from app.config import get_settings

name='zhiyan_test_migrate_'+secrets.token_hex(6)
settings=get_settings()
base=make_url(settings.database_url)
created=False; granted=False

def mysql(sql):
 result=subprocess.run(['docker','compose','exec','-T','mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root'],input=sql,text=True,capture_output=True,check=False)
 if result.returncode: raise RuntimeError('MySQL administrative operation failed: '+result.stderr[-500:])

try:
 mysql(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;')
 created=True
 # Grant only the exact temporary schema to the existing application account.
 user=base.username.replace("'","''")
 mysql(f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{user}'@'%';")
 granted=True
 url=base.set(database=name)
 env=os.environ.copy();env['DATABASE_URL']=url.render_as_string(hide_password=False)
 result=subprocess.run([sys.executable,'-m','alembic','upgrade','0018_projects'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
 if result.returncode:raise RuntimeError('baseline migration failed')
 fixture_engine=create_engine(url)
 try:
  with fixture_engine.begin() as con:
   con.execute(text("INSERT INTO users(email,email_norm,password_hash,display_name) VALUES ('old@example.org','old@example.org','hash','old')"))
   con.execute(text("INSERT INTO papers(owner_id,title,authors,status) VALUES (1,'legacy source','[]','unread')"))
   con.execute(text("INSERT INTO cards(owner_id,paper_id,source_title_snapshot,title,type,content,version) VALUES (1,1,'legacy source','legacy card','idea','content',1)"))
 finally:fixture_engine.dispose()
 result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
 print('Migration exit:',result.returncode)
 if result.returncode:
  print(result.stderr[-3000:]);raise RuntimeError('migration failed')
 engine=create_engine(url)
 try:
  with engine.connect() as con:
   ver=con.execute(text('select version_num from alembic_version')).scalar_one()
   names=inspect(con).get_table_names();inspector=inspect(con)
   assert ver=='0026_pdf_import' and len(names)==39
   assert {'pdf_import_batches','pdf_import_items'} <= set(names)
   for t in ['users','papers','cards','ai_jobs','shares','share_items','share_comments','workflow_sync_failures','research_projects','project_papers','project_cards','project_plans','project_drafts','evidence_links','evidence_changes','reading_templates','structured_notes']:assert t in names
   assert any('email_norm' in u['column_names'] for u in inspector.get_unique_constraints('users'))
   assert any('owner_id' in fk['constrained_columns'] for fk in inspector.get_foreign_keys('papers'))
   assert any(i['name']=='ix_ai_jobs_owner_created' for i in inspector.get_indexes('ai_jobs'))
   assert {'content_kind','verification_status','source_state'} <= {c['name'] for c in inspector.get_columns('cards')}
   assert con.execute(text('SELECT content_kind,verification_status,source_state FROM cards WHERE id=1')).one()==('unspecified','pending','linked')
   print('PASS: empty MySQL schema migrated:',ver,'tables:',len(names),'constraints/index checked')
   con.execute(text("INSERT INTO users(email,email_norm,password_hash,display_name) VALUES ('fixture@example.org','fixture@example.org','hash','fixture')"));con.commit()
  with engine.connect() as con:
   assert con.execute(text("SELECT COUNT(*) FROM users WHERE email_norm='fixture@example.org'")).scalar_one()==1
   print('PASS: application account persists and reconnects to test schema')
   from app.database import check_database
   original=settings.database_url
   try:
    settings.database_url=url.render_as_string(hide_password=False)
    assert check_database()=='connected'
    print('PASS: application database health connects to isolated schema')
   finally:settings.database_url=original
 finally:engine.dispose()
finally:
 if granted: mysql(f"REVOKE ALL PRIVILEGES ON `{name}`.* FROM '{user}'@'%';")
 if created: mysql(f'DROP DATABASE `{name}`;')
 if created: print('Temporary schema removed')
