import http.client
import ipaddress
import json
import socket
import ssl
from datetime import timedelta
from urllib.parse import urlsplit
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.ai import cipher
from app.auth import now
from app.models import AIJob, Draft

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,ip,timeout):
        super().__init__(host,443,timeout=timeout,context=ssl.create_default_context());self.ip=ip
    def connect(self):
        sock=socket.create_connection((self.ip,443),self.timeout)
        self.sock=self._context.wrap_socket(sock,server_hostname=self.host)

def call_provider(job,key):
    parts=urlsplit(job.base_url);host=parts.hostname
    if parts.scheme!='https' or not host or parts.port not in (None,443) or parts.username or parts.password or parts.query or parts.fragment:raise ValueError('unsafe_address')
    answers=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    ips={a[4][0] for a in answers}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise ValueError('unsafe_address')
    prompt={'review':'根据材料起草综述','questions':'根据材料提出研究问题和阅读问题','tags':'根据材料提出标签建议','format':'检查文本的基础格式'}[job.task_type]
    body=json.dumps({'model':job.model_name,'messages':[{'role':'system','content':'你是科研写作助手。输出是未经核实的草稿，不得编造参考文献；仅依据用户材料。'},{'role':'user','content':prompt+'\n材料：\n'+json.dumps(job.payload,ensure_ascii=False)}]},ensure_ascii=False).encode()
    conn=PinnedHTTPS(host,sorted(ips)[0],job.timeout_seconds)
    try:
        conn.request('POST',parts.path.rstrip('/')+'/chat/completions',body=body,headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        response=conn.getresponse()
        if response.status<200 or response.status>=300:raise ValueError('provider_error')
        raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('response_too_large')
        content=json.loads(raw)['choices'][0]['message']['content']
        if not isinstance(content,str) or not content.strip() or len(content)>15000:raise ValueError('invalid_response')
        return content
    finally:conn.close()

def run_ai_once(engine):
    with Session(engine) as db:
        stale=now()-timedelta(minutes=10)
        db.execute(update(AIJob).where(AIJob.status=='running',AIJob.started_at<stale).values(status='unknown',error_code='interrupted',key_ciphertext=b''))
        job=db.scalar(select(AIJob).where(AIJob.status=='pending').order_by(AIJob.id).with_for_update(skip_locked=True).limit(1))
        if not job:db.commit();return False
        job.status='running';job.started_at=now();job_id=job.id;db.commit()
    try:
        with Session(engine) as db:
            job=db.get(AIJob,job_id)
            key=cipher().decrypt(job.key_ciphertext).decode()
            content=call_provider(job,key)
            job=db.scalar(select(AIJob).where(AIJob.id==job_id).with_for_update())
            if job.status!='running':db.rollback();return True
            d=Draft(owner_id=job.owner_id,task_type=job.task_type,title='AI 辅助草稿',content=content,sources=job.payload['sources']+([{'type':'text','content':job.payload['text']}] if job.payload['text'] else []),status='draft');db.add(d);db.flush()
            job.draft_id=d.id;job.status='success';job.key_ciphertext=b'';db.commit()
    except Exception as exc:
        if isinstance(exc,(TimeoutError,socket.timeout)):code='timeout_unknown'
        elif isinstance(exc,ValueError) and str(exc) in ('unsafe_address','provider_error','response_too_large','invalid_response'):code=str(exc)
        else:code='connection_or_config_error'
        with Session(engine) as db:
            job=db.scalar(select(AIJob).where(AIJob.id==job_id).with_for_update())
            if job and job.status=='running':job.status='failed';job.error_code=code;job.key_ciphertext=b'';db.commit()
    return True
