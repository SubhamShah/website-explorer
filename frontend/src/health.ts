export function healthScoreTone(score?: number): 'neutral' | 'good' | 'warning' | 'poor' {
  if (score === undefined) return 'neutral'
  if (score >= 80) return 'good'
  if (score >= 50) return 'warning'
  return 'poor'
}
