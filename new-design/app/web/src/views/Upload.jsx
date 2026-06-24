import React, { useEffect, useRef, useState } from 'react'
import { uploadFile, startAnalyze, getProgress } from '../api.js'

const STAGE_LABEL = {
  uploaded: '已上传', splitting: '拆章中', starting: '准备中', analyzing: '分析中',
  aggregating: '全局聚合', done: '完成', error: '出错', unknown: '—',
}

export default function Upload({ onDone }) {
  const [file, setFile] = useState(null)
  const [slug, setSlug] = useState(null)
  const [prog, setProg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  const poll = (s) => {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const p = await getProgress(s)
        setProg(p)
        if (p.stage === 'done' || p.stage === 'error') {
          clearInterval(pollRef.current); setBusy(false)
        }
      } catch (e) { /* 瞬时失败忽略 */ }
    }, 1000)
  }

  const run = async () => {
    setErr(null); setProg(null); setBusy(true)
    try {
      if (!file) { setErr('请选择 .txt 或 .zip 文件'); setBusy(false); return }
      const up = await uploadFile(file)
      setSlug(up.slug)
      await startAnalyze(up.slug)
      poll(up.slug)
    } catch (e) {
      // 409 = 同名已存在
      setErr(e.status === 409 ? (e.message || '该小说已存在') : (e.message || String(e)))
      setBusy(false)
    }
  }

  const pct = (() => {
    if (!prog) return 0
    if (prog.stage === 'done') return 100
    if (!prog.total) return 0
    const stepTotal = prog.step_total || 1
    const stepIdx = prog.step_idx || 0
    const units = prog.total * stepTotal
    const completedUnits = (prog.done || 0) * stepTotal + stepIdx
    return Math.min(99, Math.round((completedUnits / units) * 100))
  })()

  const idle = !busy && (!prog || prog.stage === 'error')

  return (
    <div className="view-scroll">
      <div className="upload-wrap">
        <h2 className="up-h">上传小说 · 启动分析</h2>

        {idle && (
          <>
            <div className="up-drop">
              <label className="up-file">
                <input type="file" accept=".txt,.zip"
                  onChange={e => setFile(e.target.files?.[0] || null)} />
                {file ? file.name : '选择 .txt 或 .zip 文件'}
              </label>
              <p className="up-hint">txt:整本或单章文本 · zip:多个 txt(每文件可含多章),将自动拆章清洗</p>
            </div>
            <div className="up-row">
              <button className="up-btn" onClick={run} disabled={!file}>上传并分析</button>
            </div>
            {err && <div className="up-err">{err}</div>}
          </>
        )}

        {(busy || (prog && prog.stage !== 'error')) && prog && (
          <div className="up-progress">
            <div className="upp-head">
              <span className="upp-stage">{STAGE_LABEL[prog.stage] || prog.stage}</span>
              {prog.total > 0 && <span className="upp-frac">{prog.done || 0} / {prog.total} 章</span>}
            </div>
            <div className="upp-bar"><div className="upp-fill" style={{ width: pct + '%' }} /></div>
            {prog.stage === 'analyzing' && prog.step_name && (
              <div className="upp-step">
                第{prog.cur_chapter}章 · 正在{prog.step_name}…
                {prog.step_total && <span className="upp-step-frac"> ({prog.step_idx}/{prog.step_total})</span>}
              </div>
            )}
            {prog.chapters?.length > 0 && (
              <ul className="upp-chs">
                {prog.chapters.map((c, i) => (
                  <li key={i} className={c.error ? 'err' : ''}>
                    第{c.chapter}章
                    {c.error ? ` ✗ ${c.error}` : c.skipped ? ' (已存在,跳过)'
                      : ` ✓ 场景${c.scenes ?? '-'} 人物${c.characters ?? '-'} 事件${c.events ?? '-'}`}
                  </li>
                ))}
              </ul>
            )}
            {prog.stage === 'done' && (
              <div className="upp-done">
                <span>分析完成 · {prog.counts ? `${prog.counts.global_characters || 0}人物 / ${prog.counts.global_locations || 0}地点` : ''}</span>
                {onDone && <button className="up-btn" onClick={() => onDone(slug)}>查看结果</button>}
              </div>
            )}
            {prog.stage === 'error' && <div className="up-err">分析失败:{prog.error}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
