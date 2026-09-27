import { useEffect, useMemo, useState } from 'react'
import { getJobs, setJobStatus } from '../api.js'
import JobCard from './JobCard.jsx'
import { ErrorBanner, Spinner } from './ui.jsx'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'new', label: 'New' },
  { key: 'accepted', label: 'Accepted' },
]

export default function JobsView() {
  const [filter, setFilter] = useState('all')
  const [order, setOrder] = useState('score')
  const [search, setSearch] = useState('')
  const [jobs, setJobs] = useState([])
  const [counts, setCounts] = useState({ total: 0, new: 0, accepted: 0, rejected: 0 })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [busyKey, setBusyKey] = useState(null)
  const [rejectedOpen, setRejectedOpen] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const data = await getJobs({ order })
      setJobs(data.jobs || [])
      getJobs({ status: 'rejected', order })
        .then((r) => setCounts((c) => ({ ...c, rejected: r.total })))
        .catch(() => {})
      getJobs({ status: 'accepted', order })
        .then((r) => setCounts((c) => ({ ...c, accepted: r.total })))
        .catch(() => {})
      getJobs({ status: 'new', order })
        .then((r) => setCounts((c) => ({ ...c, new: r.total })))
        .catch(() => {})
    } catch (e) {
      setError(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order])

  async function handleStatus(job, status) {
    const prev = jobs
    setBusyKey(job.job_key)
    // Optimistic update; roll back on failure.
    setJobs((list) =>
      list.map((j) => (j.job_key === job.job_key ? { ...j, status } : j)),
    )
    try {
      await setJobStatus(job.job_key, status)
    } catch (e) {
      setError(e)
      setJobs(prev)
    } finally {
      setBusyKey(null)
    }
  }

  const visible = useMemo(() => {
    let list = jobs
    if (filter !== 'all') list = list.filter((j) => (j.status || 'new') === filter)
    if (search.trim()) {
      const needle = search.trim().toLowerCase()
      list = list.filter(
        (j) =>
          (j.title || '').toLowerCase().includes(needle) ||
          (j.company || '').toLowerCase().includes(needle) ||
          (j.location || '').toLowerCase().includes(needle),
      )
    }
    return list
  }, [jobs, filter, search])

  const main = visible.filter((j) => (j.status || 'new') !== 'rejected')
  const rejected = visible.filter((j) => (j.status || 'new') === 'rejected')

  return (
    <section>
      <p className="eyebrow" style={{ marginBottom: 12 }}>Job board</p>
      <div className="toolbar">
        <div className="chips-row">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className={`chip-btn ${filter === f.key ? 'chip-btn--on' : ''}`}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          className="input"
          type="search"
          placeholder="Search title, company, location…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label className="inline">
          sort
          <select className="select" value={order} onChange={(e) => setOrder(e.target.value)}>
            <option value="score">by score</option>
            <option value="recent">by recency</option>
            <option value="title">by title</option>
          </select>
        </label>
        <button className="btn" onClick={load} disabled={loading}>
          {loading ? <Spinner label="Loading…" /> : 'Refresh'}
        </button>
      </div>

      <ErrorBanner error={error} />

      {loading && !jobs.length ? <Spinner label="Loading jobs…" /> : null}

      {!loading && !visible.length ? (
        <div className="empty">
          <h3>No jobs in view</h3>
          <p>Run the pipeline from the Dashboard (or wait for the cron scheduler) to fill the board.</p>
        </div>
      ) : null}

      <div className="grid">
        {main.map((job) => (
          <JobCard key={job.job_key} job={job} onStatus={handleStatus} busy={busyKey === job.job_key} />
        ))}
      </div>

      {rejected.length ? (
        <div className="rejected-section">
          <button className="rejected-toggle" onClick={() => setRejectedOpen((v) => !v)}>
            ✕ Rejected ({rejected.length}) {rejectedOpen ? '▲' : '▼'}
          </button>
          {rejectedOpen ? (
            <div className="grid">
              {rejected.map((job) => (
                <JobCard key={job.job_key} job={job} onStatus={handleStatus} busy={busyKey === job.job_key} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
