import React, { useEffect, useRef, useState } from 'react'
import { uploadText, startAnalyze, getProgress } from '../api.js'

const STAGE_LABEL = {
  uploaded: '已上传', starting: '准备中', analyzing: '分析中',
  aggregating: '全局聚合', done: '完成', error: '出错', unknown: '—',
}

export default function Upload({ onDone }) {
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [presplit, setPresplit] = useState(false)
  const [job, setJob] = useState(null)
  const [prog, setProg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  const poll = (jobId) => {
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const p = await getProgress(jobId)
        setProg(p)
        if (p.stage === 'done' || p.stage === 'error') {
          clearInterval(pollRef.current)
          setBusy(false)
        }
      } catch (e) { /* 轮询瞬时失败忽略,下次再试 */ }
    }, 1000)
  }

  const run = async () => {
    setErr(null); setProg(null); setBusy(true)
    try {
      const payload = file || text
      if (!payload || (typeof payload === 'string' && !payload.trim())) {
        setErr('请粘贴文本或选择文件'); setBusy(false); return
      }
      const up = await uploadText(payload)
      setJob(up.job_id)
      await startAnalyze(up.job_id, presplit)
      poll(up.job_id)
    } catch (e) {
      setErr(String(e)); setBusy(false)
    }
  }

  // 子步骤级进度:(已完成章×步数 + 当前章已完成步) / (总章×步数)
  const pct = (() => {
    if (!prog) return 0
    if (prog.stage === 'done') return 100
    if (!prog.total) return 0
    const stepTotal = prog.step_total || 1
    const stepIdx = prog.step_idx || 0
    const units = prog.total * stepTotal
    const completedUnits = prog.done * stepTotal + stepIdx
    return Math.min(99, Math.round((completedUnits / units) * 100))
  })()

  return (
    <div className="view-scroll">
      <div className="upload-wrap">
        <h2 className="up-h">上传文本 · 启动分析</h2>

        {!busy && (!prog || prog.stage === 'error') && (
          <>
            <textarea
              className="up-text"
              placeholder="在此粘贴小说文本…(或在下方选择 .txt 文件)"
              value={text}
              onChange={e => setText(e.target.value)}
            />
            <div className="up-row">
              <label className="up-file">
                <input type="file" accept=".txt,text/plain"
                  onChange={e => setFile(e.target.files?.[0] || null)} />
                {file ? file.name : '选择 .txt 文件'}
              </label>
              <label className="up-chk">
                <input type="checkbox" checked={presplit}
                  onChange={e => setPresplit(e.target.checked)} />
                预拆分(每文件/段当一章)
              </label>
              <button className="up-btn" onClick={run}>开始分析</button>
            </div>
            {err && <div className="up-err">{err}</div>}
          </>
        )}

        {(busy || (prog && prog.stage !== 'error')) && prog && (
          <div className="up-progress">
            <div className="upp-head">
              <span className="upp-stage">{STAGE_LABEL[prog.stage] || prog.stage}</span>
              {prog.total > 0 && <span className="upp-frac">{prog.done} / {prog.total} 章</span>}
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
                {onDone && <button className="up-btn" onClick={() => onDone(job)}>查看结果</button>}
              </div>
            )}
            {prog.stage === 'error' && <div className="up-err">分析失败:{prog.error}</div>}
          </div>
        )}
      </div>
    </div>
  )
}
