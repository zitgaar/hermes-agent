import { type MutableRefObject, useEffect, useRef } from 'react'

import type { ClientSessionState } from '../../../types'

export function shouldHydrateAfterGatewayReconnect(state: ClientSessionState | null | undefined): boolean {
  return Boolean(state?.busy || state?.awaitingResponse || state?.streamId)
}

export function useHydrateStuckSessionAfterGatewayReconnect({
  activeSessionIdRef,
  gatewayState,
  hydrateFromStoredSession,
  selectedStoredSessionIdRef,
  sessionStateByRuntimeIdRef
}: {
  activeSessionIdRef: MutableRefObject<string | null>
  gatewayState: string
  hydrateFromStoredSession: (
    attempts?: number,
    storedSessionId?: string | null,
    runtimeSessionId?: string | null
  ) => Promise<void>
  selectedStoredSessionIdRef: MutableRefObject<string | null>
  sessionStateByRuntimeIdRef: MutableRefObject<Map<string, ClientSessionState>>
}) {
  const previousGatewayStateRef = useRef(gatewayState)

  useEffect(() => {
    const previousGatewayState = previousGatewayStateRef.current
    previousGatewayStateRef.current = gatewayState

    if (gatewayState !== 'open' || previousGatewayState === 'open') {
      return
    }

    const runtimeSessionId = activeSessionIdRef.current

    if (!runtimeSessionId) {
      return
    }

    const state = sessionStateByRuntimeIdRef.current.get(runtimeSessionId)

    if (!shouldHydrateAfterGatewayReconnect(state)) {
      return
    }

    void hydrateFromStoredSession(
      3,
      state?.storedSessionId ?? selectedStoredSessionIdRef.current,
      runtimeSessionId
    )
  }, [activeSessionIdRef, gatewayState, hydrateFromStoredSession, selectedStoredSessionIdRef, sessionStateByRuntimeIdRef])
}
