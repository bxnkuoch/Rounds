"""Chat model config. The API key is read from env or local.env and never logged."""
import os
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = "anthropic:claude-haiku-5-5"


class AgentUnavailable(Exception):
    """The agent cannot run (e.g. no API key). The rest of the app keeps working."""


def read_env(path: Path) -> dict[str, str]:
    """Copied from tools/matterport_export/serve.py (tools/ is not a package)."""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def build_chat_model(model_id: str | None = None, env_path: Path = REPO_ROOT / "local.env") -> BaseChatModel:
    file_env = read_env(env_path)

    def get(name: str) -> str | None:
        return os.environ.get(name) or file_env.get(name) or None

    resolved = model_id or get("AGENT_MODEL") or DEFAULT_MODEL
    kwargs: dict = {}
    if resolved.startswith("anthropic:"):
        key = get("ANTHROPIC_API_KEY")
        if not key:
            raise AgentUnavailable("ANTHROPIC_API_KEY not set")
        kwargs["api_key"] = key
    return init_chat_model(resolved, **kwargs)
