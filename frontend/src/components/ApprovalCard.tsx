import { useState } from 'react'
import type { Job, PlanDiff, Plan } from '../types'
import { meters } from '../ui'

type Props = {
  title: string
  diff: PlanDiff
  plan?: Plan | null
  rationale?: string
  jobs: Job[]
  busy?: boolean
  onApprove: () => void
  onReject: (note: string) => void
  rejectLabel?: string
}

/** Before/after card for a proposed schedule change. Nothing changes until a human approves. */
export function ApprovalCard({ title, diff, plan, rationale, jobs, busy, onApprove, onReject, rejectLabel }: Props) {
  const [note, setNote] = useState('')
  const kind = (id: string) => jobs.find(j => j.id === id)?.kind.replace(/_/g, ' ') ?? ''
  const delta = (n: number, unit = '') => `${n > 0 ? '+' : ''}${unit === 'm' ? meters(n) : n}`

  return (
    <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-3 text-sm shadow-sm">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="font-semibold">{title}</h3>
        <span className="font-mono text-xs text-slate-500">{diff.from_plan_id ?? 'none'} → {diff.to_plan_id}</span>
      </div>
      {rationale && <p className="mb-2 text-slate-700">{rationale}</p>}

      <dl className="mb-2 grid grid-cols-2 gap-x-3 gap-y-1">
        <dt className="text-slate-500">Walking</dt>
        <dd className={diff.meters_delta > 0 ? 'text-rose-700' : 'text-emerald-700'}>{delta(diff.meters_delta, 'm')}</dd>
        <dt className="text-slate-500">Late jobs</dt>
        <dd className={diff.late_jobs_delta > 0 ? 'text-rose-700' : 'text-emerald-700'}>{delta(diff.late_jobs_delta)}</dd>
        {plan?.baseline && (<>
          <dt className="text-slate-500">vs. due-order baseline</dt>
          <dd>{meters(plan.total_meters)} vs {meters(plan.baseline.total_meters)}</dd>
        </>)}
        <dt className="text-slate-500">Routes changed</dt>
        <dd>{diff.reordered_staff_ids.length ? diff.reordered_staff_ids.join(', ') : 'none'}</dd>
      </dl>

      {diff.added_job_ids.length > 0 && (
        <p><span className="text-slate-500">Added: </span>
          {diff.added_job_ids.slice(0, 6).map(id => `${id} (${kind(id)})`).join(', ')}
          {diff.added_job_ids.length > 6 && ` and ${diff.added_job_ids.length - 6} more`}</p>
      )}
      {diff.removed_job_ids.length > 0 && (
        <p><span className="text-slate-500">Removed: </span>{diff.removed_job_ids.join(', ')}</p>
      )}
      {diff.newly_infeasible.length > 0 && (
        <ul className="mt-1 rounded bg-rose-100 p-2 text-rose-800">
          {diff.newly_infeasible.map(i => <li key={i.job_id}><b>{i.job_id}</b>: {i.reason}</li>)}
        </ul>
      )}

      <div className="mt-3 flex gap-2">
        <button disabled={busy} onClick={onApprove}
                className="rounded bg-emerald-600 px-3 py-1.5 font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
          Approve
        </button>
        <input value={note} onChange={e => setNote(e.target.value)} placeholder="note (optional)"
               className="min-w-0 flex-1 rounded border border-slate-300 bg-white px-2" />
        <button disabled={busy} onClick={() => onReject(note)}
                className="rounded border border-slate-400 px-3 py-1.5 hover:bg-white disabled:opacity-50">
          {rejectLabel ?? 'Reject'}
        </button>
      </div>
    </div>
  )
}
