import pytest

from ultron_agent.tools import apps, registry, workflows
from ultron_agent.tools.base import Cancelled, ToolContext, ToolError


def test_open_allowed_app(ctx) -> None:
    out = apps.open_app(ctx, {"app": "sleeper"})
    assert out["verified"] and out["app"] == "Sleeper"


def test_app_name_matching_and_refusals(ctx, config) -> None:
    assert config.app("SLEEP").name == "Sleeper"  # unique partial match
    with pytest.raises(ToolError, match="isn't in your allowed apps"):
        apps.open_app(ctx, {"app": "cmd.exe /c del"})
    with pytest.raises(ToolError, match="Couldn't find"):
        apps.open_app(ctx, {"app": "missing"})
    out = apps.open_app(ctx, {"app": "crasher"})
    assert out["verified"] is False and "code 3" in out["summary"]
    assert apps.list_apps(ctx, {})["apps"] == ["Crasher", "Missing", "Sleeper"]


def test_workflows(ctx, config) -> None:
    out = workflows.run(ctx, {"name": "build"})
    assert out["verified"] and "step one" in out["text"] and "two" in out["text"]
    broken = workflows.run(ctx, {"name": "broken"})
    assert broken["verified"] is False and "exit code 2" in broken["summary"]
    with pytest.raises(ToolError, match="took longer"):
        workflows.run(ctx, {"name": "slow"})
    with pytest.raises(ToolError, match="No workflow named"):
        workflows.run(ctx, {"name": "rm -rf"})


def test_workflow_cancel(config) -> None:
    calls = []

    def progress(message: str) -> bool:
        calls.append(message)
        return len(calls) > 1

    with pytest.raises(Cancelled):
        workflows.run(ToolContext(config=config, progress=progress), {"name": "slow"})


def test_enabled_tools_follow_config(config) -> None:
    assert "pc.files.organize" in registry.enabled(config)
    config.disabled_tools = {"pc.files.delete"}
    config.workflows = {}
    names = registry.enabled(config)
    assert "pc.files.delete" not in names and "pc.workflows.run" not in names
