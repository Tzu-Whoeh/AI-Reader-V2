import React from 'react'

const TC = { character: '#a8332a', item: '#b8884a', location: '#6f9b8e' }

export default function Filters({ types, show, onToggle }) {
  return (
    <div className="filters">
      {Object.keys(types).map(t => (
        <label key={t}>
          <input
            type="checkbox"
            checked={!!show[t]}
            onChange={e => onToggle(t, e.target.checked)}
          />
          <i style={{ background: TC[t] }} />
          {types[t]}
        </label>
      ))}
    </div>
  )
}
