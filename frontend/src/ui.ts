import type { Role, StaffMember } from './types'

const PALETTE = ['#2563eb', '#db2777', '#059669', '#d97706', '#7c3aed', '#0891b2', '#dc2626', '#4d7c0f']

export function staffColor(staff: StaffMember[], id: string, fallback = 0): string {
  const i = staff.findIndex(s => s.id === id)
  return PALETTE[(i >= 0 ? i : fallback) % PALETTE.length]
}

export const ROLE_LABEL: Record<Role, string> = {
  respiratory_therapist: 'Respiratory therapist',
  iv_nurse: 'IV nurse',
  transporter: 'Transporter',
}

/** "2026-11-15T07:20:00" -> "07:20" (simulated shift time, no timezone). */
export const hhmm = (iso: string | null) => (iso ? iso.slice(11, 16) : '—')

export const meters = (m: number) => `${Math.round(m).toLocaleString()} m`

export const kindLabel = (k: string) => k.replace(/_/g, ' ')

export const PRIORITY_LABEL: Record<number, string> = { 1: 'STAT', 2: 'Urgent', 3: 'Routine', 4: 'Low', 5: 'Low' }
