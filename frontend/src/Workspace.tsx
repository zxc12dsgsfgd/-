import { lazy, Suspense, useCallback, useEffect, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react'

const Papers=lazy(()=>import('./Papers').then(m=>({default:m.Papers})))
const Cards=lazy(()=>import('./Knowledge').then(m=>({default:m.Cards})))
const TagsManager=lazy(()=>import('./Tags').then(m=>({default:m.TagsManager})))
const Graph=lazy(()=>import('./Graph').then(m=>({default:m.Graph})))
const Workflows=lazy(()=>import('./Workflows').then(m=>({default:m.Workflows})))
const Plans=lazy(()=>import('./Plans').then(m=>({default:m.Plans})))
const AIAssistant=lazy(()=>import('./AIAssistant').then(m=>({default:m.AIAssistant})))
const Exports=lazy(()=>import('./Exports').then(m=>({default:m.Exports})))
const Shares=lazy(()=>import('./Shares').then(m=>({default:m.Shares})))
const ProfileSettings=lazy(()=>import('./ProfileSettings').then(m=>({default:m.ProfileSettings})))
const Projects=lazy(()=>import('./Projects').then(m=>({default:m.Projects})))
const PersonalBackup=lazy(()=>import('./PersonalBackup').then(m=>({default:m.PersonalBackup})))
const Trash=lazy(()=>import('./Trash').then(m=>({default:m.Trash})))
const BatchActions=lazy(()=>import('./BatchActions').then(m=>({default:m.BatchActions})))

type Profile = { display_name:string; email:string }
type Page = 'overview'|'projects'|'papers'|'cards'|'plans'|'workflow'|'ai'|'output'|'batch'|'settings'
type Dashboard = { papers_total:number; papers_by_status:Record<string,number>; cards_total:number; unread_notifications:number; recent_cards:{id:number;title:string}[] }
type Report = { week_start:string; week_end_exclusive:string; papers_added:number; cards_added:number; papers_read:number; coverage_note:string }
const pages:{id:Page;label:string;icon:string;description:string}[] = [
  {id:'overview',label:'工作台',icon:'▦',description:'研究进展与近期动态'},
  {id:'projects',label:'研究项目',icon:'▧',description:'组织课题与关联资料'},
  {id:'papers',label:'文献库',icon:'▤',description:'收集与阅读研究文献'},
  {id:'cards',label:'知识卡片',icon:'▱',description:'积累观点与连接'},
  {id:'plans',label:'阅读计划',icon:'▣',description:'安排阅读与查看进度'},
  {id:'workflow',label:'工作流',icon:'⌁',description:'规则、任务与提醒'},
  {id:'ai',label:'AI 辅助',icon:'✳',description:'生成与审核研究草稿'},
  {id:'output',label:'导出与分享',icon:'↗',description:'整理、导出和协作'},
  {id:'batch',label:'批量操作',icon:'▥',description:'批量整理文献与卡片'},
  {id:'settings',label:'设置与备份',icon:'⚙',description:'个人设置与数据管理'},
]

function NumberTween({value}:{value:number}) {
  const [display,setDisplay]=useState(value); const previous=useRef(value)
  useEffect(()=>{ const start=previous.current, delta=value-start; if(!delta)return; if(matchMedia('(prefers-reduced-motion: reduce)').matches){previous.current=value;const timer=window.setTimeout(()=>setDisplay(value),0);return()=>clearTimeout(timer)} let frame=0,begin=0; const tick=(time:number)=>{if(!begin)begin=time;const p=Math.min((time-begin)/450,1);setDisplay(Math.round(start+delta*(1-(1-p)**3)));if(p<1)frame=requestAnimationFrame(tick);else previous.current=value};frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)},[value])
  return <>{display.toLocaleString('zh-CN')}</>
}

