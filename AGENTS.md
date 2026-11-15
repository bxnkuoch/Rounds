# Rounds: Agent Instructions

Shared instructions for every coding agent on this repo (Claude Code, Codex, Cursor, etc.).
Two humans work on it at the same time, each with their own agent. Following these rules keeps the two of you from overwriting each other's work.

## 1. Sync before any work (mandatory)

Before starting **any** task, including reading code to plan:

```bash
git fetch --all --prune
git status                 # check for uncommitted local changes first
git pull --rebase          # bring in your teammate's latest commits
```

- Claude Code runs this automatically through the SessionStart hook (`.claude/hooks/sync-latest.sh`). Read its `[sync]` message. If it says WARNING, resolve that before doing anything else.
- Other agents: run the commands above yourself at the start of every session.
- If you've been working a long time (>30 min), **pull again before you commit and push.**
- Never `git push --force` to `main`. Never `git reset --hard` or discard changes you didn't make.

## 2. Git workflow for a 2-person team

- `main` must always run. Do work on short-lived branches: `<name>/<feature>` (e.g. `minh/optimizer`, `alex/frontend-routes`).
- Commit small and often. Push at least every hour so your teammate sees your progress.
- Merge to `main` through a PR (fast review) or by rebasing onto `main` and fast-forwarding. Rebase onto the latest `main` before merging.
- Commit messages: `area: what changed` (e.g. `optimizer: add pickup-before-dropoff constraint`).
- If you hit a merge conflict in code your teammate owns (see §3), **stop and ask your human.** Don't guess.

## 3. Ownership (to avoid conflicts)

Each area has one owner at a time. Don't make large edits to the other person's area without asking.

| Area | Path | Owner |
|---|---|---|
| Frontend (framework TBD) | `frontend/` | _TBD_ |
| Backend API (FastAPI) | `backend/app/api/` | _TBD_ |
| Optimizer + routing | `backend/app/optimization/` | _TBD_ |
| Deep Agent + tools | `backend/app/agents/`, `backend/app/tools/` | _TBD_ |
| Spatial / Matterport / CoStar | `backend/app/spatial/` | _TBD_ |
| Shared contracts | `backend/app/models/`, frontend types folder (path depends on the framework) | **both; announce changes** |

**Shared contracts:** Pydantic models and TypeScript types must stay identical. If you change one, update the other in the same commit and mention it in the commit message.

## 4. Project context

- What we're building and why: [`pitch.md`](pitch.md)
- Deep Agents (LangChain) reference and architecture: [`deepagents-notes.md`](deepagents-notes.md)
- Status: **early build.**
- Stack:
  - **Backend (decided):** Python + FastAPI. All the AI and optimization runs here: LangChain `deepagents` on an Amazon Bedrock model, OR-Tools, A* pathfinding, and the Matterport/CoStar API clients (keys stay server-side).
  - **Frontend (UNDECIDED):** the options are React + Vite (a single-page app) or Next.js. Both would use TypeScript + Tailwind + shadcn/ui, call FastAPI, and show a 2D floor plan plus the Matterport Showcase SDK 3D view. **Agents: don't scaffold the frontend or pick a framework until both teammates confirm here.**

**Product in one line:** Rounds plans and replans shifts for hospital staff who cover the whole building (transporters, respiratory therapists, IV team nurses). It uses a deterministic optimizer on a navigation graph built from a Matterport digital twin, with a Deep Agent coordinating and a human approving every change.

## 5. Non-negotiable product rules

1. **The LLM coordinates; deterministic code does the math.** Routes, orderings, distances, and arrival times come only from the optimizer and pathfinding code, never from the model.
2. **Never fabricate data.** No invented patients, tasks, distances, API results, or performance metrics. Compute before/after comparisons on the same graph, from the same start, with the same job set. Don't hardcode improvements.
3. **Clinical safety.** The app never decides clinical urgency or changes medication timing. Priority comes from input data. Every schedule change goes through human approval (`interrupt_on`).
4. **Never silently drop jobs.** Infeasible deadlines are flagged explicitly.
5. **Synthetic data only.** No real patient information. Don't send patient-identifying fields to the LLM; use IDs.
6. **Be honest about integrations.** Label which data is real (Matterport/CoStar) and which is synthetic. Don't claim a building is a hospital if it isn't.
7. **Secrets:** API keys go only in `.env` (gitignored). Never put keys in frontend code. Never commit CoStar/Matterport raw datasets (sponsor restrictions; the repo is public).

## 6. LangChain / Deep Agents work: use the docs MCP servers

Any work involving LangChain, LangGraph, or `deepagents` (the agent, tools, middleware, subagents, backends, human-in-the-loop, Bedrock model setup) must **check the official docs through MCP before writing or changing code.** Don't rely on memory, because these APIs change often.

| MCP server | URL | Use it for |
|---|---|---|
| `docs-langchain` | https://docs.langchain.com/mcp | Guides and concepts: Deep Agents overview, customization, subagents, backends, HITL, MCP adapters |
| `reference-langchain` | https://reference.langchain.com/mcp | API reference: exact signatures, parameters, import paths, class names |

- Both are listed in the repo's `.mcp.json`. Claude Code asks once to approve them; other agents should add these URLs to their own MCP config.
- Workflow: find the concept in `docs-langchain`, confirm the exact signature or import in `reference-langchain`, then check it against the installed version (`pip show deepagents`).
- `deepagents-notes.md` is a summary from 2026-11-14 and may be out of date. If it disagrees with the MCP docs, the docs win; update the notes.

## 7. Engineering conventions

- **Check, don't guess, library APIs.** Read the installed version (`pip show deepagents`, `npm ls`) and its docs before using an API. `deepagents` changes quickly (e.g. `write_todos` requires `TodoListMiddleware` since v0.7). For LangChain, see §6.
- Keep services separate: agent, task service, optimizer, routing, spatial, data access. Don't build one giant file.
- External APIs (Matterport, CoStar, Bedrock) must fail gracefully. The core app keeps working without them.
- Test the optimizer with small deterministic fixtures (known graph → known best order). It's the core of the demo.
- When you finish a task, say what you verified (ran tests, clicked through the UI) and what you didn't.
