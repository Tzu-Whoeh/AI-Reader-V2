import React, { useEffect, useState } from 'react'
import { getNode } from '../api.js'

// 正则元字符转义(修旧前端 new RegExp(term) 未转义的隐患)。
function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function highlight(sentence, term) {
  if (!term) return sentence
  const parts = sentence.split(new RegExp(`(${escapeRe(term)})`, 'g'))
  return parts.map((p, i) =>
    p === term ? <b key={i}>{p}</b> : <React.Fragment key={i}>{p}</React.Fragment>
  )
}

export default function SidePanel({ selected, typeNames, novel }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!selected) { setData(null); return }
    setLoading(true); setData(null)
    getNode(selected.type, selected.id, novel)
      .then(setData)
      .catch(e => { console.error(e); setData({ occurrences: [] }) })
      .finally(() => setLoading(false))
  }, [selected])

  if (!selected) {
    return (
      <div className="side">
        <div className="hint">点击左侧任一节点<br />查看详情与原文出处</div>
      </div>
    )
  }

  const occ = data?.occurrences || []
  return (
    <div className="side">
      <h2>{selected.label}</h2>
      <div className="meta">
        {typeNames[selected.type]} · {loading ? '加载原文出处…' : `${occ.length} 处原文出处`}
      </div>
      {!loading && occ.length === 0 && <div className="empty">未在原文中定位到出处</div>}
      {occ.map((o, i) => (
        <div className="occ" key={i}>
          <span className="ch">第{o.chapter}章 · 「{o.term}」</span>
          {highlight(o.sentence, o.term)}
        </div>
      ))}
    </div>
  )
}
