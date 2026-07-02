import { describe, expect, it } from 'vitest'

import type { ClientSessionState } from '../../../types'

import { applySessionInfoRunningState } from './running-state'

describe('applySessionInfoRunningState', () => {
  it('treats backend running=false as authoritative even before assistant payload arrives', () => {
    const stuck = {
      awaitingResponse: true,
      busy: true,
      pendingBranchGroup: 'branch-after-turn',
      sawAssistantPayload: false,
      streamId: 'stream-1',
      turnStartedAt: 123
    } as ClientSessionState

    expect(applySessionInfoRunningState(stuck, false)).toMatchObject({
      awaitingResponse: false,
      busy: false,
      pendingBranchGroup: null,
      streamId: null,
      turnStartedAt: null
    })
  })

  it('marks backend running=true as a live turn without resetting an existing clock', () => {
    const idleWithClock = {
      awaitingResponse: false,
      busy: false,
      sawAssistantPayload: false,
      turnStartedAt: 123
    } as ClientSessionState

    expect(applySessionInfoRunningState(idleWithClock, true, 999)).toMatchObject({
      busy: true,
      turnStartedAt: 123
    })
  })
})
