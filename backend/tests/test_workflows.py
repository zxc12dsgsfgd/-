from sqlalchemy import select
from sqlalchemy.orm import Session
from test_papers import clients
from app.models import Notification, WorkflowEvent
from app.workflows import emit


def test_workflow_triggers_isolation_and_read(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    rule={'name':'已读提醒','enabled':True,'trigger':'paper_status_changed','filter_value':'read','message':'文献已读'}
    created=a.post('/api/v1/workflows',json=rule,headers=h);assert created.status_code==201
    rid=created.json()['id'];assert b.put(f'/api/v1/workflows/{rid}',json=rule,headers=h).status_code==404
    paper=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json();pid=paper['id']
    assert a.get('/api/v1/notifications').json()==[]
    assert a.put(f'/api/v1/papers/{pid}',json={'title':'文献','status':'read'},headers=h).status_code==200
    assert a.put(f'/api/v1/papers/{pid}',json={'title':'文献','status':'read'},headers=h).status_code==200
    notices=a.get('/api/v1/notifications').json();assert len(notices)==1 and notices[0]['message']=='文献已读'
    assert b.get('/api/v1/notifications').json()==[]
    assert b.post(f"/api/v1/notifications/{notices[0]['id']}/read",headers=h).status_code==404
    assert a.post(f"/api/v1/notifications/{notices[0]['id']}/read",headers=h).json()['read_at'] is not None
    assert len(a.get('/api/v1/workflow-runs').json())==1
    assert a.delete(f'/api/v1/workflows/{rid}',headers=h).status_code==204
    assert len(a.get('/api/v1/workflow-runs').json())==1


def test_duplicate_event_no_second_notification(clients):
    from app.auth import get_db
    from app.main import app
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    assert a.post('/api/v1/workflows',json={'name':'新卡片','trigger':'card_created','message':'新增'},headers=h).status_code==201
    user=a.get('/api/v1/auth/me').json()['id']
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        emit(db,user,'card_created',999,'idea',event_id='test-event');db.commit()
        emit(db,user,'card_created',999,'idea',event_id='test-event');db.commit()
        assert len(db.scalars(select(Notification).where(Notification.owner_id==user)).all())==1
        assert db.get(WorkflowEvent,'test-event') is not None
    finally:gen.close()


def test_actions_and_loop_rollback(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    tid=a.post('/api/v1/tags',json={'name':'已读'},headers=h).json()['id']
    rule={'name':'加标签','trigger':'paper_status_changed','filter_value':'read','message':'加标签','action_type':'add_tag','action_value':str(tid)}
    assert b.post('/api/v1/workflows',json=rule,headers=h).status_code==404
    assert a.post('/api/v1/workflows',json=rule,headers=h).status_code==201
    pid=a.post('/api/v1/papers',json={'title':'测试'},headers=h).json()['id']
    assert a.put(f'/api/v1/papers/{pid}',json={'title':'测试','status':'read'},headers=h).status_code==200
    assert a.get(f'/api/v1/papers/{pid}/tags').json()[0]['id']==tid
    assert a.delete(f'/api/v1/tags/{tid}',headers=h).status_code==409
    for source,target in [('reading','archived'),('archived','reading')]:
        r={'name':source,'trigger':'paper_status_changed','filter_value':source,'message':'切换','action_type':'set_status','action_value':target}
        assert a.post('/api/v1/workflows',json=r,headers=h).status_code==201
    assert a.put(f'/api/v1/papers/{pid}',json={'title':'测试','status':'reading'},headers=h).status_code==409
    assert a.get(f'/api/v1/papers/{pid}').json()['status']=='read'


def test_scheduled_overdue_is_idempotent_and_owner_scoped(clients):
    from datetime import timedelta
    from sqlalchemy import update
    from app.auth import now
    from app.models import Paper
    from app.workflows import run_scheduled_once
    from app.auth import get_db
    from app.main import app
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    pa=a.post('/api/v1/papers',json={'title':'超期','status':'unread'},headers=h).json()['id']
    pb=b.post('/api/v1/papers',json={'title':'他人超期','status':'unread'},headers=h).json()['id']
    rule={'name':'超期提醒','trigger':'scheduled_check','filter_value':'1','message':'超期','action_type':'notify'}
    assert a.post('/api/v1/workflows',json=rule,headers=h).status_code==201
    generator=app.dependency_overrides[get_db]();db=next(generator)
    try:
        db.execute(update(Paper).where(Paper.id.in_([pa,pb])).values(created_at=now()-timedelta(days=3)));db.commit()
        assert run_scheduled_once(db)==1
        assert run_scheduled_once(db)==0
    finally:generator.close()
    assert len(a.get('/api/v1/notifications').json())==1
    assert b.get('/api/v1/notifications').json()==[]


def test_scheduled_failure_isolated_and_retry(clients, monkeypatch):
    from datetime import timedelta
    from sqlalchemy import update
    from app.auth import get_db, now
    from app.main import app
    from app.models import Paper, SchedulerFailure
    from app.workflows import run_scheduled_once
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    first=a.post('/api/v1/papers',json={'title':'失败项'},headers=h).json()['id']
    second=a.post('/api/v1/papers',json={'title':'正常项'},headers=h).json()['id']
    assert a.post('/api/v1/workflows',json={'name':'定时','trigger':'scheduled_check','filter_value':'1','message':'提醒'},headers=h).status_code==201
    generator=app.dependency_overrides[get_db]();db=next(generator)
    try:
        db.execute(update(Paper).where(Paper.id.in_([first,second])).values(created_at=now()-timedelta(days=2)));db.commit()
        import app.workflows as wf
        original=wf.Notification
        def fail_once(**kwargs):
            if not getattr(fail_once,'failed',False):fail_once.failed=True;raise ValueError('simulated')
            return original(**kwargs)
        monkeypatch.setattr(wf,'Notification',fail_once)
        assert run_scheduled_once(db)==1
        failure=db.scalar(select(SchedulerFailure));assert failure and failure.attempts==1 and failure.resolved_at is None
        assert run_scheduled_once(db)==0
        failure.next_retry_at=now()-timedelta(seconds=1);db.commit()
        assert run_scheduled_once(db)==1
        db.refresh(failure);assert failure.resolved_at is not None
    finally:generator.close()
    monkeypatch.setattr(wf,'Notification',original)
    assert len(a.get('/api/v1/notifications').json())==2


def test_scheduled_failure_recovers_next_day_without_duplicate(clients, monkeypatch):
    from datetime import datetime, timedelta
    from sqlalchemy import update
    from app.auth import get_db
    from app.main import app
    from app.models import Paper, SchedulerFailure
    import app.workflows as wf
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    pid=a.post('/api/v1/papers',json={'title':'跨日测试'},headers=h).json()['id']
    assert a.post('/api/v1/workflows',json={'name':'定时','trigger':'scheduled_check','filter_value':'1','message':'提醒'},headers=h).status_code==201
    gen=app.dependency_overrides[get_db]();db=next(gen)
    today=datetime(2026,11,20,23,59)
    try:
        db.execute(update(Paper).where(Paper.id==pid).values(created_at=today-timedelta(days=3)));db.commit()
        original=wf.Notification
        monkeypatch.setattr(wf,'now',lambda:today)
        def fail(**kwargs):raise ValueError('simulated')
        monkeypatch.setattr(wf,'Notification',fail)
        assert wf.run_scheduled_once(db)==0
        failure=db.scalar(select(SchedulerFailure));assert failure and failure.resolved_at is None
        monkeypatch.setattr(wf,'Notification',original)
        monkeypatch.setattr(wf,'now',lambda:today+timedelta(minutes=2))
        assert wf.run_scheduled_once(db)==1
        assert wf.run_scheduled_once(db)==0
        db.refresh(failure);assert failure.resolved_at is not None
    finally:gen.close()
    assert len(a.get('/api/v1/notifications').json())==1
