import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { PaperFiles } from './PaperFiles'
import { Notes } from './Knowledge'
import { ResourceTags } from './Tags'
import { BatchImport } from './BatchImport'
import { StructuredNotes } from './StructuredNotes'

type Paper = { id:number; title:string; authors:string[]; year:number|null; doi:string|null; venue:string|null; abstract:string|null; source_url:string|null; bibtex:string|null; status:string }
const empty = {title:'', authors:'', year:'', doi:'', venue:'', abstract:'', source_url:'', bibtex:'', status:'unread'}
const statuses: Record<string,string> = {unread:'待读', reading:'阅读中', read:'已读', archived:'已归档'}

export function Papers() {
  const [papers,setPapers]=useState<Paper[]>([])
  const [form,setForm]=useState(empty)
  const [editing,setEditing]=useState<number|null>(null)
  const [message,setMessage]=useState('')
  const [query,setQuery]=useState('')
  const [filter,setFilter]=useState('')
  const [tagFilter,setTagFilter]=useState('')
  const [cursor,setCursor]=useState<number|null>(null)
  const [loading,setLoading]=useState(false)
  const [importKind,setImportKind]=useState<'bibtex'|'doi'|'link'>('bibtex')
  const [importValue,setImportValue]=useState('')
  const [importBusy,setImportBusy]=useState(false)
  const requestId=useRef(0)
  const load=useCallback(async (before?:number, append=false) => {
    const id=++requestId.current
    setLoading(true)
    try {
      const params=new URLSearchParams({q:query}); if(filter) params.set('status',filter); if(tagFilter) params.set('tag_id',tagFilter); if(before) params.set('before_id',String(before))
      const res=await fetch(`/api/v1/papers?${params}`); if(!res.ok) throw new Error(res.status===401?'登录已过期，请重新登录':'文献加载失败')
      const data=await res.json(); if(id!==requestId.current) return; setPapers(old=>append?[...old,...data.items]:data.items); setCursor(data.next_cursor)
    } catch(e){if(id===requestId.current) setMessage(e instanceof Error?e.message:'请求失败')} finally {if(id===requestId.current) setLoading(false)}
  },[query,filter,tagFilter])
  useEffect(()=>{ void load(); const changed=()=>void load(); window.addEventListener('zhiyan:papers-changed',changed); return()=>window.removeEventListener('zhiyan:papers-changed',changed) },[load])
  function update(key:keyof typeof empty,value:string){setForm(old=>({...old,[key]:value}))}
  async function previewImport(){
    if ((form.title || form.authors || form.doi || form.abstract || form.bibtex) && !window.confirm('解析结果会替换当前表单中尚未保存的内容，继续吗？')) return
    setMessage(''); setImportBusy(true)
    try {
      const res=await fetch('/api/v1/papers/import/preview',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'zhiyan'},body:JSON.stringify({kind:importKind,value:importValue})})
      const data=await res.json(); if(!res.ok) throw new Error(typeof data.detail==='string'?data.detail:'解析失败，请检查输入或手动填写')
      const p=data.paper; setEditing(null); setForm({title:p.title,authors:p.authors.join('\n'),year:p.year?.toString()||'',doi:p.doi||'',venue:p.venue||'',abstract:p.abstract||'',source_url:p.source_url||'',bibtex:p.bibtex||'',status:p.status})
      setMessage(data.duplicates.length?`发现 ${data.duplicates.length} 条可能重复的文献：${data.duplicates.map((x:{title:string})=>x.title).join('、')}。请核对后保存。`:'解析完成，请检查内容后保存')
    } catch(e){setMessage(e instanceof Error?e.message:'解析失败，请手动填写')} finally {setImportBusy(false)}
  }
  async function save(e:FormEvent){
    e.preventDefault(); setMessage('')
    const body={...form,authors:form.authors.split('\n').map(x=>x.trim()).filter(Boolean),year:form.year?Number(form.year):null,doi:form.doi||null,venue:form.venue||null,abstract:form.abstract||null,source_url:form.source_url||null,bibtex:form.bibtex||null}
    try {const options={method:editing?'PUT':'POST',headers:{'Content-Type':'application/json','X-Requested-With':'zhiyan'},body:JSON.stringify(body)}; let res=await fetch(editing?`/api/v1/papers/${editing}`:'/api/v1/papers',options); if(res.status===409 && !editing){const detail=await res.json(); const matches=detail.detail?.matches || []; if(!window.confirm(`可能存在重复文献：${matches.map((x:{title:string})=>x.title).join('、')}。仍要单独保存吗？`)) return; res=await fetch('/api/v1/papers?confirm_duplicate=true',options)} if(!res.ok) throw new Error(res.status===401?'登录已过期，请重新登录':'保存失败，请检查输入'); setForm(empty); setEditing(null); setMessage('文献已保存'); await load()} catch(err){setMessage(err instanceof Error?err.message:'保存失败')}
  }
  function edit(p:Paper){setEditing(p.id); setForm({title:p.title,authors:p.authors.join('\n'),year:p.year?.toString()||'',doi:p.doi||'',venue:p.venue||'',abstract:p.abstract||'',source_url:p.source_url||'',bibtex:p.bibtex||'',status:p.status}); window.scrollTo({top:0,behavior:'smooth'})}
  async function remove(p:Paper){if(!window.confirm(`将“${p.title}”移入回收站？PDF 和笔记暂时保留，关联卡片的文献来源暂不可用。`)) return; try {const r=await fetch(`/api/v1/papers/${p.id}`,{method:'DELETE',headers:{'X-Requested-With':'zhiyan'}}); if(!r.ok) {const body=await r.json(); throw new Error(typeof body.detail==='string'?body.detail:'删除失败')}; setMessage('文献已移入回收站'); window.dispatchEvent(new Event('zhiyan:trash-changed')); window.dispatchEvent(new Event('zhiyan:cards-changed')); await load()}catch(e){setMessage(e instanceof Error?e.message:'删除失败')}}
  return <div className="papers"><h2>文献库</h2><p className="note">支持手动录入、BibTeX、DOI、HTTPS 文献网页及 PDF 上传和预览</p><BatchImport onImported={()=>void load()}/><div className="paper-form"><h3>导入预览</h3><label>导入方式<select value={importKind} onChange={e=>setImportKind(e.target.value as 'bibtex'|'doi'|'link')}><option value="bibtex">BibTeX</option><option value="doi">DOI 或 doi.org 链接</option><option value="link">HTTPS 文献网页</option></select></label>{importKind==='link'&&<p className="note">仅解析可直接访问的 HTTPS 网页；页面可能无法提供完整信息，请核对。请勿输入含密钥的链接。</p>}<label>导入内容<textarea maxLength={60000} value={importValue} onChange={e=>setImportValue(e.target.value)}/></label><button type="button" disabled={importBusy || !importValue.trim()} onClick={()=>void previewImport()}>{importBusy?'解析中':'解析并预览'}</button></div>{message && <p role="status" className="feedback">{message}</p>}<form onSubmit={save} className="paper-form"><h3>{editing?'编辑文献':'添加文献'}</h3><label>标题<input required maxLength={500} value={form.title} onChange={e=>update('title',e.target.value)}/></label><label>作者（每行一位）<textarea value={form.authors} onChange={e=>update('authors',e.target.value)} /></label><label>年份<input type="number" min="1" max="9999" value={form.year} onChange={e=>update('year',e.target.value)}/></label><label>DOI<input maxLength={512} value={form.doi} onChange={e=>update('doi',e.target.value)}/></label><label>期刊或会议<input maxLength={500} value={form.venue} onChange={e=>update('venue',e.target.value)}/></label><label>原始链接<input maxLength={2048} value={form.source_url} onChange={e=>update('source_url',e.target.value)}/></label><label>摘要<textarea maxLength={60000} value={form.abstract} onChange={e=>update('abstract',e.target.value)}/></label><label>BibTeX 原文<textarea maxLength={60000} value={form.bibtex} onChange={e=>update('bibtex',e.target.value)}/></label><label>阅读状态<select value={form.status} onChange={e=>update('status',e.target.value)}>{Object.entries(statuses).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><div className="actions"><button>保存文献</button>{editing && <button type="button" className="secondary" onClick={()=>{setEditing(null);setForm(empty)}}>取消编辑</button>}</div></form><div className="paper-list"><h3>我的文献</h3><label>标签编号筛选<input type="number" min="1" value={tagFilter} onChange={e=>setTagFilter(e.target.value)}/></label><label>搜索标题<input value={query} onChange={e=>setQuery(e.target.value)}/></label><label>阅读状态<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="">全部</option>{Object.entries(statuses).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>{loading?<p>正在加载</p>:papers.length===0?<p>暂无文献</p>:papers.map(p=><article key={p.id} id={`paper-${p.id}`}><h4>{p.title}（编号 {p.id}）</h4><p>{p.authors.join('、') || '未填写作者'} {p.year ? `· ${p.year}` : ''} · {statuses[p.status]}</p>{p.doi && <p>DOI：{p.doi}</p>}{p.venue && <p>期刊或会议：{p.venue}</p>}{p.abstract && <p>{p.abstract}</p>}<ResourceTags kind="papers" id={p.id}/><PaperFiles paperId={p.id}/><Notes paperId={p.id}/><StructuredNotes paperId={p.id}/><div className="actions"><button className="secondary" onClick={()=>edit(p)}>编辑</button><button className="secondary" onClick={()=>void remove(p)}>删除</button></div></article>)}{cursor && <button className="secondary" disabled={loading} onClick={()=>void load(cursor,true)}>加载更多</button>}</div></div>
}
