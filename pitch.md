# Rounds: Pitch & Problem Statement

> **The smarter way through every shift.**
> Rounds is built for the people who keep a hospital moving: transporters, respiratory therapists, and IV teams.

Status: brainstorming draft (2026-11-14). Items marked **[verify]** need a source before they go on a slide.

---

## One-liner

**Rounds turns a hospital's 3D digital twin into a live plan for every staff member who covers the whole building. An AI agent re-optimizes each shift as new requests arrive, and a human approves every change.**

## Problem statement

Some hospital staff don't stay on one unit: transporters, respiratory therapists, and IV/vascular access teams. They cover the **entire building**, and each shift is a moving target:

- **Spread out:** jobs are on different floors and wings, and moving a bed or wheelchair means elevators and accessible routes.
- **Time windows:** scheduled breathing treatments, OR start times, scan slots, line placements.
- **Constant interruptions:** STAT calls and new requests arrive all shift and break whatever plan existed.

**Example: the IV team nurse.** A hospital may have only a few vascular access nurses covering every unit. On a typical morning, one of them might get a dozen IV and line consults spread across five floors, several needed before morning meds or a procedure, and STAT requests keep coming. That's a large task volume, all over the building, in a short window, with no tool to plan it. **[verify the typical consult volume with a clinician]**

Today that plan lives in their heads or on a pager. Every interruption means re-sequencing the whole shift from memory while walking.

**Why this is a bottleneck and not just an inconvenience:** these roles connect the rest of the hospital. A late transport delays an OR start or a CT slot. A delayed treatment pushes back a discharge. A delayed discharge holds a bed the ER needs. One poorly ordered shift spreads delays through patient flow.

> Stats to find and cite **[verify]**:
> - Hendrich et al. 2008 (36-hospital time-and-motion study): nurses walk ~1–5 mi/shift; ~19% of time on direct patient care.
> - Respiratory therapist workforce shortage figures (e.g. AARC).
> - Transport delays and OR/imaging start delays, and their link to ER boarding.
> - Best: **a quote from a real RT, transporter, or IV nurse at HackPrinceton.**

## Who it's for

| Role | Their shift looks like | What Rounds fixes |
|---|---|---|
| **Respiratory therapist** (demo hero) | Scheduled treatments across 3+ floors, ventilator checks, STAT calls | Orders treatments within their time windows; replans when a STAT call arrives |
| **Transporter** | Pickup → drop-off jobs from a dispatcher, beds and wheelchairs | Accessible routes only (no stairs); keeps jobs on time for OR and imaging slots |
| **IV / vascular access team nurse** | Hospital-wide consults (e.g. a dozen across 5 floors before mid-morning), 15–60 min procedures | Groups nearby consults together; sequences them against when they're needed; flags requests that can't be done in time |
| **Float / resource nurse** | Pulled to whichever unit needs help; ad-hoc tasks across units | Same engine; tasks arrive in bursts from different units |
| **Supervisor / dispatcher** (approver) | Oversees the team | Approves replans; sees on-time risk across staff |

**Nurses are in scope when their work covers the building** (IV team, float/resource nurses). **Out of scope (on purpose):** bedside nurses on a single unit (patients grouped together, so the gain comes from sequencing, not routing) and ER staff (priorities set by triage, a clinical judgment Rounds must never make). Both are possible future work.

## Solution

Rounds tells each staff member **what to do next, when, and the best way to get there**, and keeps that answer correct as the shift changes.

1. **One job model for all three roles.** A job is either a **single-stop job** (treatment, line placement) or a **pickup → drop-off job** (transport), with time windows, a duration, a priority from the source system, and an accessibility requirement.
2. **Deterministic optimizer (pickup-and-delivery in the MVP).** A* on the building's navigation graph plus OR-Tools routing with time windows. For transport jobs, the pickup comes before its drop-off, both are done by the same person, at most one bed or wheelchair is moved at a time, and each end has its own window (patient ready / CT slot). The output is an ordered route, arrival times, walking distance, and **explicit flags for jobs that can't be done in time**. Jobs are never silently dropped.
3. **Deep Agent coordinator.** Handles requests in plain language ("STAT ABG in 204, fit it in"), plans the steps, calls the optimizer and the routing code, and explains its choices from real numbers.
4. **Human approval.** Every replan appears as a before/after card for the staff member or supervisor to approve.
5. **Spatially aware.** The navigation graph comes from the building's Matterport digital twin, so routes respect real walls, elevators, and accessibility.

