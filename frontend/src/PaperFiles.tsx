import { lazy, Suspense, useEffect, useState, type ChangeEvent } from 'react'
const PdfViewer=lazy(()=>import('./PdfViewer').then(m=>({default:m.PdfViewer})))

type PaperFile = {id:number; name:string; size_bytes:number; state:string}
export function PaperFiles({paperId}:{paperId:number}) {
  const [files,setFiles]=useState<PaperFile[]>([])
  const [message,setMessage]=useState('')
  const [selected,setSelected]=useState<number|null>(null)
  const [busy,setBusy]=useState(false)
  async function load(){const r=await fetch(`/api/v1/papers/${paperId}/files`); if(!r.ok) throw new Error('文件列表加载失败'); setFiles(await r.json())}
  useEffect(()=>{let live=true; const refresh=()=>{fetch(`/api/v1/papers/${paperId}/files`).then(async r=>{if(!r.ok) throw new Error(); const data=await r.json(); if(live)setFiles(data)}).catch(()=>{if(live)setMessage('文件列表加载失败')})}; refresh(); window.addEventListener('zhiyan:pdf-imported',refresh); return ()=>{live=false;window.removeEventListener('zhiyan:pdf-imported',refresh)}},[paperId])
  async function upload(e:ChangeEvent<HTMLInputElement>){
    const file=e.target.files?.[0]; e.target.value=''; if(!file)return
    if(file.size>50*1024*1024){setMessage('PDF 不能超过 50 MiB'); return}
    const data=new FormData(); data.append('file',file); setBusy(true); setMessage('')
    try {const r=await fetch(`/api/v1/papers/${paperId}/files`,{method:'POST',headers:{'X-Requested-With':'zhiyan'},body:data}); if(!r.ok){const body=await r.json(); throw new Error(typeof body.detail==='string'?body.detail:'上传失败')}; await load(); setMessage('PDF 已上传')} catch(err){setMessage(err instanceof Error?err.message:'上传失败')} finally {setBusy(false)}
  }
  async function remove(f:PaperFile){if(!window.confirm(`确定删除 PDF“${f.name}”？此操作无法恢复。`))return; setBusy(true); try{const r=await fetch(`/api/v1/papers/${paperId}/files/${f.id}`,{method:'DELETE',headers:{'X-Requested-With':'zhiyan'}}); if(!r.ok)throw new Error('删除失败，请重试'); if(selected===f.id)setSelected(null); await load(); setMessage('PDF 已删除')}catch(e){setMessage(e instanceof Error?e.message:'删除失败')}finally{setBusy(false)}}
  return <div className="paper-files"><label>上传 PDF（最大 50 MiB）<input type="file" accept="application/pdf,.pdf" disabled={busy} onChange={e=>void upload(e)}/></label>{files.map(f=><div key={f.id}><span>{f.name} · {(f.size_bytes/1024/1024).toFixed(2)} MiB {f.state==='deleting'?'· 等待清理':''}</span><div className="actions">{f.state==='ready' && <button type="button" className="secondary" onClick={()=>setSelected(selected===f.id?null:f.id)}>{selected===f.id?'关闭预览':'预览 PDF'}</button>}<button type="button" className="secondary" disabled={busy} onClick={()=>void remove(f)}>删除 PDF</button></div>{selected===f.id && <Suspense fallback={<p role="status">正在加载 PDF 阅读器…</p>}><PdfViewer paperId={paperId} url={`/api/v1/papers/${paperId}/files/${f.id}`}/></Suspense>}</div>)}{message && <p role="status">{message}</p>}</div>
}
