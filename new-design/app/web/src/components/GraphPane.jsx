import React, { useEffect, useMemo, useRef, useState } from 'react'

const TC = { character: '#a8332a', item: '#b8884a', location: '#6f9b8e', event: '#9a7db8', organization: '#4a8fb8' }

// 网格近似斥力的力导向布局。
// 优化点(对比旧版 260 固定迭代 + O(n²) 全量斥力):
//  1. 收敛即停:能量低于阈值提前结束;迭代上限按节点数自适应。
//  2. 网格近似斥力:仅邻近网格内节点参与斥力计算,O(n²)→近 O(n)。
//  3. 布局在归一坐标系([0,1])求解,渲染时再映射到画布尺寸 —— resize 不必重算物理。
function computeLayout(nodes, edges) {
  const n = nodes.length
  if (n === 0) return
  const idx = {}
  nodes.forEach((nd, i) => { idx[nd.id] = i })

  // 初始化:圆形布局于归一坐标(中心 0.5,半径 0.33)
  nodes.forEach((nd, i) => {
    const a = (2 * Math.PI * i) / n
    nd.x = 0.5 + Math.cos(a) * 0.33
    nd.y = 0.5 + Math.sin(a) * 0.33
  })

  // 参数(归一坐标下重新标定):斥力常数、弹簧静长、步长
  const REP = 0.6 / n          // 斥力随规模归一,避免大图爆开
  const SPRING_LEN = 0.18
  const SPRING_K = 0.02
  const MAX_STEP = 0.03
  const maxIter = Math.min(300, Math.max(80, Math.round(4000 / Math.sqrt(n))))
  // 网格:单元边长 ≈ 斥力作用半径
  const CELL = 0.12
  const REACH = 1            // 邻接 ±1 格

  for (let it = 0; it < maxIter; it++) {
    // 建网格
    const grid = new Map()
    const key = (cx, cy) => cx + ',' + cy
    nodes.forEach((nd, i) => {
      const cx = Math.floor(nd.x / CELL), cy = Math.floor(nd.y / CELL)
      const k = key(cx, cy)
      let arr = grid.get(k); if (!arr) { arr = []; grid.set(k, arr) }
      arr.push(i)
      nd._cx = cx; nd._cy = cy; nd.fx = 0; nd.fy = 0
    })

    // 斥力:仅邻近格
    nodes.forEach((a, ai) => {
      for (let gx = a._cx - REACH; gx <= a._cx + REACH; gx++) {
        for (let gy = a._cy - REACH; gy <= a._cy + REACH; gy++) {
          const arr = grid.get(key(gx, gy)); if (!arr) continue
          for (const bi of arr) {
            if (bi === ai) continue
            const b = nodes[bi]
            let dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy
            if (d2 < 1e-9) { dx = (Math.random() - 0.5) * 1e-3; dy = (Math.random() - 0.5) * 1e-3; d2 = dx * dx + dy * dy }
            if (d2 > CELL * CELL * 9) continue // 超出作用域忽略
            const d = Math.sqrt(d2), f = REP / d2
            a.fx += (dx / d) * f; a.fy += (dy / d) * f
          }
        }
      }
    })

    // 弹簧(边)
    edges.forEach(e => {
      const a = nodes[idx[e.from]], b = nodes[idx[e.to]]
      if (!a || !b) return
      let dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1e-6
      const f = (d - SPRING_LEN) * SPRING_K
      a.fx += (dx / d) * f; a.fy += (dy / d) * f
      b.fx -= (dx / d) * f; b.fy -= (dy / d) * f
    })

    // 位移 + 能量统计(收敛判定)
    let energy = 0
    nodes.forEach(nd => {
      let sx = Math.max(-MAX_STEP, Math.min(MAX_STEP, nd.fx))
      let sy = Math.max(-MAX_STEP, Math.min(MAX_STEP, nd.fy))
      nd.x += sx; nd.y += sy
      nd.x = Math.max(0.02, Math.min(0.98, nd.x))
      nd.y = Math.max(0.02, Math.min(0.98, nd.y))
      energy += sx * sx + sy * sy
    })
    if (energy / n < 1e-6) break  // 收敛即停
  }
  return idx
}

// 稳定 key:节点 id 集合 + 边数,决定是否需要重算布局
function layoutKey(nodes, edges) {
  return nodes.map(n => n.id).join('|') + '#' + edges.length
}

export default function GraphPane({ graph, show, onSelect }) {
  const ref = useRef(null)
  const [size, setSize] = useState({ W: 800, H: 600 })
  const cacheRef = useRef({ key: null, nodes: [], idx: {} })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setSize({ W: el.clientWidth || 800, H: el.clientHeight || 600 })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // 全量节点布局只算一次(按 id 集合缓存);筛选只隐藏不重算物理
  const layout = useMemo(() => {
    const ns = graph.nodes.map(n => ({ ...n }))
    const idset = new Set(ns.map(n => n.id))
    const es = graph.edges.filter(e => idset.has(e.from) && idset.has(e.to))
    const key = layoutKey(ns, es)
    if (cacheRef.current.key === key) {
      return { nodes: cacheRef.current.nodes, edges: es, idx: cacheRef.current.idx }
    }
    const idx = computeLayout(ns, es)
    cacheRef.current = { key, nodes: ns, idx }
    return { nodes: ns, edges: es, idx }
  }, [graph])

  // 归一坐标 → 画布像素(resize 仅触发此映射,不重算物理)
  const px = (x) => 40 + x * (size.W - 80)
  const py = (y) => 30 + y * (size.H - 60)

  const visNodes = layout.nodes.filter(n => show[n.type])
  const visIds = new Set(visNodes.map(n => n.id))
  const visEdges = layout.edges.filter(e => visIds.has(e.from) && visIds.has(e.to))

  return (
    <svg ref={ref} viewBox={`0 0 ${size.W} ${size.H}`}>
      {visEdges.map((e, i) => {
        const a = layout.nodes[layout.idx[e.from]], b = layout.nodes[layout.idx[e.to]]
        if (!a || !b) return null
        const stroke = e.kind === 'loc' ? '#6f9b8e' : e.kind === 'event' ? '#9a7db8'
          : e.kind === 'item' ? '#b8884a'
          : e.kind === 'membership' ? '#4a8fb8'
          : e.kind === 'org' ? '#3a7090' : '#c98b6a'
        return (
          <line key={i} x1={px(a.x)} y1={py(a.y)} x2={px(b.x)} y2={py(b.y)}
            stroke={stroke} strokeWidth="1" opacity=".4" />
        )
      })}
      {visNodes.map(n => {
        const r = n.type === 'character' ? 9 : n.type === 'organization' ? 8 : n.type === 'event' ? 5 : 6
        return (
          <g key={n.id} className="node"
            onClick={() => onSelect({ type: n.type, id: n.id.split(':')[1], label: n.label })}>
            <circle cx={px(n.x)} cy={py(n.y)} r={r} fill={TC[n.type]} stroke="#2a241d" strokeWidth="1.5" />
            <text x={px(n.x)} y={py(n.y) - r - 5} textAnchor="middle">{n.label}</text>
          </g>
        )
      })}
    </svg>
  )
}