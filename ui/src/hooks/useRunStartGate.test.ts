import { describe, expect, it } from 'vitest'
import { isConnectBrowserBusy, resolveRunStartBlock } from './useRunStartGate'

describe('isConnectBrowserBusy', () => {
  it('treats starting, ready, and stopping as busy while Connect is online', () => {
    expect(isConnectBrowserBusy(true, 'idle')).toBe(false)
    expect(isConnectBrowserBusy(true, 'starting')).toBe(true)
    expect(isConnectBrowserBusy(true, 'ready')).toBe(true)
    expect(isConnectBrowserBusy(true, 'stopping')).toBe(true)
  })

  it('is not busy when Connect is offline', () => {
    expect(isConnectBrowserBusy(false, 'ready')).toBe(false)
  })
})

describe('resolveRunStartBlock', () => {
  it('blocks Start after cancel while Chrome is still stopping', () => {
    const block = resolveRunStartBlock({
      localBrowserMode: false,
      connectOnline: true,
      hasActiveRun: false,
      browserBusy: true,
      browserState: 'stopping',
    })
    expect(block.blockReason).toBe('busy')
    expect(block.blockHint).toMatch(/shutting down/i)
  })

  it('asks to finish a live run rather than wait for Chrome', () => {
    const block = resolveRunStartBlock({
      localBrowserMode: false,
      connectOnline: true,
      hasActiveRun: true,
      browserBusy: true,
    })
    expect(block.blockHint).toMatch(/cancel/i)
  })
})
