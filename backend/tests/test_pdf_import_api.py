import json

from test_papers import clients


def test_pdf_import_confirmation_idempotency_and_owner_scope(clients, tmp_path, monkeypatch):
    import app.paper_files as files
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    source=a.post('/api/v1/papers',json={'title':'source'},headers=h).json()['id']
    target=b.post('/api/v1/papers',json={'title':'target'},headers=h).json()['id']
    payload=b'%PDF-synthetic'
    assert a.post(f'/api/v1/papers/{source}/files',files={'file':('x.pdf',payload,'application/pdf')},headers=h).status_code==201
    raw=a.get('/api/v1/personal-backup/pdf-export').content
    preview=b.post('/api/v1/personal-backup/pdf-preview',files={'file':('x.zip',raw,'application/zip')},headers=h).json()
    mapping=json.dumps([{'source_paper_id':source,'target_paper_id':target}])
    form={'expected_sha256':preview['sha256'],'mapping':mapping}
    mapped=b.post('/api/v1/personal-backup/pdf-mapping-preview',files={'file':('x.zip',raw,'application/zip')},data=form,headers=h).json()
    form.update(receipt=mapped['mapping_receipt'],request_id='d'*32,confirmed='true')
    url='/api/v1/personal-backup/pdf-import'
    def submit(client, fields=form):
        return client.post(url,files={'file':('x.zip',raw,'application/zip')},data=fields,headers=h)
    assert submit(b,{**form,'receipt':'bad'}).status_code==409
    assert submit(a).status_code==409
    response=submit(b);assert response.status_code==200, response.text
    assert response.json()['count']==1
    assert submit(b).json()['status']=='completed'
    target_files=b.get(f'/api/v1/papers/{target}/files').json()
    assert len(target_files)==1
    assert b.get(f"/api/v1/papers/{target}/files/{target_files[0]['id']}").content==payload
    assert a.post('/api/v1/personal-backup/pdf-import-batches/'+'d'*32+'/recover',headers=h).status_code==404


def test_pdf_import_failed_publication_is_recoverable(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    import app.pdf_import_publish as publish
    a,_=clients;h={'X-Requested-With':'zhiyan'};monkeypatch.setattr(files,'STORAGE',tmp_path)
    paper=a.post('/api/v1/papers',json={'title':'paper'},headers=h).json()['id']
    a.post(f'/api/v1/papers/{paper}/files',files={'file':('x.pdf',b'%PDF-fixture','application/pdf')},headers=h)
    raw=a.get('/api/v1/personal-backup/pdf-export').content
    preview=a.post('/api/v1/personal-backup/pdf-preview',files={'file':('x.zip',raw,'application/zip')},headers=h).json()
    mapping=json.dumps([{'source_paper_id':paper,'target_paper_id':paper}]);form={'mapping':mapping,'expected_sha256':preview['sha256']}
    mapped=a.post('/api/v1/personal-backup/pdf-mapping-preview',files={'file':('x.zip',raw,'application/zip')},data=form,headers=h).json()
    form.update(receipt=mapped['mapping_receipt'],request_id='e'*32,confirmed='true')
    original=publish.os.link
    def fail(*args,**kwargs):raise OSError('synthetic')
    monkeypatch.setattr(publish.os,'link',fail)
    result=a.post('/api/v1/personal-backup/pdf-import',files={'file':('x.zip',raw,'application/zip')},data=form,headers=h)
    assert result.status_code==503
    assert len(a.get(f'/api/v1/papers/{paper}/files').json())==1
    monkeypatch.setattr(publish.os,'link',original)
    assert a.get('/api/v1/personal-backup/pdf-import-batches').json()['items'][0]['id']=='e'*32
    recovery=a.post('/api/v1/personal-backup/pdf-import-batches/'+'e'*32+'/recover',headers=h)
    assert recovery.status_code==200 and recovery.json()['status']=='cleaned'
    assert len(a.get(f'/api/v1/papers/{paper}/files').json())==1
