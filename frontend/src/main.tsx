import { FormEvent, useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { filterFindings } from './filters'
import './styles.css'

const API_ORIGIN = 'http://localhost:8100'
const API = `${API_ORIGIN}/api`

type EvidenceItem = { level?: string; message?: string; method?: string; url?: string; status?: number | string; error?: string }
type Redirect = { from: string; to: string; status: number }
type Finding = { id: string; severity: string; category: string; title: string; detail: string; page_url?: string }
type Page = {
  url: string
  final_url?: string
  depth: number
  status: number
  title: string
  h1: string
  meta_description: string
  load_ms: number
  screenshot_path?: string
  error_type?: string
  error_detail?: string
  redirect_chain: Redirect[]
  console: EvidenceItem[]
  network: EvidenceItem[]
}
type Summary = {
  pages_scanned?: number
  findings?: number
  console_errors?: number
  failed_requests?: number
  health_score?: number
  timeouts?: number
  robots_skipped?: number
  blocked_redirects?: number
  robots_policy?: string
  robots_detail?: string
  rate_limit_ms?: number
}
type Scan = {
  id: string
  url: string
  status: string
  created_at: string
  completed_at?: string
  max_pages: number
  max_depth: number
  error?: string
  summary: Summary
  pages?: Page[]
  findings?: Finding[]
}

function App() {
  const [url, setUrl] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const [maxPages, setMaxPages] = useState(25)
  const [scans, setScans] = useState<Scan[]>([])
  const [selected, setSelected] = useState<Scan | null>(null)
  const [selectedPageUrl, setSelectedPageUrl] = useState<string | null>(null)
  const [severity, setSeverity] = useState('all')
  const [category, setCategory] = useState('all')
  const [query, setQuery] = useState('')
  const [message, setMessage] = useState('')
  const [starting, setStarting] = useState(false)

  const loadScans = async () => {
    try {
      const response = await fetch(`${API}/scans`, { cache: 'no-store' })
      if (!response.ok) throw new Error()
      setScans(await response.json())
    } catch {
      setMessage('Cannot reach Website Explorer API. Start the backend on port 8100.')
    }
  }
  const openScan = async (id: string) => {
    const response = await fetch(`${API}/scans/${id}`, { cache: 'no-store' })
    if (response.ok) {
      const scan: Scan = await response.json()
      setSelected(scan)
      setSelectedPageUrl((current) => current && scan.pages?.some((page) => page.url === current) ? current : null)
    }
  }

  useEffect(() => { void loadScans() }, [])
  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadScans()
      if (selected?.status === 'queued' || selected?.status === 'running') void openScan(selected.id)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [selected?.id, selected?.status])
  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => setMessage(''), 4200)
    return () => window.clearTimeout(timer)
  }, [message])

  const start = async (event: FormEvent) => {
    event.preventDefault()
    if (!authorized) {
      setMessage('Confirm you own or are authorized to scan this website.')
      return
    }
    setStarting(true)
    try {
      const response = await fetch(`${API}/scans`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, authorized, max_pages: maxPages, max_depth: 3 }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail)
      setMessage('Website scan started. Results will update automatically.')
      setUrl('')
      setAuthorized(false)
      await loadScans()
      await openScan(payload.id)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not start the scan.')
    } finally {
      setStarting(false)
    }
  }

  const summary = selected?.summary || {}
  const findings = selected?.findings || []
  const categories = useMemo(() => [...new Set(findings.map((item) => item.category))].sort(), [findings])
  const visibleFindings = useMemo(
    () => filterFindings(findings, severity, category, query),
    [findings, severity, category, query],
  )
  const selectedPage = selected?.pages?.find((page) => page.url === selectedPageUrl) ?? null
  const pageFindings = selectedPage ? findings.filter((finding) => finding.page_url === selectedPage.url) : []

  return <main>
    <header>
      <div><span className="eyebrow">BugBuster Labs</span><h1>Website Explorer</h1><p>Authorized, read-only website health scans.</p></div>
      <button className="secondary" onClick={() => void loadScans()}>Refresh scans</button>
    </header>
    {message && <div className="toast" role="status">{message}</div>}
    <section className="card start-card">
      <h2>Start a website scan</h2>
      <form onSubmit={start}>
        <input aria-label="Website URL" required type="url" placeholder="https://your-website.com" value={url} onChange={(event) => setUrl(event.target.value)} />
        <label>Maximum pages <input type="number" min="1" max="250" value={maxPages} onChange={(event) => setMaxPages(Number(event.target.value))} /></label>
        <button disabled={starting}>{starting ? 'Starting scan…' : 'Start safe scan'}</button>
        <label className="consent"><input type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} /> I own this website or have authorization to scan it.</label>
      </form>
      <p className="muted">Same-domain navigation only. Robots rules and crawl delays are respected. The explorer never logs in, submits forms, purchases, deletes, or publishes.</p>
    </section>

    <div className="layout">
      <section className="card scan-list">
        <h2>Scan history</h2>
        {scans.length ? scans.map((scan) =>
          <button className={selected?.id === scan.id ? 'scan active' : 'scan'} key={scan.id} onClick={() => void openScan(scan.id)}>
            <b>{scan.url}</b><span>{scan.status} · {new Date(scan.created_at).toLocaleString()}</span>
          </button>,
        ) : <p className="muted">No scans yet.</p>}
      </section>
      <section className="card results">
        <h2>{selected ? selected.url : 'Scan results'}</h2>
        {!selected ? <p className="muted">Select a scan to view its evidence.</p> : <>
          {selected.status !== 'completed' && <p className="running">{selected.status === 'failed' ? selected.error : 'Scan in progress… Results refresh every few seconds.'}</p>}
          <div className="metrics">
            <article><b>{summary.health_score ?? '—'}</b><span>Health score</span></article>
            <article><b>{summary.pages_scanned ?? 0}</b><span>Pages scanned</span></article>
            <article><b>{summary.findings ?? 0}</b><span>Findings</span></article>
            <article><b>{summary.timeouts ?? 0}</b><span>Timeouts</span></article>
          </div>
          {summary.robots_policy && <div className="policy"><b>Robots policy: {summary.robots_policy.replace('_', ' ')}</b><span>{summary.robots_detail} Minimum delay: {summary.rate_limit_ms} ms.</span></div>}

          <div className="section-title"><h3>Findings</h3><span>{visibleFindings.length} of {findings.length}</span></div>
          <div className="filters" aria-label="Findings filters">
            <select aria-label="Filter by severity" value={severity} onChange={(event) => setSeverity(event.target.value)}>
              <option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
            </select>
            <select aria-label="Filter by category" value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="all">All categories</option>{categories.map((item) => <option value={item} key={item}>{item}</option>)}
            </select>
            <input aria-label="Search findings" type="search" placeholder="Search title, evidence, or URL" value={query} onChange={(event) => setQuery(event.target.value)} />
            {(severity !== 'all' || category !== 'all' || query) && <button className="link-button" onClick={() => { setSeverity('all'); setCategory('all'); setQuery('') }}>Clear</button>}
          </div>
          {visibleFindings.length ? <div className="findings">{visibleFindings.map((finding) =>
            <article key={finding.id}><span className={`badge ${finding.severity}`}>{finding.severity}</span><div><b>{finding.title}</b><p>{finding.detail}</p><small>{finding.category} · {finding.page_url}</small></div></article>,
          )}</div> : <p className="muted">{findings.length ? 'No findings match these filters.' : 'No findings recorded yet.'}</p>}

          <h3>Pages</h3>
          <div className="pages">{selected.pages?.map((page) =>
            <button className={selectedPageUrl === page.url ? 'page-row active' : 'page-row'} key={page.url} onClick={() => setSelectedPageUrl(page.url)}>
              <div><b>{page.title || 'Untitled page'}</b><p>{page.url}</p><small>Status {page.status || page.error_type || 'failed'} · {page.load_ms} ms · depth {page.depth}</small></div><span>View evidence →</span>
            </button>,
          )}</div>

          {selectedPage && <section className="evidence-panel" aria-label="Page evidence">
            <div className="section-title"><div><span className="eyebrow">Page evidence</span><h3>{selectedPage.title || 'Untitled page'}</h3></div><button className="close" aria-label="Close page evidence" onClick={() => setSelectedPageUrl(null)}>×</button></div>
            <a className="page-url" href={selectedPage.url} target="_blank" rel="noreferrer">{selectedPage.url}</a>
            {selectedPage.error_detail && <p className="error-box">{selectedPage.error_detail}</p>}
            <dl>
              <div><dt>Status</dt><dd>{selectedPage.status || 'Failed'}</dd></div>
              <div><dt>Load time</dt><dd>{selectedPage.load_ms} ms</dd></div>
              <div><dt>H1</dt><dd>{selectedPage.h1 || 'Missing'}</dd></div>
              <div><dt>Meta description</dt><dd>{selectedPage.meta_description || 'Missing'}</dd></div>
            </dl>
            {selectedPage.redirect_chain.length > 0 && <EvidenceList title="Redirects" items={selectedPage.redirect_chain.map((item) => `${item.status} ${item.from} → ${item.to}`)} />}
            <EvidenceList title={`Findings (${pageFindings.length})`} items={pageFindings.map((item) => `${item.severity.toUpperCase()}: ${item.title} — ${item.detail}`)} />
            <EvidenceList title={`Console (${selectedPage.console.length})`} items={selectedPage.console.map((item) => `${item.level}: ${item.message}`)} />
            <EvidenceList title={`Failed requests (${selectedPage.network.length})`} items={selectedPage.network.map((item) => `${item.method} ${item.url} — ${item.status}${item.error ? `: ${item.error}` : ''}`)} />
            {selectedPage.screenshot_path && <a className="screenshot" href={`${API_ORIGIN}/evidence/${selectedPage.screenshot_path}`} target="_blank" rel="noreferrer">Open full-page screenshot</a>}
          </section>}
        </>}
      </section>
    </div>
  </main>
}

function EvidenceList({ title, items }: { title: string; items: string[] }) {
  return <div className="evidence-list"><b>{title}</b>{items.length ? <ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>None recorded.</p>}</div>
}

createRoot(document.getElementById('root')!).render(<App />)
