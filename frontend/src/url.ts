export type UrlScheme = 'https' | 'http'
export type RecentDomain = { domain: string; scheme: UrlScheme; url: string }

export function parseWebsiteInput(value: string, currentScheme: UrlScheme) {
  const entered = value.trimStart()
  const fullUrl = entered.match(/^(https?):\/\/(.*)$/i)
  return fullUrl
    ? { scheme: fullUrl[1].toLocaleLowerCase() as UrlScheme, domain: fullUrl[2] }
    : { scheme: currentScheme, domain: entered }
}

export function buildWebsiteUrl(scheme: UrlScheme, domain: string) {
  const entered = domain.trim()
  return /^https?:\/\//i.test(entered)
    ? entered
    : `${scheme}://${entered.replace(/^\/+/, '')}`
}

export function recentWebsiteDomains(urls: string[], limit = 10): RecentDomain[] {
  const seen = new Set<string>()
  const domains: RecentDomain[] = []
  for (const value of urls) {
    try {
      const parsed = new URL(value)
      const key = parsed.host.toLocaleLowerCase()
      if (!key || seen.has(key)) continue
      seen.add(key)
      domains.push({
        domain: parsed.host,
        scheme: parsed.protocol === 'http:' ? 'http' : 'https',
        url: `${parsed.protocol}//${parsed.host}`,
      })
      if (domains.length >= limit) break
    } catch {
      // Ignore invalid legacy scan addresses.
    }
  }
  return domains
}
