import { describe, expect, it } from 'vitest'
import { sitemapPresentation } from './sitemap'

describe('sitemapPresentation', () => {
  it('recognizes old scans with a responding source but no parsed URLs', () => {
    const result = sitemapPresentation({
      sitemap_sources: ['https://example.com/?sitemap.xml'],
      sitemap_errors: [{ url: 'https://example.com/sitemap.xml', status: 404 }],
      sitemap_url_count: 0,
    })

    expect(result.status).toBe('empty_or_invalid')
    expect(result.comparisonAvailable).toBe(false)
  })

  it('makes comparisons available when page URLs were parsed', () => {
    const result = sitemapPresentation({
      sitemap_sources: ['https://example.com/sitemap.xml'],
      sitemap_url_count: 12,
    })

    expect(result.status).toBe('valid')
    expect(result.comparisonAvailable).toBe(true)
  })
})
