import React, { useEffect, useState, useCallback, useRef } from 'react'
import { getSummary, getGraph, getNovels, getProgress } from './api.js'
import Filters from './components/Filters.jsx'
import GraphPane from './components/GraphPane.jsx'
import SidePanel from './components/SidePanel.jsx'
import Timeline from './views/Timeline.jsx'
import Scenes from './views/Scenes.jsx'
import Reader from './views/Reader.jsx'
import Library from './views/Library.jsx'

const TYPES = { character: '人物', item: '物品', location: '地点' }
const VIEWS = { library: '书库', graph: '图谱', reader: '阅读', timeline: '时间线', scenes: '场景' }
const ACTIVE_STAGES = new Set(['uploaded', 'splitting', 'starting', 'analyzing', 'aggregating', 'paused', 'stopping'])

// 进度百分比(与 Upload 内一致):章 × 步
function progPct(p) {
  if (!p) return 0
  if (p.stage === 'done') return 100
  if (!p.total) return 0
  const stepTotal = p.step_total || 1
  const units = p.total * stepTotal
  const completedUnits = (p.done || 0) * stepTotal + (p.step_idx || 0)
  return Math.min(99, Math.round((completedUnits / units) * 100))
}

export default function App() {
  const [summary, setSummary] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [show, setShow] = useState({ character: true, item: true, location: true })
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('graph')
  const [navOpen, setNavOpen] = useState(false)   // 窄屏视图汉堡菜单
  const [novels, setNovels] = useState([])
  const [novel, setNovel] = useState(null)   // 当前小说 slug(全局,所有视图跟随)

  // ── 应用级"进行中任务":状态与轮询提到 App,任意视图可见、切走不中断 ──
  const [job, setJob] = useState(null)        // { slug, prog }
  const pollRef = useRef(null)
  const jobSlugRef = useRef(null)             // 当前被轮询的 slug,避免重复起轮询

  const refreshNovels = useCallback(() => {
    return getNovels().then(d => {
      setNovels(d.novels || [])
      setNovel(cur => cur || d.current || (d.novels?.[0]?.slug ?? null))
      return d
    }).catch(console.error)
  }, [])

  // 开始轮询某个 slug 的进度(全局,唯一一处定时器)
  const startPolling = useCallback((slug) => {
    if (!slug || jobSlugRef.current === slug) return
    clearInterval(pollRef.current)
    jobSlugRef.current = slug
    setJob({ slug, prog: null })
    pollRef.current = setInterval(async () => {
      try {
        const p = await getProgress(slug)
        setJob({ slug, prog: p })
        // 单一真相:把实时进度的 stage 同步进对应卡片,避免顶栏与卡片状态打架
        setNovels(list => list.map(n => n.slug === slug
          ? { ...n, stage: p.stage, running: !!p.running,
              chapter_count: (p.done != null ? p.done : n.chapter_count) }
          : n))
        const TERMINAL = ['done', 'error', 'interrupted']
        if (TERMINAL.includes(p.stage) || p.running === false) {
          clearInterval(pollRef.current)
          jobSlugRef.current = null
          setJob(null)               // 收起顶栏进度条
          // 拉一次权威列表(后端会据实给出 done/partial/interrupted)
          refreshNovels().then(() => { if (p.stage === 'done') setNovel(cur => cur || slug) })
        }
      } catch (e) { /* 瞬时失败忽略,下一拍重试 */ }
    }, 1000)
  }, [refreshNovels])

  // 卸载清定时器
  useEffect(() => () => clearInterval(pollRef.current), [])

  // 启动:载入小说列表 + 扫描未完成任务自动重连轮询(刷新页面/重进也能恢复)
  useEffect(() => {
    refreshNovels().then(d => {
      const list = d?.novels || []
      const active = list.find(n => n.running || ACTIVE_STAGES.has(n.stage))
      if (active) startPolling(active.slug)
    })
  }, [refreshNovels, startPolling])

  // 小说变化 → 刷新概览 + 图谱
  useEffect(() => {
    if (novel == null) { setSummary(null); setGraph({ nodes: [], edges: [] }); return }
    setSelected(null)
    getSummary(novel).then(setSummary).catch(console.error)
    getGraph(novel).then(setGraph).catch(console.error)
  }, [novel])

  const c = summary?.counts || {}
  const stat = summary
    ? `${c.characters || 0}人物 · ${c.items || 0}物品 · ${c.locations || 0}地点 · ` +
      `${c.events || 0}事件 · ${(summary.chapters || []).length}章`
    : (novel ? '加载中…' : '未选择小说')

  const jp = job?.prog
  const jobActive = job && (!jp || ACTIVE_STAGES.has(jp.stage))
  const jobLabel = jp?.stage === 'aggregating' ? '全局聚合'
    : jp?.total ? `分析中 ${jp.done || 0}/${jp.total} 章` : '分析中'

  return (
    <>
      <div className="top">
        <h1>叙事档案</h1>
        <span className="sub">NARRATIVE BROWSER</span>
        <button className="nav-toggle" onClick={() => setNavOpen(o => !o)} aria-label="切换视图菜单">☰</button>
        <nav className={'views' + (navOpen ? ' open' : '')}>
          {Object.keys(VIEWS).map(v => (
            <button key={v} className={view === v ? 'active' : ''}
              onClick={() => { setView(v); setNavOpen(false) }}>
              {VIEWS[v]}
            </button>
          ))}
        </nav>
        <span className="stat">{stat}</span>
      </div>

      {/* 全局进度条:有进行中任务且不在分析页时显示,点击跳回分析页 */}
      {jobActive && view !== 'library' && (
        <div className="gjob" onClick={() => setView('library')} title="点击查看分析进度">
          <div className="gjob-bar"><div className="gjob-fill" style={{ width: progPct(jp) + '%' }} /></div>
          <span className="gjob-txt">{jobLabel} · 点击查看</span>
        </div>
      )}

      {view === 'graph' && (
        <>
          <Filters types={TYPES} show={show} onToggle={(t, v) => setShow(s => ({ ...s, [t]: v }))} />
          <div className="main">
            <div className="graph-pane">
              <GraphPane graph={graph} show={show} onSelect={setSelected} />
            </div>
            <SidePanel selected={selected} typeNames={TYPES} novel={novel} />
          </div>
        </>
      )}

      {view === 'timeline' && <Timeline novel={novel} />}
      {view === 'scenes' && <Scenes novel={novel} />}
      {view === 'reader' && (
        <Reader novel={novel} novels={novels} onPickNovel={setNovel} />
      )}
      {view === 'library' && (
        <Library
          novels={novels}
          job={job}
          onStarted={(slug) => startPolling(slug)}
          onOpen={(slug) => { setNovel(slug); setView('reader') }}
          onRefresh={refreshNovels}
        />
      )}
    </>
  )
}