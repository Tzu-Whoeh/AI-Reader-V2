import React from 'react'

const TC = { character: '#a8332a', item: '#b8884a', location: '#6f9b8e', event: '#9a7db8', organization: '#4a8fb8' }

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
