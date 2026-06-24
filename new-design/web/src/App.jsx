import React, { useEffect, useState } from 'react'
import { getSummary, getGraph } from './api.js'
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
  const [selected, setSelected] = useState(null) // {type, id, label}
  const [view, setView] = useState('graph')

  useEffect(() => {
    getSummary().then(setSummary).catch(console.error)
    getGraph().then(setGraph).catch(console.error)
  }, [])

  const c = summary?.counts || {}
  const stat = summary
    ? `${c.characters || 0}人物 · ${c.items || 0}物品 · ${c.locations || 0}地点 · ` +
      `${c.events || 0}事件 · ${(summary.chapters || []).length}章`
    : '加载中…'

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
            <SidePanel selected={selected} typeNames={TYPES} />
          </div>
        </>
      )}

      {view === 'timeline' && <Timeline />}
      {view === 'scenes' && <Scenes />}
      {view === 'reader' && <Reader />}
      {view === 'upload' && <Upload onDone={() => setView('reader')} />}
    </>
  )
}