function GlassCard({children,className='',onClick}:{children:ReactNode;className?:string;onClick?:()=>void}) {
  const ref=useRef<HTMLDivElement>(null)
  function move(event:PointerEvent<HTMLDivElement>){if(event.pointerType!=='mouse'||matchMedia('(prefers-reduced-motion: reduce)').matches)return;const box=event.currentTarget.getBoundingClientRect();const x=(event.clientX-box.left)/box.width,y=(event.clientY-box.top)/box.height;event.currentTarget.style.setProperty('--light-x',`${x*100}%`);event.currentTarget.style.setProperty('--light-y',`${y*100}%`);event.currentTarget.style.setProperty('--tilt-x',`${(0.5-y)*4}deg`);event.currentTarget.style.setProperty('--tilt-y',`${(x-0.5)*4}deg`)}
  function leave(){ref.current?.style.setProperty('--tilt-x','0deg');ref.current?.style.setProperty('--tilt-y','0deg')}
  return <div ref={ref} className={`glass-card ${className}`} onPointerMove={move} onPointerLeave={leave} onClick={event=>{if(onClick&&!(event.target as HTMLElement).closest('button, a, input, select, textarea'))onClick()}}>{children}</div>
}

function Overview({navigate}:{navigate:(p:Page)=>void}) {
  const [data,setData]=useState<Dashboard|null>(null),[report,setReport]=useState<Report|null>(null),[error,setError]=useState(''),[period,setPeriod]=useState<'all'|'week'>('all'),[open,setOpen]=useState(false),[expanded,setExpanded]=useState<string|null>(null)
  function changeExpanded(next:string|null){if(document.startViewTransition&&!matchMedia('(prefers-reduced-motion: reduce)').matches)document.startViewTransition(()=>setExpanded(next));else setExpanded(next)}
  const load=useCallback(async()=>{try{const [d,w]=await Promise.all([fetch('/api/v1/dashboard'),fetch('/api/v1/reports/weekly')]);if(!d.ok||!w.ok)throw new Error();setData(await d.json());setReport(await w.json());setError('')}catch{setError('工作台数据加载失败，请重试')}},[])
  useEffect(()=>{void load();window.addEventListener('zhiyan:papers-changed',load);window.addEventListener('zhiyan:cards-changed',load);return()=>{window.removeEventListener('zhiyan:papers-changed',load);window.removeEventListener('zhiyan:cards-changed',load)}},[load])
  const stats=period==='all'?[{label:'文献总数',value:data?.papers_total},{label:'知识卡片',value:data?.cards_total},{label:'未读提醒',value:data?.unread_notifications}]:[{label:'本周新增文献',value:report?.papers_added},{label:'本周新增卡片',value:report?.cards_added},{label:'本周已读文献',value:report?.papers_read}]
  const bars=period==='all'?[['待读',data?.papers_by_status.unread??0],['阅读中',data?.papers_by_status.reading??0],['已读',data?.papers_by_status.read??0],['已归档',data?.papers_by_status.archived??0]] as const:[['新增文献',report?.papers_added??0],['新增卡片',report?.cards_added??0],['已读文献',report?.papers_read??0]] as const
  const max=Math.max(...bars.map(x=>x[1]),1)
  const modules=[{id:'chart',label:period==='all'?'文献阅读状态':'本周研究记录'},{id:'recent',label:'最近卡片'},{id:'focus',label:'研究速览'}]
  return <><div className="overview-toolbar"><div><span className="section-kicker">YOUR RESEARCH SPACE</span><h1>研究工作台<span className="title-dot">.</span></h1><p>从阅读到思考，让每一份积累都有迹可循</p></div><div className={`period-control ${open?'is-open':''}`}><button className="period-main" aria-expanded={open} onClick={()=>setOpen(!open)}>{period==='all'?'全部时间':'本周'} <span>⌄</span></button>{open&&<div className="period-options">{([['all','全部时间'],['week','本周']] as const).map(([id,label])=><button key={id} onClick={()=>{setPeriod(id);setOpen(false)}}>{label}</button>)}</div>}</div></div>
    {error&&<p role="alert">{error} <button className="text-button" onClick={()=>void load()}>重试</button></p>}
    {!data&&!error&&<p>正在加载工作台…</p>}
    {data&&report&&<><div className="stat-grid">{stats.map((s,i)=><GlassCard className="stat-card" key={i}><div className="stat-top"><span>{s.label}</span><span className="stat-index">0{i+1}</span></div><strong><NumberTween value={s.value??0}/></strong><span className="stat-meta">{period==='all'?'当前知识库':'本周 · UTC+08:00'}</span><span className="stat-mark" aria-hidden="true">⌁</span></GlassCard>)}</div>
    <div className={`overview-grid ${expanded?'has-expanded':''}`}>
      <GlassCard onClick={()=>changeExpanded(expanded==='chart'?null:'chart')} className={`chart-card ${expanded&&expanded!=='chart'?'overview-hidden':''} ${expanded==='chart'?'expanded-card':''}`}><div className="card-heading"><div><span className="card-eyebrow">RESEARCH OVERVIEW</span><h2>{period==='all'?'文献阅读状态':'本周研究记录'}</h2><p>{period==='all'?'基于当前文献状态':'按本周实际记录统计'}</p></div><button className="expand-button" aria-label={expanded==='chart'?'收起文献图表':'放大文献图表'} onClick={()=>changeExpanded(expanded==='chart'?null:'chart')}>{expanded==='chart'?'×':'↗'}</button></div><div className="bar-chart" aria-label="研究数据图表">{bars.map(([label,value])=><div className="bar-column" key={label}><span className="bar-value">{value}</span><div className="bar-track"><span style={{'--bar-height':`${Math.max(value/max*100,value?5:0)}%`} as CSSProperties}/></div><span>{label}</span></div>)}</div><p className="chart-footnote">{period==='week'?`${report.week_start} 至 ${report.week_end_exclusive}（不含结束日）`:'统计来源于当前知识库'}</p></GlassCard>
      <GlassCard onClick={()=>changeExpanded(expanded==='focus'?null:'focus')} className={`focus-card ${expanded&&expanded!=='focus'?'overview-hidden':''} ${expanded==='focus'?'expanded-card':''}`}><div className="card-heading"><div><span className="card-eyebrow">YOUR LIBRARY</span><h2>研究速览</h2></div><button className="expand-button dark-expand" aria-label={expanded==='focus'?'收起研究速览':'放大研究速览'} onClick={()=>changeExpanded(expanded==='focus'?null:'focus')}>{expanded==='focus'?'×':'↗'}</button></div><strong><NumberTween value={data.papers_total}/></strong><p>篇文献，构成你的研究基础</p><div className="focus-divider"/><div className="focus-row"><span>待阅读</span><b>{data.papers_by_status.unread??0}</b></div><div className="focus-row"><span>阅读中</span><b>{data.papers_by_status.reading??0}</b></div><div className="focus-row"><span>已读</span><b>{data.papers_by_status.read??0}</b></div><button className="focus-link" onClick={()=>navigate('papers')}>进入文献库 <span>↗</span></button></GlassCard>
      <GlassCard onClick={()=>changeExpanded(expanded==='recent'?null:'recent')} className={`recent-card ${expanded&&expanded!=='recent'?'overview-hidden':''} ${expanded==='recent'?'expanded-card':''}`}><div className="card-heading"><div><span className="card-eyebrow">KNOWLEDGE NOTES</span><h2>最近卡片</h2><p>记录正在生长的思考</p></div><button className="expand-button" aria-label={expanded==='recent'?'收起最近卡片':'放大最近卡片'} onClick={()=>changeExpanded(expanded==='recent'?null:'recent')}>{expanded==='recent'?'×':'↗'}</button></div>{data.recent_cards.length?data.recent_cards.map((card,i)=><button className="recent-row" key={card.id} onClick={()=>navigate('cards')}><span className="recent-number">{String(i+1).padStart(2,'0')}</span><span>{card.title}</span><span>↗</span></button>):<div className="empty-recent">还没有卡片，记录你的第一个想法 <button onClick={()=>navigate('cards')}>创建卡片 ↗</button></div>}</GlassCard>
      <GlassCard className={`week-card ${expanded?'overview-hidden':''}`}><span className="card-eyebrow">THIS WEEK</span><h2>本周小结</h2><p>新增 {report.papers_added} 篇文献<br/>记录 {report.cards_added} 张卡片</p><span className="week-note">{report.coverage_note}</span><button className="week-link" onClick={()=>navigate('plans')}>查看阅读计划 ↗</button></GlassCard>
      {expanded&&<div className="thumbnail-strip" aria-label="切换放大模块">{modules.map(m=><button className={expanded===m.id?'selected':''} key={m.id} onClick={()=>changeExpanded(m.id)}><span className="thumbnail-art"/><span>{m.label}</span></button>)}<button onClick={()=>changeExpanded(null)}>返回全部模块</button></div>}
    </div></>}
  </>
}

