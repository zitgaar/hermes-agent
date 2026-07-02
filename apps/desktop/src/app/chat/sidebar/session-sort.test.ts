import { describe, expect, it } from 'vitest'

import type { SessionInfo } from '@/types/hermes'

import { sortAgentSessionsByRecency } from './session-sort'

const session = (id: string, startedAt: number, lastActive: number): SessionInfo =>
  ({
    archived: false,
    ended_at: null,
    id,
    input_tokens: 0,
    is_active: false,
    last_active: lastActive,
    message_count: 1,
    model: null,
    output_tokens: 0,
    preview: null,
    source: 'desktop',
    started_at: startedAt,
    title: null,
    tool_call_count: 0
  }) as SessionInfo

describe('sortAgentSessionsByRecency', () => {
  it('uses last_active before started_at so continued compressed threads do not sink', () => {
    const oldButActive = session('old-but-active', 10, 500)
    const newlyCreatedButIdle = session('new-idle', 400, 400)

    expect(sortAgentSessionsByRecency([newlyCreatedButIdle, oldButActive]).map(s => s.id)).toEqual([
      'old-but-active',
      'new-idle'
    ])
  })

  it('falls back to started_at when last_active is absent', () => {
    expect(sortAgentSessionsByRecency([session('older', 1, 0), session('newer', 2, 0)]).map(s => s.id)).toEqual([
      'newer',
      'older'
    ])
  })
})
