// API 封装。单后端单 base:读类 + 任务类都走 import.meta.env.BASE_URL + /api。
// 合并后端(app/server/main.py)在同一前缀下同时提供两类端点。
const API = import.meta.env.BASE_URL.replace(/\/$/, '') + '/api'

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
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`)
  return r.json()
}

// 只读
export const getSummary = () => get('/summary')
export const getGraph = () => get('/graph')
export const getDimension = (name) => get('/dimension/' + encodeURIComponent(name))
export const getEvents = () => get('/events')
export const getChapters = () => get('/chapters')
export const getReader = (ch) => get('/reader/' + encodeURIComponent(ch))
export const getNode = (type, id) =>
  get(`/node/${encodeURIComponent(type)}/${encodeURIComponent(id)}`)

// 任务
export const uploadText = (fileOrText) => {
  if (fileOrText instanceof File) {
    const fd = new FormData(); fd.append('file', fileOrText)
    return post('/upload', fd, false)
  }
  return post('/upload', fileOrText)
}
export const startAnalyze = (jobId, presplit = false) =>
  post('/analyze/' + encodeURIComponent(jobId) + (presplit ? '?presplit=1' : ''))
export const getProgress = (jobId) => get('/progress/' + encodeURIComponent(jobId))
export const getJobs = () => get('/jobs')
