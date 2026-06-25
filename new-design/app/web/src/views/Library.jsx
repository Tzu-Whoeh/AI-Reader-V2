import React, { useState, useEffect } from 'react'
import { uploadFile, startAnalyze, updateNovelMeta, deleteNovel, reclean, pauseAnalyze, resumeAnalyze, getSummary } from '../api.js'
import RulesPanel from './RulesPanel.jsx'

const STAGE_LABEL = {
  uploaded: '已上传', splitting: '拆章中', starting: '准备中', analyzing: '分析中',
  aggregating: '全局聚合', paused: '已暂停', stopping: '停止中', done: '已分析', partial: '部分完成', error: '出错', unknown: '—',
}
const COVER_PRESETS = ['#a8332a', '#b8884a', '#6f9b8e', '#5a6b8c', '#8c5a7a', '#3a322a']

// 从 slug/书名派生稳定色(无 meta.cover 时)
function deriveColor(s) {
  let h = 0
  for (let i = 0; i < (s || '').length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return COVER_PRESETS[h % COVER_PRESETS.length]
}

function progPct(p) {
  if (!p) return 0
  if (p.stage === 'done') return 100
  if (!p.total) return 0
  const stepTotal = p.step_total || 1
  const units = p.total * stepTotal
  const done = (p.done || 0) * stepTotal + (p.step_idx || 0)
  return Math.min(99, Math.round((done / units) * 100))
}

export default function Library({ novels = [], job, onStarted, onOpen, onRefresh }) {
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [editing, setEditing] = useState(null)   // 编辑中的小说对象
  const [confirmDel, setConfirmDel] = useState(null)
  const [rulesPanel, setRulesPanel] = useState(null)   // {mode:'global'|'book', slug?, initial?}
  const [recleaning, setRecleaning] = useState(null)
  const [expanded, setExpanded] = useState(null)   // 点击放大的卡片(slug)
  const [stats, setStats] = useState(null)         // 放大卡片的分析统计 {loading, counts, chapters}

  const jp = job?.prog
  const jobSlug = job?.slug
  const expandedNovel = expanded ? novels.find(n => n.slug === expanded) : null

  useEffect(() => {
    if (!expandedNovel) { setStats(null); return }
    // 只要已有章节产物就拉统计(分析中也有部分结果);完全没开始(uploaded/splitting)才不拉
    const hasData = (expandedNovel.chapter_count || 0) > 0 ||
      ['done','partial','analyzing','aggregating','paused','stopping'].includes(expandedNovel.stage)
    if (!hasData) { setStats(null); return }
    let stale = false
    setStats({ loading: true })
    getSummary(expandedNovel.slug)
      .then(s => { if (!stale) setStats({ loading: false, counts: s.counts || {}, chapters: (s.chapters || []).length }) })
      .catch(() => { if (!stale) setStats({ loading: false, counts: null }) })
    return () => { stale = true }
  }, [expanded, expandedNovel && expandedNovel.chapter_count, expandedNovel && expandedNovel.stage]) // eslint-disable-line

  const doUpload = async () => {
    setErr(null); setBusy(true)
    try {
      if (!file) { setErr('请选择 .txt 或 .zip 文件'); setBusy(false); return }
      const up = await uploadFile(file)
      await startAnalyze(up.slug)
      setFile(null)
      onStarted?.(up.slug)
      onRefresh?.()
    } catch (e) {
      setErr(e.status === 409 ? (e.message || '该小说已存在') : (e.message || String(e)))
    } finally { setBusy(false) }
  }

  const analyzeAgain = async (slug) => {
    try { await startAnalyze(slug); onStarted?.(slug) }
    catch (e) { setErr(e.message || String(e)) }
  }

  const doPause = async (slug) => {
    try { await pauseAnalyze(slug); onRefresh?.() }
    catch (e) { setErr(e.message || String(e)) }
  }
  const doResume = async (slug) => {
    try { await resumeAnalyze(slug); onRefresh?.() }
    catch (e) { setErr(e.message || String(e)) }
  }

  const saveEdit = async () => {
    const e = editing
    try {
      await updateNovelMeta(e.slug, {
        novel_name: e.novel_name, author: e.author || null,
        tags: e.tags || [], cover: e.cover || null,
      })
      setEditing(null); onRefresh?.()
    } catch (er) { setErr(er.message || String(er)) }
  }

  const doDelete = async (slug) => {
    try { await deleteNovel(slug); setConfirmDel(null); onRefresh?.() }
    catch (e) { setErr(e.message || String(e)); setConfirmDel(null) }
  }

  const doReclean = async (slug) => {
    setErr(null); setRecleaning(slug)
    try { await reclean(slug); onRefresh?.() }
    catch (e) { setErr(e.message || String(e)) }
    finally { setRecleaning(null) }
  }

  const applyBookRules = async (slug, enabledIds) => {
    try { await updateNovelMeta(slug, { rules_selected: enabledIds }); onRefresh?.() }
    catch (e) { setErr(e.message || String(e)) }
  }

  return (
    <div className="view-scroll">
      <div className="lib-wrap">
        <div className="lib-head">
          <h2 className="up-h">书库</h2>
          <label className="up-file lib-upload">
            <input type="file" accept=".txt,.zip"
              onChange={ev => setFile(ev.target.files?.[0] || null)} />
            {file ? file.name : '选择 .txt / .zip'}
          </label>
          <button className="up-btn lib-up-btn" onClick={doUpload} disabled={!file || busy}>
            {busy ? '上传中…' : '上传并分析'}
          </button>
          <button className="lib-rules-btn" onClick={() => setRulesPanel({ mode: 'global' })}>清洗规则</button>
        </div>
        {err && <div className="up-err">{err}</div>}

        {/* 进行中任务进度(嵌在书库页) */}
        {jp && jp.stage !== 'done' && jp.stage !== 'error' && (
          <div className="up-progress lib-job">
            <div className="upp-head">
              <span className="upp-stage">{STAGE_LABEL[jp.stage] || jp.stage} · {jobSlug}</span>
              {jp.total > 0 && <span className="upp-frac">{jp.done || 0} / {jp.total} 章</span>}
            </div>
            <div className="upp-bar"><div className="upp-fill" style={{ width: progPct(jp) + '%' }} /></div>
            {jp.stage === 'analyzing' && jp.step_name && (
              <div className="upp-step">第{jp.cur_chapter}章 · 正在{jp.step_name}…
                {jp.step_total && <span className="upp-step-frac"> ({jp.step_idx}/{jp.step_total})</span>}</div>
            )}
          </div>
        )}

        {/* 卡片网格 */}
        {novels.length === 0 && <div className="empty">书库为空,上传 .txt / .zip 开始。</div>}
        <div className="lib-grid">
          {novels.map(n => {
            const color = n.cover || deriveColor(n.slug)
            const running = n.running || (jobSlug === n.slug && jp && jp.stage !== 'done' && jp.stage !== 'error')
            const analyzed = n.stage === 'done' || n.stage === 'partial'
            return (
              <div key={n.slug} className="bookcard">
                <div className="bc-cover" style={{ background: color }}
                  onClick={() => setExpanded(n.slug)}>
                  <span className="bc-cover-ch">{(n.novel_name || n.slug || '?').slice(0, 1)}</span>
                  {n.dirty && <span className="bc-dirty" title="规则已变,建议重新分析">规则已变</span>}
                </div>
                <div className="bc-body" onClick={() => setExpanded(n.slug)} style={{ cursor: 'pointer' }}>
                  <div className="bc-title" title={n.novel_name || n.slug}>{n.novel_name || n.slug}</div>
                  <div className="bc-author">{n.author || '佚名'}</div>
                  {n.tags?.length > 0 && (
                    <div className="bc-tags">{n.tags.map((t, i) => <span key={i} className="bc-tag">{t}</span>)}</div>
                  )}
                  <div className="bc-meta">
                    <span className={'bc-stage s-' + (n.stage || 'unknown')}>{STAGE_LABEL[n.stage] || n.stage}</span>
                    {n.chapter_count > 0 && <span className="bc-ch">{n.chapter_count} 章</span>}
                  </div>
                  {n.stage === 'partial' && n.partial_reason &&
                    <div className="bc-partial" title={n.partial_reason}>{n.partial_reason}</div>}
                  <div className="bc-actions">
                    {analyzed && <button onClick={(e) => { e.stopPropagation(); onOpen?.(n.slug) }}>打开</button>}
                    {running && (n.stage === 'paused'
                      ? <button onClick={(e) => { e.stopPropagation(); doResume(n.slug) }}>继续</button>
                      : <button onClick={(e) => { e.stopPropagation(); doPause(n.slug) }} disabled={n.stage === 'stopping'}>暂停</button>)}
                    <button className="bc-more" onClick={(e) => { e.stopPropagation(); setExpanded(n.slug) }}>更多…</button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* 放大卡片:详情 + 操作 */}
      {expandedNovel && (() => {
        const n = expandedNovel
        const color = n.cover || deriveColor(n.slug)
        const running = n.running || (jobSlug === n.slug && jp && jp.stage !== 'done' && jp.stage !== 'error')
        const analyzed = n.stage === 'done' || n.stage === 'partial'
        const close = () => setExpanded(null)
        const act = (fn) => { fn(); }
        return (
          <div className="modal-bg" onClick={close}>
            <div className="modal bookcard-modal" onClick={ev => ev.stopPropagation()}>
              <button className="bcm-close" onClick={close}>×</button>
              <div className="bcm-head">
                <div className="bcm-cover" style={{ background: color }}>
                  <span className="bc-cover-ch">{(n.novel_name || n.slug || '?').slice(0, 1)}</span>
                </div>
                <div className="bcm-info">
                  <div className="bcm-title">{n.novel_name || n.slug}</div>
                  <div className="bcm-author">{n.author || '佚名'}</div>
                  {n.tags && n.tags.length > 0 &&
                    <div className="bc-tags">{n.tags.map((t, i) => <span key={i} className="bc-tag">{t}</span>)}</div>}
                  <div className="bc-meta">
                    <span className={'bc-stage s-' + (n.stage || 'unknown')}>{STAGE_LABEL[n.stage] || n.stage}</span>
                    {n.chapter_count > 0 && <span className="bc-ch">{n.chapter_count} 章</span>}
                  </div>
                  {n.stage === 'partial' && n.partial_reason &&
                    <div className="bc-partial">{n.partial_reason}</div>}
                </div>
              </div>
              {stats && (
                <div className="bcm-stats">
                  {stats.loading ? <span className="bcm-stats-hint">统计加载中…</span>
                   : stats.counts ? (
                    <>
                      {[['characters','人物'],['organizations','组织'],['items','物品'],
                        ['locations','地点'],['events','事件']].map(([k, label]) => (
                        <div key={k} className="bcm-stat">
                          <span className="bcm-stat-n">{stats.counts[k] ?? 0}</span>
                          <span className="bcm-stat-l">{label}</span>
                        </div>
                      ))}
                      <div className="bcm-stat">
                        <span className="bcm-stat-n">{stats.chapters ?? 0}</span>
                        <span className="bcm-stat-l">章</span>
                      </div>
                    </>
                   ) : <span className="bcm-stats-hint">统计不可用</span>}
                </div>
              )}
              <div className="bcm-actions">
                {analyzed && <button className="up-btn" onClick={() => { onOpen?.(n.slug); close() }}>打开阅读</button>}
                {running && (n.stage === 'paused'
                  ? <button onClick={() => act(() => doResume(n.slug))}>继续分析</button>
                  : <button onClick={() => act(() => doPause(n.slug))} disabled={n.stage === 'stopping'}>暂停分析</button>)}
                {!running && <button onClick={() => { analyzeAgain(n.slug); close() }}>{analyzed ? '重新分析' : '开始分析'}</button>}
                <button onClick={() => { setEditing({ ...n, tags: n.tags || [], cover: n.cover || color }); close() }}>编辑信息</button>
                {!running && <button onClick={() => { setRulesPanel({ mode: 'book', slug: n.slug, initial: n.rules_selected ?? null }); close() }}>清洗规则</button>}
                {!running && <button onClick={() => act(() => doReclean(n.slug))} disabled={recleaning === n.slug}>{recleaning === n.slug ? '清洗中…' : '重新清洗'}</button>}
                <button className="bc-del" onClick={() => { setConfirmDel(n.slug); close() }}>删除</button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* 编辑弹层 */}
      {editing && (
        <div className="modal-bg" onClick={() => setEditing(null)}>
          <div className="modal" onClick={ev => ev.stopPropagation()}>
            <h3 className="modal-h">编辑书籍信息</h3>
            <label className="fld"><span>书名</span>
              <input value={editing.novel_name || ''} onChange={e => setEditing({ ...editing, novel_name: e.target.value })} /></label>
            <label className="fld"><span>作者</span>
              <input value={editing.author || ''} onChange={e => setEditing({ ...editing, author: e.target.value })} /></label>
            <label className="fld"><span>标签</span>
              <input value={(editing.tags || []).join(', ')} placeholder="逗号分隔"
                onChange={e => setEditing({ ...editing, tags: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })} /></label>
            <div className="fld"><span>封面色</span>
              <div className="color-row">
                {COVER_PRESETS.map(col => (
                  <button key={col} className={'swatch' + (editing.cover === col ? ' on' : '')}
                    style={{ background: col }} onClick={() => setEditing({ ...editing, cover: col })} />
                ))}
              </div>
            </div>
            <div className="modal-actions">
              <button onClick={() => setEditing(null)}>取消</button>
              <button className="up-btn" onClick={saveEdit}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认 */}
      {confirmDel && (
        <div className="modal-bg" onClick={() => setConfirmDel(null)}>
          <div className="modal" onClick={ev => ev.stopPropagation()}>
            <h3 className="modal-h">删除「{confirmDel}」?</h3>
            <p className="modal-warn">将永久删除原文、清洗结果与分析产物,不可恢复。</p>
            <div className="modal-actions">
              <button onClick={() => setConfirmDel(null)}>取消</button>
              <button className="bc-del-confirm" onClick={() => doDelete(confirmDel)}>确认删除</button>
            </div>
          </div>
        </div>
      )}

      {rulesPanel && (
        <RulesPanel
          mode={rulesPanel.mode}
          initialEnabled={rulesPanel.mode === 'book' ? rulesPanel.initial : null}
          title={rulesPanel.mode === 'book' ? ('清洗规则 · ' + rulesPanel.slug) : null}
          onClose={() => setRulesPanel(null)}
          onApply={(ids) => { if (rulesPanel.mode === 'book') applyBookRules(rulesPanel.slug, ids) }}
        />
      )}
    </div>
  )
}