import { useState } from 'react'

type Paper = {title:string; authors:string[]; year:number|null; doi:string|null; venue:string|null; abstract:string|null; source_url:string|null; bibtex:string|null; status:string}
type Item = {paper:Paper;duplicates:{id:number;title:string}[];batch_duplicates:number[]}
const headers = {'Content-Type':'application/json','X-Requested-With':'zhiyan'}

export function BatchImport({onImported}:{onImported:()=>void}) {
  const [raw,setRaw]=useState(''),[items,setItems]=useState<Item[]>([]),[selected,setSelected]=useState<number[]>([]),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[done,setDone]=useState<number[]>([])
  async function preview(){
    setBusy(true);setMessage('');setItems([]);setSelected([]);setDone([])
    try {
      const response=await fetch('/api/v1/papers/import/batch-preview',{method:'POST',headers,body:JSON.stringify({value:raw})})
      const data=await response.json()
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'预览失败')
      setItems(data.items);setSelected(data.items.map((_:Item,i:number)=>i));setMessage(`已解析 ${data.items.length} 条，请核对后选择导入。`)
    }catch(e){setMessage(e instanceof Error?e.message:'预览失败')}finally{setBusy(false)}
  }
  async function save(){
    setBusy(true);setMessage('');let saved=0,skipped=0;const pending:number[]=[];let failed=false
    for(const index of selected){
      const paper=items[index].paper
      try{
        const options={method:'POST',headers,body:JSON.stringify(paper)}
        let response=await fetch('/api/v1/papers',options)
        if(response.status===409){
          const data=await response.json();const matches=data.detail?.matches||[]
          if(!window.confirm(`“${paper.title}”可能重复：${matches.map((x:{title:string})=>x.title).join('、')}。仍要单独保存吗？`)){skipped++;pending.push(index);continue}
          response=await fetch('/api/v1/papers?confirm_duplicate=true',options)
        }
        if(!response.ok)throw new Error('保存失败')
        saved++;setDone(old=>[...old,index])
      }catch{failed=true;pending.push(index)}
    }
    setSelected(pending);setBusy(false);onImported();setMessage(`已导入 ${saved} 条，跳过 ${skipped} 条${failed?'；部分条目未确认保存结果，请先刷新文献库核对后再重试':''}。已导入条目不会再次勾选。`)
  }
  return <div className="paper-form"><h3>批量 BibTeX 导入</h3><p className="note">每次最多 50 条、总共 60000 字符。先预览再勾选；重复条目在保存时需要确认。记录会重建为单条 BibTeX。</p><label>粘贴 BibTeX 内容<textarea maxLength={60000} disabled={busy} value={raw} onChange={e=>{setRaw(e.target.value);setItems([]);setSelected([]);setDone([]);setMessage('')}}/></label><button type="button" className="secondary" disabled={busy||!raw.trim()} onClick={()=>void preview()}>预览批量记录</button>{items.length>0&&<div><h4>预览结果</h4>{items.map((item,index)=><article key={index}><label><input type="checkbox" disabled={busy||done.includes(index)} checked={selected.includes(index)} onChange={e=>setSelected(old=>e.target.checked?[...old,index].sort((a,b)=>a-b):old.filter(i=>i!==index))}/> {index+1}. {item.paper.title}</label><p>{item.paper.authors.join('、')||'未填写作者'}{item.paper.year?` · ${item.paper.year}`:''}{item.paper.doi?` · ${item.paper.doi}`:''}</p>{item.duplicates.length>0&&<p>已有疑似重复：{item.duplicates.map(d=>d.title).join('、')}</p>}{item.batch_duplicates.length>0&&<p>与本批第 {item.batch_duplicates.join('、')} 条可能重复</p>}</article>)}<button type="button" disabled={busy||selected.length===0} onClick={()=>void save()}>{busy?'正在导入':'导入所选记录'}</button></div>}{message&&<p role="status">{message}</p>}</div>
}
