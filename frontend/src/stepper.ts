export const MIN_PAGE_COUNT = 1
export const MAX_PAGE_COUNT = 250

export function stepPageCount(current: number, change: number) {
  return Math.min(MAX_PAGE_COUNT, Math.max(MIN_PAGE_COUNT, current + change))
}

export function startPressRepeat(
  action: () => void,
  initialDelay = 360,
  repeatEvery = 90,
) {
  let repeatTimer: ReturnType<typeof setInterval> | undefined
  const delayTimer = setTimeout(() => {
    action()
    repeatTimer = setInterval(action, repeatEvery)
  }, initialDelay)

  return () => {
    clearTimeout(delayTimer)
    if (repeatTimer !== undefined) clearInterval(repeatTimer)
  }
}
