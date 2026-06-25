import React, { useEffect, useMemo, useState } from 'react'
import { getDimension } from '../api.js'

// 场景视图:按章分组列出场景,标注叙事类型、地点、功能标签、首尾原文。
// 功能标签可点击 → 跨章筛选出含同标签的场景。
// 数据源 /api/dimension/scenes(= global/scenes.json:{chapters:[{chapter,scenes:[...]}]})。
const TYPE_COLOR = {
  现实叙述: '#6f9b8e', 回忆: '#b8884a', 内心独白: '#9a7db8', 动作: '#a8332a',
}

// 取场景的功能标签(C2a 写入 s.tags.function;清单外的在 s.tags.function_novel)。
function fnTags(s) {
  const t = s.tags || {}
  return [...(t.function || []), ...(t.function_novel || [])]
}

export default function Scenes({ novel }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [activeTag, setActiveTag] = useState(null)   // 当前筛选的功能标签

  useEffect(() => {
    setActiveTag(null); setData(null); setErr(null)
    getDimension('scenes', novel).then(setData).catch(e => setErr(String(e)))
  }, [novel])

  const chapters = data?.chapters || []

  // 所有出现过的功能标签 + 计数(供筛选条显示;也判断是否有标签可用)
  const tagCounts = useMemo(() => {
    const c = {}
    for (const ch of chapters)
      for (const s of (ch.scenes || []))
        for (const t of fnTags(s)) c[t] = (c[t] || 0) + 1
    return c
  }, [chapters])

  // 应用筛选:只保留含 activeTag 的场景;空章节整章隐藏
  const shownChapters = useMemo(() => {
    if (!activeTag) return chapters
    return chapters
      .map(ch => ({ ...ch, scenes: (ch.scenes || []).filter(s => fnTags(s).includes(activeTag)) }))
      .filter(ch => ch.scenes.length > 0)
  }, [chapters, activeTag])

  if (err) return <div className="empty" style={{ padding: 24 }}>加载失败:{err}</div>
  if (!data) return <div className="hint">加载场景…</div>
  if (!chapters.length) return <div className="empty" style={{ padding: 24 }}>暂无场景</div>

  const matchCount = activeTag
    ? shownChapters.reduce((n, ch) => n + ch.scenes.length, 0) : 0

  return (
    <div className="view-scroll">
      {/* 筛选状态条:仅当有功能标签数据时显示 */}
      {Object.keys(tagCounts).length > 0 && (
        <div className="sc-filterbar">
          {activeTag ? (
            <>
              <span className="sc-fb-label">筛选:</span>
              <span className="sc-tag sc-tag-fn active">{activeTag}</span>
              <span className="sc-fb-count">{matchCount} 个场景</span>
              <button className="sc-fb-clear" onClick={() => setActiveTag(null)}>清除筛选</button>
            </>
          ) : (
            <span className="sc-fb-hint">点击场景上的功能标签可筛选同类场景</span>
          )}
        </div>
      )}

      {shownChapters.map(ch => (
        <section key={ch.chapter} className="sc-chapter">
          <h3 className="sc-ch-title">第 {ch.chapter} 章 · {(ch.scenes || []).length} 场景</h3>
          <div className="sc-grid">
            {(ch.scenes || []).map(s => {
              const tags = fnTags(s)
              return (
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
                  {tags.length > 0 && (
                    <div className="sc-tags">
                      {tags.map((t, i) => (
                        <button key={i}
                          className={'sc-tag sc-tag-fn' + (t === activeTag ? ' active' : '')}
                          onClick={() => setActiveTag(t === activeTag ? null : t)}
                          title={t === activeTag ? '取消筛选' : `筛选「${t}」场景`}>
                          {t}
                        </button>
                      ))}
                    </div>
                  )}
                  {(s.start_text || s.end_text) && (
                    <div className="sc-anchor">
                      <span>「{s.start_text}」</span>
                      <span className="sc-arrow">→</span>
                      <span>「{s.end_text}」</span>
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}
