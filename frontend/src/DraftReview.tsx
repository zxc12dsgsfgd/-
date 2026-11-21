import { useEffect, useState } from 'react'
import { EvidenceLinks } from './EvidenceLinks'

type Draft={id:number;title:string;content:string;task_type:string;status:string}
type Tag={id:number;name:string}
type SourceStatus={index:number;type:string|null;title:string|null;status:string}
const headers={'Content-Type':'application/json','X-Requested-With':'zhiyan'}
async function post(url:string, body:object) {
  const response=await fetch(url,{method:'POST',headers,body:JSON.stringify(body)})
  if(!response.ok){const result=await response.json().catch(()=>({}));throw new Error(typeof result.detail==='string'?result.detail:'操作失败')}
  return response.json()
}
export function DraftReview({draft,onChange}:{draft:Draft;onChange:()=>Promise<void>}) {
  const [tags,setTags]=useState<Tag[]>([]),[selected,setSelected]=useState<number[]>([]),[card,setCard]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[sources,setSources]=useState<SourceStatus[]|null>(null),[sourceError,setSourceError]=useState('')
  useEffect(()=>{
    if(draft.task_type!=='tags'||draft.status!=='accepted')return
    let active=true
    const load=()=>{void fetch('/api/v1/tags').then(r=>{if(!r.ok)throw new Error();return r.json()}).then((items:Tag[])=>{if(active){setTags(items);setSelected(old=>old.filter(id=>items.some(t=>t.id===id)))}}).catch(()=>{if(active)setMessage('标签列表加载失败')})}
    load();window.addEventListener('zhiyan:tags-changed',load)
    return()=>{active=false;window.removeEventListener('zhiyan:tags-changed',load)}
  },[draft.status,draft.task_type])
  async function accept(){
    if(!confirm('确认接受当前草稿？接受不代表内容已被事实核实。'))return
    setBusy(true);try{await post(`/api/v1/drafts/${draft.id}/accept`,{title:draft.title,content:draft.content});await onChange();setMessage('已接受当前草稿；请继续核实内容。')}catch(e){setMessage(e instanceof Error?e.message:'接受失败')}finally{setBusy(false)}
  }
  async function apply(){
    const id=Number(card)
    if(!/^[1-9]\d*$/.test(card)||!Number.isSafeInteger(id)||!selected.length){setMessage('请填写有效卡片编号并选择标签。');return}
    const names=tags.filter(t=>selected.includes(t.id)).map(t=>t.name).join('、')
    if(!confirm(`确认将标签「${names}」添加到卡片 ${id}？`))return
    setBusy(true);try{const result=await post(`/api/v1/drafts/${draft.id}/apply-tags`,{title:draft.title,content:draft.content,card_id:id,tag_ids:selected});setMessage(`操作完成，新增 ${result.added} 个标签。`);window.dispatchEvent(new Event('zhiyan:tags-changed'))}catch(e){setMessage(e instanceof Error?e.message:'应用失败')}finally{setBusy(false)}
  }
  async function checkSources(){try{const r=await fetch(`/api/v1/drafts/${draft.id}/source-status`);if(!r.ok)throw new Error();const result=await r.json();setSources(result.sources);setSourceError('')}catch{setSourceError('来源状态加载失败')}}
  return <div><EvidenceLinks kind="drafts" id={draft.id} onChanged={onChange}/><button type="button" className="secondary" onClick={()=>void checkSources()}>检查来源是否可用</button>{sources&&<div><p className="note">来源清单记录当次选择，不代表逐句引用或内容已核实。</p>{sources.length===0?<p>没有来源材料</p>:sources.map(s=><p key={s.index}>{s.title||'补充文本'} · {({available:'可访问',unavailable:'来源已删除或不可访问',text_snapshot:'文本快照',unknown:'状态未知'} as Record<string,string>)[s.status]}</p>)}</div>}{sourceError&&<p role="status">{sourceError}</p>}<p>{draft.status==='accepted'?'已接受 · 内容仍需核实':'待审核草稿'}</p>{draft.status!=='accepted'&&<button type="button" className="secondary" disabled={busy} onClick={()=>void accept()}>接受当前草稿</button>}{draft.status==='accepted'&&draft.task_type==='tags'&&<div><h4>应用已审核的标签建议</h4><p className="note">请自行对照上方建议，选择要应用的已有标签。这里不会自动解析或创建标签。</p><label>目标卡片编号<input type="number" min="1" value={card} onChange={e=>setCard(e.target.value)}/></label>{tags.length===0&&<p>暂无可选标签，请先在标签管理中创建。</p>}{tags.map(tag=><label key={tag.id}><input type="checkbox" checked={selected.includes(tag.id)} onChange={e=>setSelected(old=>e.target.checked?[...old,tag.id]:old.filter(id=>id!==tag.id))}/>{tag.name}</label>)}<button type="button" className="secondary" disabled={busy||!tags.length} onClick={()=>void apply()}>确认并应用所选标签</button></div>}{message&&<p role="status">{message}</p>}</div>
}