**Safety principle:** Rounds orders and routes work. It never decides clinical urgency. Priorities come from the source system, and a human approves every change.

## How it maps to the tracks

| Track | What we show |
|---|---|
| **Healthcare (main)** | A real patient-flow bottleneck; measurable on-time and walking improvements against a baseline; human approval for every change |
| **LangChain: Best Use of DeepAgents** | Visible todo plan, subagent handoffs (spatial / scheduler / explainer), human-in-the-loop interrupts, a filesystem-written shift handoff report, and memory across shifts |
| **CoStar: Inside & Out** | Matterport digital twin → navigation graph (walls, elevators, accessible routes) plus CoStar building data for context. The data shapes the route; it isn't decoration |

## 2-minute demo script

| Time | Scene | On screen |
|---|---|---|
| 0:00–0:20 | **Hook** | "One IV team nurse, a dozen consults, five floors, before mid-morning. Transporters and RTs have the same problem: when they run late, the OR, imaging, and the ER run late too." Show Sam, an RT with 9 treatments across 3 floors |
| 0:20–0:45 | **Optimize** | Click *Optimize My Shift*. The route draws on the floor plan and Matterport view, with arrival times and walking distance **compared with the due-time-order baseline (computed, not hardcoded)** |
| 0:45–1:15 | **Interruption** | "STAT blood gas, Room 204." The agent panel shows its todo plan → scheduler-agent → spatial-agent → **approval card** showing the old and new routes, and one job flagged as now at risk |
| 1:15–1:35 | **Same engine, different role** | Switch to a transporter with 4 queued jobs, then add "bed move 204 → CT, scan at 10:30." The optimizer puts the pickup and drop-off into the queue (pickup before drop-off, one bed at a time, arriving before the CT slot), and the route detours to the elevator because of the accessibility flag |
| 1:35–1:50 | **Explain** | "Why is 310 before 305?" The agent answers with actual travel times and time windows |
| 1:50–2:00 | **Close** | "Rounds is built for the people who keep a hospital moving." Then the metrics |

## Questions judges will ask

- **"Don't hospitals already have dispatch software?"** Yes, for transport, and it assigns one job at a time. Rounds optimizes the whole shift's sequence and route against the building's real geometry, works across roles, and replans conversationally.
- **"Who decides priority?"** The source system (orders, dispatch). Rounds never changes clinical urgency or medication timing.
- **"Will staff actually use it?"** They get one "next job" card and a single tap to accept. Voice input is next. The supervisor uses the full dashboard.
- **"Is the hospital data real?"** The patients and jobs are synthetic. The spatial data is real Matterport/CoStar data where available, and the demo labels which is which.
- **"How do you know it's better?"** Both routes run on the same graph, from the same start, with the same jobs. We show the computed difference in walking and on-time rate.

## Open questions

- [ ] Can we get a Matterport model that looks like a hospital or clinic? If not, which building do we use, and how do we label it honestly?
- [ ] Does the Matterport API expose doors and room adjacency? This decides whether the navigation graph is auto-generated or hand-drawn on top of the model.
- [x] Model: Claude Haiku 5.5 via the Anthropic API (tool calling works; configurable with `AGENT_MODEL`). No Bedrock, so we make no Amazon track claim.
- [x] Pickup-and-delivery (transport) is **in the MVP**: OR-Tools pickup-and-delivery with time windows, one-bed capacity, and accessible-only edges for bed and wheelchair moves.
- [ ] Do transport jobs take accessible-only routes for every job, or only when a bed or wheelchair is involved? (Suggest: a per-job `requires_accessible` flag.)
- [ ] Find a clinician on site for a validation quote.

See also: [deepagents-notes.md](deepagents-notes.md)
