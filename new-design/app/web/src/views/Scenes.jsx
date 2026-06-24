import React, { useEffect, useState } from 'react'
import { getDimension } from '../api.js'

// 场景视图:按章分组列出场景,标注叙事类型(现实/回忆/独白/动作)、地点、首尾原文。
// 数据源 /api/dimension/scenes(= global/scenes.json:{chapters:[{chapter,scenes:[...]}]})。
const TYPE_COLOR = {
  现实叙述: '#6f9b8e', 回忆: '#b8884a', 内心独白: '#9a7db8', 动作: '#a8332a',
}

export default function Scenes({ novel }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    getDimension('scenes', novel).then(setData).catch(e => setErr(String(e)))
  }, [novel])

  if (err) return <div className="empty" style={{ padding: 24 }}>加载失败:{err}</div>
  if (!data) return <div className="hint">加载场景…</div>
  const chapters = data.chapters || []
  if (!chapters.length) return <div className="empty" style={{ padding: 24 }}>暂无场景</div>

  return (
    <div className="view-scroll">
      {chapters.map(ch => (
        <section key={ch.chapter} className="sc-chapter">
          <h3 className="sc-ch-title">第 {ch.chapter} 章 · {(ch.scenes || []).length} 场景</h3>
          <div className="sc-grid">
            {(ch.scenes || []).map(s => (
              <article key={s.index} className="sc-card">
                <div className="sc-head">
                  <span className="sc-idx">{s.index}</span>
                  <span className="sc-type" style={{ background: TYPE_COLOR[s.type] || '#666' }}>
                    {s.type}
                  </span>
                  {s.location && <span className="sc-loc">{s.location}</span>}
                </div>
                <div className="sc-title">{s.title}</div>
                {s.summary && <div className="sc-sum">{s.summary}</div>}
                {(s.start_text || s.end_text) && (
                  <div className="sc-anchor">
                    <span>「{s.start_text}」</span>
                    <span className="sc-arrow">→</span>
                    <span>「{s.end_text}」</span>
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
