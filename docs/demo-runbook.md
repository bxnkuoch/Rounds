# Demo runbook

How to run the 2-minute demo in `pitch.md`. Rehearsed on 2026-11-15 in headless Chrome against the real app with a real `ANTHROPIC_API_KEY`: every scene passed, with 0 page errors.

## Before you present

```bash
cd backend && uv run uvicorn app.main:app --port 8000     # needs data/raw/matterport/6Ee2LwLfx58.json
cd frontend && npm install && npm run dev                  # open http://localhost:5173 (not 127.0.0.1)
```

- `ANTHROPIC_API_KEY` must be in the backend's environment (or `local.env`) for the agent scenes.
- All state is in memory. **Restart the backend before each run** so the plan ids start at P-1 and the clock at 07:00.
- The 3D tour tab only works on `localhost` (the Matterport key's domain allowlist).

## Scenes, with measured agent time

| Scene | What to click | Agent wait (rehearsal) |
|---|---|---|
| Hook | Point at the SYNTHETIC badge and the Airedale credit under the map | none |
| Optimize | **Optimize shift** → the card shows 760 m vs a 1,040 m due-order baseline, 0 late → **Approve** | none (instant) |
| Interruption | **Dispatch**: kind *breathing treatment*, Where *Room 15*, Due by *+20 min*, Priority *1 · STAT* → **Add request**. The agent replans → card shows **+21 m, 0 late, SYN-RT-1 and SYN-RT-2 changed** → **Approve** | 12–13 s |
| Transporter | **Plan** tab → click **SYN-TR-1**. **Dispatch**: kind *transport*, From *Room 12*, To *Main Entrance*, Due by *+30 min* → **Add request** → card (+90 m, 0 late) → **Approve** | 13–17 s |
| Explain | **Agent** tab: "Why is Room 8 before Room 6 for SYN-RT-1?" (pick two stops from the Plan tab). The explainer answers with `compare_swap` numbers | 11–15 s |
| Close / LangChain extra | **Write shift handoff** → **Start next shift** → "What did the previous shift hand off?" | about 10 s |

Total agent waiting is about 50 s, so narrate during the waits: the todo list, tool calls and subagent handoffs stream into the Agent tab while it works.

## Presenter notes

- **The Room 7 trap:** Room 7 (and Rooms 1 and 8) lie on an existing walking path, so a STAT job there costs **0 m** extra. That's correct, but it looks like a bug, and the agent may add a caveat about it. Use Room 15.
- **No API key, or the model is down:** the agent tab shows `model_unavailable`, and everything else keeps working. In **Dispatch**, untick *Send new requests to the agent* to re-optimize directly; Optimize → Approve still works.
- Late jobs: with seed 0, nothing is late. To show a late flag, dispatch a job with **Due by** set before the sim time. It is still scheduled and flagged late, never dropped.
- Before the demo, do a visual check of the 15 out-of-room place labels in the 3D tour (`docs/handoff-2026-11-15.md`, caveat 2).

## Still open

- Whether we may use the public Airedale tour for the demo (`docs/task-split.md`, "Both: decide later"). Ask the CoStar/Matterport sponsor team.
