import { useState, type FormEvent } from 'react'

export function Exports() {
  const [kind, setKind] = useState('cards')
  const [ids, setIds] = useState('')
  const [format, setFormat] = useState('markdown')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  async function download(event: FormEvent) {
    event.preventDefault()
    const pieces = ids.split(/[,，]/).map(s => s.trim())
    if (pieces.some(s => !/^[1-9]\d*$/.test(s) || !Number.isSafeInteger(Number(s))) || (kind === 'draft' && pieces.length !== 1)) {
      setMessage('请输入有效的编号；草稿只能选择一项。'); return
    }
    setBusy(true); setMessage('')
    try {
      const selection = kind === 'cards' ? {card_ids: pieces.map(Number)} : {draft_id: Number(pieces[0])}
      const response = await fetch('/api/v1/exports', {method:'POST', headers:{'Content-Type':'application/json','X-Requested-With':'zhiyan'}, body:JSON.stringify({format,...selection})})
      if (!response.ok) { const data = await response.json(); throw new Error(typeof data.detail === 'string' ? data.detail : '请检查选择的编号') }
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a'); link.href = url; link.download = format === 'markdown' ? 'export.md' : format === 'latex' ? 'export.tex' : 'references.bib'
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
      setMessage('文件已生成，请检查浏览器下载。')
    } catch (error) { setMessage(error instanceof Error ? error.message : '导出失败') } finally { setBusy(false) }
  }
  return <section className="papers"><h2>导出与来源</h2><p className="note">按编号选择本人卡片或草稿。参考文献来自实际关联文献或草稿中保存的文献快照；请人工核对。</p><form onSubmit={download}><label>导出内容<select value={kind} onChange={e=>{setKind(e.target.value);setIds('')}}><option value="cards">知识卡片</option><option value="draft">草稿</option></select></label><label>{kind === 'cards' ? '卡片编号（以逗号分隔，最多 50 项）' : '草稿编号'}<input required value={ids} onChange={e=>setIds(e.target.value)} /></label><label>文件格式<select value={format} onChange={e=>setFormat(e.target.value)}><option value="markdown">Markdown</option><option value="latex">LaTeX</option><option value="bibtex">BibTeX 参考文献</option></select></label><button disabled={busy}>{busy ? '正在生成' : '下载文件'}</button></form>{message && <p role="status">{message}</p>}</section>
}
