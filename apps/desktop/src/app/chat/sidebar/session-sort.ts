import type { SessionInfo } from '@/types/hermes'

export const agentSessionRecency = (session: SessionInfo): number => session.last_active || session.started_at || 0

export function compareAgentSessionsByRecency(a: SessionInfo, b: SessionInfo): number {
  const recencyDelta = agentSessionRecency(b) - agentSessionRecency(a)

  if (recencyDelta !== 0) {
    return recencyDelta
  }

  const createdDelta = (b.started_at || 0) - (a.started_at || 0)

  if (createdDelta !== 0) {
    return createdDelta
  }

  return b.id.localeCompare(a.id)
}

export function sortAgentSessionsByRecency(sessions: SessionInfo[]): SessionInfo[] {
  return [...sessions].sort(compareAgentSessionsByRecency)
}
