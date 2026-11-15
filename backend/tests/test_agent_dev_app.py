import app.agent_dev_app as dev
from fastapi.testclient import TestClient


def test_bad_nav_graph_export_does_not_crash_startup(tmp_path, monkeypatch, caplog):
    bad = tmp_path / "g.json"
    bad.write_text("{}")
    monkeypatch.setattr(dev, "AIREDALE", bad)

    def raising(path):
        raise ValueError("schema mismatch")

    monkeypatch.setattr(dev, "load_nav_graph", raising)
    with TestClient(dev.app) as client:
        assert client.post("/agent/threads").status_code == 200
    assert "could not be loaded" in caplog.text
