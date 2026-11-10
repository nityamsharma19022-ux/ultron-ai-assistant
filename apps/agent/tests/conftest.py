from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ultron_agent.config import AgentConfig, AppEntry, Workflow
from ultron_agent.tools.base import ToolContext

PY = sys.executable


@pytest.fixture
def config(tmp_path: Path) -> AgentConfig:
    downloads = tmp_path / "Downloads"
    documents = tmp_path / "Documents"
    project = tmp_path / "Project"
    for d in (downloads, documents, project):
        d.mkdir()
    return AgentConfig(
        server_url="http://core.test",
        device_name="Test PC",
        data_dir=tmp_path / "agent-data",
        roots={"downloads": downloads, "documents": documents, "project": project},
        apps={
            "sleeper": AppEntry("Sleeper", [PY, "-c", "import time; time.sleep(5)"]),
            "crasher": AppEntry("Crasher", [PY, "-c", "raise SystemExit(3)"]),
            "missing": AppEntry("Missing", ["/no/such/program"]),
        },
        workflows={
            "build": Workflow(
                "Build",
                [[PY, "-c", "print('step one')"], [PY, "-c", "print('two')"]],
                cwd="project",
            ),
            "broken": Workflow("Broken", [[PY, "-c", "import sys; print('bad'); sys.exit(2)"]]),
            "slow": Workflow(
                "Slow", [[PY, "-c", "import time; time.sleep(30)"]], timeout_seconds=1
            ),
        },
    )


@pytest.fixture
def ctx(config: AgentConfig) -> ToolContext:
    return ToolContext(config=config, progress=lambda _m: False)