export function Workspace({user,onSaved,onLogout}:{user:Profile;onSaved:(p:Profile)=>void;onLogout:()=>void}) {
  const [page,setPage]=useState<Page>('overview'),[palette,setPalette]=useState(false),[query,setQuery]=useState(''),[choice,setChoice]=useState(0),[hovered,setHovered]=useState<number|null>(null),[direction,setDirection]=useState<'up'|'down'>('down')
  const [visited,setVisited]=useState<Set<Page>>(()=>new Set(['overview']))
  const searchRef=useRef<HTMLInputElement>(null)
  const filtered=pages.filter(p=>`${p.label}${p.description}`.toLowerCase().includes(query.toLowerCase()))
  const navigate=useCallback((id:Page)=>{setVisited(old=>new Set(old).add(id));setPage(old=>{setDirection(pages.findIndex(p=>p.id===id)<pages.findIndex(p=>p.id===old)?'up':'down');return id});setPalette(false);setQuery('');setChoice(0);window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})},[])
  useEffect(()=>{const listener=(e:KeyboardEvent)=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setPalette(v=>!v)}if(e.key==='Escape')setPalette(false)};window.addEventListener('keydown',listener);return()=>window.removeEventListener('keydown',listener)},[])
  useEffect(()=>{if(palette)searchRef.current?.focus()},[palette])
  const selected=pages.find(p=>p.id===page)!
  return <div className="workspace-root"><main className="workspace-shell"><aside className="sidebar"><div className="brand"><span className="brand-mark">知</span><div><strong>知研云枢</strong><small>RESEARCH SPACE</small></div></div><div className="sidebar-label">WORKSPACE</div><nav className="side-nav" aria-label="主导航"><span className={`nav-pill ${direction}`} style={{'--nav-index':pages.findIndex(p=>p.id===page)} as CSSProperties}><span key={page}/></span>{pages.map(p=><button key={p.id} className={page===p.id?'active':''} aria-current={page===p.id?'page':undefined} onClick={()=>navigate(p.id)}><span className="nav-icon">{p.icon}</span><span>{p.label}</span>{page===p.id&&<span className="nav-active-dot"/>}</button>)}</nav><div className="side-bottom"><span className="avatar">{user.display_name.slice(0,1)}</span><div><strong>{user.display_name}</strong><small>个人研究空间</small></div><button aria-label="个人设置" onClick={()=>navigate('settings')}>↗</button></div></aside>
  <div className="workspace-body"><header className="workspace-header"><div className="breadcrumb"><span>知研云枢</span><span>/</span><strong>{selected.label}</strong></div><div className="header-actions"><button className="search-trigger" onClick={()=>setPalette(true)} aria-label="打开命令面板">⌕ <span>搜索功能</span><kbd>Ctrl K</kbd></button><button className="icon-button" onClick={()=>navigate('workflow')} aria-label="查看提醒">♧</button><button className="header-avatar" onClick={()=>navigate('settings')} aria-label="个人设置">{user.display_name.slice(0,1)}</button></div></header><div className="workspace-content"><Suspense fallback={<p role="status">正在加载页面…</p>}>
    <div className="page-panel" hidden={page!=='overview'}><Overview navigate={navigate}/></div>
    <div className="page-panel" hidden={page!=='projects'}>{visited.has('projects')&&<><PageTitle title="研究项目" description="围绕每一个课题，组织你的研究资料"/><Projects/></>}</div>
    <div className="page-panel" hidden={page!=='papers'}>{visited.has('papers')&&<><PageTitle title="文献库" description="收集、阅读并沉淀值得记住的文献"/><Papers/></>}</div>
    <div className="page-panel" hidden={page!=='cards'}>{visited.has('cards')&&<><PageTitle title="知识卡片" description="将零散的想法连接成知识网络"/><Cards/><TagsManager/><Graph/></>}</div>
    <div className="page-panel" hidden={page!=='plans'}>{visited.has('plans')&&<><PageTitle title="阅读计划" description="按自己的节奏，推进每一项研究"/><Plans/></>}</div>
    <div className="page-panel" hidden={page!=='workflow'}>{visited.has('workflow')&&<><PageTitle title="工作流与提醒" description="让重复的整理工作有序进行"/><Workflows/></>}</div>
    <div className="page-panel" hidden={page!=='ai'}>{visited.has('ai')&&<><PageTitle title="AI 辅助" description="以你的材料为基础，生成并审核草稿"/><AIAssistant/></>}</div>
    <div className="page-panel" hidden={page!=='output'}>{visited.has('output')&&<><PageTitle title="导出与分享" description="整理研究成果，与他人交换想法"/><Exports/><Shares/></>}</div>
    <div className="page-panel" hidden={page!=='batch'}>{visited.has('batch')&&<><PageTitle title="批量操作" description="一次整理选中的文献与卡片"/><BatchActions/></>}</div>
    <div className="page-panel" hidden={page!=='settings'}>{visited.has('settings')&&<><PageTitle title="设置与备份" description="管理个人信息，妥善保存研究资料"/><div className="settings-card"><h2>个人设置</h2><ProfileSettings profile={user} onSaved={onSaved} onLogout={onLogout}/></div><PersonalBackup/><Trash/></>}</div>
  </Suspense></div></div></main><nav className="glass-dock" aria-label="快捷导航" onPointerLeave={()=>setHovered(null)}>{pages.map((p,i)=><button key={p.id} aria-label={p.label} aria-current={page===p.id?'page':undefined} className={`${page===p.id?'active':''} ${hovered===i?'hovered':''} ${hovered!==null&&Math.abs(hovered-i)===1?'neighbor':''}`} onPointerEnter={()=>setHovered(i)} onClick={()=>navigate(p.id)}><span className="dock-tooltip">{p.label}</span><span className="dock-icon">{p.icon}</span></button>)}</nav>
  {palette&&<div className="palette-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setPalette(false)}}><div className="command-palette" role="dialog" aria-modal="true" aria-label="命令面板"><div className="palette-input"><span>⌕</span><input ref={searchRef} value={query} placeholder="搜索页面或功能…" onChange={e=>{setQuery(e.target.value);setChoice(0)}} onKeyDown={e=>{if(e.key==='ArrowDown'){e.preventDefault();setChoice(v=>Math.min(v+1,filtered.length-1))}if(e.key==='ArrowUp'){e.preventDefault();setChoice(v=>Math.max(v-1,0))}if(e.key==='Enter'&&filtered[choice])navigate(filtered[choice].id)}}/><kbd>ESC</kbd></div><div className="palette-label">跳转到</div><div role="listbox">{filtered.length?filtered.map((p,i)=><button role="option" aria-selected={choice===i} key={p.id} className={choice===i?'selected':''} onMouseEnter={()=>setChoice(i)} onClick={()=>navigate(p.id)}><span className="palette-icon">{p.icon}</span><span><strong>{highlight(p.label,query)}</strong><small>{p.description}</small></span><span>↵</span></button>):<p className="palette-empty">没有找到匹配的功能</p>}</div><div className="palette-footer">↑ ↓ 选择 <span>↵ 打开</span></div></div></div>}
  </div>
}
function highlight(label:string,query:string){const i=label.toLowerCase().indexOf(query.toLowerCase());return query&&i>=0?<>{label.slice(0,i)}<mark>{label.slice(i,i+query.length)}</mark>{label.slice(i+query.length)}</>:label}
function PageTitle({title,description}:{title:string;description:string}){return <div className="page-title"><span className="section-kicker">RESEARCH WORKSPACE</span><h1>{title}<span className="title-dot">.</span></h1><p>{description}</p></div>}
