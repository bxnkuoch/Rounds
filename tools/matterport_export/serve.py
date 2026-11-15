"""Local exporter for Matterport models via the Showcase SDK.

Why this exists: the Model (GraphQL) API only reaches models in our own
account. Public third-party models (e.g. the Airedale Hospital AAU scan) are
only readable through the Showcase SDK, which runs in a browser and, with our
SDK key, only on localhost. This server:

  1. serves export.html on http://localhost:<port> with the SDK key from
     local.env injected at request time (the key is never written to disk);
  2. receives the exported graph JSON from the page and writes it to
     data/raw/matterport/<model_id>.json (gitignored: third-party data).

Usage (from the repo root):
    python3 tools/matterport_export/serve.py
    open "http://localhost:8765/?m=6Ee2LwLfx58"

Stdlib only, so it runs without a venv.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = Path(__file__).with_name("export.html")
ENV_PATH = REPO_ROOT / "local.env"
OUT_DIR = REPO_ROOT / "data" / "raw" / "matterport"
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9]{11}$")
MAX_BODY = 50 * 1024 * 1024
KEY_PLACEHOLDER = "__MATTERPORT_SDK_KEY__"


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def summarize(doc: dict) -> dict:
    """Sanity checks on the exported graph, printed after each save."""
    sweeps = doc["sweeps"]
    ids = {s["id"] for s in sweeps}
    edges: set[tuple[str, str]] = set()
    asymmetric = 0
    dangling = 0
    nbrs = {s["id"]: set(s["neighbors"]) for s in sweeps}
    for sid, ns in nbrs.items():
        for n in ns:
            if n not in ids:
                dangling += 1
                continue
            edges.add(tuple(sorted((sid, n))))
            if sid not in nbrs.get(n, set()):
                asymmetric += 1

    # connected components over enabled sweeps
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    seen: set[str] = set()
    comps: list[int] = []
    for sid in ids:
        if sid in seen:
            continue
        stack, size = [sid], 0
        seen.add(sid)
        while stack:
            cur = stack.pop()
            size += 1
            for n in adj[cur]:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        comps.append(size)

    return {
        "sweeps": len(sweeps),
        "enabled_sweeps": sum(1 for s in sweeps if s["enabled"]),
        "undirected_edges": len(edges),
        "asymmetric_links": asymmetric,
        "dangling_links": dangling,
        "components": sorted(comps, reverse=True),
        "floors": len(doc["floors"]),
        "rooms": len(doc["rooms"]),
        "labeled_rooms": sum(1 for r in doc["rooms"] if r.get("label")),
        "labels": len(doc.get("labels", [])),
        "tags": len(doc.get("tags", [])),
    }


class Handler(BaseHTTPRequestHandler):
    sdk_key = ""

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?")[0] not in ("/", "/index.html"):
            self._send(404, b"not found", "text/plain")
            return
        html = HTML_PATH.read_text().replace(KEY_PLACEHOLDER, self.sdk_key)
        self._send(200, html.encode(), "text/html; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/save":
            self._send(404, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > MAX_BODY:
            self._send(413, b"bad size", "text/plain")
            return
        try:
            doc = json.loads(self.rfile.read(length))
            model_id = doc["source"]["model_id"]
            if not MODEL_ID_RE.match(model_id):
                raise ValueError(f"bad model id {model_id!r}")
            doc["stats"] = summarize(doc)
        except (ValueError, KeyError, TypeError) as e:
            self._send(400, f"invalid export: {e}".encode(), "text/plain")
            return
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{model_id}.json"
        out.write_text(json.dumps(doc, indent=1))
        print(f"[export] wrote {out.relative_to(REPO_ROOT)}")
        print(f"[export] stats {json.dumps(doc['stats'])}")
        self._send(200, json.dumps({"path": str(out.relative_to(REPO_ROOT)), "stats": doc["stats"]}).encode(),
                   "application/json")

    def log_message(self, fmt: str, *args) -> None:
        pass  # keep output to export results only


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    key = read_env(ENV_PATH).get("MATTERPORT_SDK_KEY", "")
    if not key:
        raise SystemExit(f"MATTERPORT_SDK_KEY missing in {ENV_PATH}")
    Handler.sdk_key = key

    # SDK key is allowlisted for localhost only, so bind loopback and open via "localhost".
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[export] open http://localhost:{args.port}/?m=<MODEL_ID>  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
