import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { BuildingMap, Plan, StaffMember } from '../types'
import { staffColor } from '../ui'

type Props = {
  map: BuildingMap
  plan: Plan | null
  staff: StaffMember[]
  selected: string | null
  highlightPlaceIds: string[]
}

const routeCache = new Map<string, Promise<string[]>>()

function legNodes(a: string, b: string): Promise<string[]> {
  const key = `${a}>${b}`
  if (!routeCache.has(key)) {
    routeCache.set(key, a === b ? Promise.resolve([]) : api.route(a, b).then(r => r.node_ids).catch(() => []))
  }
  return routeCache.get(key)!
}

/** 2D floor plan: rooms, walking graph, named places, and each staff route along real A* paths. */
export function FloorPlan({ map, plan, staff, selected, highlightPlaceIds }: Props) {
  const [paths, setPaths] = useState<Record<string, string[]>>({})

  const node = useMemo(() => new Map(map.nodes.map(n => [n.id, n])), [map])
  const place = useMemo(() => new Map(map.places.map(p => [p.id, p])), [map])

  const box = useMemo(() => {
    const xs = [...map.nodes.map(n => n.x), ...map.rooms.flatMap(r => [r.min_x, r.max_x])]
    const ys = [...map.nodes.map(n => -n.y), ...map.rooms.flatMap(r => [-r.min_y, -r.max_y])]
    const pad = 2
    const minX = Math.min(...xs) - pad, minY = Math.min(...ys) - pad
    return { minX, minY, w: Math.max(...xs) - minX + pad, h: Math.max(...ys) - minY + pad }
  }, [map])

  useEffect(() => {
    let cancelled = false
    if (!plan) { setPaths({}); return }
    const startOf = new Map(staff.map(s => [s.id, s.start_place_id]))
    Promise.all(plan.assignments.map(async a => {
      const seq = [startOf.get(a.staff_id)!, ...a.stops.map(s => s.place_id)]
      const legs = await Promise.all(seq.slice(1).map((p, i) => legNodes(seq[i], p)))
      return [a.staff_id, legs.flat()] as const
    })).then(entries => { if (!cancelled) setPaths(Object.fromEntries(entries)) })
    return () => { cancelled = true }
  }, [plan, staff])

  const pt = (id: string) => {
    const n = node.get(id)
    return n ? `${n.x},${-n.y}` : ''
  }
  const fs = Math.max(box.w, box.h) / 90

  return (
    <svg viewBox={`${box.minX} ${box.minY} ${box.w} ${box.h}`} className="h-full w-full" role="img"
         aria-label="Floor plan with staff routes">
      {map.rooms.map(r => (
        <rect key={r.id} x={r.min_x} y={-r.max_y} width={r.max_x - r.min_x} height={r.max_y - r.min_y}
              className="fill-white stroke-slate-300" strokeWidth={fs * 0.12} />
      ))}
      {map.edges.map(([a, b]) => (
        <polyline key={`${a}-${b}`} points={`${pt(a)} ${pt(b)}`} className="stroke-slate-200"
                  strokeWidth={fs * 0.08} />
      ))}
      {plan?.assignments.map((a, i) => {
        const pts = (paths[a.staff_id] ?? []).map(pt).join(' ')
        const dim = selected && selected !== a.staff_id
        return pts && (
          <polyline key={a.staff_id} points={pts} fill="none" stroke={staffColor(staff, a.staff_id, i)}
                    strokeWidth={fs * (selected === a.staff_id ? 0.55 : 0.35)} strokeLinejoin="round"
                    strokeLinecap="round" opacity={dim ? 0.12 : 0.85} />
        )
      })}
      {map.places.map(p => {
        const hot = highlightPlaceIds.includes(p.id)
        return (
          <g key={p.id}>
            <circle cx={p.x} cy={-p.y} r={fs * (hot ? 0.6 : 0.3)}
                    className={hot ? 'fill-rose-500' : 'fill-slate-500'} />
            <text x={p.x + fs * 0.5} y={-p.y + fs * 0.3} fontSize={fs} className="fill-slate-600 select-none">
              {p.name}
            </text>
          </g>
        )
      })}
      {plan?.assignments.flatMap((a, i) => {
        if (selected && selected !== a.staff_id) return []
        return a.stops.map((s, k) => {
          const p = place.get(s.place_id)
          if (!p) return null
          return (
            <g key={`${a.staff_id}-${k}`}>
              <circle cx={p.x} cy={-p.y} r={fs * 0.55} fill={staffColor(staff, a.staff_id, i)} />
              <text x={p.x} y={-p.y + fs * 0.25} fontSize={fs * 0.7} textAnchor="middle"
                    className="fill-white font-semibold select-none">{k + 1}</text>
            </g>
          )
        })
      })}
    </svg>
  )
}
