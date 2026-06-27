import React, { useEffect, useMemo, useState } from 'react'
import { getDimension } from '../api.js'

// 场景视图:按章分组列出场景,标注叙事类型、地点、功能标签、动作标签、首尾原文。
// 功能/动作标签均可点击 → 跨章筛选出含同标签的场景。
// 数据源 /api/dimension/scenes(= global/scenes.json:{chapters:[{chapter,scenes:[...]}]})。
const TYPE_COLOR = {
  现实叙述: '#6f9b8e', 回忆: '#b8884a', 内心独白: '#9a7db8', 动作: '#a8332a',
}

// 取场景的功能标签(写入 s.tags.function;清单外的在 s.tags.function_novel)。
function fnTags(s) {
  const t = s.tags || {}
  return [...(t.function || []), ...(t.function_novel || [])]
}
// 取场景的动作标签(写入 s.tags.action;清单外的在 s.tags.action_novel)。
function acTags(s) {
  const t = s.tags || {}
  return [...(t.action || []), ...(t.action_novel || [])]
}
// 场景的全部可筛选标签(功能 + 动作),用于筛选命中判断。
function allTags(s) {
  return [...fnTags(s), ...acTags(s)]
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

  // 所有出现过的标签 + 计数(功能 + 动作;供筛选条显示;也判断是否有标签可用)
  const tagCounts = useMemo(() => {
    const c = {}
    for (const ch of chapters)
      for (const s of (ch.scenes || []))
        for (const t of allTags(s)) c[t] = (c[t] || 0) + 1
    return c
  }, [chapters])

  // 应用筛选:只保留含 activeTag 的场景(功能或动作标签任一命中);空章节整章隐藏
  const shownChapters = useMemo(() => {
    if (!activeTag) return chapters
    return chapters
      .map(ch => ({ ...ch, scenes: (ch.scenes || []).filter(s => allTags(s).includes(activeTag)) }))
      .filter(ch => ch.scenes.length > 0)
  }, [chapters, activeTag])

  if (err) return <div className="empty" style={{ padding: 24 }}>加载失败:{err}</div>
  if (!data) return <div className="hint">加载场景…</div>
  if (!chapters.length) return <div className="empty" style={{ padding: 24 }}>暂无场景</div>

  const matchCount = activeTag
    ? shownChapters.reduce((n, ch) => n + ch.scenes.length, 0) : 0
  // 当前激活标签是否属于动作标签集合(决定筛选条 chip 配色;同名极少见,按动作优先判定足够)
  const acIsActive = useMemo(() => {
    if (!activeTag) return false
    for (const ch of chapters)
      for (const s of (ch.scenes || []))
        if (acTags(s).includes(activeTag)) return true
    return false
  }, [chapters, activeTag])

  return (
    <div className="view-scroll">
      {/* 筛选状态条:仅当有功能标签数据时显示 */}
      {Object.keys(tagCounts).length > 0 && (
        <div className="sc-filterbar">
          {activeTag ? (
            <>
              <span className="sc-fb-label">筛选:</span>
              <span className={'sc-tag ' + (acIsActive ? 'sc-tag-ac' : 'sc-tag-fn') + ' active'}>{activeTag}</span>
              <span className="sc-fb-count">{matchCount} 个场景</span>
              <button className="sc-fb-clear" onClick={() => setActiveTag(null)}>清除筛选</button>
            </>
          ) : (
            <span className="sc-fb-hint">点击场景上的功能/动作标签可筛选同类场景</span>
          )}
        </div>
      )}

      {shownChapters.map(ch => (
        <section key={ch.chapter} className="sc-chapter">
          <h3 className="sc-ch-title">第 {ch.chapter} 章 · {(ch.scenes || []).length} 场景</h3>
          <div className="sc-grid">
            {(ch.scenes || []).map(s => {
              const ftags = fnTags(s)
              const atags = acTags(s)
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
                  {(ftags.length > 0 || atags.length > 0) && (
                    <div className="sc-tags">
                      {ftags.map((t, i) => (
                        <button key={'f' + i}
                          className={'sc-tag sc-tag-fn' + (t === activeTag ? ' active' : '')}
                          onClick={() => setActiveTag(t === activeTag ? null : t)}
                          title={t === activeTag ? '取消筛选' : `筛选「${t}」功能场景`}>
                          {t}
                        </button>
                      ))}
                      {atags.map((t, i) => (
                        <button key={'a' + i}
                          className={'sc-tag sc-tag-ac' + (t === activeTag ? ' active' : '')}
                          onClick={() => setActiveTag(t === activeTag ? null : t)}
                          title={t === activeTag ? '取消筛选' : `筛选「${t}」动作场景`}>
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
