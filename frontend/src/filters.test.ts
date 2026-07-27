import { describe, expect, it } from 'vitest'
import { filterFindings } from './filters'

const findings = [
  { severity: 'high', category: 'network', title: 'Failed request', detail: 'GET /missing returned 404', page_url: 'https://example.com' },
  { severity: 'low', category: 'seo', title: 'Missing H1', detail: 'No heading', page_url: 'https://example.com/about' },
]

describe('filterFindings', () => {
  it('combines severity and category filters', () => {
    expect(filterFindings(findings, 'high', 'network', '')).toEqual([findings[0]])
    expect(filterFindings(findings, 'high', 'seo', '')).toEqual([])
  })

  it('searches evidence and URL without case sensitivity', () => {
    expect(filterFindings(findings, 'all', 'all', 'MISSING')).toEqual(findings)
    expect(filterFindings(findings, 'all', 'all', '/about')).toEqual([findings[1]])
  })

  it('hides informational network activity in the issues view', () => {
    const informational = { severity: 'info', category: 'network', title: 'API request passed', detail: '200 OK' }
    expect(filterFindings([...findings, informational], 'issues', 'all', '')).toEqual(findings)
  })
})
