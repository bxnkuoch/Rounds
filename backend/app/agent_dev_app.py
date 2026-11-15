"""Dev-only app that mounts just the agent router. Delete once Benjamin's main.py mounts it.

Run: uv run uvicorn app.agent_dev_app:app --reload
The Airedale nav graph (gitignored export) is loaded at startup if present; otherwise the stub services run
without a graph (place/route tools return errors). The model is built lazily on the first agent run.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.agents.model import build_chat_model
from app.agents.runtime import AgentRuntime
from app.api.agent import router
from app.services.stub import StubServices
from app.spatial.nav_graph import load_nav_graph

AIREDALE = Path(__file__).resolve().parents[2] / "data" / "raw" / "matterport" / "6Ee2LwLfx58.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    graph = load_nav_graph(AIREDALE) if AIREDALE.exists() else None
    app.state.agent_runtime = AgentRuntime(StubServices(graph), build_chat_model)
    yield


app = FastAPI(title="Rounds agent (dev)", lifespan=lifespan)
app.include_router(router)
