import React, { useEffect, useMemo, useRef, useState } from 'react'

const TC = { character: '#a8332a', item: '#b8884a', location: '#6f9b8e' }

// 力导向布局(从旧前端平移:斥力 5000、弹簧静长 140、260 次迭代)。
// 平移阶段保持同参数以对齐旧行为;性能/拖拽优化留待后续视图迭代。
function layout(nodes, edges, W, H) {
  const idx = {}
  nodes.forEach((n, i) => {
    idx[n.id] = i
    const a = (2 * Math.PI * i) / nodes.length
    n.x = W / 2 + Math.cos(a) * Math.min(W, H) * 0.33
    n.y = H / 2 + Math.sin(a) * Math.min(W, H) * 0.33
  })
  for (let it = 0; it < 260; it++) {
    nodes.forEach(a => {
      a.fx = 0; a.fy = 0
      nodes.forEach(b => {
        if (a === b) return
        let dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy) || 1
        let f = 5000 / (d * d)
        a.fx += (dx / d) * f; a.fy += (dy / d) * f
      })
    })
    edges.forEach(e => {
      const a = nodes[idx[e.from]], b = nodes[idx[e.to]]
      if (!a || !b) return
      let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1, f = (d - 140) * 0.02
      a.fx += (dx / d) * f; a.fy += (dy / d) * f
      b.fx -= (dx / d) * f; b.fy -= (dy / d) * f
    })
    nodes.forEach(n => {
      n.x += Math.max(-7, Math.min(7, n.fx))
      n.y += Math.max(-7, Math.min(7, n.fy))
      n.x = Math.max(40, Math.min(W - 40, n.x))
      n.y = Math.max(30, Math.min(H - 30, n.y))
    })
  }
  return { nodes, idx }
}

export default function GraphPane({ graph, show, onSelect }) {
  const ref = useRef(null)
  const [size, setSize] = useState({ W: 800, H: 600 })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setSize({ W: el.clientWidth || 800, H: el.clientHeight || 600 })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const { nodes, edges, idx } = useMemo(() => {
    const ns = graph.nodes.filter(n => show[n.type]).map(n => ({ ...n }))
    const idset = new Set(ns.map(n => n.id))
    const es = graph.edges.filter(e => idset.has(e.from) && idset.has(e.to))
    const { idx } = layout(ns, es, size.W, size.H)
    return { nodes: ns, edges: es, idx }
  }, [graph, show, size.W, size.H])

  return (
    <svg ref={ref} viewBox={`0 0 ${size.W} ${size.H}`}>
      {edges.map((e, i) => {
        const a = nodes[idx[e.from]], b = nodes[idx[e.to]]
        if (!a || !b) return null
        return (
          <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke={e.kind === 'loc' ? '#6f9b8e' : '#b8884a'} strokeWidth="1" opacity=".4" />
        )
      })}
      {nodes.map(n => {
        const r = n.type === 'character' ? 9 : 6
        return (
          <g key={n.id} className="node"
            onClick={() => onSelect({ type: n.type, id: n.id.split(':')[1], label: n.label })}>
            <circle cx={n.x} cy={n.y} r={r} fill={TC[n.type]} stroke="#2a241d" strokeWidth="1.5" />
            <text x={n.x} y={n.y - r - 5} textAnchor="middle">{n.label}</text>
          </g>
        )
      })}
    </svg>
  )
}
