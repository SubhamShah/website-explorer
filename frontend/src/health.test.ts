import { describe, expect, it } from 'vitest'
import { healthScoreTone } from './health'

describe('healthScoreTone', () => {
  it('maps score ranges to semantic tones', () => {
    expect(healthScoreTone(100)).toBe('good')
    expect(healthScoreTone(80)).toBe('good')
    expect(healthScoreTone(79)).toBe('warning')
    expect(healthScoreTone(50)).toBe('warning')
    expect(healthScoreTone(49)).toBe('poor')
    expect(healthScoreTone(0)).toBe('poor')
    expect(healthScoreTone()).toBe('neutral')
  })
})
