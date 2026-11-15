"""Rounds FastAPI app: domain API (/api, Benjamin) + agent API (/agent, Minh).

Run from backend/:  uv run uvicorn app.main:app --reload --port 8000

Startup loads the building nav graph (gitignored Matterport export) and a
seeded SYNTHETIC scenario into RoundsServices, which both the /api routes and
the agent's tools call. If the export is missing or broken, the app still
starts: /api domain routes return 503 and the agent runs on StubServices
(AGENTS.md §7). A missing ANTHROPIC_API_KEY only affects /agent runs.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.model import build_chat_model
from app.agents.runtime import AgentRuntime
from app.api.agent import router as agent_router
from app.api.rounds import router as rounds_router
from app.services.rounds import RoundsServices
from app.services.stub import StubServices
from app.spatial.nav_graph import load_nav_graph
from app.synthetic import generate_scenario

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_ID = "6Ee2LwLfx58"
# Vite dev server. localhost (not 127.0.0.1): the Matterport SDK key only allows localhost.
DEFAULT_ORIGINS = "http://localhost:5173"


def graph_path() -> Path:
    model_id = os.environ.get("MATTERPORT_MODEL_ID") or DEFAULT_MODEL_ID
    return REPO_ROOT / "data" / "raw" / "matterport" / f"{model_id}.json"


def build_services(path: Path, seed: int) -> RoundsServices | None:
    if not path.exists():
        log.warning("nav graph export %s not found; domain API disabled (run tools/matterport_export)", path)
        return None
    try:
        graph = load_nav_graph(path)
        return RoundsServices(graph, generate_scenario(graph, seed=seed))
    except (ValueError, KeyError) as exc:
        log.warning("nav graph %s could not be loaded (%s); domain API disabled", path.name, exc)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = build_services(graph_path(), int(os.environ.get("ROUNDS_SEED", "0")))
    app.state.services = services
    app.state.agent_runtime = AgentRuntime(services or StubServices(None), build_chat_model)
    yield


app = FastAPI(title="Rounds", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ROUNDS_CORS_ORIGINS", DEFAULT_ORIGINS).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(rounds_router)
app.include_router(agent_router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "domain_api": app.state.services is not None}
