import { lazy, Suspense, useEffect, useState, type FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import { Workspace } from './Workspace'
const PublicShare=lazy(()=>import('./Shares').then(m=>({default:m.PublicShare})))

function App() {
  const [user, setUser] = useState<{display_name: string; email: string} | null>(null)
  const [loading, setLoading] = useState(true)
  const [register, setRegister] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/v1/auth/me', { signal: controller.signal }).then(async r => { if (r.ok) setUser(await r.json()) }).catch(() => { if (!controller.signal.aborted) setMessage('无法连接服务，请检查后端是否启动') }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage('')
    try {
      const res = await fetch(`/api/v1/auth/${register ? 'register' : 'login'}`, {method: 'POST', headers: {'Content-Type':'application/json','X-Requested-With':'zhiyan'}, body: JSON.stringify(register ? {email, password, display_name:name} : {email,password})})
      const data = await res.json()
      if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请检查输入内容')
      setPassword('')
      if (register) { setRegister(false); setMessage('注册成功，请登录') } else setUser(data)
    } catch (e) { setMessage(e instanceof Error ? e.message : '请求失败') } finally { setBusy(false) }
  }
  async function logout() {
    try { const res = await fetch('/api/v1/auth/logout', {method:'POST',headers:{'X-Requested-With':'zhiyan'}}); if (!res.ok && res.status !== 401) throw new Error(); setUser(null); setMessage('已退出登录') } catch { setMessage('退出失败，请重试') }
  }
  if(user)return <Workspace user={user} onSaved={setUser} onLogout={logout}/>
  return <main className="auth-shell"><div className="auth-panel"><header><span className="mark" aria-hidden="true">知</span><span>知研云枢</span></header><section><p className="eyebrow">YOUR RESEARCH SPACE</p>{loading ? <p>正在加载</p> : <><h1>{register ? '创建账户' : <>欢迎回到<br/>你的研究空间</>}</h1><p className="description">让文献、思考与灵感，在这里连接</p><form onSubmit={submit}>{register && <label>姓名<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)} /></label>}<label>邮箱<input required type="email" autoComplete="email" value={email} onChange={e=>setEmail(e.target.value)} /></label><label>密码<input required type="password" minLength={register ? 10 : 1} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'} value={password} onChange={e=>setPassword(e.target.value)} /></label>{register && <p className="note">密码至少 10 个字符</p>}<button disabled={busy}>{busy ? '处理中' : register ? '注册' : '登录'}</button></form><button className="link" onClick={()=>{setRegister(!register); setMessage(''); setPassword('')}}>{register ? '已有账户？登录' : '没有账户？注册'}</button></>}{message && <p role="status" className="feedback">{message}</p>}</section><footer>文献 · 知识卡片 · 工作流</footer></div><div className="auth-aside"><span>NOTES FOR<br/>CURIOUS MINDS.</span><div>让每一次阅读<br/>都成为新的开始 <b>↗</b></div></div></main>
}

const shareToken = new URLSearchParams(window.location.hash.slice(1)).get('share')
createRoot(document.getElementById('root')!).render(shareToken ? <Suspense fallback={<p role="status">正在加载分享…</p>}><PublicShare token={shareToken} /></Suspense> : <App />)
