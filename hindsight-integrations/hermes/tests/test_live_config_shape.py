"""The fork keeps saving on the live config shape (Wslynllc/Homelab-Memory#68).

Fork main turned project mode on from any ``project:*`` observation scope, and project mode then
refuses every write that has no ``project_memory`` binding. The homes carry that scope and no binding,
so installing the fork would have stopped all saves with nothing the user sees. Two rules keep it safe:

* project mode is opt-in: it starts only when the config has a ``project_memory`` key, never from a
  scope alone;
* kanban and subagent runs are not auto-retained, as upstream does since #5555, so the fork does not
  turn that skip off for the homes that run it today.

``LIVE`` is the non-secret shape of the nine homes' ``hindsight/config.json`` (read 2026-11-22), with
a stand-in ``api_url`` and the real static ``retain_tags``. ``SCRUB`` is the tenth home, whose scopes are
still ``"shared"``. The session below is the same for every case and runs on the conftest ``FakeClient``:
no server, no network.

The save counts are what upstream ``vectorize-io/hindsight`` hermes plugin 1.2.4 (commit ``f14cc1eb5624``,
"release(hermes): v1.2.4", the version six homes run) sends for this session. They were measured by
running this file's shape cases against that tree, not worked out from the code.
"""

import hashlib
import json
import logging
import subprocess
from pathlib import Path

import pytest
from conftest import plugin

LIVE = {
    "mode": "local_external",
    "api_url": "http://server.test",
    "bank_id": "homelab",
    "memory_mode": "hybrid",
    "observation_scopes": [["project:*"]],
    "recall_budget": "mid",
    "recall_prefetch_method": "recall",
    "recall_types": "observation,world,experience",
    "retain_async": True,
    "retain_every_n_turns": 3,
    "retain_tags": ["project:Hermes"],
}
LIVE_NO_TAG = {key: value for key, value in LIVE.items() if key != "retain_tags"}
SCRUB = {**LIVE_NO_TAG, "observation_scopes": "shared"}
SHAPES = {"LIVE": LIVE, "LIVE_NO_TAG": LIVE_NO_TAG, "SCRUB": SCRUB}

# Saves sent by upstream 1.2.4 (f14cc1eb5624) for one session: 6 sync_turn calls at cadence 3, 1 built-in
# memory write and 1 hindsight_retain call. Kanban and subagent runs skip the 2 automatic saves.
UPSTREAM_124_SAVES = {"primary": 4, "kanban": 2, "subagent": 2}

BLOCKED = "Project memory write blocked"
ROUTES = ("sync_turn", "on_memory_write", "hindsight_retain")


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "synthetic fixture",
        ],
        check=True,
        capture_output=True,
    )
    return path


def _binding(root: Path, bank_id: str) -> dict:
    """A valid ``project_memory`` block with a reviewed exclusion config, all synthetic."""
    excluded = root / "excluded"
    excluded.mkdir()
    data = json.dumps({"paths": {str(excluded): {"disabled": True}}}).encode()
    config_path = root / "synthetic-coding-agent.json"
    config_path.write_bytes(data)
    return {
        "bank_id": bank_id,
        "capture_policy": "coding-agent",
        "exclusion_config": str(config_path),
        "exclusion_config_sha256": hashlib.sha256(data).hexdigest(),
        "excluded_path_ids": [hashlib.sha256(json.dumps(str(excluded)).encode()).hexdigest()[:16]],
    }


@pytest.fixture
def non_git_cwd(hermes_env):
    """A working directory outside any git checkout, like ``/opt/data`` and kanban scratch on the VM."""
    path = hermes_env / "not-a-checkout"
    path.mkdir()
    probe = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True
    )
    assert probe.returncode != 0, "the test directory sits inside a git checkout; point TMPDIR elsewhere"
    return path


def _tool_ok(raw: str) -> bool:
    """True for a tool result carrying ``result`` and no ``error`` (the stub's failures are not JSON)."""
    try:
        body = json.loads(raw)
    except ValueError:
        return False
    return isinstance(body, dict) and "result" in body and "error" not in body


def _session(instance) -> str:
    """Six turns, one built-in memory write and one ``hindsight_retain`` call; returns the tool result."""
    for turn in range(6):
        instance.sync_turn(f"user turn {turn}", f"assistant turn {turn}", session_id="session-1")
    instance.on_memory_write("add", "memory", "A synthetic built-in memory entry.")
    result = instance.handle_tool_call("hindsight_retain", {"content": "A synthetic explicit note."})
    instance.shutdown()
    return result


