import React, { useEffect, useState } from 'react'
import { getSummary, getGraph } from './api.js'
import Filters from './components/Filters.jsx'
import GraphPane from './components/GraphPane.jsx'
import SidePanel from './components/SidePanel.jsx'

const TYPES = { character: '人物', item: '物品', location: '地点' }

export default function App() {
  const [summary, setSummary] = useState(null)
  const [graph, setGraph] = useState({ nodes: [], edges: [] })
  const [show, setShow] = useState({ character: true, item: true, location: true })
  const [selected, setSelected] = useState(null) // {type, id, label}

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
        <span className="stat">{stat}</span>
      </div>
      <Filters types={TYPES} show={show} onToggle={(t, v) => setShow(s => ({ ...s, [t]: v }))} />
      <div className="main">
        <div className="graph-pane">
          <GraphPane graph={graph} show={show} onSelect={setSelected} />
        </div>
        <SidePanel selected={selected} typeNames={TYPES} />
      </div>
    </>
  )
}
