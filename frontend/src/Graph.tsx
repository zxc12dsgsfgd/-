import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Node={id:number;title:string;type:string}
type Edge={id:number;source:number;target:number;type:string}
type GraphData={nodes:Node[];edges:Edge[];truncated:boolean}
const labels:Record<string,string>={related:'相关',supports:'支持',contradicts:'反驳',extends:'延伸'}
const headers={'Content-Type':'application/json','X-Requested-With':'zhiyan'}
export function Graph(){
 const [data,setData]=useState<GraphData>({nodes:[],edges:[],truncated:false}),[source,setSource]=useState(''),[target,setTarget]=useState(''),[kind,setKind]=useState('related'),[selected,setSelected]=useState<{title:string;content:string}|null>(null),[message,setMessage]=useState(''),[loading,setLoading]=useState(true)
 const load=useCallback(async()=>{setLoading(true);try{const r=await fetch('/api/v1/graph');if(!r.ok)throw new Error();setData(await r.json())}catch{setMessage('图谱加载失败')}finally{setLoading(false)}},[])
 useEffect(()=>{void load()},[load])
 async function create(e:FormEvent){e.preventDefault();try{const r=await fetch('/api/v1/card-relations',{method:'POST',headers,body:JSON.stringify({source_card_id:Number(source),target_card_id:Number(target),relation_type:kind})});if(!r.ok){const x=await r.json();throw new Error(typeof x.detail==='string'?x.detail:'创建失败')}setMessage('关系已创建');await load()}catch(e){setMessage(e instanceof Error?e.message:'创建失败')}}
 async function detail(id:number){try{const r=await fetch(`/api/v1/cards/${id}`);if(!r.ok)throw new Error();setSelected(await r.json())}catch{setMessage('卡片不可用')}}
 async function remove(id:number){if(!confirm('确定删除这条卡片关系？'))return;try{const r=await fetch(`/api/v1/card-relations/${id}`,{method:'DELETE',headers});if(!r.ok)throw new Error();await load()}catch{setMessage('删除关系失败')}}
 const positions=data.nodes.map((n,i)=>({id:n.id,x:120+(i%4)*180,y:55+Math.floor(i/4)*90}))
 const pos=(id:number)=>positions.find(p=>p.id===id)
 // Place both ends outside the node rectangles, leaving the arrowhead visible.
 function edgeEndpoints(a:{x:number;y:number},b:{x:number;y:number}) {
  const dx=b.x-a.x, dy=b.y-a.y
  const nodeHalfWidth=65, nodeHalfHeight=18, gap=3
  const offset=Math.min(
   dx===0 ? Infinity : (nodeHalfWidth+gap)/Math.abs(dx),
   dy===0 ? Infinity : (nodeHalfHeight+gap)/Math.abs(dy),
  )
  return {x1:a.x+dx*offset,y1:a.y+dy*offset,x2:b.x-dx*offset,y2:b.y-dy*offset}
 }
 return <section className="papers"><h2>知识图谱</h2><p className="note">关系有方向，来源卡片指向目标卡片</p><form onSubmit={create}><label>来源卡片<select required value={source} onChange={e=>setSource(e.target.value)}><option value="">选择卡片</option>{data.nodes.map(n=><option key={n.id} value={n.id}>{n.title}（{n.id}）</option>)}</select></label><label>关系<select value={kind} onChange={e=>setKind(e.target.value)}>{Object.entries(labels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label><label>目标卡片<select required value={target} onChange={e=>setTarget(e.target.value)}><option value="">选择卡片</option>{data.nodes.map(n=><option key={n.id} value={n.id}>{n.title}（{n.id}）</option>)}</select></label><button>建立关系</button></form><button type="button" className="secondary" onClick={()=>void load()}>刷新图谱</button>{loading?<p>正在加载</p>:data.nodes.length===0?<p>暂无卡片，创建卡片后可建立关系</p>:<div className="graph-scroll"><svg role="img" aria-label="卡片关联图谱" width="800" height={Math.max(180,Math.ceil(data.nodes.length/4)*90+40)}><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#647771"/></marker></defs>{data.edges.map(e=>{const a=pos(e.source),b=pos(e.target);if(!a||!b)return null;const ends=edgeEndpoints(a,b);return <g key={e.id}><line {...ends} stroke="#647771" markerEnd="url(#arrow)"/><text x={(a.x+b.x)/2} y={(a.y+b.y)/2-6}>{labels[e.type]}</text></g>})}{data.nodes.map(n=>{const p=pos(n.id)!;return <g key={n.id} role="button" tabIndex={0} aria-label={`查看卡片 ${n.title}`} onClick={()=>void detail(n.id)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();void detail(n.id)}}}><rect x={p.x-65} y={p.y-18} width="130" height="36" rx="4" fill="#e7ece9" stroke="#315e54"/><text x={p.x} y={p.y+5} textAnchor="middle">{n.title.length>12?n.title.slice(0,12)+'…':n.title}</text></g>})}</svg></div>}{data.truncated&&<p>数据较多，当前最多显示最近 200 张卡片和 500 条关系</p>}{data.edges.map(e=><p key={e.id}>{data.nodes.find(n=>n.id===e.source)?.title} → {labels[e.type]} → {data.nodes.find(n=>n.id===e.target)?.title} <button className="link" onClick={()=>void remove(e.id)}>删除关系</button></p>)}{selected&&<div><h3>{selected.title}</h3><p>{selected.content}</p><button className="secondary" onClick={()=>setSelected(null)}>关闭</button></div>}{message&&<p role="status">{message}</p>}</section>
}
