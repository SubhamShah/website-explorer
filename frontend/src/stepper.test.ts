import { afterEach, describe, expect, it, vi } from 'vitest'
import { startPressRepeat, stepPageCount } from './stepper'

afterEach(() => vi.useRealTimers())

describe('maximum-page stepper', () => {
  it('keeps the value inside the supported range', () => {
    expect(stepPageCount(1, -1)).toBe(1)
    expect(stepPageCount(25, 1)).toBe(26)
    expect(stepPageCount(250, 1)).toBe(250)
  })

  it('repeats while the control remains pressed and stops on release', () => {
    vi.useFakeTimers()
    const action = vi.fn()
    const stop = startPressRepeat(action)

    vi.advanceTimersByTime(359)
    expect(action).not.toHaveBeenCalled()

    vi.advanceTimersByTime(271)
    expect(action).toHaveBeenCalledTimes(4)

    stop()
    vi.advanceTimersByTime(500)
    expect(action).toHaveBeenCalledTimes(4)
  })
})
