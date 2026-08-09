import { describe, expect, it } from 'vitest'
import { buildWebsiteUrl, parseWebsiteInput, recentWebsiteDomains } from './url'

describe('website URL input', () => {
  it('adds HTTPS to a domain by default', () => {
    expect(buildWebsiteUrl('https', 'javra.com')).toBe('https://javra.com')
  })

  it('supports an explicitly selected HTTP protocol', () => {
    expect(buildWebsiteUrl('http', 'example.test/path')).toBe('http://example.test/path')
  })

  it('separates a pasted full URL without duplicating its protocol', () => {
    expect(parseWebsiteInput('https://javra.com/blog', 'http')).toEqual({
      scheme: 'https',
      domain: 'javra.com/blog',
    })
  })

  it('lists unique recently scanned domains in newest-first order', () => {
    expect(recentWebsiteDomains([
      'https://javra.com/',
      'https://stablecluster.com/',
      'http://javra.com/older',
      'invalid',
    ])).toEqual([
      { domain: 'javra.com', scheme: 'https', url: 'https://javra.com' },
      { domain: 'stablecluster.com', scheme: 'https', url: 'https://stablecluster.com' },
    ])
  })
})
