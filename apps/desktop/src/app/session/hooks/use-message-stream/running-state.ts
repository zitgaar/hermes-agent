import type { ClientSessionState } from '../../../types'

export function applySessionInfoRunningState(
  state: ClientSessionState,
  running: boolean,
  now = Date.now()
): ClientSessionState {
  const busy = Boolean(running)

  if (state.busy === busy && (busy || !state.awaitingResponse)) {
    return state
  }

  if (busy) {
    return {
      ...state,
      busy: true,
      turnStartedAt: state.turnStartedAt ?? now
    }
  }

  return {
    ...state,
    awaitingResponse: false,
    busy: false,
    pendingBranchGroup: null,
    streamId: null,
    turnStartedAt: null
  }
}
