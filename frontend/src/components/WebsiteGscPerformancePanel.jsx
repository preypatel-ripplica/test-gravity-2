import { useMemo, useState } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import { formatDateLabel, formatNumber, shortPagePath } from './websiteReportsShared'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip, Legend)

export default function WebsiteGscPerformancePanel({
  connected,
  loading,
  perfLoading,
  performance,
  googleConnection,
  connecting,
  onConnect,
  onDisconnect,
  onRefreshProperties,
  onRefreshPerformance,
}) {
  const [breakdownTab, setBreakdownTab] = useState('queries')
  const [selectedMetrics, setSelectedMetrics] = useState({ clicks: true, impressions: true })

  function toggleMetric(key) {
    setSelectedMetrics((current) => {
      const next = { ...current, [key]: !current[key] }
      if (!next.clicks && !next.impressions) return current
      return next
    })
  }

  const totals = performance?.totals

  const chartData = useMemo(() => {
    const daily = performance?.daily || []
    const labels = daily.map((row) => formatDateLabel(row.date))
    const datasets = []
    if (selectedMetrics.clicks) {
      datasets.push({
        label: 'Clicks',
        data: daily.map((row) => row.clicks),
        borderColor: '#4285f4',
        backgroundColor: 'rgba(66, 133, 244, 0.12)',
        yAxisID: 'y',
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
        fill: false,
      })
    }
    if (selectedMetrics.impressions) {
      datasets.push({
        label: 'Impressions',
        data: daily.map((row) => row.impressions),
        borderColor: '#a142f4',
        backgroundColor: 'rgba(161, 66, 244, 0.08)',
        yAxisID: 'y1',
        tension: 0.25,
        pointRadius: 0,
        borderWidth: 2,
        fill: false,
      })
    }
    return { labels, datasets }
  }, [performance, selectedMetrics])

  const chartOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => {
              const idx = items[0]?.dataIndex
              return performance?.daily?.[idx]?.date || ''
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            maxTicksLimit: 8,
            color: '#64748b',
            font: { size: 11 },
          },
        },
        y: {
          display: selectedMetrics.clicks,
          position: 'left',
          grid: { color: 'rgba(148, 163, 184, 0.18)' },
          ticks: { color: '#4285f4', font: { size: 11 } },
          title: { display: selectedMetrics.clicks, text: 'Clicks', color: '#4285f4', font: { size: 11 } },
        },
        y1: {
          display: selectedMetrics.impressions,
          position: 'right',
          grid: { drawOnChartArea: false },
          ticks: { color: '#a142f4', font: { size: 11 } },
          title: {
            display: selectedMetrics.impressions,
            text: 'Impressions',
            color: '#a142f4',
            font: { size: 11 },
          },
        },
      },
    }),
    [performance, selectedMetrics],
  )

  const breakdownRows =
    breakdownTab === 'pages' ? performance?.pages || [] : performance?.queries || []

  return (
    <>
      <div className="website-gsc-toolbar">
        <div className="connection-status-pill card">
          <span className={`status-dot ${connected ? 'connected' : 'disconnected'}`} />
          <span>
            {loading
              ? 'Loading…'
              : connected
                ? googleConnection.connected_email || 'Google connected'
                : 'Not connected'}
          </span>
        </div>
        <div className="website-gsc-toolbar-actions">
          {!connected ? (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onConnect}
              disabled={loading || connecting}
            >
              <i className="fa-brands fa-google" /> {connecting ? 'Opening…' : 'Connect Google'}
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onRefreshProperties}
                disabled={loading || perfLoading}
              >
                <i className="fa-solid fa-list" /> Properties
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={onDisconnect}
                disabled={loading || perfLoading}
              >
                <i className="fa-solid fa-unlink" /> Disconnect
              </button>
            </>
          )}
          <button
            type="button"
            className="btn btn-primary"
            disabled={!connected || loading || perfLoading}
            onClick={onRefreshPerformance}
          >
            <i className={`fa-solid fa-arrows-rotate ${perfLoading ? 'fa-spin' : ''}`} />{' '}
            {perfLoading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      <section className="access-panel card animate-fade-in" style={{ marginBottom: 24 }}>
        <div className="access-panel-head">
          <div>
            <h2>Performance</h2>
            <p className="text-muted">
              {performance?.property
                ? `${performance.property} · ${performance.period?.start_date} → ${performance.period?.end_date} · Web`
                : connected
                  ? 'Loading Search Console search analytics…'
                  : 'Connect Google to pull Search Console performance.'}
            </p>
          </div>
        </div>

        {!connected ? (
          <div className="access-empty-state">
            <i className="fa-brands fa-google" />
            <h3>Connect Google Search Console</h3>
            <p>OAuth once, then we pull the same Performance metrics you see in GSC.</p>
          </div>
        ) : loading || (perfLoading && !performance) ? (
          <div className="inline-loading">
            <i className="fa-solid fa-spinner fa-spin" /> Loading performance…
          </div>
        ) : !performance ? (
          <div className="access-empty-state">
            <i className="fa-solid fa-chart-line" />
            <h3>No performance data</h3>
            <p>Save a site URL / GSC property in Data sources, then hit Refresh.</p>
          </div>
        ) : (
          <>
            <div className="gsc-scorecards">
              <button
                type="button"
                className={`gsc-scorecard ${selectedMetrics.clicks ? 'is-active is-clicks' : ''}`}
                onClick={() => toggleMetric('clicks')}
              >
                <span className="gsc-scorecard-label">Total clicks</span>
                <span className="gsc-scorecard-value">{formatNumber(totals?.clicks)}</span>
              </button>
              <button
                type="button"
                className={`gsc-scorecard ${selectedMetrics.impressions ? 'is-active is-impressions' : ''}`}
                onClick={() => toggleMetric('impressions')}
              >
                <span className="gsc-scorecard-label">Total impressions</span>
                <span className="gsc-scorecard-value">{formatNumber(totals?.impressions)}</span>
              </button>
              <div className="gsc-scorecard is-static">
                <span className="gsc-scorecard-label">Average CTR</span>
                <span className="gsc-scorecard-value">{Number(totals?.ctr || 0).toFixed(1)}%</span>
              </div>
              <div className="gsc-scorecard is-static">
                <span className="gsc-scorecard-label">Average position</span>
                <span className="gsc-scorecard-value">{Number(totals?.position || 0).toFixed(1)}</span>
              </div>
            </div>

            <div className="gsc-chart-wrap">
              {(performance.daily || []).length ? (
                <Line data={chartData} options={chartOptions} />
              ) : (
                <div className="access-empty-state" style={{ padding: 32 }}>
                  <p>No daily rows in this period.</p>
                </div>
              )}
            </div>

            <div className="gsc-breakdown-tabs">
              {[
                { id: 'queries', label: 'Queries' },
                { id: 'pages', label: 'Pages' },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  className={`gsc-breakdown-tab ${breakdownTab === tab.id ? 'is-active' : ''}`}
                  onClick={() => setBreakdownTab(tab.id)}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="gsc-table-wrap">
              <table className="gsc-table">
                <thead>
                  <tr>
                    <th>{breakdownTab === 'pages' ? 'Top pages' : 'Top queries'}</th>
                    <th>Clicks</th>
                    <th>Impressions</th>
                    <th>CTR</th>
                    <th>Position</th>
                  </tr>
                </thead>
                <tbody>
                  {breakdownRows.length ? (
                    breakdownRows.map((row) => (
                      <tr key={row.key}>
                        <td title={row.key}>
                          {breakdownTab === 'pages' ? shortPagePath(row.key) : row.key}
                        </td>
                        <td>{Number(row.clicks || 0).toLocaleString()}</td>
                        <td>{Number(row.impressions || 0).toLocaleString()}</td>
                        <td>{Number(row.ctr || 0).toFixed(1)}%</td>
                        <td>{Number(row.position || 0).toFixed(1)}</td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={5} className="text-muted">
                        No rows returned for this dimension.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </>
  )
}
