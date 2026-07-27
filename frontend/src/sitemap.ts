export type SitemapStatus = 'valid' | 'empty_or_invalid' | 'not_found' | 'unavailable'

type SitemapAnalysisInput = {
  sitemap_sources?: string[]
  sitemap_errors?: { url: string; status: number | string; detail?: string }[]
  sitemap_url_count?: number
  sitemap_status?: SitemapStatus
  sitemap_status_detail?: string
  sitemap_comparison_available?: boolean
}

export function sitemapPresentation(analysis: SitemapAnalysisInput) {
  const urlCount = analysis.sitemap_url_count ?? 0
  const sourceCount = analysis.sitemap_sources?.length ?? 0
  const errors = analysis.sitemap_errors ?? []
  const inferredStatus: SitemapStatus = urlCount > 0
    ? 'valid'
    : sourceCount > 0
      ? 'empty_or_invalid'
      : errors.some((item) => String(item.status) !== '404')
        ? 'unavailable'
        : 'not_found'
  const status = analysis.sitemap_status ?? inferredStatus
  const comparisonAvailable = analysis.sitemap_comparison_available ?? urlCount > 0
  const titles: Record<SitemapStatus, string> = {
    valid: 'Valid XML sitemap',
    empty_or_invalid: 'Empty or invalid sitemap',
    not_found: 'XML sitemap not found',
    unavailable: 'Sitemap unavailable',
  }
  const details: Record<SitemapStatus, string> = {
    valid: `The sitemap contains ${urlCount} page URL${urlCount === 1 ? '' : 's'}, so indexing comparisons are available.`,
    empty_or_invalid: 'A sitemap address responded, but no valid <loc> page URLs were parsed. It may be empty XML or an HTML page instead of an XML sitemap.',
    not_found: 'No XML sitemap was found at the sitemap addresses checked.',
    unavailable: 'The sitemap could not be read because one or more sitemap requests failed.',
  }

  return {
    status,
    title: titles[status],
    detail: analysis.sitemap_status_detail || details[status],
    comparisonAvailable,
  }
}
