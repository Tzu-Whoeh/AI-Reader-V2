// API 封装。所有请求走 import.meta.env.BASE_URL,自动跟随 Vite base。
// 开发期 BASE_URL=/new/ → 请求 /new/api/...,由 dev proxy / nginx 透传到 server.py。
// 迁顶层时 base 改 / 即可,无需改此文件。
const API = import.meta.env.BASE_URL.replace(/\/$/, '') + '/api'

async function get(path) {
  const r = await fetch(API + path)
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`)
  return r.json()
}

export const getSummary = () => get('/summary')
export const getGraph = () => get('/graph')
export const getDimension = (name) => get('/dimension/' + encodeURIComponent(name))
export const getEvents = () => get('/events')
export const getChapters = () => get('/chapters')
export const getReader = (ch) => get('/reader/' + encodeURIComponent(ch))
export const getNode = (type, id) =>
  get(`/node/${encodeURIComponent(type)}/${encodeURIComponent(id)}`)

// ===== 任务层(M2)API =====
// tasks.py 是独立后端(开发期 :8090);部署时 nginx 把 <base>/tasks/* 反代到任务层。
// 双 base:读类走 server.py(上方 /api),任务类走任务层(/tasks/api)。
const TASKS = (import.meta.env.VITE_TASKS_BASE
  || import.meta.env.BASE_URL.replace(/\/$/, '') + '/tasks') + '/api'

async function tget(path) {
  const r = await fetch(TASKS + path)
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`)
  return r.json()
}
async function tpost(path, body, isJson = true) {
  const opt = { method: 'POST' }
  if (body !== undefined) {
    opt.body = body
    if (isJson) opt.headers = { 'Content-Type': 'text/plain' }
  }
  const r = await fetch(TASKS + path, opt)
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`)
  return r.json()
}

// 上传:支持 File 对象(multipart)或纯文本字符串
export const uploadText = (fileOrText) => {
  if (fileOrText instanceof File) {
    const fd = new FormData()
    fd.append('file', fileOrText)
    return tpost('/upload', fd, false)
  }
  return tpost('/upload', fileOrText)
}
export const startAnalyze = (jobId, presplit = false) =>
  tpost('/analyze/' + encodeURIComponent(jobId) + (presplit ? '?presplit=1' : ''))
export const getProgress = (jobId) => tget('/progress/' + encodeURIComponent(jobId))
export const getJobs = () => tget('/jobs')
