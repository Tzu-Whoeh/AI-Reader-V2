import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import './theme.css'

// 错误边界:任何渲染异常不再让整页空白(黑屏),而是显示可读的错误信息,便于定位。
class ErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null, info: null } }
  static getDerivedStateFromError(err) { return { err } }
  componentDidCatch(err, info) { this.setState({ info }); console.error('UI error:', err, info) }
  render() {
    if (this.state.err) {
      const e = this.state.err
      return (
        <div style={{ padding: 20, fontFamily: 'sans-serif', color: '#e8dcc8',
          background: '#1a1714', minHeight: '100vh', boxSizing: 'border-box' }}>
          <h2 style={{ color: '#a8332a', marginBottom: 12 }}>页面出错(已捕获,未崩溃)</h2>
          <div style={{ marginBottom: 10 }}>
            <button onClick={() => this.setState({ err: null, info: null })}
              style={{ padding: '8px 16px', background: '#221d18', color: '#e8dcc8',
                border: '1px solid #4a4036', borderRadius: 4, cursor: 'pointer' }}>
              ← 返回(清除错误)
            </button>
          </div>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.6,
            background: '#221d18', padding: 14, borderRadius: 6, overflow: 'auto' }}>
            {String(e && e.message || e)}
            {'\n\n'}
            {e && e.stack ? e.stack.split('\n').slice(0, 6).join('\n') : ''}
          </pre>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)