import { useEffect, useRef, useState } from 'react'
import type { LogLine } from '../useAgent'
import type { TodoItem } from '../types'

type Props = {
  log: LogLine[]
  draft: string
  todos: TodoItem[]
  busy: boolean
  onSend: (text: string) => void
  onNewShift: () => void
}

const STYLE: Record<LogLine['kind'], string> = {
  user: 'ml-8 bg-slate-900 text-white',
  assistant: 'mr-8 bg-white border border-slate-200',
  tool: 'font-mono text-xs text-slate-500',
  subagent: 'text-xs italic text-violet-600',
  error: 'bg-rose-50 text-rose-700 border border-rose-200',
}

/** Chat with the Deep Agent coordinator: visible todo plan, tool calls and subagent handoffs. */
export function AgentChat({ log, draft, todos, busy, onSend, onNewShift }: Props) {
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [log, draft])

  return (
    <div className="flex h-full flex-col text-sm">
      {todos.length > 0 && (
        <ul className="border-b border-slate-200 bg-white p-2">
          {todos.map((t, i) => (
            <li key={i} className={t.status === 'completed' ? 'text-slate-400 line-through' : ''}>
              {t.status === 'in_progress' ? '▶ ' : t.status === 'completed' ? '✓ ' : '○ '}{t.content}
            </li>
          ))}
        </ul>
      )}
      <div className="flex-1 space-y-1.5 overflow-y-auto p-2">
        {log.length === 0 && (
          <p className="text-slate-500">Ask e.g. “Plan my shift”, or “Why is Room 4 before Room 9?”. The agent only quotes
            numbers from the optimizer, and every schedule change needs your approval.</p>
        )}
        {log.map((l, i) => (
          <div key={i} className={`whitespace-pre-wrap rounded px-2 py-1 ${STYLE[l.kind]} ${l.ok === false ? 'text-rose-600' : ''}`}>
            {l.text}
          </div>
        ))}
        {draft && <div className="mr-8 whitespace-pre-wrap rounded border border-slate-200 bg-white px-2 py-1">{draft}</div>}
        {busy && !draft && <div className="text-xs text-slate-400">working…</div>}
        <div ref={end} />
      </div>
      <div className="flex gap-2 border-t border-slate-200 px-2 pt-2 text-xs">
        <button disabled={busy} onClick={() => onSend('Write the shift handoff.')}
                className="rounded border border-slate-400 px-2 py-1 hover:bg-white disabled:opacity-40">
          Write shift handoff
        </button>
        <button disabled={busy} onClick={onNewShift} title="New conversation; the agent can read the last handoff"
                className="rounded border border-slate-400 px-2 py-1 hover:bg-white disabled:opacity-40">
          Start next shift
        </button>
      </div>
      <form className="flex gap-2 p-2"
            onSubmit={e => { e.preventDefault(); if (text.trim() && !busy) { onSend(text.trim()); setText('') } }}>
        <input value={text} onChange={e => setText(e.target.value)} maxLength={4000} placeholder="Message the agent"
               className="min-w-0 flex-1 rounded border border-slate-300 px-2 py-1.5" />
        <button disabled={busy || !text.trim()} className="rounded bg-slate-900 px-3 text-white disabled:opacity-40">Send</button>
      </form>
    </div>
  )
}
