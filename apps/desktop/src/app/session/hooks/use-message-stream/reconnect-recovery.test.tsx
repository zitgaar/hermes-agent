import { cleanup, render, waitFor } from '@testing-library/react'
import { useRef } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ClientSessionState } from '../../../types'

import {
  shouldHydrateAfterGatewayReconnect,
  useHydrateStuckSessionAfterGatewayReconnect
} from './reconnect-recovery'

const sessionState = (overrides: Partial<ClientSessionState> = {}): ClientSessionState => ({
  awaitingResponse: false,
  branch: '',
  busy: false,
  cwd: '',
  fast: false,
  interrupted: false,
  messages: [],
  model: '',
  needsInput: false,
  pendingBranchGroup: null,
  personality: '',
  provider: '',
  reasoningEffort: '',
  sawAssistantPayload: false,
  serviceTier: '',
  storedSessionId: 'stored-from-state',
  streamId: null,
  turnStartedAt: null,
  yolo: false,
  ...overrides
})

function Harness({
  activeSessionId = 'runtime-1',
  gatewayState,
  hydrateFromStoredSession,
  selectedStoredSessionId = 'selected-stored',
  state
}: {
  activeSessionId?: string | null
  gatewayState: string
  hydrateFromStoredSession: (attempts?: number, storedSessionId?: string | null, runtimeSessionId?: string | null) => Promise<void>
  selectedStoredSessionId?: string | null
  state?: ClientSessionState | null
}) {
  const activeSessionIdRef = useRef<string | null>(activeSessionId)
  const selectedStoredSessionIdRef = useRef<string | null>(selectedStoredSessionId)
  const sessionStateByRuntimeIdRef = useRef<Map<string, ClientSessionState>>(new Map())

  activeSessionIdRef.current = activeSessionId
  selectedStoredSessionIdRef.current = selectedStoredSessionId
  sessionStateByRuntimeIdRef.current = activeSessionId && state ? new Map([[activeSessionId, state]]) : new Map()

  useHydrateStuckSessionAfterGatewayReconnect({
    activeSessionIdRef,
    gatewayState,
    hydrateFromStoredSession,
    selectedStoredSessionIdRef,
    sessionStateByRuntimeIdRef
  })

  return null
}

describe('gateway reconnect recovery', () => {
  afterEach(() => {
    cleanup()
  })

  it('detects locally stuck turns as needing reconnect hydration', () => {
    expect(shouldHydrateAfterGatewayReconnect(sessionState({ awaitingResponse: true }))).toBe(true)
    expect(shouldHydrateAfterGatewayReconnect(sessionState({ busy: true }))).toBe(true)
    expect(shouldHydrateAfterGatewayReconnect(sessionState({ streamId: 'assistant-stream-1' }))).toBe(true)
    expect(shouldHydrateAfterGatewayReconnect(sessionState())).toBe(false)
    expect(shouldHydrateAfterGatewayReconnect(null)).toBe(false)
  })

  it('hydrates a locally stuck active session when the gateway reconnects', async () => {
    const hydrateFromStoredSession = vi.fn().mockResolvedValue(undefined)
    const stuck = sessionState({ awaitingResponse: true, busy: true, streamId: 'assistant-stream-1' })

    const { rerender } = render(
      <Harness gatewayState="closed" hydrateFromStoredSession={hydrateFromStoredSession} state={stuck} />
    )

    expect(hydrateFromStoredSession).not.toHaveBeenCalled()

    rerender(<Harness gatewayState="open" hydrateFromStoredSession={hydrateFromStoredSession} state={stuck} />)

    await waitFor(() => {
      expect(hydrateFromStoredSession).toHaveBeenCalledWith(3, 'stored-from-state', 'runtime-1')
    })
  })

  it('does not hydrate idle sessions on reconnect', async () => {
    const hydrateFromStoredSession = vi.fn().mockResolvedValue(undefined)
    const idle = sessionState()

    const { rerender } = render(
      <Harness gatewayState="closed" hydrateFromStoredSession={hydrateFromStoredSession} state={idle} />
    )

    rerender(<Harness gatewayState="open" hydrateFromStoredSession={hydrateFromStoredSession} state={idle} />)

    await Promise.resolve()
    expect(hydrateFromStoredSession).not.toHaveBeenCalled()
  })
})
