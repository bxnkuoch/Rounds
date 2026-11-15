import type {
  AgentEvent, BuildingMap, Job, Meta, Place, Plan, Proposal, ReplanEvent, Route, StaffMember,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const j = await res.json()
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  meta: () => req<Meta>('GET', '/api/meta'),
  map: () => req<BuildingMap>('GET', '/api/map'),
  places: () => req<Place[]>('GET', '/api/places'),
  staff: () => req<StaffMember[]>('GET', '/api/staff'),
  jobs: () => req<Job[]>('GET', '/api/jobs'),
  route: (a: string, b: string) =>
    req<Route>('GET', `/api/routes?from_place_id=${encodeURIComponent(a)}&to_place_id=${encodeURIComponent(b)}`),
  createJob: (body: Partial<Job> & { kind: string; pickup_place_id: string }) => req<Job>('POST', '/api/jobs', body),
  simulateStat: () => req<Job>('POST', '/api/jobs/simulate-stat'),
  currentPlan: () => req<Plan | null>('GET', '/api/plans/current'),
  propose: () => req<Proposal>('POST', '/api/plans/propose', {}),
  proposal: (id: string) => req<Proposal>('GET', `/api/plans/${encodeURIComponent(id)}`),
  apply: (id: string) => req<Plan>('POST', `/api/plans/${encodeURIComponent(id)}/apply`),
  setClock: (now: string) => req<Meta>('POST', '/api/clock', { now }),
}

// ---- agent (Minh's /agent router): SSE over POST, so fetch + stream reader ----

async function* sse(path: string, body: unknown): AsyncGenerator<AgentEvent> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* ignore */ }
    throw new ApiError(res.status, String(detail))
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += value
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i)
      buf = buf.slice(i + 2)
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) yield JSON.parse(line.slice(6)) as AgentEvent
      }
    }
  }
}

export const agent = {
  createThread: () => req<{ thread_id: string }>('POST', '/agent/threads'),
  message: (t: string, text: string) => sse(`/agent/threads/${t}/messages`, { text }),
  event: (t: string, e: ReplanEvent) => sse(`/agent/threads/${t}/events`, e),
  decide: (t: string, approvalId: string, decision: 'approve' | 'reject', note?: string) =>
    sse(`/agent/threads/${t}/approvals/${approvalId}`, { decision, note: note || null }),
}
