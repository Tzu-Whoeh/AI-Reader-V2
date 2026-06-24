import React, { useEffect, useMemo, useState } from 'react'
import { getEvents, getDimension } from '../api.js'

// 时间线视图:按 story_order(故事真实序)排列事件,标注倒叙、故事线、参与人物。
// 数据源 /api/events(投影 timeline.global_events)。
export default function Timeline({ novel }) {
  const [data, setData] = useState(null)
  const [charNames, setCharNames] = useState({})
  const [order, setOrder] = useState('story') // story | narrative
  const [err, setErr] = useState(null)

  useEffect(() => {
    getEvents(novel).then(setData).catch(e => setErr(String(e)))
    // 取人物全局名,用于把 global_participants 的 id 渲染成名字
    getDimension('characters', novel)
      .then(d => {
        const m = {}
        for (const g of d.global_characters || []) m[g.global_id] = g.canonical
        setCharNames(m)
      })
      .catch(() => {})
  }, [novel])

  const events = useMemo(() => {
    const ev = [...(data?.events || [])]
    const key = order === 'story' ? 'story_order' : 'narrative_order'
    ev.sort((a, b) => (a[key] ?? 0) - (b[key] ?? 0))
    return ev
  }, [data, order])

  if (err) return <div className="empty" style={{ padding: 24 }}>加载失败:{err}</div>
  if (!data) return <div className="hint">加载时间线…</div>
  if (!events.length) return <div className="empty" style={{ padding: 24 }}>暂无事件</div>

  return (
    <div className="view-scroll">
      <div className="view-bar">
        <span>共 {events.length} 事件</span>
        <span className="seg">
          <button className={order === 'story' ? 'active' : ''} onClick={() => setOrder('story')}>
            故事序
          </button>
          <button className={order === 'narrative' ? 'active' : ''} onClick={() => setOrder('narrative')}>
            叙述序
          </button>
        </span>
      </div>
      <ol className="timeline">
        {events.map(e => (
          <li key={e.event_id} className={e.is_flashback ? 'tl-item flashback' : 'tl-item'}>
            <div className="tl-dot" />
            <div className="tl-body">
              <div className="tl-head">
                <span className="tl-ord">#{order === 'story' ? e.story_order : e.narrative_order}</span>
                {e.is_flashback && <span className="tl-flag">倒叙</span>}
                {e.storyline && <span className="tl-line">{e.storyline}</span>}
                <span className="tl-ch">第{e.chapter}章</span>
              </div>
              <div className="tl-desc">{e.desc}</div>
              {(e.global_participants || []).length > 0 && (
                <div className="tl-parts">
                  {e.global_participants.map(p => (
                    <span key={p} className="tl-chip">{charNames[p] || `#${p}`}</span>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
