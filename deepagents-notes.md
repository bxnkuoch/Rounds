# LangChain Deep Agents: Notes for Rounds

> Source: github.com/langchain-ai/deepagents and docs.langchain.com/oss/python/deepagents (read 2026-11-14).
> **Use the `docs-langchain` and `reference-langchain` MCP servers (see AGENTS.md §6) for current APIs. These notes are a snapshot.**
> At the hackathon, check the installed version with `pip show deepagents` before relying on any API below.

## What it is

Deep Agents is LangChain's "batteries-included agent harness." It's an MIT-licensed Python package (`deepagents`, with a JS port in `deepagentsjs`) built on LangGraph.

A plain LangChain agent (`create_agent`) is a model calling tools in a loop. A **deep agent** adds what long, multi-step tasks need:

| Feature | What it is | Rounds use |
|---|---|---|
| **Planning** | `write_todos` tool (pending → in_progress → completed). **Opt-in since v0.7** through `TodoListMiddleware()` | Break "optimize my shift" or "add Room 204 and replan" into visible steps |
| **Virtual filesystem** | `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `delete` | Store the floor graph, shift plans, and handoff reports as files instead of in the prompt |
| **Subagents** | `task` tool hands work to specialist agents with separate context, prompt, tools and model | `spatial-agent`, `scheduler-agent`, `explainer-agent` |
| **Backends** | `StateBackend` (default, one thread) · `FilesystemBackend` (disk) · `StoreBackend` (persists across threads) · `CompositeBackend` (chooses a backend by path prefix) | `/memories/` → StoreBackend for unit knowledge that carries across shifts |
| **Human-in-the-loop** | `interrupt_on={"tool": True}` pauses before the tool runs; the human can approve, edit, or reject. **Requires a checkpointer** | Nurse approves schedule changes before they apply. This puts "nurse stays in control" in the code |
| **Context management** | Automatic summarization; large tool outputs are offloaded to files | Long shifts and long chat histories |
| **Memory and skills** | `memory=["AGENTS.md"]` is always loaded; `skills=[dirs]` with SKILL.md load only when needed | Unit rules, room naming, med-timing policy |
| **MCP** | `MCPAdapter` from `langchain.mcp` → tools | Wrap the Matterport/CoStar APIs as an MCP server (optional) |

The return value is a LangGraph `CompiledStateGraph`, so streaming, checkpointing and LangSmith tracing come built in. LangSmith traces are useful for showing judges what the agent did.

## Core API

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=...,            # "provider:model" string or a chat model instance (e.g. Bedrock)
    tools=[...],          # plain functions work; schema comes from type hints and the docstring
    system_prompt="...",
    subagents=[...],      # list of dicts (see below)
    middleware=[...],     # e.g. TodoListMiddleware()
    backend=...,          # defaults to StateBackend()
    memory=["./AGENTS.md"],
    interrupt_on={...},   # per-tool human-in-the-loop
    checkpointer=...,     # required for interrupt_on
    store=...,            # required for StoreBackend
    response_format=...,  # structured output (optional)
)
agent.invoke({"messages": [{"role": "user", "content": "What should I do next?"}]},
             config={"configurable": {"thread_id": "nurse-1-shift-0700"}})
```

### Subagent dict keys
- `name` (required). The main agent calls it through `task()`.
- `description` (required). The main agent reads it to decide when to hand off.
- `system_prompt` (required in the default `"isolated"` mode). It is **not** inherited from the parent.
- `tools`, `model`, `middleware`, `interrupt_on`, `skills`, `response_format`, `permissions` (all optional).
- A `general-purpose` subagent is added automatically unless you define one with that name.

### Human-in-the-loop flow
```python
from langgraph.types import Command
result = agent.invoke({...}, config=config)
if "__interrupt__" in result:
    reqs = result["__interrupt__"][0].value["action_requests"]   # show these in the UI
    agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config=config)
    # or {"type": "reject", "message": "..."}  /  {"type": "edit", "edited_action": {...}}
```

## Rounds architecture sketch

