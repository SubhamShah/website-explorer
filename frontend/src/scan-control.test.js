import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const mainSource = readFileSync(new URL('./main.tsx', import.meta.url), 'utf8')
const progressStyles = readFileSync(new URL('./progress.css', import.meta.url), 'utf8')

describe('scan pause and resume controls', () => {
  it('keeps paused scans polling and exposes the resume action', () => {
    expect(mainSource).toContain("selected?.status === 'paused'")
    expect(mainSource).toContain("changeScanActivity(scanPaused ? 'resume' : 'pause')")
    expect(mainSource).toContain('resume from the next unscanned page')
  })

  it('visually distinguishes paused state from active progress', () => {
    expect(progressStyles).toContain('.progress-banner.paused')
    expect(progressStyles).toContain('.progress-control')
  })
})
