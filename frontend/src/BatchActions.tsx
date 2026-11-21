import {useCallback,useEffect,useRef,useState} from 'react'

type Kind='papers'|'cards'
type Item={id:number;title:string}
type Tag={id:number;name:string}
type Project={id:number;name:string}
type Action='add_tag'|'remove_tag'|'add_project'|'set_status'|'trash'|'export'
const headers={'Content-Type':'application/json','X-Requested-With':'zhiyan'}
const statusLabels:Record<string,string>={unread:'待读',reading:'阅读中',read:'已读',archived:'已归档'}
async function read(url:string,options?:RequestInit){const r=await fetch(url,options);if(!r.ok){const body=await r.json().catch(()=>({}));const detail=body.detail;throw new Error(typeof detail==='string'?detail:typeof detail?.message==='string'?`${detail.message}（成功 ${detail.success_count}，失败 ${detail.failed_count}）`:'操作失败，请检查输入')}return r}

export function BatchActions(){
 const [kind,setKind]=useState<Kind>('papers'),[items,setItems]=useState<Item[]>([]),[selected,setSelected]=useState<Item[]>([]),[cursor,setCursor]=useState<number|null>(null),[query,setQuery]=useState(''),[tags,setTags]=useState<Tag[]>([]),[projects,setProjects]=useState<Project[]>([])
 const [action,setAction]=useState<Action>('add_tag'),[tagId,setTagId]=useState(''),[projectId,setProjectId]=useState(''),[status,setStatus]=useState('read'),[format,setFormat]=useState('markdown'),[message,setMessage]=useState(''),[busy,setBusy]=useState(false)
 const requestId=useRef(0)
 const load=useCallback(async(before?:number,append=false)=>{const request=++requestId.current;try{const params=new URLSearchParams({limit:'100',q:query});if(before)params.set('before_id',String(before));const result=await (await read(`/api/v1/${kind}?${params}`)).json();if(request!==requestId.current)return;setItems(old=>append?[...old,...result.items]:result.items);setCursor(result.next_cursor)}catch(e){if(request===requestId.current)setMessage(e instanceof Error?e.message:'资料加载失败')}},[kind,query])
 const loadTargets=useCallback(async()=>{try{const [t,p]=await Promise.all([read('/api/v1/tags'),read('/api/v1/projects')]);setTags(await t.json());setProjects(await p.json())}catch{setMessage('标签或项目加载失败')}},[])
 useEffect(()=>{void load();const refresh=()=>void load();window.addEventListener(`zhiyan:${kind}-changed`,refresh);return()=>window.removeEventListener(`zhiyan:${kind}-changed`,refresh)},[load,kind]);useEffect(()=>{void loadTargets();const refresh=()=>void loadTargets();window.addEventListener('zhiyan:tags-changed',refresh);window.addEventListener('zhiyan:projects-changed',refresh);return()=>{window.removeEventListener('zhiyan:tags-changed',refresh);window.removeEventListener('zhiyan:projects-changed',refresh)}},[loadTargets])
 function select(item:Item,checked:boolean){if(checked&&selected.length>=50){setMessage('每次最多选择 50 条');return}setSelected(old=>checked?[...old,item]:old.filter(x=>x.id!==item.id))}
 function changeKind(value:Kind){requestId.current++;setKind(value);setSelected([]);setItems([]);setCursor(null);setQuery('');setAction('add_tag');setMessage('')}
 async function execute(){
  if(!selected.length)return
  if((action==='add_tag'||action==='remove_tag')&&!tagId){setMessage('请选择标签');return}
  if(action==='add_project'&&!projectId){setMessage('请选择研究项目');return}
  if(action==='set_status'&&!confirm(`确认将选中的 ${selected.length} 篇文献状态设为“${statusLabels[status]}”？`))return
  if(action==='trash'&&!confirm(`确认将选中的 ${selected.length} 条${kind==='papers'?'文献':'卡片'}移入回收站？原有分享快照不会自动撤销。`))return
  setBusy(true);setMessage('')
  try{
   if(action==='export'){
    const response=await read('/api/v1/exports',{method:'POST',headers,body:JSON.stringify({format,card_ids:selected.map(x=>x.id)})});const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=format==='markdown'?'export.md':format==='latex'?'export.tex':'references.bib';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);setMessage(`已生成 ${selected.length} 张卡片的导出文件`)
   }else{
    const data={kind,ids:selected.map(x=>x.id),action,...((action==='add_tag'||action==='remove_tag')?{tag_id:Number(tagId)}:{}),...(action==='add_project'?{project_id:Number(projectId)}:{}),...(action==='set_status'?{status,confirmed:true}:{}),...(action==='trash'?{confirmed:true}:{})}
    const result=await (await read('/api/v1/batch',{method:'POST',headers,body:JSON.stringify(data)})).json();setMessage(`成功 ${result.success_count}，失败 ${result.failed_count}，实际变更 ${result.changed_count}`);setSelected([]);for(const name of ['papers','cards','projects','tags','trash'])window.dispatchEvent(new Event(`zhiyan:${name}-changed`));await load();await loadTargets()
   }
  }catch(e){setMessage(e instanceof Error?e.message:'操作失败')}finally{setBusy(false)}
 }
 return <section className="papers"><h2>批量操作</h2><p className="note">只处理明确勾选的资料，每次最多 50 条；切换类型会清空选择，加载更多时保留已选项。</p>
  <label>资料类型<select value={kind} onChange={e=>changeKind(e.target.value as Kind)}><option value="papers">文献</option><option value="cards">卡片</option></select></label><label>搜索标题或卡片正文<input maxLength={200} value={query} onChange={e=>{requestId.current++;setItems([]);setCursor(null);setQuery(e.target.value)}}/></label>
  <p>已选 {selected.length} 条{selected.length>0&&`：${selected.map(x=>x.title).join('、')}`}</p><button className="secondary" type="button" disabled={!selected.length} onClick={()=>setSelected([])}>清空选择</button>
  <fieldset><legend>勾选资料</legend>{items.length===0&&<p>暂无匹配资料</p>}{items.map(item=><label key={item.id}><input type="checkbox" checked={selected.some(x=>x.id===item.id)} onChange={e=>select(item,e.target.checked)}/>{item.title}（{item.id}）</label>)}</fieldset>{cursor&&<button className="secondary" type="button" onClick={()=>void load(cursor,true)}>加载更多</button>}
  <label>操作<select value={action} onChange={e=>setAction(e.target.value as Action)}><option value="add_tag">添加标签</option><option value="remove_tag">移除标签</option><option value="add_project">关联研究项目</option>{kind==='papers'&&<option value="set_status">调整阅读状态</option>}{kind==='cards'&&<option value="export">导出所选卡片</option>}<option value="trash">移入回收站</option></select></label>
  {(action==='add_tag'||action==='remove_tag')&&<label>标签<select value={tagId} onChange={e=>setTagId(e.target.value)}><option value="">请选择</option>{tags.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}</select></label>}
  {action==='add_project'&&<label>研究项目<select value={projectId} onChange={e=>setProjectId(e.target.value)}><option value="">请选择</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
  {action==='set_status'&&<label>目标状态<select value={status} onChange={e=>setStatus(e.target.value)}>{Object.entries(statusLabels).map(([key,value])=><option key={key} value={key}>{value}</option>)}</select></label>}
  {action==='export'&&<label>导出格式<select value={format} onChange={e=>setFormat(e.target.value)}><option value="markdown">Markdown</option><option value="latex">LaTeX</option><option value="bibtex">BibTeX</option></select></label>}
  <p className="note">任一所选资料或目标不可访问时，整批拒绝；不会处理未勾选的资料。</p><button type="button" disabled={busy||!selected.length} onClick={()=>void execute()}>{busy?'处理中':'执行所选操作'}</button>{message&&<p role="status">{message}</p>}
 </section>
}