**Rule: the LLM coordinates; deterministic code does the math.** A* or Dijkstra and OR-Tools stay as plain Python tools. The model never estimates distances, orderings, or clinical urgency.

```
Nurse (chat / voice)
   ▼
Rounds Coordinator (main deep agent)
   ├─ write_todos            → visible plan
   ├─ /plans/*.json          → current + previous schedule (lets the UI show old vs new route)
   ├─ /memories/  (Store)    → unit knowledge carried across shifts
   ├─ task → spatial-agent   : room lookup, shortest_path, floor graph (from Matterport)
   ├─ task → scheduler-agent : optimize_schedule (OR-Tools VRP with time windows)
   ├─ task → explainer-agent : "why is 205 next?" answered from real optimizer output
   └─ apply_schedule  ← interrupt_on (nurse approves)
```

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain.agents.middleware import TodoListMiddleware
from langchain_aws import ChatBedrockConverse          # Amazon track
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

model = ChatBedrockConverse(model="<bedrock model id>")  # same model serves the Amazon + LangChain tracks

subagents = [
    {"name": "spatial-agent",
     "description": "Room lookups, distances, and shortest paths on the hospital floor graph.",
     "system_prompt": "Answer spatial questions using only graph tools. Never estimate distances.",
     "tools": [get_hospital_layout, get_patient_location, calculate_route]},
    {"name": "scheduler-agent",
     "description": "Sequences pending tasks under deadlines, priorities, and travel time.",
     "system_prompt": "Always call optimize_schedule. Report infeasible deadlines explicitly; never drop tasks.",
     "tools": [get_nurse_tasks, get_task_deadlines, get_nurse_location, optimize_schedule]},
]

agent = create_deep_agent(
    model=model,
    tools=[add_patient_request, update_task, complete_task, apply_schedule, get_shift_metrics],
    system_prompt="You coordinate a nurse's shift. Plan with todos, delegate, and never invent data.",
    subagents=subagents,
    middleware=[TodoListMiddleware()],
    backend=CompositeBackend(default=StateBackend(),
                             routes={"/memories/": StoreBackend(namespace=lambda rt: ("unit-4W",))}),
    memory=["./AGENTS.md"],
    interrupt_on={"apply_schedule": True, "update_task": True},
    checkpointer=MemorySaver(),
    store=InMemoryStore(),
)
```

## Features that win "Best Use of DeepAgents"

A single agent with 14 flat tools is just a ReAct agent with extra steps. To stand out, show these:
1. **Visible todo list** in the assistant panel as the agent works.
2. **Subagent handoffs** shown in the UI ("→ scheduler-agent").
3. **HITL approval card** before a replan applies. This turns clinical safety into a feature.
4. **Filesystem artifacts**, e.g. the agent writes `/plans/shift_v2.json` and a **shift handoff report** (`/reports/handoff.md`). This is a real nursing pain point and a natural long-running task.
5. **Memory across shifts**, e.g. "Supply room on 4W moved to 4-117" is remembered next session.

## Gotchas
- `write_todos` is no longer on by default (v0.7+). Add `TodoListMiddleware()`.
- `interrupt_on` does nothing without a `checkpointer`. Resume with the **same `thread_id`**.
- Isolated subagents don't inherit the parent's system prompt or custom middleware.
- Don't use `LocalShellBackend` or `FilesystemBackend(virtual_mode=False)`; they're unsafe outside development.
- Each subagent handoff costs extra LLM round-trips. For the "Optimize My Shift" button, call the optimizer API directly and save the agent for chat.
- Send room and task IDs to the LLM, never patient-identifying info (even synthetic data, as a habit).

## To verify at the hackathon
- [ ] `deepagents` version installed, and whether `TodoListMiddleware` import path matches
- [ ] Which Bedrock models the Amazon sponsor gives us access to (tool-calling support)
- [ ] Whether the Matterport API exposes doors and room adjacency (needed to auto-build the nav graph)
- [ ] LangSmith key for tracing (good for showing the agent's steps in the demo)
