import React, { useEffect, useMemo, useState } from 'react'
import { getRules, saveCustomRule, setDefaultRules, saveUserPreset } from '../api.js'

const KIND_LABEL = { noise: '噪音', chapter: '章节' }

// mode: 'global'(编辑全局默认)| 'book'(编辑某书 rules_selected)
// initialEnabled: book 模式下传该书当前勾选(null = 继承全局默认)
// onClose, onApply(enabledIds)  — book 模式由父组件落 meta;global 模式本组件直接 PUT
export default function RulesPanel({ mode = 'global', title, initialEnabled = null, onClose, onApply }) {
  const [presets, setPresets] = useState([])
  const [custom, setCustom] = useState([])
  const [userPresets, setUserPresets] = useState([])
  const [enabled, setEnabled] = useState(new Set())
  const [defaultEnabled, setDefaultEnabled] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [editRule, setEditRule] = useState(null)   // 自定义规则编辑表单
  const [presetName, setPresetName] = useState('')
  const [inheriting, setInheriting] = useState(mode === 'book' && initialEnabled == null)

  const load = () => {
    setLoading(true)
    return getRules().then(d => {
      setPresets(d.presets || [])
      setCustom(d.custom || [])
      setUserPresets(d.user_presets || [])
      setDefaultEnabled(d.default_enabled || [])
      const base = mode === 'book'
        ? (initialEnabled != null ? initialEnabled : d.default_enabled || [])
        : (d.default_enabled || [])
      setEnabled(new Set(base))
      setLoading(false)
    }).catch(e => { setErr(e.message || String(e)); setLoading(false) })
  }
  useEffect(() => { load() }, [])

  const allRules = useMemo(() => [...presets, ...custom], [presets, custom])
  const toggle = (id) => {
    if (inheriting) setInheriting(false)
    setEnabled(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  const apply = async () => {
    setErr(null)
    try {
      if (mode === 'global') {
        await setDefaultRules([...enabled])
        onApply?.([...enabled])
      } else {
        // book 模式:inheriting → 传 null(继承全局);否则传当前集合
        onApply?.(inheriting ? null : [...enabled])
      }
      onClose?.()
    } catch (e) { setErr(e.message || String(e)) }
  }

  const submitRule = async () => {
    const r = editRule
    if (!r.id || !r.pattern || !r.kind) { setErr('需要 id / kind / pattern'); return }
    try {
      await saveCustomRule(r._isNew ? 'add' : 'update', {
        id: r.id, kind: r.kind, name: r.name || r.id, pattern: r.pattern, desc: r.desc || '',
      })
      setEditRule(null); await load()
    } catch (e) { setErr(e.message || String(e)) }
  }
  const delRule = async (id) => {
    try { await saveCustomRule('delete', { id }); await load() }
    catch (e) { setErr(e.message || String(e)) }
  }

  const savePreset = async () => {
    if (!presetName.trim()) return
    try { await saveUserPreset('save', presetName.trim(), [...enabled]); setPresetName(''); await load() }
    catch (e) { setErr(e.message || String(e)) }
  }
  const loadPreset = (p) => { setInheriting(false); setEnabled(new Set(p.enabled || [])) }
  const delPreset = async (name) => {
    try { await saveUserPreset('delete', name, []); await load() }
    catch (e) { setErr(e.message || String(e)) }
  }

  const Section = ({ label, rules, builtin }) => (
    <div className="rp-sec">
      <div className="rp-sec-h">{label}</div>
      {rules.length === 0 && <div className="rp-empty">无</div>}
      {rules.map(r => (
        <label key={r.id} className="rp-rule">
          <input type="checkbox" checked={enabled.has(r.id)} onChange={() => toggle(r.id)} />
          <span className="rp-kind">{KIND_LABEL[r.kind] || r.kind}</span>
          <span className="rp-name">{r.name || r.id}</span>
          <code className="rp-pat" title={r.pattern}>{r.pattern}</code>
          {!builtin && (
            <span className="rp-ops">
              <button onClick={(e) => { e.preventDefault(); setEditRule({ ...r, _isNew: false }) }}>改</button>
              <button onClick={(e) => { e.preventDefault(); delRule(r.id) }}>删</button>
            </span>
          )}
        </label>
      ))}
    </div>
  )

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal rp-modal" onClick={e => e.stopPropagation()}>
        <h3 className="modal-h">{title || (mode === 'global' ? '清洗规则 · 全局默认' : '清洗规则 · 本书')}</h3>
        {mode === 'book' && (
          <label className="rp-inherit">
            <input type="checkbox" checked={inheriting}
              onChange={() => { setInheriting(v => !v); if (inheriting) {/*取消继承,保留当前*/} else setEnabled(new Set(defaultEnabled)) }} />
            继承全局默认(取消勾选可单独定制本书)
          </label>
        )}
        {err && <div className="up-err">{err}</div>}
        {loading ? <div className="rp-empty">加载中…</div> : (
          <div className={'rp-body' + (inheriting ? ' rp-dim' : '')}>
            <Section label="预制规则(只读,打勾启用)" rules={presets} builtin={true} />
            <div className="rp-sec">
              <div className="rp-sec-h">自定义规则
                <button className="rp-add" onClick={() => setEditRule({ _isNew: true, kind: 'noise', id: '', name: '', pattern: '', desc: '' })}>+ 新增</button>
              </div>
              {custom.length === 0 && <div className="rp-empty">无</div>}
              {custom.map(r => (
                <label key={r.id} className="rp-rule">
                  <input type="checkbox" checked={enabled.has(r.id)} onChange={() => toggle(r.id)} />
                  <span className="rp-kind">{KIND_LABEL[r.kind] || r.kind}</span>
                  <span className="rp-name">{r.name || r.id}</span>
                  <code className="rp-pat" title={r.pattern}>{r.pattern}</code>
                  <span className="rp-ops">
                    <button onClick={(e) => { e.preventDefault(); setEditRule({ ...r, _isNew: false }) }}>改</button>
                    <button onClick={(e) => { e.preventDefault(); delRule(r.id) }}>删</button>
                  </span>
                </label>
              ))}
            </div>

            <div className="rp-sec">
              <div className="rp-sec-h">预设(命名一组勾选,复用)</div>
              <div className="rp-presets">
                {userPresets.map(p => (
                  <span key={p.name} className="rp-preset">
                    <button onClick={() => loadPreset(p)}>{p.name}</button>
                    <button className="rp-preset-del" onClick={() => delPreset(p.name)}>×</button>
                  </span>
                ))}
              </div>
              <div className="rp-save-preset">
                <input value={presetName} placeholder="预设名" onChange={e => setPresetName(e.target.value)} />
                <button onClick={savePreset} disabled={!presetName.trim()}>存为预设</button>
              </div>
            </div>
          </div>
        )}

        <div className="modal-actions">
          <button onClick={onClose}>取消</button>
          <button className="up-btn" onClick={apply}>{mode === 'global' ? '保存默认' : '应用到本书'}</button>
        </div>

        {/* 自定义规则编辑子弹层 */}
        {editRule && (
          <div className="modal-bg" onClick={() => setEditRule(null)}>
            <div className="modal" onClick={e => e.stopPropagation()}>
              <h3 className="modal-h">{editRule._isNew ? '新增自定义规则' : '编辑规则'}</h3>
              <label className="fld"><span>ID(唯一,不可与预制重名)</span>
                <input value={editRule.id} disabled={!editRule._isNew}
                  onChange={e => setEditRule({ ...editRule, id: e.target.value.replace(/\s/g, '_') })} /></label>
              <label className="fld"><span>类型</span>
                <select value={editRule.kind} onChange={e => setEditRule({ ...editRule, kind: e.target.value })}>
                  <option value="noise">噪音(整行匹配即删)</option>
                  <option value="chapter">章节(标题行)</option>
                </select></label>
              <label className="fld"><span>名称</span>
                <input value={editRule.name} onChange={e => setEditRule({ ...editRule, name: e.target.value })} /></label>
              <label className="fld"><span>正则(Python re,整行 match)</span>
                <input value={editRule.pattern} onChange={e => setEditRule({ ...editRule, pattern: e.target.value })} /></label>
              <label className="fld"><span>说明</span>
                <input value={editRule.desc} onChange={e => setEditRule({ ...editRule, desc: e.target.value })} /></label>
              <div className="modal-actions">
                <button onClick={() => setEditRule(null)}>取消</button>
                <button className="up-btn" onClick={submitRule}>保存</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}