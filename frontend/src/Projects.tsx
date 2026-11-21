import { useCallback, useEffect, useState, type FormEvent } from 'react'

type Kind = 'papers' | 'cards' | 'plans' | 'drafts'
type Item = { id: number; title?: string; name?: string; completed?: number; total?: number }
type Project = { id: number; name: string; description: string; objective: string; status: 'active' | 'completed' | 'archived'; resources: Record<Kind, Item[]>; counts: Record<Kind, number> }
const labels: Record<Kind, string> = { papers: '文献', cards: '卡片', plans: '阅读计划', drafts: '草稿' }
const kinds: Kind[] = ['papers', 'cards', 'plans', 'drafts']
const headers = { 'Content-Type': 'application/json', 'X-Requested-With': 'zhiyan' }
async function api(url: string, options?: RequestInit) {
  const response = await fetch(url, options)
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : '请求未完成') }
  return response.status === 204 ? null : response.json()
}

export function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [choices, setChoices] = useState<Record<Kind, Item[]>>({ papers: [], cards: [], plans: [], drafts: [] })
  const [more, setMore] = useState(false)
  const [selected, setSelected] = useState<number | null>(null)
  const [editing, setEditing] = useState<number | null>(null)
  const [name, setName] = useState(''), [description, setDescription] = useState(''), [objective, setObjective] = useState('')
  const [status, setStatus] = useState<Project['status']>('active')
  const [kind, setKind] = useState<Kind>('papers'), [resource, setResource] = useState('')
  const [deleting, setDeleting] = useState<number | null>(null), [message, setMessage] = useState('')
  const load = useCallback(async () => {
    try {
      const [p, papers, cards, plans, drafts] = await Promise.all([api('/api/v1/projects'), api('/api/v1/papers?limit=100'), api('/api/v1/cards?limit=100'), api('/api/v1/plans'), api('/api/v1/drafts')])
      setProjects(p); setChoices({ papers: papers.items, cards: cards.items, plans, drafts }); setMore(Boolean(papers.next_cursor || cards.next_cursor))
    } catch (error) { setMessage(error instanceof Error ? error.message : '加载失败') }
  }, [])
  useEffect(() => { void load(); const changed=()=>void load(); window.addEventListener('zhiyan:projects-changed',changed); return()=>window.removeEventListener('zhiyan:projects-changed',changed) }, [load])
  const project = projects.find(item => item.id === selected)
  function reset() { setEditing(null); setName(''); setDescription(''); setObjective(''); setStatus('active') }
  async function save(event: FormEvent) {
    event.preventDefault()
    try {
      const saved: Project = await api(editing ? `/api/v1/projects/${editing}` : '/api/v1/projects', { method: editing ? 'PUT' : 'POST', headers, body: JSON.stringify({ name, description, objective, status }) })
      setSelected(saved.id); reset(); setMessage('项目已保存'); await load()
    } catch (error) { setMessage(error instanceof Error ? error.message : '保存失败') }
  }
  async function changeLink(method: 'POST' | 'DELETE', projectId: number, type: Kind, id: number) {
    try { await api(`/api/v1/projects/${projectId}/${type}/${id}`, { method, headers }); setResource(''); setMessage(method === 'POST' ? '已关联资料' : '已移除关联，原资料仍保留'); await load() }
    catch (error) { setMessage(error instanceof Error ? error.message : '操作失败') }
  }
  async function remove(id: number) {
    try { await api(`/api/v1/projects/${id}`, { method: 'DELETE', headers }); setDeleting(null); if (selected === id) setSelected(null); setMessage('项目已移入回收站，关联资料仍保留'); window.dispatchEvent(new Event('zhiyan:trash-changed')); await load() }
    catch (error) { setMessage(error instanceof Error ? error.message : '删除失败') }
  }
  return <section className="papers"><h2>研究项目</h2><p className="note">围绕课题组织已有资料，关联不会复制或修改原资料</p><button className="secondary" onClick={() => void load()}>刷新项目与资料</button>
    <form onSubmit={save}><h3>{editing ? '编辑项目' : '创建项目'}</h3>
      <label>项目名称<input required maxLength={200} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>项目简介<textarea maxLength={20000} value={description} onChange={e => setDescription(e.target.value)} /></label>
      <label>研究目标<textarea maxLength={20000} value={objective} onChange={e => setObjective(e.target.value)} /></label>
      <label>项目状态<select value={status} onChange={e => setStatus(e.target.value as Project['status'])}><option value="active">进行中</option><option value="completed">已完成</option><option value="archived">已归档</option></select></label>
      <div className="actions"><button>保存项目</button>{editing !== null && <button type="button" className="secondary" onClick={reset}>取消编辑</button>}</div>
    </form>
    <h3>我的项目</h3>{projects.length === 0 && <p>暂无项目</p>}
    {projects.map(p => <article key={p.id}><h4>{p.name}</h4><p>{({ active: '进行中', completed: '已完成', archived: '已归档' })[p.status]} · 文献 {p.counts.papers} · 卡片 {p.counts.cards} · 计划 {p.counts.plans} · 草稿 {p.counts.drafts}</p>
      <div className="actions"><button className="secondary" onClick={() => setSelected(p.id)}>查看资料</button><button className="secondary" onClick={() => { setEditing(p.id); setName(p.name); setDescription(p.description); setObjective(p.objective); setStatus(p.status) }}>编辑</button><button className="secondary" onClick={() => setDeleting(p.id)}>删除</button></div>
      {deleting === p.id && <div><p>项目将移入回收站，关联暂时保留；不会删除原文献、卡片、计划或草稿。</p><button onClick={() => void remove(p.id)}>确认移入回收站</button><button className="secondary" onClick={() => setDeleting(null)}>取消</button></div>}</article>)}
    {project && <div><h3>{project.name} · 项目资料</h3><p>{project.description || '暂无简介'}</p><p>研究目标：{project.objective || '未填写'}</p>
      <label>资料类型<select value={kind} onChange={e => { setKind(e.target.value as Kind); setResource('') }}>{kinds.map(k => <option key={k} value={k}>{labels[k]}</option>)}</select></label>
      <label>选择资料<select value={resource} onChange={e => setResource(e.target.value)}><option value="">请选择</option>{choices[kind].filter(item => !project.resources[kind].some(existing => existing.id === item.id)).map(item => <option key={item.id} value={item.id}>{item.title || item.name}</option>)}</select></label>
      {more && <p className="note">文献和卡片选择器仅显示最近 100 条</p>}<p className="note">草稿选择器最多显示最近 100 条</p><button disabled={!resource} onClick={() => void changeLink('POST', project.id, kind, Number(resource))}>关联资料</button>
      {kinds.map(k => <div key={k}><h4>{labels[k]}</h4>{project.resources[k].length === 0 ? <p>暂无关联</p> : project.resources[k].map(item => <p key={item.id}>{item.title || item.name}{k === 'plans' && ` · 已读 ${item.completed} / ${item.total}`} <button className="secondary" onClick={() => void changeLink('DELETE', project.id, k, item.id)}>移除关联</button></p>)}</div>)}
    </div>}{message && <p role="status">{message}</p>}
  </section>
}
