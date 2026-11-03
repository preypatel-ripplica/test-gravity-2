import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../api'
import { useAuth } from '../context/AuthContext'
import { useUI } from '../context/UIContext'

function defaultReportMonth() {
  const now = new Date()
  // Prefer previous calendar month (complete GSC month)
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function monthLabel(yyyyMm) {
  if (!yyyyMm) return '—'
  const [y, m] = yyyyMm.split('-').map(Number)
  if (!y || !m) return yyyyMm
  return new Date(y, m - 1, 1).toLocaleString(undefined, { month: 'long', year: 'numeric' })
}

function statusChip(status) {
  const key = (status || '').toLowerCase()
  const label = key ? key.charAt(0).toUpperCase() + key.slice(1) : '—'
  return <span className={`report-status-chip ${key}`}>{label}</span>
}

export default function WebsiteMonthlyReportsPanel({ clientId, connected }) {
  const { token } = useAuth()
  const { toast } = useUI()

  const [reports, setReports] = useState([])
  const [reportMonth, setReportMonth] = useState(defaultReportMonth)
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState(null)
  const [html, setHtml] = useState('')
  const [loadingList, setLoadingList] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [refining, setRefining] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [refinePrompt, setRefinePrompt] = useState('')

  const loadList = useCallback(async () => {
    if (!token || !clientId) return
    setLoadingList(true)
    try {
      const data = await api.listWebsiteMonthlyReports(token, clientId)
      setReports(data.reports || [])
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setLoadingList(false)
    }
  }, [token, clientId, toast])

  const loadDetail = useCallback(
    async (reportId) => {
      if (!token || !clientId || !reportId) return
      try {
        const data = await api.getWebsiteMonthlyReport(token, clientId, reportId)
        setDetail(data)
        setSelectedId(reportId)
        if (data.html_url || data.status === 'draft' || data.status === 'ready') {
          try {
            const text = await api.fetchWebsiteMonthlyReportHtml(token, reportId)
            setHtml(text)
          } catch {
            setHtml('')
          }
        } else {
          setHtml('')
        }
      } catch (err) {
        toast(err.message, 'error')
      }
    },
    [token, clientId, toast],
  )

  useEffect(() => {
    loadList()
  }, [loadList])

  const history = useMemo(
    () => [...(detail?.refine_history || [])].reverse().slice(0, 4),
    [detail],
  )

  async function handleGenerate(event) {
    event.preventDefault()
    if (!connected) {
      toast('Connect Google first', 'error')
      return
    }
    setGenerating(true)
    try {
      const data = await api.generateWebsiteMonthlyReport(token, clientId, reportMonth)
      toast('Draft generated', 'success')
      await loadList()
      setDetail(data)
      setSelectedId(data.id)
      if (data.id) {
        const text = await api.fetchWebsiteMonthlyReportHtml(token, data.id)
        setHtml(text)
      }
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setGenerating(false)
    }
  }

  async function handleRefine(event) {
    event.preventDefault()
    if (!detail?.id || !refinePrompt.trim()) return
    setRefining(true)
    try {
      const data = await api.refineWebsiteMonthlyReport(
        token,
        clientId,
        detail.id,
        refinePrompt.trim(),
      )
      setDetail(data)
      setRefinePrompt('')
      const text = await api.fetchWebsiteMonthlyReportHtml(token, data.id)
      setHtml(text)
      toast('Draft refined', 'success')
      await loadList()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setRefining(false)
    }
  }

  async function handleFinalize() {
    if (!detail?.id) return
    setFinalizing(true)
    try {
      const data = await api.finalizeWebsiteMonthlyReport(token, clientId, detail.id)
      setDetail(data)
      toast('PDF finalized', 'success')
      await loadList()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setFinalizing(false)
    }
  }

  async function handleRevise() {
    if (!detail?.id) return
    try {
      const data = await api.reviseWebsiteMonthlyReport(token, clientId, detail.id)
      setDetail(data)
      toast('Unlocked for edits', 'success')
      await loadList()
    } catch (err) {
      toast(err.message, 'error')
    }
  }

  async function handleDownload() {
    if (!detail?.id) return
    setDownloading(true)
    try {
      const blob = await api.fetchWebsiteMonthlyReportPdfBlob(token, detail.id)
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = `${detail.report_month || 'report'}-website-report.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(objectUrl)
    } catch (err) {
      toast(err.message || 'PDF not available', 'error')
    } finally {
      setDownloading(false)
    }
  }

  const isDraft = detail?.status === 'draft'
  const isReady = detail?.status === 'ready'

  return (
    <section className="access-panel card animate-fade-in" style={{ marginBottom: 24 }}>
      <div className="access-panel-head">
        <div>
          <h2>Monthly PDF reports</h2>
          <p className="text-muted">
            Generate a draft from Search Console + PageSpeed, refine conversationally, then finalize the PDF.
          </p>
        </div>
      </div>

      <form className="website-monthly-generate" onSubmit={handleGenerate}>
        <label>
          Report month
          <input
            type="month"
            value={reportMonth}
            onChange={(event) => setReportMonth(event.target.value)}
            disabled={generating}
          />
        </label>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!connected || generating || !reportMonth}
        >
          <i className={`fa-solid ${generating ? 'fa-spinner fa-spin' : 'fa-file-lines'}`} />{' '}
          {generating ? 'Generating…' : 'Generate draft'}
        </button>
      </form>

      <div className="website-monthly-layout">
        <div className="website-monthly-list">
          <div className="text-muted" style={{ fontSize: 12, marginBottom: 8 }}>
            {loadingList ? 'Loading…' : `${reports.length} report${reports.length === 1 ? '' : 's'}`}
          </div>
          {reports.length === 0 ? (
            <p className="text-muted" style={{ fontSize: 13 }}>
              No monthly reports yet.
            </p>
          ) : (
            <ul>
              {reports.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    className={`website-monthly-item ${selectedId === row.id ? 'is-active' : ''}`}
                    onClick={() => loadDetail(row.id)}
                  >
                    <span>{monthLabel(row.report_month)}</span>
                    {statusChip(row.status)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="website-monthly-detail">
          {!detail ? (
            <div className="access-empty-state" style={{ padding: 28 }}>
              <i className="fa-solid fa-file-pdf" />
              <h3>Select or generate a report</h3>
              <p>Drafts stay editable until you finalize the PDF.</p>
            </div>
          ) : (
            <>
              <div className="website-monthly-detail-head">
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <h3 style={{ margin: 0 }}>{monthLabel(detail.report_month)}</h3>
                    {statusChip(detail.status)}
                  </div>
                  {detail.error ? (
                    <p style={{ color: '#b91c1c', margin: '8px 0 0', fontSize: 13 }}>{detail.error}</p>
                  ) : (
                    <p className="text-muted" style={{ margin: '6px 0 0', fontSize: 13 }}>
                      vs {monthLabel(detail.previous_month)}
                      {detail.metrics_summary?.current
                        ? ` · ${Number(detail.metrics_summary.current.clicks || 0).toLocaleString()} clicks`
                        : ''}
                    </p>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {isDraft && (
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={handleFinalize}
                      disabled={finalizing}
                    >
                      {finalizing ? 'Finalizing…' : 'Finalize PDF'}
                    </button>
                  )}
                  {isReady && (
                    <>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={handleDownload}
                        disabled={downloading}
                      >
                        {downloading ? 'Downloading…' : 'Download PDF'}
                      </button>
                      <button type="button" className="btn btn-secondary" onClick={handleRevise}>
                        Revise
                      </button>
                    </>
                  )}
                </div>
              </div>

              {isDraft && (
                <form onSubmit={handleRefine} style={{ marginBottom: 14 }}>
                  <div className="report-refine-row">
                    <textarea
                      value={refinePrompt}
                      onChange={(event) => setRefinePrompt(event.target.value)}
                      rows={2}
                      placeholder="Refine this draft… e.g. emphasize Hindi content, soften AI section"
                      disabled={refining}
                    />
                    <button
                      type="submit"
                      className="btn btn-primary"
                      disabled={refining || !refinePrompt.trim()}
                    >
                      {refining ? 'Refining…' : 'Refine'}
                    </button>
                  </div>
                  {history.length > 0 && (
                    <p className="text-muted" style={{ margin: '8px 0 0', fontSize: 12 }}>
                      Recent: {history.map((item) => item.prompt).filter(Boolean).join(' · ')}
                    </p>
                  )}
                </form>
              )}

              {html ? (
                <iframe
                  title="Website monthly report preview"
                  srcDoc={html}
                  className="website-monthly-iframe"
                />
              ) : (
                <p className="text-muted">
                  {detail.status === 'pending' ? 'Generating…' : 'HTML preview not available.'}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  )
}
