import hashlib
import io
import json
import zipfile

from test_papers import clients


def test_pdf_archive_scope_integrity_and_trash(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    p=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    other=b.post('/api/v1/papers',json={'title':'他人'},headers=h).json()['id']
    payload=b'%PDF-synthetic-data'
    assert a.post(f'/api/v1/papers/{p}/files',files={'file':('测试.pdf',payload,'application/pdf')},headers=h).status_code==201
    assert b.post(f'/api/v1/papers/{other}/files',files={'file':('other.pdf',b'%PDF-other','application/pdf')},headers=h).status_code==201
    assert a.get('/api/v1/personal-backup/pdf-summary').json()['count']==1
    result=a.get('/api/v1/personal-backup/pdf-export');assert result.status_code==200 and result.headers['cache-control']=='no-store'
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert archive.namelist()==['files/0001.pdf','manifest.json']
        manifest=json.loads(archive.read('manifest.json'))
        assert archive.read('files/0001.pdf')==payload
        assert manifest['files'][0]['paper_id']==p and manifest['files'][0]['sha256']==hashlib.sha256(payload).hexdigest()
    assert a.delete(f'/api/v1/papers/{p}',headers=h).status_code==204
    assert a.get('/api/v1/personal-backup/pdf-summary').json()['count']==0


def test_pdf_archive_rejects_modified_and_oversize_files(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    import app.pdf_backup as backup
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    p=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    a.post(f'/api/v1/papers/{p}/files',files={'file':('x.pdf',b'%PDF-original','application/pdf')},headers=h)
    stored=next(tmp_path.iterdir());stored.write_bytes(b'%PDF-tampered')
    assert a.get('/api/v1/personal-backup/pdf-export').status_code==409
    monkeypatch.setattr(backup,'MAX_TOTAL',1)
    assert a.get('/api/v1/personal-backup/pdf-export').status_code==413


def test_pdf_preview_validates_archive_without_writing(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    paper=a.post('/api/v1/papers',json={'title':'文献'},headers=h).json()['id']
    a.post(f'/api/v1/papers/{paper}/files',files={'file':('x.pdf',b'%PDF-content','application/pdf')},headers=h)
    raw=a.get('/api/v1/personal-backup/pdf-export').content
    before=list(tmp_path.iterdir())
    result=a.post('/api/v1/personal-backup/pdf-preview',files={'file':('a.zip',raw,'application/zip')},headers=h)
    assert result.status_code==200 and result.json()['files'][0]['paper_id']==paper
    assert '仅校验' in result.json()['notice'] and list(tmp_path.iterdir())==before


def test_pdf_preview_rejects_paths_duplicates_symlinks_and_tampering(clients):
    a,_=clients;h={'X-Requested-With':'zhiyan'}
    def preview(raw):return a.post('/api/v1/personal-backup/pdf-preview',files={'file':('x.zip',raw,'application/zip')},headers=h)
    def archive(name,content,*,link=False,duplicate=False,compressed=False):
        out=io.BytesIO();digest=hashlib.sha256(content).hexdigest()
        manifest={'format':'zhiyan-pdf-export','version':1,'files':[{'paper_id':1,'name':'x.pdf','path':name,'size_bytes':len(content),'sha256':digest}]}
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED) as z:
            info=zipfile.ZipInfo(name)
            if link:info.create_system=3;info.external_attr=(0o120777<<16)
            if compressed:info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,content)
            if duplicate:z.writestr(name,content)
            z.writestr('manifest.json',json.dumps(manifest))
        return out.getvalue()
    assert preview(archive('../x.pdf',b'%PDF-x')).status_code==422
    assert preview(archive('files/0001.pdf',b'%PDF-x',link=True)).status_code==422
    assert preview(archive('files/0001.pdf',b'%PDF-x',duplicate=True)).status_code==422
    assert preview(archive('files/0001.pdf',b'%PDF-x',compressed=True)).status_code==422
    assert preview(archive('files/0001.pdf',b'not-a-pdf')).status_code==422
    raw=archive('files/0001.pdf',b'%PDF-x').replace(b'%PDF-x',b'%PDF-y')
    assert preview(raw).status_code==422


def test_pdf_mapping_preview_requires_owned_targets_and_unchanged_archive(clients,tmp_path,monkeypatch):
    import app.paper_files as files
    a,b=clients;h={'X-Requested-With':'zhiyan'}
    monkeypatch.setattr(files,'STORAGE',tmp_path)
    source=a.post('/api/v1/papers',json={'title':'来源'},headers=h).json()['id']
    target=b.post('/api/v1/papers',json={'title':'目标'},headers=h).json()['id']
    a.post(f'/api/v1/papers/{source}/files',files={'file':('x.pdf',b'%PDF-content','application/pdf')},headers=h)
    raw=a.get('/api/v1/personal-backup/pdf-export').content
    digest=b.post('/api/v1/personal-backup/pdf-preview',files={'file':('x.zip',raw,'application/zip')},headers=h).json()['sha256']
    url='/api/v1/personal-backup/pdf-mapping-preview'
    def check(mapping,sha=digest):
        return b.post(url,files={'file':('x.zip',raw,'application/zip')},data={'mapping':json.dumps(mapping),'expected_sha256':sha},headers=h)
    mapping=[{'source_paper_id':source,'target_paper_id':target}]
    result=check(mapping)
    assert result.status_code==200 and result.json()['mappings'][0]['target_title']=='目标'
    receipt=result.json()['mapping_receipt'];assert len(receipt)==64
    assert check(mapping).json()['mapping_receipt']==receipt
    assert '尚未保存或导入' in result.json()['notice']
    assert check(mapping,'0'*64).status_code==409
    assert check([]).status_code==422
    assert check(mapping+mapping).status_code==422
    assert check([{'source_paper_id':source,'target_paper_id':source}]).status_code==404
    assert b.get(f'/api/v1/papers/{target}/files').json()==[]


def test_mapping_receipt_binds_session_archive_and_mapping():
    from app.pdf_backup import PaperMapping,mapping_receipt
    first=[PaperMapping(source_paper_id=1,target_paper_id=2),PaperMapping(source_paper_id=3,target_paper_id=4)]
    secret=b'synthetic-session-hash'
    expected=mapping_receipt(secret,'a'*64,first)
    assert mapping_receipt(secret,'a'*64,list(reversed(first)))==expected
    assert mapping_receipt(b'other-session','a'*64,first)!=expected
    assert mapping_receipt(secret,'b'*64,first)!=expected
    assert mapping_receipt(secret,'a'*64,[PaperMapping(source_paper_id=1,target_paper_id=4),first[1]])!=expected
