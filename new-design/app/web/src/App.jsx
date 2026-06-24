import React, { useEffect, useState, useCallback } from 'react'
import { getSummary, getGraph, getNovels } from './api.js'
import Filters from './components/Filters.jsx'
import GraphPane from './components/GraphPane.jsx'
import SidePanel from './components/SidePanel.jsx'
import Timeline from './views/Timeline.jsx'
import Scenes from './views/Scenes.jsx'
import Reader from './views/Reader.jsx'
import Upload from './views/Upload.jsx'

const TYPES = { character: '人物', item: '物品', location: '地点' }
const VIEWS = { upload: '分析', graph: '图谱', reader: '阅读', timeline: '时间线', scenes: '场景' }

export default function App() {
  const [summary, setSummary] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [show, setShow] = useState({ character: true, item: true, location: true })
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('graph')
  const [novels, setNovels] = useState([])
  const [novel, setNovel] = useState(null)   // 当前小说 slug(全局,所有视图跟随)

  // 载入小说列表,默认选最近上传的
  const refreshNovels = useCallback(() => {
    return getNovels().then(d => {
      setNovels(d.novels || [])
      setNovel(cur => cur || d.current || (d.novels?.[0]?.slug ?? null))
      return d
    }).catch(console.error)
  }, [])

  useEffect(() => { refreshNovels() }, [refreshNovels])

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

  return (
    <>
      <div className="top">
        <h1>叙事档案</h1>
        <span className="sub">NARRATIVE BROWSER</span>
        <nav className="views">
          {Object.keys(VIEWS).map(v => (
            <button key={v} className={view === v ? 'active' : ''} onClick={() => setView(v)}>
              {VIEWS[v]}
            </button>
          ))}
        </nav>
        <span className="stat">{stat}</span>
      </div>

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
      {view === 'upload' && (
        <Upload onDone={(slug) => { refreshNovels().then(() => { setNovel(slug); setView('reader') }) }} />
      )}
    </>
  )
}
