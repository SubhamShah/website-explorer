import { FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { filterFindings } from './filters'
import { healthScoreTone } from './health'
import { sitemapPresentation, type SitemapStatus } from './sitemap'
import './styles.css'
import './progress.css'
import './results.css'
import './controls.css'
import './insights.css'

const API_ORIGIN = 'http://localhost:8100'
const API = `${API_ORIGIN}/api`

type EvidenceItem = {
  level?: string
  message?: string
  method?: string
  url?: string
  status?: number | string
  resource_type?: string
  error?: string
  classification?: string
  failure_kind?: string
  severity?: string
  first_party?: boolean
  related_request_url?: string
  location?: { url?: string; lineNumber?: number; columnNumber?: number }
}
type Redirect = { from: string; to: string; status: number }
type ResponsiveViewport = {
  label: string
  width: number
  height: number
  screenshot_path?: string
  document_width?: number
  viewport_width?: number
  overflow_elements?: string[]
  unreadable_text?: string[]
  overlapping_elements?: string[]
  images_outside_viewport?: string[]
  hidden_content?: string[]
  visible_nav_links?: number
  visible_interactive_elements?: number
  menu_control_visible?: boolean
}
type ContentChecks = {
  duplicate_titles: boolean
  duplicate_descriptions: boolean
  headings: boolean
  broken_internal_links: boolean
  empty_pages: boolean
  placeholder_text: boolean
  short_content: boolean
  missing_image_alt: boolean
  canonical_tags: boolean
  short_content_words: number
}
type SiteAnalysis = {
  sitemap_sources?: string[]
  sitemap_errors?: { url: string; status: number | string; detail?: string }[]
  sitemap_truncated?: boolean
  sitemap_status?: SitemapStatus
  sitemap_status_detail?: string
  sitemap_comparison_available?: boolean
  sitemap_url_count?: number
  sitemap_urls_crawled?: number
  sitemap_urls_unchecked?: number
  crawled_url_count?: number
  orphan_page_count?: number
  orphan_pages?: string[]
  linked_missing_sitemap_count?: number
  linked_missing_sitemap?: string[]
  sitemap_page_error_count?: number
  sitemap_page_errors?: { url: string; status: number | string }[]
  robots_blocked_sitemap_count?: number
  robots_blocked_sitemap?: string[]
  noindex_page_count?: number
  noindex_pages?: string[]
  noindex_in_sitemap_count?: number
  noindex_in_sitemap?: string[]
  broken_internal_link_count?: number
  broken_internal_links?: string[]
}
type PageQuality = {
  h1_count?: number
  canonical_urls?: string[]
  robots_directives?: string[]
  noindex?: boolean
  word_count?: number
  placeholder_matches?: string[]
  images_missing_alt?: string[]
  images_missing_alt_count?: number
}
type Finding = {
  id: string
  severity: string
  category: string
  title: string
  detail: string
  page_url?: string
  discovered_on?: string[]
  fingerprint?: string
  confidence?: string
  verification?: string
  owner?: string
  what_happened?: string
  why_it_matters?: string
  recommended_action?: string
  severity_reason?: string
}
type IssueGroup = {
  group_id: string
  fingerprint: string
  severity: string
  category: string
  title: string
  count: number
  affected_pages: string[]
  sample_detail: string
  confidence: string
  verification: string
  owner: string
  what_happened: string
  why_it_matters: string
  recommended_action: string
  severity_reason: string
  page_priority: 'critical' | 'high_value' | 'standard'
  change_status?: 'new' | 'fixed' | 'recurring' | 'unchanged'
}
type ScanComparison = {
  baseline: null | { id: string; created_at: string; completed_at?: string; health_score?: number }
  counts: { new: number; fixed: number; recurring: number; unchanged: number }
  items: IssueGroup[]
}
type Page = {
  id: string
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
  redirect_chain?: Redirect[]
  console?: EvidenceItem[]
  network?: EvidenceItem[]
  priority: 'critical' | 'high_value' | 'standard'
  responsive?: Record<string, ResponsiveViewport>
  responsive_viewport_count?: number
  quality?: PageQuality
  findings?: Finding[]
}
type Summary = {
  pages_scanned?: number
  findings?: number
  console_errors?: number
  failed_requests?: number
  actionable_failed_requests?: number
  ignored_failed_requests?: number
  network_requests?: number
  api_requests?: number
  passed_requests?: number
  health_score?: number
  health_breakdown?: {
    page_reliability?: number
    network_failures?: number
    console_issues?: number
    seo_coverage?: number
    slow_pages?: number
  }
  timeouts?: number
  robots_policy?: string
  robots_detail?: string
  rate_limit_ms?: number
  responsive_viewports?: number
  responsive_issues?: number
  content_issues?: number
  indexing_issues?: number
  sitemap_urls?: number
}
type Scan = {
  id: string
  url: string
  status: string
  created_at: string
  max_pages: number
  max_depth: number
  error?: string
  summary: Summary
  pages?: Page[]
  findings?: Finding[]
  issue_groups?: IssueGroup[]
  comparison?: ScanComparison | null
  agency_name?: string
  report_title?: string
  brand_color?: string
  content_checks?: ContentChecks
  site_analysis?: SiteAnalysis
  page_count?: number
  finding_count?: number
}

type PagedResponse<T> = {
  items: T[]
  total: number
  offset: number
  limit: number
  has_more: boolean
}

const DEFAULT_CONTENT_CHECKS: ContentChecks = {
  duplicate_titles: true,
  duplicate_descriptions: true,
  headings: true,
  broken_internal_links: true,
  empty_pages: true,
  placeholder_text: true,
  short_content: true,
  missing_image_alt: true,
  canonical_tags: true,
  short_content_words: 100,
}

function App() {
  const [url, setUrl] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const [maxPages, setMaxPages] = useState(25)
  const [scans, setScans] = useState<Scan[]>([])
  const [selected, setSelected] = useState<Scan | null>(null)
  const [expandedPageUrl, setExpandedPageUrl] = useState<string | null>(null)
  const [severity, setSeverity] = useState('issues')
  const [category, setCategory] = useState('all')
  const [query, setQuery] = useState('')
  const [findingsView, setFindingsView] = useState<'grouped' | 'individual'>('grouped')
  const [message, setMessage] = useState('')
  const [starting, setStarting] = useState(false)
  const [deletingScanId, setDeletingScanId] = useState<string | null>(null)
  const [agencyName, setAgencyName] = useState('')
  const [reportTitle, setReportTitle] = useState('')
  const [brandColor, setBrandColor] = useState('#187249')
  const [reportKind, setReportKind] = useState<'executive' | 'qa' | 'developer'>('executive')
  const [compareTo, setCompareTo] = useState('')
  const [shareExpiry, setShareExpiry] = useState(168)
  const [shareUrl, setShareUrl] = useState('')
  const [savingReport, setSavingReport] = useState(false)
  const [contentChecks, setContentChecks] = useState<ContentChecks>(DEFAULT_CONTENT_CHECKS)
  const [pagesTotal, setPagesTotal] = useState(0)
  const [findingsTotal, setFindingsTotal] = useState(0)
  const [loadingMorePages, setLoadingMorePages] = useState(false)
  const [loadingMoreFindings, setLoadingMoreFindings] = useState(false)
  const [pageEvidence, setPageEvidence] = useState<Record<string, Page>>({})
  const [loadingPageId, setLoadingPageId] = useState<string | null>(null)
  const scansRequestActive = useRef(false)
  const overviewRequestActive = useRef<string | null>(null)
  const statusRequestActive = useRef<string | null>(null)
  const collectionsRequestActive = useRef<string | null>(null)

  const findingsEndpoint = (scanId: string, offset: number, limit: number) => {
    const parameters = new URLSearchParams({
      offset: String(offset),
      limit: String(limit),
      severity,
      category,
    })
    if (query.trim()) parameters.set('query', query.trim())
    return `${API}/scans/${scanId}/findings?${parameters}`
  }

  const loadScans = async () => {
    if (scansRequestActive.current) return
    scansRequestActive.current = true
    try {
      const response = await fetch(`${API}/scans`, { cache: 'no-store' })
      if (!response.ok) throw new Error()
      setScans(await response.json())
    } catch {
      setMessage('Cannot reach Website Explorer API. Start the backend on port 8100.')
    } finally {
      scansRequestActive.current = false
    }
  }

  const openScan = async (id: string) => {
    if (overviewRequestActive.current) return
    overviewRequestActive.current = id
    try {
      const [overviewResponse, pagesResponse, findingsResponse] = await Promise.all([
        fetch(`${API}/scans/${id}`, { cache: 'no-store' }),
        fetch(`${API}/scans/${id}/pages?offset=0&limit=50`, { cache: 'no-store' }),
        fetch(findingsEndpoint(id, 0, 250), { cache: 'no-store' }),
      ])
      if (!overviewResponse.ok) return
      const scan: Scan = await overviewResponse.json()
      const pagesPayload: PagedResponse<Page> = pagesResponse.ok
        ? await pagesResponse.json()
        : { items: [], total: scan.page_count || 0, offset: 0, limit: 50, has_more: false }
      const findingsPayload: PagedResponse<Finding> = findingsResponse.ok
        ? await findingsResponse.json()
        : { items: [], total: scan.finding_count || 0, offset: 0, limit: 250, has_more: false }
      scan.pages = pagesPayload.items
      scan.findings = findingsPayload.items
      setSelected(scan)
      setPagesTotal(pagesPayload.total)
      setFindingsTotal(findingsPayload.total)
      setPageEvidence({})
      setExpandedPageUrl((current) => current && scan.pages?.some((page) => page.url === current) ? current : null)
    } finally {
      overviewRequestActive.current = null
    }
  }

  const refreshVisibleCollections = async (id: string) => {
    if (collectionsRequestActive.current === id) return
    collectionsRequestActive.current = id
    try {
      const [pagesResponse, findingsResponse] = await Promise.all([
        fetch(`${API}/scans/${id}/pages?offset=0&limit=50`, { cache: 'no-store' }),
        fetch(findingsEndpoint(id, 0, 250), { cache: 'no-store' }),
      ])
      if (pagesResponse.ok) {
        const payload: PagedResponse<Page> = await pagesResponse.json()
        setSelected((current) => current?.id === id ? { ...current, pages: payload.items } : current)
        setPagesTotal(payload.total)
      }
      if (findingsResponse.ok) {
        const payload: PagedResponse<Finding> = await findingsResponse.json()
        setSelected((current) => current?.id === id ? { ...current, findings: payload.items } : current)
        setFindingsTotal(payload.total)
      }
    } finally {
      collectionsRequestActive.current = null
    }
  }

  const pollScanStatus = async (id: string) => {
    if (statusRequestActive.current === id) return
    statusRequestActive.current = id
    try {
      const response = await fetch(`${API}/scans/${id}/status`, { cache: 'no-store' })
      if (!response.ok) return
      const status: Scan = await response.json()
      const isActive = status.status === 'queued' || status.status === 'running'
      setSelected((current) => current?.id === id
        ? { ...current, status: status.status, summary: status.summary, error: status.error }
        : current)
      if (isActive) await refreshVisibleCollections(id)
      else await openScan(id)
    } finally {
      statusRequestActive.current = null
    }
  }

  useEffect(() => { void loadScans() }, [])
  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadScans()
      if (selected?.status === 'queued' || selected?.status === 'running') void pollScanStatus(selected.id)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [selected?.id, selected?.status])
  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => setMessage(''), 4200)
    return () => window.clearTimeout(timer)
  }, [message])
  useEffect(() => {
    if (!selected || findingsView !== 'individual') return
    const scanId = selected.id
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(findingsEndpoint(scanId, 0, 250), {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!response.ok) return
        const payload: PagedResponse<Finding> = await response.json()
        setSelected((current) => current?.id === scanId
          ? { ...current, findings: payload.items }
          : current)
        setFindingsTotal(payload.total)
      } catch (error) {
        if (!(error instanceof DOMException && error.name === 'AbortError')) {
          setMessage('Could not apply the findings filter.')
        }
      }
    }, 250)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [selected?.id, findingsView, severity, category, query])
  useEffect(() => {
    setAgencyName(selected?.agency_name || '')
    setReportTitle(selected?.report_title || '')
    setBrandColor(selected?.brand_color || '#187249')
    setCompareTo('')
    setShareUrl('')
  }, [selected?.id])

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
        body: JSON.stringify({ url, authorized, max_pages: maxPages, max_depth: 3, content_checks: contentChecks }),
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

  const deleteScan = async (scan: Scan) => {
    const action = scan.status === 'queued' || scan.status === 'running' ? 'cancel and delete' : 'delete'
    if (!window.confirm(`Permanently ${action} the scan for ${scan.url}?`)) return
    setDeletingScanId(scan.id)
    try {
      const response = await fetch(`${API}/scans/${scan.id}`, { method: 'DELETE' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'Could not delete the scan.')
      if (selected?.id === scan.id) {
        setSelected(null)
        setExpandedPageUrl(null)
        setPagesTotal(0)
        setFindingsTotal(0)
        setPageEvidence({})
      }
      setScans((current) => current.filter((item) => item.id !== scan.id))
      setMessage('Scan history and its saved evidence were deleted.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not delete the scan.')
    } finally {
      setDeletingScanId(null)
    }
  }

  const updatePagePriority = async (page: Page, priority: Page['priority']) => {
    if (!selected) return
    try {
      const response = await fetch(`${API}/scans/${selected.id}/pages/priority`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ page_url: page.url, priority }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'Could not update page importance.')
      await openScan(selected.id)
      setMessage(`Page importance changed to ${priority.replace(/_/g, ' ')}.`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not update page importance.')
    }
  }

  const saveReportSettings = async () => {
    if (!selected) return
    setSavingReport(true)
    try {
      const response = await fetch(`${API}/scans/${selected.id}/report-settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agency_name: agencyName || null, report_title: reportTitle || null, brand_color: brandColor }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'Could not save report branding.')
      setSelected((current) => current ? { ...current, ...payload } : current)
      setMessage('Report branding saved.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not save report branding.')
    } finally {
      setSavingReport(false)
    }
  }

  const reportUrl = (format: 'pdf' | 'csv' | 'xlsx') => {
    if (!selected) return '#'
    const params = new URLSearchParams({ kind: reportKind })
    if (compareTo) params.set('compare_to', compareTo)
    return `${API}/scans/${selected.id}/reports/${format}?${params}`
  }

  const createShareLink = async () => {
    if (!selected) return
    try {
      const response = await fetch(`${API}/scans/${selected.id}/report-shares`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          report_kind: reportKind,
          expires_hours: shareExpiry,
          comparison_scan_id: compareTo || null,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'Could not create the report link.')
      setShareUrl(payload.url)
      try { await navigator.clipboard.writeText(payload.url) } catch { /* Link remains available for manual copy. */ }
      setMessage('Read-only report link created and copied when clipboard access was available.')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not create the report link.')
    }
  }

  const loadMorePages = async () => {
    if (!selected || loadingMorePages || (selected.pages?.length || 0) >= pagesTotal) return
    const scanId = selected.id
    setLoadingMorePages(true)
    try {
      const response = await fetch(`${API}/scans/${scanId}/pages?offset=${selected.pages?.length || 0}&limit=50`, { cache: 'no-store' })
      if (!response.ok) throw new Error()
      const payload: PagedResponse<Page> = await response.json()
      setSelected((current) => current?.id === scanId
        ? { ...current, pages: [...(current.pages || []), ...payload.items] }
        : current)
      setPagesTotal(payload.total)
    } catch {
      setMessage('Could not load the next page results.')
    } finally {
      setLoadingMorePages(false)
    }
  }

  const loadMoreFindings = async () => {
    if (!selected || loadingMoreFindings || (selected.findings?.length || 0) >= findingsTotal) return
    const scanId = selected.id
    setLoadingMoreFindings(true)
    try {
      const response = await fetch(findingsEndpoint(scanId, selected.findings?.length || 0, 250), { cache: 'no-store' })
      if (!response.ok) throw new Error()
      const payload: PagedResponse<Finding> = await response.json()
      setSelected((current) => current?.id === scanId
        ? { ...current, findings: [...(current.findings || []), ...payload.items] }
        : current)
      setFindingsTotal(payload.total)
    } catch {
      setMessage('Could not load the next findings.')
    } finally {
      setLoadingMoreFindings(false)
    }
  }

  const togglePageEvidence = async (page: Page) => {
    if (expandedPageUrl === page.url) {
      setExpandedPageUrl(null)
      return
    }
    setExpandedPageUrl(page.url)
    if (!selected || pageEvidence[page.id]) return
    const scanId = selected.id
    setLoadingPageId(page.id)
    try {
      const response = await fetch(`${API}/scans/${scanId}/pages/${page.id}`, { cache: 'no-store' })
      if (!response.ok) throw new Error()
      const detail: Page = await response.json()
      setPageEvidence((current) => ({ ...current, [page.id]: detail }))
    } catch {
      setMessage('Could not load evidence for this page.')
    } finally {
      setLoadingPageId(null)
    }
  }

  const summary = selected?.summary || {}
  const scanInProgress = selected?.status === 'queued' || selected?.status === 'running'
  const findings = selected?.findings || []
  const issueGroups = selected?.issue_groups || []
  const categories = useMemo(
    () => [...new Set([...findings, ...issueGroups].map((item) => item.category))].sort(),
    [findings, issueGroups],
  )
  const visibleFindings = useMemo(
    () => filterFindings(findings, severity, category, query),
    [findings, severity, category, query],
  )
  const visibleGroups = useMemo(() => {
    const term = query.trim().toLocaleLowerCase()
    return issueGroups.filter((group) => {
      if (severity !== 'all' && severity !== 'issues' && group.severity !== severity) return false
      if (category !== 'all' && group.category !== category) return false
      if (!term) return true
      return [
        group.title,
        group.sample_detail,
        group.what_happened,
        group.why_it_matters,
        group.recommended_action,
        group.owner,
        ...group.affected_pages,
      ].join(' ').toLocaleLowerCase().includes(term)
    })
  }, [issueGroups, severity, category, query])
  const comparableScans = scans.filter(
    (scan) => scan.id !== selected?.id && scan.url === selected?.url && scan.status === 'completed',
  )

  return <main>
    <header>
      <div><span className="eyebrow">BugBuster Labs</span><h1>Website Explorer</h1><p>Authorized, read-only website health scans.</p></div>
      <button className="secondary" onClick={() => void loadScans()}>Refresh scans</button>
    </header>
    {message && <div className="toast" role="status">{message}</div>}
    {scanInProgress && <div className="progress-banner" role="status" aria-live="polite">
      <span className="progress-dot" aria-hidden="true" />
      <div><b>Scan in progress</b><span>Pages and findings refresh automatically until the scan completes.</span></div>
      <strong className="progress-count">{summary.pages_scanned ?? selected.pages?.length ?? 0} / {selected.max_pages} pages</strong>
    </div>}

    <section className="card start-card">
      <h2>Start a website scan</h2>
      <form onSubmit={start}>
        <label className="scan-field website-field"><span>Website URL</span><input required type="url" placeholder="https://your-website.com" value={url} onChange={(event) => setUrl(event.target.value)} /></label>
        <label className="scan-field page-limit-field">
          <span>Maximum pages <small>1-250</small></span>
          <div className="page-stepper">
            <button type="button" aria-label="Decrease maximum pages" onClick={() => setMaxPages((current) => Math.max(1, current - 1))}>-</button>
            <input aria-label="Maximum pages" type="number" min="1" max="250" value={maxPages} onChange={(event) => setMaxPages(Math.min(250, Math.max(1, Number(event.target.value))))} />
            <button type="button" aria-label="Increase maximum pages" onClick={() => setMaxPages((current) => Math.min(250, current + 1))}>+</button>
          </div>
        </label>
        <button className="scan-start-button" disabled={starting}><span>{starting ? 'Starting scan...' : 'Start safe scan'}</span><small>Authorized read-only crawl</small></button>
        <label className="consent"><input type="checkbox" checked={authorized} onChange={(event) => setAuthorized(event.target.checked)} /> I own this website or have authorization to scan it.</label>
        <details className="content-check-settings">
          <summary>Content-quality checks <span>9 configurable checks enabled by default</span></summary>
          <div className="check-grid">
            {([
              ['duplicate_titles', 'Duplicate titles'],
              ['duplicate_descriptions', 'Duplicate descriptions'],
              ['headings', 'Missing or multiple H1'],
              ['broken_internal_links', 'Broken internal links'],
              ['empty_pages', 'Empty pages'],
              ['placeholder_text', 'Placeholder text'],
              ['short_content', 'Extremely short content'],
              ['missing_image_alt', 'Missing image alternative text'],
              ['canonical_tags', 'Incorrect canonical tags'],
            ] as [keyof Omit<ContentChecks, 'short_content_words'>, string][]).map(([key, label]) =>
              <label key={key}><input type="checkbox" checked={contentChecks[key]} onChange={(event) => setContentChecks((current) => ({ ...current, [key]: event.target.checked }))} /> {label}</label>,
            )}
            <label className="word-threshold"><span>Short-content minimum</span><input type="number" min="20" max="500" value={contentChecks.short_content_words} disabled={!contentChecks.short_content} onChange={(event) => setContentChecks((current) => ({ ...current, short_content_words: Math.min(500, Math.max(20, Number(event.target.value))) }))} /><small>visible words</small></label>
          </div>
        </details>
      </form>
      <p className="muted">Same-domain navigation only. Robots rules and crawl delays are respected. The explorer never logs in, submits forms, purchases, deletes, or publishes.</p>
    </section>

    <div className="layout">
      <section className="card scan-list">
        <h2>Scan history</h2>
        {scans.length ? scans.map((scan) =>
          <div className={selected?.id === scan.id ? 'scan-entry active' : 'scan-entry'} key={scan.id}>
            <button className="scan" onClick={() => void openScan(scan.id)}>
              <b>{scan.url}</b><span>{scan.status} - {new Date(scan.created_at).toLocaleString()}</span>
            </button>
            <button className="scan-delete" disabled={deletingScanId === scan.id} aria-label={`Delete scan for ${scan.url}`} title="Delete scan" onClick={() => void deleteScan(scan)}>
              {deletingScanId === scan.id ? '...' : 'Delete'}
            </button>
          </div>,
        ) : <p className="muted">No scans yet.</p>}
      </section>

      <section className="card results">
        <h2>{selected ? selected.url : 'Scan results'}</h2>
        {!selected ? <p className="muted">Select a scan to view its evidence.</p> : <>
          {selected.status === 'failed' && <p className="running">{selected.error || 'The scan failed without an error message. Restart the backend without reload mode and try again.'}</p>}
          <div className="metrics">
            <article className={`health-metric ${healthScoreTone(summary.health_score)}`}><b>{summary.health_score ?? '-'}</b><span>Health score <small>/ 100</small></span></article>
            <article><b>{summary.pages_scanned ?? 0}</b><span>Pages scanned</span></article>
            <article><b>{summary.network_requests ?? 0}</b><span>Network requests</span></article>
            <article><b>{summary.actionable_failed_requests ?? summary.failed_requests ?? 0}</b><span>Actionable failures</span></article>
            <article><b>{summary.responsive_issues ?? 0}</b><span>Responsive issues</span></article>
          </div>
          {summary.health_breakdown && <details className="score-explainer">
            <summary>How this health score is calculated</summary>
            <p>The score starts at 100. Deductions are based on issue rates, not the total size of the crawl. {summary.ignored_failed_requests ? `${summary.ignored_failed_requests} low-impact network failures were excluded.` : ''}</p>
            <div className="score-breakdown">
              <span><b>-{summary.health_breakdown.page_reliability ?? 0}</b> Page reliability <small>max 30</small></span>
              <span><b>-{summary.health_breakdown.network_failures ?? 0}</b> Network failures <small>max 20</small></span>
              <span><b>-{summary.health_breakdown.console_issues ?? 0}</b> Console issues <small>max 15</small></span>
              <span><b>-{summary.health_breakdown.seo_coverage ?? 0}</b> SEO coverage <small>max 20</small></span>
              <span><b>-{summary.health_breakdown.slow_pages ?? 0}</b> Slow pages <small>max 15</small></span>
            </div>
          </details>}
          {summary.robots_policy && <div className="policy"><b>Robots policy: {summary.robots_policy.replace('_', ' ')}</b><span>{summary.robots_detail} Minimum delay: {summary.rate_limit_ms} ms.</span></div>}
          <SiteAnalysisPanel analysis={selected.site_analysis} />
          <ComparisonPanel comparison={selected.comparison} />
          <ReportPanel
            agencyName={agencyName}
            reportTitle={reportTitle}
            brandColor={brandColor}
            reportKind={reportKind}
            compareTo={compareTo}
            shareExpiry={shareExpiry}
            shareUrl={shareUrl}
            saving={savingReport}
            comparableScans={comparableScans}
            setAgencyName={setAgencyName}
            setReportTitle={setReportTitle}
            setBrandColor={setBrandColor}
            setReportKind={setReportKind}
            setCompareTo={setCompareTo}
            setShareExpiry={setShareExpiry}
            saveSettings={saveReportSettings}
            createShareLink={createShareLink}
            reportUrl={reportUrl}
          />

          <section className="result-panel findings-panel" aria-labelledby="findings-heading">
            <div className="result-panel-heading">
              <div><span className="eyebrow">Prioritized quality issues</span><h3 id="findings-heading">Findings</h3></div>
              <span>{findingsView === 'grouped' ? `${visibleGroups.length} root causes` : `${visibleFindings.length} shown · ${findings.length} of ${findingsTotal} loaded`}</span>
            </div>
            <div className="view-switch" role="group" aria-label="Findings view">
              <button className={findingsView === 'grouped' ? 'active' : ''} aria-pressed={findingsView === 'grouped'} onClick={() => setFindingsView('grouped')}>Grouped issues</button>
              <button className={findingsView === 'individual' ? 'active' : ''} aria-pressed={findingsView === 'individual'} onClick={() => setFindingsView('individual')}>Individual evidence</button>
            </div>
            <div className="filters" aria-label="Findings filters">
              <select aria-label="Filter by severity" value={severity} onChange={(event) => setSeverity(event.target.value)}>
                <option value="issues">Issues only</option><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="info">Info / passed</option>
              </select>
              <select aria-label="Filter by category" value={category} onChange={(event) => setCategory(event.target.value)}>
                <option value="all">All categories</option>{categories.map((item) => <option value={item} key={item}>{item}</option>)}
              </select>
              <input aria-label="Search findings" type="search" placeholder="Search title, evidence, or URL" value={query} onChange={(event) => setQuery(event.target.value)} />
              {(severity !== 'issues' || category !== 'all' || query) && <button className="link-button" onClick={() => { setSeverity('issues'); setCategory('all'); setQuery('') }}>Clear</button>}
            </div>
            <div className="result-scroll findings" tabIndex={0} aria-label="Scrollable findings">
              {findingsView === 'grouped'
                ? (visibleGroups.length
                    ? visibleGroups.map((group) => <IssueGroupCard group={group} key={group.group_id} />)
                    : <p className="muted">{issueGroups.length ? 'No grouped issues match these filters.' : 'No actionable root causes recorded yet.'}</p>)
                : (visibleFindings.length
                    ? visibleFindings.map((finding) => <FindingCard finding={finding} key={finding.id} />)
                    : <p className="muted">{findings.length ? 'No findings match these filters.' : 'No findings recorded yet.'}</p>)}
              {findings.length < findingsTotal && <button className="load-more" disabled={loadingMoreFindings} onClick={() => void loadMoreFindings()}>
                {loadingMoreFindings ? 'Loading findings...' : `Load more findings (${findings.length} of ${findingsTotal})`}
              </button>}
            </div>
          </section>

          <section className="result-panel pages-panel" aria-labelledby="pages-heading">
            <div className="result-panel-heading">
              <div><span className="eyebrow">Crawled inventory</span><h3 id="pages-heading">Pages</h3></div>
              <span>{selected.pages?.length ?? 0} of {pagesTotal} pages loaded</span>
            </div>
            <div className="result-scroll pages" tabIndex={0} aria-label="Scrollable crawled pages">
              {selected.pages?.length ? selected.pages.map((page) => {
                const isExpanded = expandedPageUrl === page.url
                const detailedPage = pageEvidence[page.id] || page
                const pageFindings = detailedPage.findings || findings.filter((finding) => finding.page_url === page.url)
                return <article className={isExpanded ? 'page-item expanded' : 'page-item'} key={page.url}>
                  <div className="page-summary-row">
                    <button className="page-row" aria-expanded={isExpanded} aria-controls={`evidence-${page.id}`} onClick={() => void togglePageEvidence(page)}>
                      <div><b>{page.title || 'Untitled page'}</b><p>{page.url}</p><small>Status {page.status || page.error_type || 'failed'} - {page.load_ms} ms - depth {page.depth} - {page.responsive_viewport_count ?? Object.keys(page.responsive || {}).length}/3 viewports</small></div>
                      <span>{isExpanded ? 'Hide evidence' : 'View evidence'} <i aria-hidden="true">{isExpanded ? '−' : '+'}</i></span>
                    </button>
                    <label className={`priority-control ${page.priority || 'standard'}`}>
                      <span>Importance</span>
                      <select aria-label={`Importance for ${page.url}`} value={page.priority || 'standard'} onChange={(event) => void updatePagePriority(page, event.target.value as Page['priority'])}>
                        <option value="critical">Critical</option>
                        <option value="high_value">High value</option>
                        <option value="standard">Standard</option>
                      </select>
                    </label>
                  </div>
                  {isExpanded && (loadingPageId === page.id
                    ? <p className="evidence-loading" id={`evidence-${page.id}`}>Loading console, network, responsive, and content evidence...</p>
                    : <PageEvidence page={detailedPage} findings={pageFindings} panelId={`evidence-${page.id}`} />)}
                </article>
              }) : <p className="muted">No pages recorded yet.</p>}
              {(selected.pages?.length || 0) < pagesTotal && <button className="load-more" disabled={loadingMorePages} onClick={() => void loadMorePages()}>
                {loadingMorePages ? 'Loading pages...' : `Load more pages (${selected.pages?.length || 0} of ${pagesTotal})`}
              </button>}
            </div>
          </section>
        </>}
      </section>
    </div>
  </main>
}

function SiteAnalysisPanel({ analysis }: { analysis?: SiteAnalysis }) {
  if (!analysis || !Object.keys(analysis).length) return null
  const sitemap = sitemapPresentation(analysis)
  const sourceCount = analysis.sitemap_sources?.length ?? 0
  const comparisonValue = (value: number | undefined) => sitemap.comparisonAvailable ? (value ?? 0) : '—'
  const lists: [string, string[], boolean][] = [
    ['Orphan pages', analysis.orphan_pages || [], true],
    ['Internally linked but missing from sitemap', analysis.linked_missing_sitemap || [], true],
    ['Robots-blocked sitemap URLs', analysis.robots_blocked_sitemap || [], true],
    ['Noindex pages', analysis.noindex_pages || [], false],
    ['Broken internal links', analysis.broken_internal_links || [], false],
  ]
  return <section className="site-analysis" aria-labelledby="site-analysis-heading">
    <div className="site-analysis-heading">
      <div><span className="eyebrow">Search visibility</span><h3 id="site-analysis-heading">Sitemap and indexing</h3></div>
      <span>{sourceCount ? `${sourceCount} sitemap address${sourceCount === 1 ? '' : 'es'} responded` : 'No sitemap address responded'}</span>
    </div>
    <div className={`sitemap-status ${sitemap.status}`} role="status">
      <div><span aria-hidden="true">{sitemap.status === 'valid' ? '✓' : '!'}</span><b>{sitemap.title}</b></div>
      <p>{sitemap.detail}</p>
      {!sitemap.comparisonAvailable && <small>Comparison-dependent results are marked “Not available” instead of showing a misleading zero.</small>}
    </div>
    <div className="site-analysis-metrics">
      <div><b>{analysis.sitemap_url_count || 0}</b><span>Sitemap URLs</span></div>
      <div className={!sitemap.comparisonAvailable ? 'unavailable' : ''}><b>{comparisonValue(analysis.sitemap_urls_crawled)}</b><span>Sitemap URLs crawled</span>{!sitemap.comparisonAvailable && <small>Not available</small>}</div>
      <div className={!sitemap.comparisonAvailable ? 'unavailable' : ''}><b>{comparisonValue(analysis.sitemap_urls_unchecked)}</b><span>Outside scan limit</span>{!sitemap.comparisonAvailable && <small>Not available</small>}</div>
      <div className={!sitemap.comparisonAvailable ? 'unavailable' : ''}><b>{comparisonValue(analysis.orphan_page_count ?? analysis.orphan_pages?.length)}</b><span>Orphan pages</span>{!sitemap.comparisonAvailable && <small>Not available</small>}</div>
      <div className={!sitemap.comparisonAvailable ? 'unavailable' : ''}><b>{comparisonValue(analysis.linked_missing_sitemap_count ?? analysis.linked_missing_sitemap?.length)}</b><span>Missing from sitemap</span>{!sitemap.comparisonAvailable && <small>Not available</small>}</div>
    </div>
    {analysis.sitemap_sources?.length ? <div className="sitemap-sources"><b>{sitemap.status === 'valid' ? 'Sitemap sources' : 'Addresses that responded'}</b>{analysis.sitemap_sources.map((url) => <a href={url} target="_blank" rel="noreferrer" key={url}>{url}</a>)}</div> : null}
    {analysis.sitemap_errors?.length ? <details className="sitemap-attempt-list">
      <summary>Sitemap addresses that failed <span>{analysis.sitemap_errors.length}</span></summary>
      <ul>{analysis.sitemap_errors.map((item) => <li key={item.url}><b>{String(item.status)}</b> <a href={item.url} target="_blank" rel="noreferrer">{item.url}</a>{item.detail ? <small>{item.detail}</small> : null}</li>)}</ul>
    </details> : null}
    <div className="analysis-lists">{lists.map(([title, urls, requiresSitemap]) =>
      <details key={title}>
        <summary>{title} <span>{requiresSitemap && !sitemap.comparisonAvailable ? '—' : urls.length}</span></summary>
        {requiresSitemap && !sitemap.comparisonAvailable
          ? <p>Not available until a valid sitemap provides page URLs.</p>
          : urls.length
            ? <ul>{urls.map((url) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>
            : <p>None detected in the scanned pages.</p>}
      </details>,
    )}</div>
    {analysis.sitemap_page_errors?.length ? <details className="sitemap-error-list">
      <summary>Sitemap URLs returning errors <span>{analysis.sitemap_page_errors.length}</span></summary>
      <ul>{analysis.sitemap_page_errors.map((item) => <li key={item.url}><b>{String(item.status)}</b> <a href={item.url} target="_blank" rel="noreferrer">{item.url}</a></li>)}</ul>
    </details> : null}
  </section>
}

type ReportPanelProps = {
  agencyName: string
  reportTitle: string
  brandColor: string
  reportKind: 'executive' | 'qa' | 'developer'
  compareTo: string
  shareExpiry: number
  shareUrl: string
  saving: boolean
  comparableScans: Scan[]
  setAgencyName: (value: string) => void
  setReportTitle: (value: string) => void
  setBrandColor: (value: string) => void
  setReportKind: (value: 'executive' | 'qa' | 'developer') => void
  setCompareTo: (value: string) => void
  setShareExpiry: (value: number) => void
  saveSettings: () => Promise<void>
  createShareLink: () => Promise<void>
  reportUrl: (format: 'pdf' | 'csv' | 'xlsx') => string
}

function ReportPanel(props: ReportPanelProps) {
  return <section className="report-panel result-panel" aria-labelledby="reports-heading">
    <div className="result-panel-heading">
      <div><span className="eyebrow">Share decisions, not raw logs</span><h3 id="reports-heading">Reports and exports</h3></div>
      <span>PDF · CSV · Excel · secure link</span>
    </div>
    <div className="report-body">
      <div className="report-branding">
        <label><span>Agency or company</span><input value={props.agencyName} maxLength={100} placeholder="BugBuster Labs" onChange={(event) => props.setAgencyName(event.target.value)} /></label>
        <label><span>Report title</span><input value={props.reportTitle} maxLength={140} placeholder="Website quality report" onChange={(event) => props.setReportTitle(event.target.value)} /></label>
        <label className="brand-color"><span>Brand color</span><input type="color" value={props.brandColor} onChange={(event) => props.setBrandColor(event.target.value)} /></label>
        <button className="secondary report-save" disabled={props.saving} onClick={() => void props.saveSettings()}>{props.saving ? 'Saving…' : 'Save branding'}</button>
      </div>
      <div className="report-options">
        <label><span>Report audience</span><select value={props.reportKind} onChange={(event) => props.setReportKind(event.target.value as ReportPanelProps['reportKind'])}>
          <option value="executive">Executive summary</option>
          <option value="qa">QA report</option>
          <option value="developer">Developer evidence</option>
        </select></label>
        <label><span>Compare with</span><select value={props.compareTo} onChange={(event) => props.setCompareTo(event.target.value)}>
          <option value="">Current scan only — no comparison</option>
          <option value="__previous__" disabled={!props.comparableScans.length}>Previous completed scan</option>
          {props.comparableScans.map((scan) =>
            <option value={scan.id} key={scan.id}>
              {new Date(scan.created_at).toLocaleString()} · score {scan.summary?.health_score ?? '—'} · {scan.summary?.pages_scanned ?? 0} pages
            </option>,
          )}
        </select></label>
        <div className="report-downloads" aria-label="Download report">
          <a href={props.reportUrl('pdf')} target="_blank" rel="noreferrer">Download PDF</a>
          <a href={props.reportUrl('csv')}>Export CSV</a>
          <a href={props.reportUrl('xlsx')}>Export Excel</a>
        </div>
      </div>
      <div className="share-controls">
        <label><span>Read-only link expires</span><select value={props.shareExpiry} onChange={(event) => props.setShareExpiry(Number(event.target.value))}>
          <option value={24}>24 hours</option><option value={168}>7 days</option><option value={720}>30 days</option>
        </select></label>
        <button onClick={() => void props.createShareLink()}>Create share link</button>
        {props.shareUrl && <div className="share-result" role="status"><span>Expiring read-only report</span><a href={props.shareUrl} target="_blank" rel="noreferrer">{props.shareUrl}</a></div>}
      </div>
    </div>
  </section>
}

function ComparisonPanel({ comparison }: { comparison?: ScanComparison | null }) {
  if (!comparison) return null
  if (!comparison.baseline) {
    return <section className="comparison-panel first-baseline">
      <div><span className="eyebrow">Change tracking</span><h3>Baseline scan</h3></div>
      <p>This is the first completed scan for this URL. The next scan will identify new, fixed, recurring, and unchanged root causes.</p>
    </section>
  }
  const changed = comparison.items.filter((item) => item.change_status !== 'unchanged')
  return <section className="comparison-panel" aria-labelledby="comparison-heading">
    <div className="comparison-heading">
      <div><span className="eyebrow">Since the previous scan</span><h3 id="comparison-heading">What changed</h3></div>
      <small>Compared with {new Date(comparison.baseline.created_at).toLocaleString()}</small>
    </div>
    <div className="comparison-counts">
      {(['new', 'fixed', 'recurring', 'unchanged'] as const).map((status) =>
        <div className={`comparison-count ${status}`} key={status}>
          <b>{comparison.counts[status]}</b><span>{status}</span>
        </div>,
      )}
    </div>
    {changed.length > 0
      ? <details className="comparison-changes">
          <summary>Review {changed.length} changed root {changed.length === 1 ? 'cause' : 'causes'}</summary>
          <ul>{changed.map((item) =>
            <li key={`${item.change_status}-${item.group_id}`}>
              <span className={`change-badge ${item.change_status}`}>{item.change_status}</span>
              <div><b>{item.title}</b><small>{item.category} · {item.affected_pages.length} affected {item.affected_pages.length === 1 ? 'page' : 'pages'}</small></div>
            </li>,
          )}</ul>
        </details>
      : <p className="comparison-steady">No issue status changed since the previous scan.</p>}
  </section>
}

function IssueGroupCard({ group }: { group: IssueGroup }) {
  return <article className="issue-group">
    <span className={`badge ${group.severity}`}>{group.severity}</span>
    <div className="issue-group-body">
      <div className="issue-title-row">
        <div><b>{group.title}</b><small>{group.category} · {group.count} occurrences across {group.affected_pages.length} {group.affected_pages.length === 1 ? 'page' : 'pages'}</small></div>
        <div className="issue-markers"><span className={`page-priority ${group.page_priority}`}>{group.page_priority.replace(/_/g, ' ')}</span><span className={`confidence ${group.confidence}`}>{group.confidence.replace(/_/g, ' ')}</span></div>
      </div>
      <p>{group.what_happened}</p>
      <div className="ownership"><span>Suggested owner</span><b>{group.owner}</b></div>
      <details className="remediation">
        <summary>View impact, fix guidance, and affected pages</summary>
        <div className="guidance-grid">
          <div><b>Why it matters</b><p>{group.why_it_matters}</p></div>
          <div><b>Recommended action</b><p>{group.recommended_action}</p></div>
          <div><b>How it was verified</b><p>{group.verification}</p></div>
          <div><b>Why this severity</b><p>{group.severity_reason}</p></div>
        </div>
        <AffectedPages urls={group.affected_pages} />
      </details>
    </div>
  </article>
}

function FindingCard({ finding }: { finding: Finding }) {
  return <article className="individual-finding">
    <span className={`badge ${finding.severity}`}>{finding.severity}</span>
    <div>
      <div className="issue-title-row">
        <b>{finding.title}</b>
        {finding.confidence && <span className={`confidence ${finding.confidence}`}>{finding.confidence.replace(/_/g, ' ')}</span>}
      </div>
      <p>{finding.detail}</p>
      <small>{finding.category} - {finding.page_url}</small>
      {(finding.why_it_matters || finding.recommended_action) && <details className="remediation compact">
        <summary>Understand and resolve</summary>
        <div className="guidance-grid">
          {finding.why_it_matters && <div><b>Why it matters</b><p>{finding.why_it_matters}</p></div>}
          {finding.recommended_action && <div><b>Recommended action</b><p>{finding.recommended_action}</p></div>}
          {finding.owner && <div><b>Suggested owner</b><p>{finding.owner}</p></div>}
          {finding.verification && <div><b>How it was verified</b><p>{finding.verification}</p></div>}
        </div>
      </details>}
      <DiscoveredOn urls={finding.discovered_on || []} />
    </div>
  </article>
}

function AffectedPages({ urls }: { urls: string[] }) {
  return <div className="affected-pages">
    <b>Affected pages ({urls.length})</b>
    {urls.length
      ? <ul>{urls.map((url) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>
      : <p>No page URL was attached to this root cause.</p>}
  </div>
}

function PageEvidence({ page, findings, panelId }: { page: Page; findings: Finding[]; panelId: string }) {
  const consoleItems = page.console || []
  const networkItems = page.network || []
  const redirects = page.redirect_chain || []
  const responsiveFindings = findings.filter((finding) => finding.category === 'responsive')
  const generalFindings = findings.filter((finding) => finding.category !== 'responsive')
  return <section className="inline-evidence" id={panelId} aria-label={`Evidence for ${page.url}`}>
    {page.error_detail && <p className="error-box">{page.error_detail}</p>}
    <dl>
      <div><dt>Status</dt><dd>{page.status || 'Failed'}</dd></div>
      <div><dt>Load time</dt><dd>{page.load_ms} ms</dd></div>
      <div><dt>H1</dt><dd>{page.h1 || 'Missing'}</dd></div>
      <div><dt>Meta description</dt><dd>{page.meta_description || 'Missing'}</dd></div>
    </dl>
    <ContentEvidence quality={page.quality || {}} />
    <ResponsiveEvidence evidence={page.responsive || {}} findings={responsiveFindings} />
    {redirects.length > 0 && <EvidenceList title={`Redirects (${redirects.length})`} items={redirects.map((item) => `${item.status} ${item.from} -> ${item.to}`)} />}
    <EvidenceList title={`General findings (${generalFindings.length})`} items={generalFindings.map((item) => `${item.severity.toUpperCase()}: ${item.title} - ${item.detail}`)} />
    <EvidenceList title={`Console (${consoleItems.length})`} items={consoleItems.map((item) => {
      const classification = item.classification ? ` [${item.severity || 'info'} - ${item.classification.replace(/_/g, ' ')}]` : ''
      const related = item.related_request_url ? ` Related request: ${item.related_request_url}` : ''
      return `${item.level}${classification}: ${item.message}${related}`
    })} />
    <NetworkEvidence items={networkItems} />
    {page.screenshot_path && <a className="screenshot" href={`${API_ORIGIN}/evidence/${page.screenshot_path}`} target="_blank" rel="noreferrer">Open full-page screenshot</a>}
  </section>
}

function ContentEvidence({ quality }: { quality: PageQuality }) {
  if (!Object.keys(quality).length) return null
  return <section className="content-evidence">
    <div className="evidence-title"><b>Content and indexability</b><span>Rendered page evidence</span></div>
    <dl>
      <div><dt>Visible words</dt><dd>{quality.word_count ?? 0}</dd></div>
      <div><dt>H1 headings</dt><dd>{quality.h1_count ?? 0}</dd></div>
      <div><dt>Missing image alt</dt><dd>{quality.images_missing_alt_count ?? 0}</dd></div>
      <div><dt>Indexability</dt><dd className={quality.noindex ? 'failed' : 'passed'}>{quality.noindex ? 'noindex' : 'index allowed'}</dd></div>
    </dl>
    <div className="content-evidence-lines">
      <div><b>Canonical</b><span>{quality.canonical_urls?.length ? quality.canonical_urls.join(', ') : 'No canonical tag found'}</span></div>
      <div><b>Robots directives</b><span>{quality.robots_directives?.length ? quality.robots_directives.join(', ') : 'No page-level directives'}</span></div>
      {quality.placeholder_matches?.length ? <div><b>Placeholder text</b><span>{quality.placeholder_matches.join(', ')}</span></div> : null}
    </div>
  </section>
}

function ResponsiveEvidence({ evidence, findings }: { evidence: Record<string, ResponsiveViewport>; findings: Finding[] }) {
  const viewports = ['desktop', 'tablet', 'mobile']
    .map((key) => evidence[key])
    .filter((item): item is ResponsiveViewport => Boolean(item))
  const findingsFor = (label: string) => findings.filter((finding) =>
    finding.title.toLocaleLowerCase().includes(label.toLocaleLowerCase())
    || finding.detail.toLocaleLowerCase().startsWith(`${label.toLocaleLowerCase()} (`),
  )
  const assignedIds = new Set(viewports.flatMap((viewport) => findingsFor(viewport.label).map((finding) => finding.id)))
  const overallFindings = findings.filter((finding) => !assignedIds.has(finding.id))
  return <section className="responsive-evidence">
    <div className="evidence-title"><b>Responsive testing ({viewports.length}/3 viewports)</b><span>Desktop · Tablet · Mobile</span></div>
    {viewports.length
      ? <div className="viewport-grid">{viewports.map((viewport) => {
          const overflow = Math.max(0, (viewport.document_width || viewport.width) - (viewport.viewport_width || viewport.width))
          const viewportFindings = findingsFor(viewport.label)
          return <article className="viewport-card" key={viewport.label}>
            <div className="viewport-heading">
              <div><b>{viewport.label}</b><span>{viewport.width} × {viewport.height}</span></div>
              <span className={viewportFindings.length ? 'viewport-status issues' : 'viewport-status passed'}>
                {viewportFindings.length ? `${viewportFindings.length} ${viewportFindings.length === 1 ? 'finding' : 'findings'}` : 'No findings'}
              </span>
            </div>
            {viewport.screenshot_path && <a className="viewport-shot" href={`${API_ORIGIN}/evidence/${viewport.screenshot_path}`} target="_blank" rel="noreferrer">
              <img src={`${API_ORIGIN}/evidence/${viewport.screenshot_path}`} alt={`${viewport.label} screenshot at ${viewport.width} by ${viewport.height}`} loading="lazy" />
              <span>Open full screenshot</span>
            </a>}
            <dl className="viewport-checks">
              <div><dt>Horizontal overflow</dt><dd className={overflow > 4 ? 'failed' : 'passed'}>{overflow > 4 ? `${overflow}px` : 'None'}</dd></div>
              <div><dt>Overlaps</dt><dd className={viewport.overlapping_elements?.length ? 'failed' : 'passed'}>{viewport.overlapping_elements?.length || 0}</dd></div>
              <div><dt>Small text</dt><dd className={viewport.unreadable_text?.length ? 'failed' : 'passed'}>{viewport.unreadable_text?.length || 0}</dd></div>
              <div><dt>Off-screen images</dt><dd className={viewport.images_outside_viewport?.length ? 'failed' : 'passed'}>{viewport.images_outside_viewport?.length || 0}</dd></div>
              <div><dt>Hidden primary content</dt><dd className={viewport.hidden_content?.length ? 'failed' : 'passed'}>{viewport.hidden_content?.length || 0}</dd></div>
              <div><dt>Navigation</dt><dd>{viewport.visible_nav_links || 0} links{viewport.menu_control_visible ? ' + menu' : ''}</dd></div>
            </dl>
            <div className="viewport-findings">
              <b>{viewport.label} findings</b>
              {viewportFindings.length
                ? <ul>{viewportFindings.map((finding) => <li key={finding.id}>
                    <span className={`badge ${finding.severity}`}>{finding.severity}</span>
                    <div><b>{finding.title}</b><p>{finding.detail}</p></div>
                  </li>)}</ul>
                : <p>No responsive findings at this viewport.</p>}
            </div>
          </article>
        })}</div>
      : <p className="muted">Responsive evidence is available on newly completed scans.</p>}
    {overallFindings.length > 0 && <div className="responsive-overall">
      <b>Overall responsive scan findings</b>
      <ul>{overallFindings.map((finding) => <li key={finding.id}>{finding.severity.toUpperCase()}: {finding.title} - {finding.detail}</li>)}</ul>
    </div>}
  </section>
}

function NetworkEvidence({ items }: { items: EvidenceItem[] }) {
  return <div className="network-evidence">
    <div className="evidence-title"><b>Network ({items.length})</b><span>{items.filter((item) => typeof item.status === 'number' && item.status < 400).length} passed</span></div>
    {items.length ? <div className="network-table">
      {items.map((item, index) => {
        const passed = typeof item.status === 'number' && item.status < 400
        return <div className="network-row" key={`${item.method}-${item.url}-${index}`}>
          <span className={passed ? 'network-status passed' : 'network-status failed'}>{String(item.status)}</span>
          <span className="network-type">{item.resource_type || 'other'}</span>
          <b>{item.method || 'GET'}</b>
          <span className="network-url" title={item.url}>{item.url}</span>
          {item.classification && <small className={`network-classification ${item.severity || 'info'}`}>{item.classification.replace(/_/g, ' ')} · {item.failure_kind?.replace(/_/g, ' ')}</small>}
          {item.error && <small>{item.error}</small>}
        </div>
      })}
    </div> : <p className="muted">No network activity recorded.</p>}
  </div>
}

function DiscoveredOn({ urls }: { urls: string[] }) {
  if (!urls.length) return null
  const visible = urls.slice(0, 3)
  const remaining = urls.slice(3)
  return <div className="discovered-on">
    <b>Discovered on {urls.length} {urls.length === 1 ? 'page' : 'pages'}</b>
    <ul>{visible.map((url) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>
    {remaining.length > 0 && <details>
      <summary>View {remaining.length} more source {remaining.length === 1 ? 'page' : 'pages'}</summary>
      <ul>{remaining.map((url) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>
    </details>}
  </div>
}

function EvidenceList({ title, items }: { title: string; items: string[] }) {
  return <div className="evidence-list"><b>{title}</b>{items.length ? <ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>None recorded.</p>}</div>
}

createRoot(document.getElementById('root')!).render(<App />)
