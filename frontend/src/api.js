const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

async function readError(res) {
  let detail = `${res.status} ${res.statusText}`
  try {
    const data = await res.json()
    if (data && data.detail != null) {
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    }
  } catch {
    // non-JSON body — keep the status line
  }
  const err = new Error(detail)
  err.status = res.status
  return err
}

async function getJSON(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw await readError(res)
  return res.json()
}

async function postJSON(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok) throw await readError(res)
  return res.json()
}

export const getHealth = () => getJSON('/health')
export const getStats = () => getJSON('/stats')
export const getJobs = ({ status, order = 'score', limit = 200, offset = 0 } = {}) => {
  const q = new URLSearchParams()
  if (status) q.set('status', status)
  q.set('order', order)
  q.set('limit', String(limit))
  if (offset) q.set('offset', String(offset))
  return getJSON(`/jobs?${q.toString()}`)
}
export const getJob = (key) => getJSON(`/jobs/${encodeURIComponent(key)}`)
export const setJobStatus = (key, status) =>
  postJSON(`/jobs/${encodeURIComponent(key)}/status`, { new_status: status })
export const getRuns = (limit = 50) => getJSON(`/runs?limit=${limit}`)
export const startRun = (forceRescore = false) =>
  postJSON(`/run?force_rescore=${forceRescore}`)
export const getRunLatest = () => getJSON('/run/latest')
export const getScheduler = () => getJSON('/scheduler')
export const saveSchedulerConfig = (config) => postJSON('/scheduler/config', config)
export const toggleScheduler = (enabled) => postJSON(`/scheduler/toggle?enabled=${enabled}`)
export const getSettings = () => getJSON('/settings')
export const saveSettings = (settings) => postJSON('/settings', settings)
export const testNotify = () => postJSON('/notify/test')
export const getResumeInfo = () => getJSON('/resume')
export const uploadResume = (file) => {
  const form = new FormData()
  form.append('resume', file, file.name)
  return fetch(`${BASE}/resume`, { method: 'POST', body: form }).then(async (res) => {
    if (!res.ok) throw await readError(res)
    return res.json()
  })
}
export const exportUrl = () => `${BASE}/export.xlsx`
