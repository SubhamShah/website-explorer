export type FilterableFinding = {
  severity: string
  category: string
  title: string
  detail: string
  page_url?: string
}

export function filterFindings<T extends FilterableFinding>(
  findings: T[],
  severity: string,
  category: string,
  query: string,
): T[] {
  const term = query.trim().toLocaleLowerCase()
  return findings.filter((finding) => {
    if (severity === 'issues' && finding.severity === 'info') return false
    if (severity !== 'all' && severity !== 'issues' && finding.severity !== severity) return false
    if (category !== 'all' && finding.category !== category) return false
    if (!term) return true
    return [finding.title, finding.detail, finding.page_url ?? '']
      .join(' ')
      .toLocaleLowerCase()
      .includes(term)
  })
}