def _context_kwargs(context: str) -> dict:
    return {} if context == "primary" else {"agent_context": context}


def _items(fake) -> list[dict]:
    return [item for call in fake.retains for item in call["items"]]


def _project_tags(fake) -> set[str]:
    return {tag for item in _items(fake) for tag in item.get("tags", []) if tag.startswith("project:")}


@pytest.mark.parametrize("context", UPSTREAM_124_SAVES)
@pytest.mark.parametrize("shape", SHAPES)
def test_fork_keeps_saving_on_the_live_config_shape(provider, caplog, non_git_cwd, shape, context):
    config = SHAPES[shape]
    instance, fake = provider(config, cwd=str(non_git_cwd), **_context_kwargs(context))
    result = _session(instance)

    assert len(fake.retains) == UPSTREAM_124_SAVES[context], f"saves sent for {shape} in a {context} run"
    assert _tool_ok(result), result
    assert BLOCKED not in caplog.text
    assert all(item["observation_scopes"] == config["observation_scopes"] for item in _items(fake))
    # Without project mode the fork stamps nothing of its own: only the static tag, when the home has one.
    assert _project_tags(fake) == set(config.get("retain_tags", []))
    if shape == "LIVE":
        assert all("project:Hermes" in item["tags"] for item in _items(fake))
        assert all(item["observation_scopes"] == [["project:*"]] for item in _items(fake))


def test_a_wildcard_scope_without_project_memory_saves(provider, caplog, hermes_env):
    """Opt-in: ``observation_scopes [["project:*"]]`` alone is no binding request, even inside a checkout."""
    repo = _git_repo(hermes_env / "fleet")
    instance, fake = provider(LIVE_NO_TAG, cwd=str(repo))
    assert not instance._project_memory_mode()
    result = _session(instance)

    assert len(fake.retains) == UPSTREAM_124_SAVES["primary"]
    assert _tool_ok(result), result
    assert BLOCKED not in caplog.text
    assert _project_tags(fake) == set()  # no computed project:<repo> tag without the opt-in


def test_a_project_memory_binding_still_turns_project_mode_on(provider, caplog, hermes_env):
    """The opt-in works: a valid block with no conflicting static tag saves, tagged with the repository."""
    repo = _git_repo(hermes_env / "fleet")
    config = {**LIVE_NO_TAG, "project_memory": _binding(hermes_env, "homelab")}
    instance, fake = provider(config, cwd=str(repo))
    assert instance._project_memory_mode()
    result = _session(instance)

    assert len(fake.retains) == UPSTREAM_124_SAVES["primary"]
    assert _tool_ok(result), result
    assert BLOCKED not in caplog.text
    assert _project_tags(fake) == {"project:fleet"}


def _attempt_route(instance, route: str) -> bool:
    """Drive one write route; returns True when the plugin raised its refusal (it may also only log)."""
    raised = False
    try:
        if route == "sync_turn":
            for turn in range(6):
                instance.sync_turn(f"user turn {turn}", f"assistant turn {turn}", session_id="session-1")
        elif route == "on_memory_write":
            instance.on_memory_write("add", "memory", "A synthetic built-in memory entry.")
        else:
            instance.handle_tool_call("hindsight_retain", {"content": "A synthetic explicit note."})
    except plugin.ProjectMemoryDenied:
        raised = True
    finally:
        instance.shutdown()
    return raised


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("case", ["invalid-binding", "conflicting-static-tag"])
def test_an_opted_in_but_unusable_binding_stays_blocked(provider, caplog, hermes_env, case, route):
    repo = _git_repo(hermes_env / "fleet")
    if case == "invalid-binding":
        config = {**LIVE_NO_TAG, "project_memory": {}}
    else:
        # The static tag the homes carry names another project than the checkout does (project:fleet).
        config = {**LIVE, "project_memory": _binding(hermes_env, "homelab")}
    instance, fake = provider(config, cwd=str(repo))
    assert instance._project_memory_mode()
    raised = _attempt_route(instance, route)

    assert fake.retains == []
    assert raised or BLOCKED in caplog.text, "the refusal came from the project guard, not from something else"
