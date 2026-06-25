// API 封装。单后端单 base。读类支持 ?novel=<slug> 选择小说。
const API = import.meta.env.BASE_URL.replace(/\/$/, '') + '/api'

function nq(novel) { return novel ? ('?novel=' + encodeURIComponent(novel)) : '' }

async function get(path) {
  const r = await fetch(API + path)
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`)
  return r.json()
}
async function post(path, body, isJson = true) {
  const opt = { method: 'POST' }
  if (body !== undefined) {
    opt.body = body
    if (isJson) opt.headers = { 'Content-Type': 'text/plain' }
  }
  const r = await fetch(API + path, opt)
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).error || '' } catch {}
    const e = new Error(detail || `${path} → HTTP ${r.status}`)
    e.status = r.status
    throw e
  }
  return r.json()
}
async function req(method, path, jsonBody) {
  const opt = { method }
  if (jsonBody !== undefined) {
    opt.body = JSON.stringify(jsonBody)
    opt.headers = { 'Content-Type': 'text/plain' }   // 后端 get_json(force=True) 接受
  }
  const r = await fetch(API + path, opt)
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).error || '' } catch {}
    const e = new Error(detail || `${path} → HTTP ${r.status}`)
    e.status = r.status; throw e
  }
  return r.json()
}

// 只读(可带 novel slug)
export const getSummary = (novel) => get('/summary' + nq(novel))
export const getGraph = (novel) => get('/graph' + nq(novel))
export const getDimension = (name, novel) =>
  get('/dimension/' + encodeURIComponent(name) + nq(novel))
export const getEvents = (novel) => get('/events' + nq(novel))
export const getChapters = (novel) => get('/chapters' + nq(novel))
export const getReader = (ch, novel) =>
  get('/reader/' + encodeURIComponent(ch) + nq(novel))
export const getNode = (type, id, novel) =>
  get(`/node/${encodeURIComponent(type)}/${encodeURIComponent(id)}` + nq(novel))

// 小说库
export const getNovels = () => get('/novels')

// 任务(基于 slug)
export const uploadFile = (file) => {
  const fd = new FormData(); fd.append('file', file)
  return post('/upload', fd, false)
}
export const startAnalyze = (slug) =>
  post('/analyze/' + encodeURIComponent(slug))
export const getProgress = (slug) => get('/progress/' + encodeURIComponent(slug))

// 书库管理
export const updateNovelMeta = (slug, patch) =>
  req('PUT', '/novels/' + encodeURIComponent(slug) + '/meta', patch)
export const deleteNovel = (slug) =>
  req('DELETE', '/novels/' + encodeURIComponent(slug))

// 规则
export const getRules = () => get('/rules')
export const saveCustomRule = (op, rule) =>
  req('POST', '/rules/custom', { op, rule })
export const setDefaultRules = (enabled) =>
  req('PUT', '/rules/default', { enabled })
export const saveUserPreset = (op, name, enabled) =>
  req('POST', '/rules/presets', { op, name, enabled })
export const reclean = (slug) =>
  req('POST', '/reclean/' + encodeURIComponent(slug))