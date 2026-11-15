import type { Job, Place, Plan, StaffMember } from '../types'
import { hhmm, kindLabel, meters, PRIORITY_LABEL, ROLE_LABEL, staffColor } from '../ui'

type Props = {
  plan: Plan | null
  isProposal: boolean
  staff: StaffMember[]
  unavailable: string[]
  jobs: Job[]
  places: Place[]
  selected: string | null
  onSelect: (id: string | null) => void
}

/** Per-staff ordered stops with ETAs and meters, plus optimized vs baseline metrics. */
export function PlanPanel({ plan, isProposal, staff, unavailable, jobs, places, selected, onSelect }: Props) {
  const job = new Map(jobs.map(j => [j.id, j]))
  const placeName = (id: string) => places.find(p => p.id === id)?.name ?? id
  const lateBy = new Map(plan?.late.map(l => [l.job_id, l.minutes_late]) ?? [])

  if (!plan) {
    return <p className="p-3 text-sm text-slate-500">No plan yet. Click <b>Optimize shift</b>.</p>
  }

  return (
    <div className="space-y-3 p-3 text-sm">
      <div className="grid grid-cols-3 gap-2 text-center">
        <Stat label={isProposal ? 'Proposed walking' : 'Planned walking'} value={meters(plan.total_meters)} />
        <Stat label="Due-order baseline" value={plan.baseline ? meters(plan.baseline.total_meters) : '—'} />
        <Stat label="Late (plan / baseline)" value={`${plan.late.length} / ${plan.baseline?.late_jobs ?? '—'}`} />
      </div>
      <p className="text-xs text-slate-500">
        Both computed on the same building graph, start positions and job set. Walking distances are approximate
        (Matterport scan-point links).
      </p>

      {plan.infeasible.length > 0 && (
        <div className="rounded border border-rose-300 bg-rose-50 p-2 text-rose-800">
          <b>Not scheduled ({plan.infeasible.length})</b>
          <ul>{plan.infeasible.map(i => <li key={i.job_id}>{i.job_id}: {i.reason}</li>)}</ul>
        </div>
      )}

      {staff.map(s => {
        const a = plan.assignments.find(x => x.staff_id === s.id)
        const off = unavailable.includes(s.id)
        const total = a?.stops.reduce((m, x) => m + x.meters_from_prev, 0) ?? 0
        return (
          <section key={s.id} className={`rounded border bg-white ${selected === s.id ? 'border-slate-900' : 'border-slate-200'}`}>
            <button onClick={() => onSelect(selected === s.id ? null : s.id)}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left">
              <span className="h-3 w-3 rounded-full" style={{ background: staffColor(staff, s.id) }} />
              <span className="font-medium">{s.id}</span>
              <span className="text-slate-500">{ROLE_LABEL[s.role]}</span>
              <span className="ml-auto text-slate-500">
                {off ? 'unavailable' : `${a?.stops.length ?? 0} stops · ${meters(total)}`}
              </span>
            </button>
            {a && a.stops.length > 0 && (
              <ol className="border-t border-slate-100 px-2 py-1">
                {a.stops.map((x, k) => {
                  const j = job.get(x.job_id)
                  const late = x.action !== 'pickup' ? lateBy.get(x.job_id) : undefined
                  return (
                    <li key={k} className="flex gap-2 py-0.5">
                      <span className="w-10 font-mono text-slate-500">{hhmm(x.eta)}</span>
                      <span className="w-14 text-slate-500">{x.action}</span>
                      <span className="flex-1">
                        {placeName(x.place_id)} <span className="text-slate-400">· {j ? kindLabel(j.kind) : x.job_id}</span>
                        {j && j.priority <= 2 && (
                          <span className="ml-1 rounded bg-rose-100 px-1 text-xs text-rose-700">{PRIORITY_LABEL[j.priority]}</span>
                        )}
                        {late !== undefined && <span className="ml-1 text-xs text-rose-600">late {late} min</span>}
                      </span>
                      <span className="text-slate-400">+{Math.round(x.meters_from_prev)} m</span>
                    </li>
                  )
                })}
              </ol>
            )}
          </section>
        )
      })}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-white p-2 shadow-sm">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  )
}
