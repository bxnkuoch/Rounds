import { useState } from 'react'
import type { Meta, Place } from '../types'
import { kindLabel } from '../ui'

export type NewJob = {
  kind: string
  pickup_place_id: string
  dropoff_place_id: string | null
  latest: string | null
  priority: number
}

type Props = {
  meta: Meta
  places: Place[]
  busy: boolean
  onCreate: (job: NewJob) => void
  onSimulateStat: () => void
}

/** Dispatch inbox: structured requests come from here (or the source system), never from the chat model. */
export function DispatchPanel({ meta, places, busy, onCreate, onSimulateStat }: Props) {
  const rooms = places.filter(p => /^(Room \d+|Assessment Room \d+)$/.test(p.name))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  const named = [...places].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
  const kinds = Object.keys(meta.job_kinds)
  const [kind, setKind] = useState(kinds[0] ?? '')
  const [pickup, setPickup] = useState(rooms[0]?.id ?? '')
  const [dropoff, setDropoff] = useState(named[0]?.id ?? '')
  const [due, setDue] = useState(meta.now.slice(11, 16))
  const [priority, setPriority] = useState(2)

  const submit = () => onCreate({
    kind,
    pickup_place_id: pickup,
    dropoff_place_id: kind === 'transport' ? dropoff : null,
    latest: due ? `${meta.now.slice(0, 11)}${due}:00` : null,
    priority,
  })

  const field = 'rounded border border-slate-300 bg-white px-1.5 py-1'
  return (
    <div className="space-y-2 p-3 text-sm">
      <button disabled={busy} onClick={onSimulateStat}
              className="w-full rounded bg-rose-600 py-2 font-medium text-white hover:bg-rose-700 disabled:opacity-50">
        Simulate STAT call
      </button>
      <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5">
        <label>Kind</label>
        <select className={field} value={kind} onChange={e => setKind(e.target.value)}>
          {kinds.map(k => <option key={k} value={k}>{kindLabel(k)}</option>)}
        </select>
        <label>{kind === 'transport' ? 'From' : 'Where'}</label>
        <select className={field} value={pickup} onChange={e => setPickup(e.target.value)}>
          {rooms.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        {kind === 'transport' && (<>
          <label>To</label>
          <select className={field} value={dropoff} onChange={e => setDropoff(e.target.value)}>
            {named.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </>)}
        <label>Due by</label>
        <input type="time" className={field} value={due} onChange={e => setDue(e.target.value)} />
        <label>Priority</label>
        <select className={field} value={priority} onChange={e => setPriority(Number(e.target.value))}>
          <option value={1}>1 · STAT</option><option value={2}>2 · Urgent</option><option value={3}>3 · Routine</option>
        </select>
      </div>
      <button disabled={busy || !pickup} onClick={submit}
              className="w-full rounded border border-slate-400 py-1.5 hover:bg-white disabled:opacity-50">
        Add request
      </button>
      <p className="text-xs text-slate-500">Priority comes from the request, never from the AI. Requests are synthetic demo data.</p>
    </div>
  )
}
