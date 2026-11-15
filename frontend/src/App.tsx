import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './api'
import { AgentChat } from './components/AgentChat'
import { ApprovalCard } from './components/ApprovalCard'
import { DispatchPanel, type NewJob } from './components/DispatchPanel'
import { FloorPlan } from './components/FloorPlan'
import { PlanPanel } from './components/PlanPanel'
import type { BuildingMap, Job, Meta, Place, Plan, Proposal, StaffMember } from './types'
import { hhmm } from './ui'
import { useAgent } from './useAgent'

type Tab = 'plan' | 'dispatch' | 'agent'
type View = 'plan2d' | 'tour3d'

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [map, setMap] = useState<BuildingMap | null>(null)
  const [places, setPlaces] = useState<Place[]>([])
  const [staff, setStaff] = useState<StaffMember[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [current, setCurrent] = useState<Plan | null>(null)
  const [proposal, setProposal] = useState<Proposal | null>(null) // from "Optimize" (no agent)
  const [agentPreview, setAgentPreview] = useState<Proposal | null>(null) // plan behind the agent's approval card
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('plan')
  const [view, setView] = useState<View>('plan2d')
  const [viaAgent, setViaAgent] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fatal, setFatal] = useState<string | null>(null)
  const [lastJob, setLastJob] = useState<Job | null>(null)

  const refresh = useCallback(async () => {
    const [m, j, c] = await Promise.all([api.meta(), api.jobs(), api.currentPlan()])
    setMeta(m); setJobs(j); setCurrent(c)
  }, [])

  const ag = useAgent(useCallback(() => { refresh().catch(() => {}) }, [refresh]))

  useEffect(() => {
    Promise.all([api.map(), api.places(), api.staff(), refresh()])
      .then(([mp, pl, st]) => { setMap(mp); setPlaces(pl); setStaff(st) })
      .catch(e => setFatal(e instanceof ApiError && e.status === 503
        ? 'The backend is running but the building export is missing. Run tools/matterport_export (see docs/handoff-2026-11-15.md).'
        : `Can't reach the backend (${String(e)}). Start it: cd backend && uv run uvicorn app.main:app --port 8000`))
  }, [refresh])

  useEffect(() => {
    if (!ag.pending) { setAgentPreview(null); return }
    setTab('agent')
    // Ignore a response that arrives after this card was decided or replaced, so a stale plan never
    // shows on the next card or the map.
    let live = true
    api.proposal(ag.pending.plan_id)
      .then(p => { if (live) setAgentPreview(p) })
      .catch(() => { if (live) setAgentPreview(null) })
    return () => { live = false }
  }, [ag.pending])

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null)
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }

  const optimize = () => guard(async () => { setProposal(await api.propose()); setTab('plan') })
  const approveProposal = () => guard(async () => {
    if (!proposal) return
    await api.apply(proposal.plan.id)
    setProposal(null)
    await refresh()
  })
  const afterNewJob = async (job: Job) => {
    setLastJob(job)
    await refresh()
    if (viaAgent) { setTab('agent'); await ag.sendEvent({ kind: 'job_added', job_id: job.id }) }
    else { setProposal(await api.propose()); setTab('plan') }
  }
  const createJob = (j: NewJob) => guard(async () => afterNewJob(await api.createJob(j)))
  const simulateStat = () => guard(async () => afterNewJob(await api.simulateStat()))
  const advanceClock = (min: number) => guard(async () => {
    if (!meta) return
    const t = new Date(`${meta.now}Z`)
    t.setUTCMinutes(t.getUTCMinutes() + min)
    setMeta(await api.setClock(t.toISOString().slice(0, 19)))
  })

  if (fatal) return <div className="m-8 rounded border border-rose-300 bg-rose-50 p-4 text-rose-800">{fatal}</div>
  if (!meta || !map) return <div className="m-8 text-slate-500">Loading…</div>

  const shown = agentPreview?.plan ?? proposal?.plan ?? current
  const highlight = lastJob ? [lastJob.pickup_place_id, ...(lastJob.dropoff_place_id ? [lastJob.dropoff_place_id] : [])] : []
  const attribution = map.attribution
  const tabBtn = (t: Tab, label: string) => (
    <button onClick={() => setTab(t)}
            className={`flex-1 py-2 text-sm ${tab === t ? 'border-b-2 border-slate-900 font-medium' : 'text-slate-500'}`}>
      {label}{t === 'agent' && ag.pending ? ' •' : ''}
    </button>
  )

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-4 py-2">
        <h1 className="text-lg font-semibold">Rounds</h1>
        <span title={meta.scenario_label}
              className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">SYNTHETIC staff &amp; jobs</span>
        <span className="text-sm text-slate-600">
          Sim time <b className="font-mono">{hhmm(meta.now)}</b> · shift {hhmm(meta.shift_start)}–{hhmm(meta.shift_end)}
        </span>
        <button disabled={busy} onClick={() => advanceClock(15)}
                className="rounded border border-slate-300 px-2 py-0.5 text-sm hover:bg-slate-50">+15 min</button>
        <button disabled={busy} onClick={optimize}
                className="ml-auto rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
          Optimize shift
        </button>
      </header>

      {error && (
        <div className="flex items-center gap-2 bg-rose-50 px-4 py-1.5 text-sm text-rose-700">
          {error}<button className="ml-auto" onClick={() => setError(null)}>✕</button>
        </div>
      )}

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <section className="flex min-h-[50vh] flex-1 flex-col">
          <div className="flex gap-1 border-b border-slate-200 bg-white px-2">
            {(['plan2d', 'tour3d'] as View[]).map(v => (
              <button key={v} onClick={() => setView(v)}
                      className={`px-3 py-1.5 text-sm ${view === v ? 'border-b-2 border-slate-900 font-medium' : 'text-slate-500'}`}>
                {v === 'plan2d' ? 'Floor plan' : '3D tour'}
              </button>
            ))}
            <span className="ml-auto self-center text-xs text-slate-500">
              {shown === agentPreview?.plan ? `Previewing ${shown?.id} (awaiting approval)`
                : shown === proposal?.plan ? `Previewing ${shown?.id} (not applied)`
                  : current ? `Current plan ${current.id}` : 'No plan applied'}
            </span>
          </div>
          <div className="min-h-0 flex-1 p-2">
            {view === 'plan2d'
              ? <FloorPlan map={map} plan={shown} staff={staff} selected={selected} highlightPlaceIds={highlight} />
              : <iframe title="Matterport 3D tour" className="h-full w-full rounded" allow="xr-spatial-tracking; fullscreen"
                        src={`https://my.matterport.com/show?m=${map.model_id}&play=1&qs=1`} />}
          </div>
          <p className="px-3 pb-2 text-xs text-slate-500">
            Layout and place names: {attribution.name ?? 'Matterport model'} ({map.model_id}), public Matterport tour
            {attribution.presented_by ? <> by {attribution.presented_by}</> : null}
            {attribution.share_url ? <> · <a className="underline" href={attribution.share_url} target="_blank" rel="noreferrer">source</a></> : null}.
            Patients, staff and jobs are synthetic.
          </p>
        </section>

        <aside className="flex min-h-0 w-full flex-col border-l border-slate-200 bg-slate-50 lg:w-[460px]">
          <div className="space-y-2 p-2 empty:hidden">
            {ag.pending && (
              <ApprovalCard title="Agent proposes a schedule change" diff={ag.pending.plan_diff}
                            plan={agentPreview?.plan} rationale={ag.pending.rationale} jobs={jobs} busy={ag.busy}
                            onApprove={() => ag.decide('approve')} onReject={note => ag.decide('reject', note)} />
            )}
            {proposal && (
              <ApprovalCard title="Optimized plan ready" diff={proposal.diff} plan={proposal.plan} jobs={jobs} busy={busy}
                            onApprove={approveProposal} onReject={() => setProposal(null)} rejectLabel="Discard" />
            )}
          </div>
          <nav className="flex border-b border-slate-200 bg-white">
            {tabBtn('plan', 'Plan')}{tabBtn('dispatch', 'Dispatch')}{tabBtn('agent', 'Agent')}
          </nav>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {tab === 'plan' && (
              <PlanPanel plan={shown} isProposal={shown !== current} staff={staff} unavailable={meta.unavailable_staff_ids}
                         jobs={jobs} places={places} selected={selected} onSelect={setSelected} />
            )}
            {tab === 'dispatch' && (<>
              <label className="flex items-center gap-2 px-3 pt-3 text-sm">
                <input type="checkbox" checked={viaAgent} onChange={e => setViaAgent(e.target.checked)} />
                Send new requests to the agent (otherwise re-optimize directly)
              </label>
              <DispatchPanel meta={meta} places={places} busy={busy || ag.busy} onCreate={createJob}
                             onSimulateStat={simulateStat} />
            </>)}
            {tab === 'agent' && (
              <AgentChat log={ag.log} draft={ag.draft} todos={ag.todos} busy={ag.busy} onSend={ag.send} onNewShift={ag.newShift} />
            )}
          </div>
        </aside>
      </main>
    </div>
  )
}
