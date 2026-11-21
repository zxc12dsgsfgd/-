import { useEffect, useState, type FormEvent } from 'react'

type Link = { id:number; source_type:string; source_id:number; source_snapshot:{title:string;doi?:string|null;source_url?:string|null}; location:string; excerpt:string; note:string; status:string }
type Change = { action:string; detail:{location:string;excerpt:string;note:string}; created_at:string }
const headers = {'Content-Type':'application/json', 'X-Requested-With':'zhiyan'}
async function api(url:string, options?:RequestInit) {
  const result=await fetch(url,options)
  if(!result.ok){const body=await result.json().catch(()=>({}));throw new Error(typeof body.detail==='string'?body.detail:'操作失败')}
  return result.status===204?null:result.json()
}
export function EvidenceLinks({kind,id,onChanged}:{kind:'cards'|'drafts';id:number;onChanged:()=>Promise<void>}) {
  const [links,setLinks]=useState<Link[]>([]),[type,setType]=useState('paper'),[sourceId,setSourceId]=useState(''),[location,setLocation]=useState(''),[excerpt,setExcerpt]=useState(''),[note,setNote]=useState('')
  const [editing,setEditing]=useState<number|null>(null),[historyId,setHistoryId]=useState<number|null>(null),[history,setHistory]=useState<Change[]>([]),[error,setError]=useState('')
  const base=`/api/v1/${kind}/${id}/evidence`
  async function load(){try{setLinks(await api(base));setError('')}catch{setError('来源关联加载失败')}}
  useEffect(()=>{void load()},[kind,id])
  function clear(){setEditing(null);setSourceId('');setLocation('');setExcerpt('');setNote('')}
  async function save(event:FormEvent){
    event.preventDefault()
    try{const fields={location,excerpt,note};await api(editing?`${base}/${editing}`:base,{method:editing?'PUT':'POST',headers,body:JSON.stringify(editing?fields:{...fields,source_type:type,source_id:Number(sourceId)})});clear();await load();await onChanged()}
    catch(e){setError(e instanceof Error?e.message:'保存失败')}
  }
  async function remove(link:Link){try{await api(`${base}/${link.id}`,{method:'DELETE',headers});await load();await onChanged()}catch(e){setError(e instanceof Error?e.message:'移除失败')}}
  async function showHistory(link:Link){try{setHistory(await api(`${base}/${link.id}/history`));setHistoryId(link.id)}catch{setError('变更记录加载失败')}}
  return <div><h4>手动关联的来源</h4><p className="note">这些关联由用户维护；不改变草稿创建时选择的材料，也不代表内容已核实。</p>
    <form onSubmit={save}>{editing===null&&<><label>来源类型<select value={type} onChange={e=>setType(e.target.value)}><option value="paper">文献</option><option value="card">卡片</option></select></label><label>来源编号<input required type="number" min="1" value={sourceId} onChange={e=>setSourceId(e.target.value)}/></label></>}
      <label>位置<input maxLength={200} value={location} onChange={e=>setLocation(e.target.value)}/></label><label>来源原文<textarea maxLength={20000} value={excerpt} onChange={e=>setExcerpt(e.target.value)}/></label><label>用户备注<textarea maxLength={20000} value={note} onChange={e=>setNote(e.target.value)}/></label>
      <div className="actions"><button>{editing===null?'添加来源':'保存来源修改'}</button>{editing!==null&&<button type="button" className="secondary" onClick={clear}>取消</button>}</div></form>
    {links.length===0&&<p>暂无手动关联来源</p>}{links.map(link=><div key={link.id}><p>{link.source_snapshot.title} · {link.source_type==='paper'?'文献':'卡片'} · {({available:'可访问',unavailable:'来源已删除或不可访问',removed:'关联已移除'} as Record<string,string>)[link.status]}</p>
      {link.source_snapshot.doi&&<p>DOI：{link.source_snapshot.doi}</p>}{link.source_snapshot.source_url&&<p>原始链接：{link.source_snapshot.source_url}</p>}{link.location&&<p>位置：{link.location}</p>}{link.excerpt&&<blockquote>{link.excerpt}</blockquote>}{link.note&&<p>备注：{link.note}</p>}
      <div className="actions">{link.status!=='removed'&&<><button className="secondary" onClick={()=>{setEditing(link.id);setLocation(link.location);setExcerpt(link.excerpt);setNote(link.note)}}>编辑来源</button><button className="secondary" onClick={()=>void remove(link)}>移除关联</button></>}<button className="secondary" onClick={()=>void showHistory(link)}>变更记录</button></div>
      {historyId===link.id&&<div>{history.map((item,index)=><div key={index}><p>{({created:'添加',updated:'修改',removed:'移除'} as Record<string,string>)[item.action]} · {item.created_at} · {item.detail.location || '未填写位置'}</p>{item.detail.excerpt&&<blockquote>{item.detail.excerpt}</blockquote>}<p>备注：{item.detail.note || '无'}</p></div>)}</div>}</div>)}
    {error&&<p role="status">{error}</p>}</div>
}
