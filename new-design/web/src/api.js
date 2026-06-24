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
export const getNode = (type, id) =>
  get(`/node/${encodeURIComponent(type)}/${encodeURIComponent(id)}`)
