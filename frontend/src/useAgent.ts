import { useCallback, useRef, useState } from 'react'
import { agent, ApiError } from './api'
import type { AgentEvent, ApprovalRequired, ReplanEvent, TodoItem } from './types'

export type LogLine = { kind: 'user' | 'assistant' | 'tool' | 'subagent' | 'error'; text: string; ok?: boolean }

/** One agent thread: streams Minh's typed events into chat log, todos and a pending approval. */
export function useAgent(onRunFinished: () => void) {
  const thread = useRef<string | null>(null)
  const [log, setLog] = useState<LogLine[]>([])
  const [draft, setDraft] = useState('')
  const [todos, setTodos] = useState<TodoItem[]>([])
  const [pending, setPending] = useState<ApprovalRequired | null>(null)
  const [busy, setBusy] = useState(false)

  const push = (l: LogLine) => setLog(prev => [...prev, l])

  const run = useCallback(async (start: (t: string) => AsyncGenerator<AgentEvent>) => {
    setBusy(true)
    let text = ''
    try {
      if (!thread.current) thread.current = (await agent.createThread()).thread_id
      for await (const e of start(thread.current)) {
        switch (e.type) {
          case 'token': text += e.text; setDraft(text); break
          case 'todos': setTodos(e.items); break
          case 'tool_call': push({ kind: 'tool', text: `${e.name}(${JSON.stringify(e.args)})` }); break
          case 'tool_result': push({ kind: 'tool', text: `${e.name} → ${e.summary}`, ok: e.ok }); break
          case 'subagent_started': push({ kind: 'subagent', text: `→ ${e.subagent} subagent` }); break
          case 'subagent_finished': push({ kind: 'subagent', text: `← ${e.subagent} done` }); break
          case 'approval_required': setPending(e); break
          case 'message': push({ kind: 'assistant', text: e.text }); text = ''; setDraft(''); break
          case 'error': push({ kind: 'error', text: `${e.code}: ${e.message}` }); break
          case 'done':
            if (text) push({ kind: 'assistant', text })
            text = ''
            setDraft('')
            if (e.status === 'completed') setPending(null)
            break
        }
      }
    } catch (err) {
      push({ kind: 'error', text: err instanceof ApiError ? `${err.status}: ${err.message}` : String(err) })
    } finally {
      setBusy(false)
      setDraft('')
      onRunFinished()
    }
  }, [onRunFinished])

  const send = (text: string) => {
    push({ kind: 'user', text })
    return run(t => agent.message(t, text))
  }
  const sendEvent = (e: ReplanEvent) => {
    push({ kind: 'user', text: e.kind === 'job_added' ? `[dispatch] new job ${e.job_id}` : `[dispatch] ${e.staff_id} unavailable` })
    return run(t => agent.event(t, e))
  }
  const decide = (decision: 'approve' | 'reject', note?: string) => {
    if (!pending) return
    const id = pending.approval_id
    push({ kind: 'user', text: `${decision === 'approve' ? 'Approved' : 'Rejected'} ${pending.plan_id}${note ? `: ${note}` : ''}` })
    setPending(null)
    return run(t => agent.decide(t, id, decision, note))
  }

  return { log, draft, todos, pending, busy, send, sendEvent, decide }
}
