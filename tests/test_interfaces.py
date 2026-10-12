import json
from pathlib import Path

import pytest

from ecoops.cli import main
from ecoops.report import leadership_markdown

ROOT = Path(__file__).resolve().parents[1]


def test_cli_generate_and_analyse(tmp_path):
    data_dir, out_dir = tmp_path / "data", tmp_path / "reports"
    assert main(["generate", "--out", str(data_dir)]) == 0
    assert main(["analyse", "--data", str(data_dir), "--out", str(out_dir)]) == 0
    for name in ("opportunities.csv", "opportunities.json", "pathways.json", "summary.json", "measures.csv",
                 "footprint.csv", "leadership_report.md"):
        assert (out_dir / name).exists(), name
    summary = json.loads((out_dir / "summary.json").read_text())
    assert summary["opportunity_counts"]["total"] > 0


def test_cli_config_override(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "rules.yaml").write_text("kubernetes_offhours:\n  offhours_util_max: 0.01\n")
    out = tmp_path / "reports"
    assert main(["analyse", "--config", str(tmp_path / "cfg"), "--out", str(out)]) == 0
    ids = {o["id"] for o in json.loads((out / "opportunities.json").read_text())}
    assert "schedule_off:nonprod-gke-dev" not in ids


def test_leadership_report_sections(result):
    md = leadership_markdown(result)
    for heading in ("Current state", "Identified opportunities", "Pathway comparison", "human review", "Assumptions"):
        assert heading.lower() in md.lower()


def test_api_endpoints():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ecoops.api import create_app

    client = TestClient(create_app())
    assert client.get("/health").json()["status"] == "ok"
    assert "current_state" in client.get("/summary").json()
    opps = client.get("/opportunities", params={"status": "blocked"}).json()
    assert opps and all(o["constraint_status"] == "blocked" for o in opps)
    detail = client.get(f"/opportunities/{opps[0]['id']}").json()
    assert detail["evidence"]
    assert client.get("/opportunities/nope:missing").status_code == 404
    assert len(client.get("/pathways").json()) == 3


def test_streamlit_app_renders():
    pytest.importorskip("streamlit")
    pytest.importorskip("plotly")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert len(at.tabs) == 7
