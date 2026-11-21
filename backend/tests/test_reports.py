from datetime import datetime, timedelta
from sqlalchemy import update
from test_papers import clients
from app.auth import get_db
from app.main import app
from app.models import Card, Paper, PaperStatusEvent


def test_weekly_report_boundaries_and_isolation(clients):
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    paper=a.post('/api/v1/papers',json={'title':'周报文献'},headers=h).json()['id']
    card=a.post('/api/v1/cards',json={'title':'卡片','type':'idea','content':'内容'},headers=h).json()['id']
    assert a.put(f'/api/v1/papers/{paper}',json={'title':'周报文献','status':'read'},headers=h).status_code==200
    gen=app.dependency_overrides[get_db]();db=next(gen)
    try:
        # Monday 00:00 UTC+8 is Sunday 16:00 UTC.
        start=datetime(2026,11,15,16)
        db.execute(update(Paper).where(Paper.id==paper).values(created_at=start))
        db.execute(update(Card).where(Card.id==card).values(created_at=start+timedelta(days=7)))
        db.execute(update(PaperStatusEvent).where(PaperStatusEvent.paper_id==paper,PaperStatusEvent.to_status=='read').values(occurred_at=start))
        db.commit()
    finally:gen.close()
    report=a.get('/api/v1/reports/weekly?week=2026-11-18').json()
    assert (report['papers_added'],report['cards_added'],report['papers_read'])==(1,0,1)
    assert report['week_start']=='2026-11-16' and report['read_history_complete'] is False
    assert b.get('/api/v1/reports/weekly?week=2026-11-18').json()['papers_read']==0
    assert a.delete(f'/api/v1/papers/{paper}',headers=h).status_code==204
    assert a.get('/api/v1/reports/weekly?week=2026-11-18').json()['papers_read']==0
