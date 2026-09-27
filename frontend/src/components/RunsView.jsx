import { useEffect, useState } from 'react'
import { getRuns } from '../api.js'
import { ErrorBanner, Spinner } from './ui.jsx'

export default function RunsView() {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true)
    getRuns(100)
      .then((data) => setRuns(data.runs || []))
      .catch(setError)
      .finally(() => setLoading(false))
  }, [])

  return (
    <section>
      <p className="eyebrow" style={{ marginBottom: 12 }}>Pipeline runs</p>
      <ErrorBanner error={error} />
      {loading ? <Spinner label="Loading runs…" /> : null}
      {!loading && !runs.length ? (
        <div className="empty">
          <h3>No runs yet</h3>
          <p>Trigger one from the Dashboard, or let the cron scheduler fire.</p>
        </div>
      ) : null}
      {runs.length ? (
        <table className="runs-table">
          <thead>
            <tr>
              <th>started</th>
              <th>trigger</th>
              <th>status</th>
              <th>scraped</th>
              <th>new</th>
              <th>scored</th>
              <th>alerts</th>
              <th>took</th>
              <th>error</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id} className={run.status === 'failed' ? 'runs-table__row--bad' : ''}>
                <td>{new Date(run.started_at + (run.started_at.endsWith('Z') ? '' : 'Z')).toLocaleString()}</td>
                <td><span className="badge">{run.trigger}</span></td>
                <td>
                  <span className={`badge ${run.status === 'completed' ? 'badge--ok' : run.status === 'failed' ? 'badge--no' : ''}`}>
                    {run.status}
                  </span>
                </td>
                <td>{run.jobs_scraped ?? '—'}</td>
                <td>{run.new_jobs ?? '—'}</td>
                <td>{run.scored ?? '—'}</td>
                <td>{run.alerts_sent ?? '—'}</td>
                <td>{run.finished_at && run.started_at
                  ? `${Math.max(0, Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000))}s`
                  : '—'}</td>
                <td className="runs-table__error">{run.error || ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}
