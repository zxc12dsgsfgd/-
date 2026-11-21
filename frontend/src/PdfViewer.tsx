import { useEffect, useRef, useState, type FormEvent } from 'react'
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist/build/pdf.min.mjs'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = workerUrl

export function PdfViewer({url,paperId}:{url:string;paperId:number}) {
  const canvas=useRef<HTMLCanvasElement>(null), textLayer=useRef<HTMLDivElement>(null), reader=useRef<HTMLDivElement>(null)
  const [page,setPage]=useState(1),[count,setCount]=useState(0),[error,setError]=useState(''),[loading,setLoading]=useState(true)
  const [readerWidth,setReaderWidth]=useState(0)
  const [excerpt,setExcerpt]=useState(''),[sourcePage,setSourcePage]=useState(1),[title,setTitle]=useState(''),[content,setContent]=useState(''),[kind,setKind]=useState('concept'),[formOpen,setFormOpen]=useState(false),[saving,setSaving]=useState(false),[message,setMessage]=useState('')
  useEffect(()=>{const node=reader.current;if(!node)return;const observer=new ResizeObserver(entries=>setReaderWidth(Math.floor(entries[0].contentRect.width)));observer.observe(node);return()=>observer.disconnect()},[])
  useEffect(()=>{
    let active=true
    setLoading(true);setError('')
    const task=getDocument({url,withCredentials:true})
    let renderTask: {cancel:()=>void;promise:Promise<void>}|undefined
    let layer: TextLayer|undefined
    const container=textLayer.current
    if(container)container.replaceChildren()
    task.promise.then(async pdf=>{
      if(!active)return
      setCount(pdf.numPages)
      const p=await pdf.getPage(page)
      if(!active||!canvas.current||!container)return
      const base=p.getViewport({scale:1});const scale=readerWidth>0?Math.min(1.25,readerWidth/base.width):1.25
      const viewport=p.getViewport({scale}); const ctx=canvas.current.getContext('2d')
      if(!ctx)throw new Error('无法创建绘图区域')
      canvas.current.width=viewport.width;canvas.current.height=viewport.height
      const shell=container.parentElement!
      shell.style.width=`${viewport.width}px`;shell.style.height=`${viewport.height}px`
      shell.style.setProperty('--total-scale-factor',String(viewport.scale))
      renderTask=p.render({canvas:canvas.current,canvasContext:ctx,viewport})
      layer=new TextLayer({textContentSource:p.streamTextContent(),container,viewport})
      await Promise.all([renderTask.promise,layer.render()])
      if(active)setLoading(false)
    }).catch(()=>{if(active){setError('PDF 无法预览，请确认文件完整或下载后使用其他阅读器打开');setLoading(false)}})
    return ()=>{active=false;renderTask?.cancel();layer?.cancel();void task.destroy();container?.replaceChildren()}
  },[url,page,readerWidth])
  function useSelection(){
    const selection=window.getSelection()
    if(!selection||selection.isCollapsed||!textLayer.current||!selection.anchorNode||!selection.focusNode||!textLayer.current.contains(selection.anchorNode)||!textLayer.current.contains(selection.focusNode)){setMessage('请先在当前 PDF 页面选中文字，或手动输入摘录。');return}
    const value=selection.toString().trim()
    if(!value){setMessage('未检测到文字，请手动输入摘录。');return}
    if(value.length>60000){setMessage('选中文字超过 60000 字，请缩短后重试。');return}
    setExcerpt(value);setSourcePage(page);setFormOpen(true);setMessage('已载入所选文字，请核对并填写卡片。')
  }
  function manual(){setExcerpt('');setSourcePage(page);setFormOpen(true);setMessage('可手动填写摘录；扫描件可能无法选中文字。')}
  async function save(event:FormEvent){
    event.preventDefault();setSaving(true);setMessage('')
    try{
      const response=await fetch('/api/v1/cards',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'zhiyan'},body:JSON.stringify({title,type:kind,content,paper_id:paperId,source_page:sourcePage,source_excerpt:excerpt||null,note:null})})
      if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(typeof data.detail==='string'?data.detail:'保存失败，请检查输入')}
      setTitle('');setContent('');setExcerpt('');setFormOpen(false);setMessage('卡片已保存，可在知识卡片中查看。');window.dispatchEvent(new Event('zhiyan:cards-changed'))
    }catch(e){setMessage(e instanceof Error?e.message:'保存失败')}finally{setSaving(false)}
  }
  return <div ref={reader} className="pdf-reader"><div className="actions"><button type="button" className="secondary" disabled={page<=1||loading} onClick={()=>setPage(p=>p-1)}>上一页</button><span>第 {page} / {count||'—'} 页</span><button type="button" className="secondary" disabled={page>=count||loading} onClick={()=>setPage(p=>p+1)}>下一页</button><a href={url} target="_blank" rel="noreferrer">在新窗口打开</a></div>{loading&&<p>正在加载 PDF</p>}{error&&<p role="alert">{error}</p>}<div className="pdf-page"><canvas ref={canvas} aria-label={`PDF 第 ${page} 页`} /><div ref={textLayer} className="pdf-text-layer" /></div><p className="note">在页面中选中文字后创建卡片；如果无法选择，可手动输入。</p><div className="actions"><button type="button" className="secondary" disabled={loading||!!error} onMouseDown={e=>e.preventDefault()} onClick={useSelection}>用选中文字建卡</button><button type="button" className="secondary" onClick={manual}>手动建卡</button></div>{formOpen&&<form onSubmit={save} className="pdf-card-form"><h4>创建来源卡片</h4><p>来源文献 {paperId} · 第 {sourcePage} 页</p><label>卡片标题<input required maxLength={500} value={title} onChange={e=>setTitle(e.target.value)}/></label><label>类型<select value={kind} onChange={e=>setKind(e.target.value)}><option value="concept">概念</option><option value="method">方法</option><option value="conclusion">结论</option><option value="question">问题</option><option value="idea">想法</option><option value="other">其他</option></select></label><label>卡片正文<textarea required maxLength={60000} value={content} onChange={e=>setContent(e.target.value)}/></label><label>来源摘录<textarea maxLength={60000} value={excerpt} onChange={e=>setExcerpt(e.target.value)}/></label><div className="actions"><button disabled={saving}>{saving?'保存中':'保存卡片'}</button><button type="button" className="secondary" onClick={()=>setFormOpen(false)}>取消</button></div></form>}{message&&<p role="status">{message}</p>}</div>
}
