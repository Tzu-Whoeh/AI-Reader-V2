import React, { useEffect, useMemo, useState } from 'react'
import { getChapters, getReader, getNode, getDimension } from '../api.js'

const TC = { character: '#a8332a', item: '#b8884a', location: '#6f9b8e' }
const TN = { character: '人物', item: '物品', location: '地点' }

function renderText(text, highlights, onPick) {
  const out = []
  let cur = 0
  highlights.forEach((h, i) => {
    if (h.start > cur) out.push(<span key={'t' + i}>{text.slice(cur, h.start)}</span>)
    out.push(
      <mark
        key={'h' + i}
        className="hl"
        style={{ '--hc': TC[h.type] || '#888' }}
        onClick={() => onPick({ type: h.type, id: h.global_id, label: h.label })}
        title={`${TN[h.type] || h.type}:${h.label}`}
      >
        {text.slice(h.start, h.end)}
      </mark>
    )
    cur = h.end
  })
  if (cur < text.length) out.push(<span key="tail">{text.slice(cur)}</span>)
  return out
}

export default function Reader({ novel, novels = [], onPickNovel }) {
  const [chapters, setChapters] = useState([])
  const [ch, setCh] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [picked, setPicked] = useState(null)
  const [detail, setDetail] = useState(null)
  const [dims, setDims] = useState({})
  const [err, setErr] = useState(null)
  const [chOpen, setChOpen] = useState(false)   // 窄屏章节抽屉

  // 小说变化 → 重取章节,缓存清空
  useEffect(() => {
    setErr(null); setData(null); setPicked(null); setDetail(null); setDims({}); setCh(null)
    if (!novel) { setChapters([]); return }
    getChapters(novel)
      .then(d => {
        setChapters(d.chapters || [])
        setCh((d.chapters || []).length ? d.chapters[0] : null)
      })
      .catch(e => setErr(String(e)))
  }, [novel])

  useEffect(() => {
    if (ch == null || !novel) return
    setLoading(true); setData(null); setPicked(null); setDetail(null)
    getReader(ch, novel).then(setData).catch(e => setErr(String(e))).finally(() => setLoading(false))
  }, [ch, novel])

  useEffect(() => {
    if (!picked) { setDetail(null); return }
    const dimName = picked.type === 'character' ? 'characters'
      : picked.type === 'item' ? 'items' : 'locations'
    const ensureDim = dims[dimName]
      ? Promise.resolve(dims[dimName])
      : getDimension(dimName, novel).then(d => { setDims(s => ({ ...s, [dimName]: d })); return d })
    Promise.all([ensureDim, getNode(picked.type, picked.id, novel)])
      .then(([dim, node]) => {
        const listKey = picked.type === 'character' ? 'global_characters'
          : picked.type === 'item' ? 'global_items' : 'global_locations'
        const ent = (dim[listKey] || []).find(g => g.global_id === picked.id)
        setDetail({ ent, node })
      })
      .catch(e => setErr(String(e)))
  }, [picked]) // eslint-disable-line


  // 窄屏:底部弹层/抽屉打开时,用 overflow:hidden 锁背景滚动(不挪动 body,
  // 避免 position:fixed 与 #root:100vh 冲突导致整页移出视口变黑)。关闭即恢复,滚动位置不丢。
  useEffect(() => {
    if (typeof document === 'undefined') return
    const open = !!picked || chOpen
    const b = document.body
    const prev = b.style.overflow
    if (open) b.style.overflow = 'hidden'
    return () => { b.style.overflow = prev || '' }
  }, [picked, chOpen])

  // 上一章/下一章(按 chapters 数组定位,兼容非连续章号;头尾为 null)
  const navAdj = useMemo(() => {
    const i = chapters.indexOf(ch)
    if (i < 0) return { prev: null, next: null }
    return {
      prev: i > 0 ? chapters[i - 1] : null,
      next: i < chapters.length - 1 ? chapters[i + 1] : null,
    }
  }, [chapters, ch])
  const goCh = (c) => { if (c != null) { setCh(c); window.scrollTo(0, 0) } }

  const counts = useMemo(() => {
    if (!data?.highlights) return {}
    const c = {}
    for (const h of data.highlights) c[h.type] = (c[h.type] || 0) + 1
    return c
  }, [data])

  return (
    <div className={'reader' + (chOpen ? ' ch-open' : '') + (picked ? ' detail-open' : '')}>
      <button className="reader-ch-toggle" onClick={() => setChOpen(o => !o)} aria-label="章节列表">☰ 章节</button>
      {(chOpen || picked) && <div className="reader-overlay" onClick={() => { setChOpen(false); setPicked(null) }} />}
      <aside className="reader-chs">
        <div className="rc-title">小说</div>
        <select className="novel-sel" value={novel || ''}
          onChange={e => onPickNovel && onPickNovel(e.target.value || null)}>
          {!novels.length && <option value="">(无)</option>}
          {novels.map(n => (
            <option key={n.slug} value={n.slug}>
              {n.novel_name}{n.stage && n.stage !== 'done' ? ` (${n.stage})` : ''}
            </option>
          ))}
        </select>

        <div className="rc-title" style={{ marginTop: 16 }}>章节</div>
        {chapters.map(c => (
          <button key={c} className={c === ch ? 'active' : ''} onClick={() => { setCh(c); setChOpen(false) }}>
            第 {c} 章
          </button>
        ))}
        {novel && !chapters.length && <div className="empty">无可读章节</div>}
        {!novel && <div className="empty">请先选择小说</div>}
      </aside>

      <main className="reader-text">
        {err && <div className="empty">加载失败:{err}</div>}
        {loading && <div className="hint">加载原文…</div>}
        {data && data.text == null && (
          <div className="empty">{data.error || '该章原文不可用'}</div>
        )}
        {data && data.text != null && (
          <>
            <div className="rt-bar">
              第 {data.chapter} 章 · 高亮 {' '}
              {Object.keys(counts).map(t => (
                <span key={t} className="rt-cnt" style={{ color: TC[t] }}>
                  {TN[t]} {counts[t]}
                </span>
              ))}
            </div>
            <article className="rt-body">{renderText(data.text, data.highlights, setPicked)}</article>
            <nav className="rt-nav">
              {navAdj.prev != null
                ? <button className="rt-nav-prev" onClick={() => goCh(navAdj.prev)}>← 第 {navAdj.prev} 章</button>
                : <span className="rt-nav-edge">已是第一章</span>}
              {navAdj.next != null
                ? <button className="rt-nav-next" onClick={() => goCh(navAdj.next)}>第 {navAdj.next} 章 →</button>
                : <span className="rt-nav-edge">已是最后一章</span>}
            </nav>
          </>
        )}
      </main>

      <aside className="reader-detail">
        <button className="reader-detail-close" onClick={() => setPicked(null)} aria-label="关闭">×</button>
        {!picked && <div className="hint">点击高亮的<br />人物 / 物品 / 地点<br />查看属性</div>}
        {picked && !detail && <div className="hint">加载属性…</div>}
        {detail && (
          <>
            <h2>{detail.ent?.canonical || picked.label}</h2>
            <div className="meta" style={{ color: TC[picked.type] }}>{TN[picked.type]}</div>
            {detail.ent?.all_names?.length > 1 && (
              <div className="d-row"><span className="d-k">别名</span>{detail.ent.all_names.join('、')}</div>
            )}
            {detail.ent?.members?.length > 0 && (
              <div className="d-row"><span className="d-k">出现章</span>
                {[...new Set(detail.ent.members.map(m => m.chapter))].join('、')}</div>
            )}
            <div className="d-row"><span className="d-k">原文出处</span>{detail.node?.occurrences?.length || 0} 处</div>
            <div className="occ-list">
              {(detail.node?.occurrences || []).slice(0, 30).map((o, i) => (
                <div className="occ" key={i}>
                  <span className="ch">第{o.chapter}章 · 「{o.term}」</span>{o.sentence}
                </div>
              ))}
            </div>
          </>
        )}
      </aside>
    </div>
  )
}