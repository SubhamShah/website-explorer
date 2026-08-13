import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const controlsCss = readFileSync(new URL('./controls.css', import.meta.url), 'utf8')

describe('health panel layout states', () => {
  it('does not apply the unavailable flex layout to a calculating neutral score', () => {
    expect(controlsCss).toContain('.health-overview.unavailable {')
    expect(controlsCss).not.toMatch(/\.health-overview\.neutral\s*\{/)
  })

  it('adapts to the result panel width instead of only the browser width', () => {
    expect(controlsCss).toContain('container-type: inline-size')
    expect(controlsCss).toContain('@container (max-width: 700px)')
  })
})
