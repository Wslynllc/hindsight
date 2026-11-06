"""Project-mode transport contracts using the maintained native provider fixture.

The guard/resolver are real. Only Hermes core and the SDK are replaced by the
existing conftest harness. Git fixtures and all payload text are synthetic.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import threading

import pytest


BANK = "shared-synthetic-projects"


def _git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _repository(path):
    _git("init", "-q", str(path))
    _git("-C", str(path), "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-q",
         "--allow-empty", "-m", "synthetic fixture")


def _bind_exclusions(policy, prefixes, **overrides):
    data = json.dumps({"paths": {str(path): {"disabled": True} for path in prefixes}, **overrides}).encode()
    Path(policy["exclusion_config"]).write_bytes(data)
    policy["exclusion_config_sha256"] = hashlib.sha256(data).hexdigest()
    policy["excluded_path_ids"] = [
        hashlib.sha256(json.dumps(str(path)).encode()).hexdigest()[:16] for path in prefixes
    ]


@dataclass
class ProjectLayout:
    repo: Path
    other: Path
    worktree: Path
    subdir: Path
    excluded: list[Path]
    config: dict


@pytest.fixture
def project_layout(hermes_env) -> ProjectLayout:
    repo, other, worktree = (hermes_env / name for name in ("owned-main", "other-main", "linked-view"))
    _repository(repo)
    _repository(other)
    _git("-C", str(repo), "worktree", "add", "-q", "-b", "synthetic-linked", str(worktree))
    subdir = repo / "src"
    subdir.mkdir()
    excluded = [hermes_env / "excluded-a", hermes_env / "excluded-b"]
    for path in excluded:
        path.mkdir()
    policy = {
        "bank_id": BANK,
        "approved_roots": [str(path) for path in (repo, other, worktree)],
        "exclusion_config": str(hermes_env / "synthetic-coding-agent.json"),
        "exclusion_config_sha256": "",
        "excluded_path_ids": [],
    }
    _bind_exclusions(policy, excluded)
    config = {
        "bank_id": BANK,
        "observation_scopes": [["project:*"]],
        "retain_tags": ["manual:kept", "literal:{unchanged}"],
        "project_memory": policy,
    }
    return ProjectLayout(repo, other, worktree, subdir, excluded, config)


def _note(instance, tags=None):
    return instance.handle_tool_call("hindsight_retain", {"content": "Synthetic note.", "tags": tags or []})


def _item(fake, index=0):
    return fake.retains[index]["items"][0]


@pytest.mark.parametrize("binding", ["approved_roots", "coding-agent"])
def test_checkout_subdirectory_and_real_worktree_share_project(provider, project_layout, binding):
    repo, worktree, subdir, config = (
        project_layout.repo,
        project_layout.worktree,
        project_layout.subdir,
        project_layout.config,
    )
    if binding == "coding-agent":
        config["project_memory"].pop("approved_roots")
        config["project_memory"]["capture_policy"] = "coding-agent"
    identities = []
    for origin in (repo, subdir, worktree):
        instance, fake = provider(config, cwd=str(origin))
        try:
            instance.sync_turn("Synthetic user.", "Synthetic answer.")
        finally:
            instance.shutdown()
        assert len(fake.retains) == 1
        item = _item(fake)
        assert fake.retains[0]["bank_id"] == BANK
        assert item["observation_scopes"] == [["project:*"]]
        assert set(item["tags"]) == {
            "project:owned-main", "manual:kept", "literal:{unchanged}", "session:session-1"
        }
        assert item["metadata"]["repo"] == item["metadata"]["project"] == "owned-main"
        identity = item["metadata"]["worktree_id"]
        assert re.fullmatch("[0-9a-f]{64}", identity)
        identities.append(identity)
        assert str(repo.parent) not in json.dumps(fake.retains)
        assert "caller_context" not in json.dumps(fake.retains)
    assert identities[0] == identities[1]
    assert identities[0] != identities[2]


@pytest.mark.parametrize("route", ["automatic", "manual", "builtin"])
@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("binding", ["approved_roots", "coding-agent"])
def test_project_routes_enforce_valid_binding_before_transport(provider, project_layout, route, linked, binding):
    repo, worktree, excluded, config = (
        project_layout.repo,
        project_layout.worktree,
        project_layout.excluded,
        project_layout.config,
    )
    if binding == "coding-agent":
        config["project_memory"].pop("approved_roots")
        config["project_memory"]["capture_policy"] = "coding-agent"
    instance, fake = provider(config, cwd=str(worktree if linked else repo))
    try:
        _note(instance)
        assert len(fake.retains) == 1  # otherwise-valid predecessor reaches SDK
        # A correctly re-pinned policy now excludes this origin. Exercise each
        # public producer; none may bypass the same real provenance guard.
        _bind_exclusions(instance._config["project_memory"], [*excluded, repo])
        if route == "automatic":
            instance.sync_turn("Excluded synthetic user.", "Excluded answer.")
        elif route == "manual":
            _note(instance)
        else:
            instance.on_memory_write("add", "memory", "Excluded synthetic builtin.")
    finally:
        instance.shutdown()
    assert len(fake.retains) == 1


@pytest.mark.parametrize("restriction", [
    {"disabled": True}, {"retainSessions": False}, {"optInOnly": True},
    {"mapPathToBank": {"/synthetic": "private-synthetic"}},
    {"harnesses": {"codex": {"retainSessions": False}}},
    {"harnesses": {"codex": {"optInOnly": True}}},
    {"banks": {BANK: {"disabled": True}}},
])
def test_capture_policy_does_not_bypass_capture_restrictions(provider, project_layout, restriction):
    repo, excluded, config = project_layout.repo, project_layout.excluded, project_layout.config
    policy = config["project_memory"]
    policy.pop("approved_roots")
    policy["capture_policy"] = "coding-agent"
    instance, fake = provider(config, cwd=str(repo))
    try:
        _note(instance)
        assert len(fake.retains) == 1
        _bind_exclusions(instance._config["project_memory"], excluded, **restriction)
        _note(instance)
    finally:
        instance.shutdown()
    assert len(fake.retains) == 1


@pytest.mark.parametrize("defect", [
    "missing-policy", "invalid-policy", "missing-cwd", "unknown-root", "non-git",
    "hash", "missing-config", "malformed-worktree", "wrong-bank", "wrong-scopes",
    "conflicting-tag",
])
def test_project_binding_failures_send_no_additional_retain(provider, project_layout, defect):
    repo, worktree, config = project_layout.repo, project_layout.worktree, project_layout.config
    origin = worktree if defect == "malformed-worktree" else repo
    instance, fake = provider(config, cwd=str(origin))
    tags = None
    try:
        _note(instance, ["project:owned-main"])
        assert len(fake.retains) == 1
        policy = instance._config["project_memory"]
        if defect == "missing-policy":
            del instance._config["project_memory"]  # explicit project:* still fails closed
        elif defect == "invalid-policy":
            instance._config["project_memory"] = {}
        elif defect == "missing-cwd":
            instance._cwd = ""
        elif defect == "unknown-root":
            policy["approved_roots"].remove(str(repo))
        elif defect == "non-git":
            plain = repo.parent / "plain-directory"
            plain.mkdir()
            policy["approved_roots"].append(str(plain))
            instance._cwd = str(plain)
        elif defect == "hash":
            policy["exclusion_config_sha256"] = "0" * 64
        elif defect == "missing-config":
            Path(policy["exclusion_config"]).unlink()
        elif defect == "malformed-worktree":
            (worktree / ".git").write_text("unqualified synthetic link")
        elif defect == "wrong-bank":
            policy["bank_id"] = "other-synthetic-bank"
        elif defect == "wrong-scopes":
            instance._observation_scopes = "shared"
        else:
            tags = ["project:wrong-project"]
        _note(instance, tags)
    finally:
        instance.shutdown()
    assert len(fake.retains) == 1


@pytest.mark.parametrize("context,retain_cron,expected", [
    ("subagent", False, 1), ("cron", False, 0), ("cron", True, 1),
])
def test_project_mode_preserves_helper_and_cron_policy(provider, project_layout, context, retain_cron, expected):
    repo, config = project_layout.repo, project_layout.config
    config = {**config, "retain_cron": retain_cron}
    instance, fake = provider(config, cwd=str(repo), agent_context=context)
    try:
        instance.sync_turn("Synthetic scheduled/helper user.", "Synthetic answer.")
    finally:
        instance.shutdown()
    assert len(fake.retains) == expected
    if expected:
        assert "project:owned-main" in _item(fake)["tags"]


@pytest.mark.parametrize("route,cadence", [("automatic", 1), ("automatic", 3), ("builtin", 1)])
@pytest.mark.parametrize("changed_origin", [False, True])
def test_old_queued_or_buffered_work_survives_session_switch(
    provider, project_layout, route, cadence, changed_origin
):
    repo, other, config = project_layout.repo, project_layout.other, project_layout.config
    instance, fake = provider({**config, "retain_every_n_turns": cadence}, cwd=str(repo))
    entered, release = threading.Event(), threading.Event()

    def hold_writer():
        entered.set()
        release.wait(10)

    instance._enqueue_retain(hold_writer)
    try:
        assert entered.wait(3)
        if route == "automatic":
            instance.sync_turn("Old synthetic user.", "Old answer.")
        else:
            instance.on_memory_write("add", "memory", "Old synthetic builtin.")
        kwargs = {"cwd": str(other)} if changed_origin else {}
        instance.on_session_switch("session-2", **kwargs)
        instance.sync_turn("New synthetic user.", "New answer.")
    finally:
        release.set()
        instance.shutdown()
    assert [call.get("document_id") for call in fake.retains] == [
        "session-1" if route == "automatic" else None, "session-2"
    ]
    assert [call["items"][0]["metadata"]["repo"] for call in fake.retains] == [
        "owned-main", "other-main" if changed_origin else "owned-main"
    ]
    old_content = _item(fake)["content"]
    if route == "automatic":
        assert json.loads(old_content)[0]["content"] == "User: Old synthetic user."
    else:
        assert old_content == "Old synthetic builtin."
    assert json.loads(_item(fake, -1)["content"])[0]["content"] == "User: New synthetic user."


@pytest.mark.parametrize("route", ["automatic", "builtin"])
def test_queued_origin_is_rechecked_against_current_exclusions(provider, project_layout, route):
    repo, other, excluded, config = (
        project_layout.repo,
        project_layout.other,
        project_layout.excluded,
        project_layout.config,
    )
    instance, fake = provider(config, cwd=str(repo))
    entered, release = threading.Event(), threading.Event()

    def hold_writer():
        entered.set()
        release.wait(10)

    try:
        _note(instance)
        assert len(fake.retains) == 1
        instance._enqueue_retain(hold_writer)
        assert entered.wait(3)
        if route == "automatic":
            instance.sync_turn("Queued old user.", "Queued old answer.")
        else:
            instance.on_memory_write("add", "memory", "Queued old builtin.")
        instance.on_session_switch("session-2", cwd=str(other))
        instance.sync_turn("Permitted new user.", "Permitted new answer.")
        # New session remains valid; only the frozen OLD origin is now excluded.
        _bind_exclusions(instance._config["project_memory"], [*excluded, repo])
    finally:
        release.set()
        instance.shutdown()
    assert len(fake.retains) == 2
    assert fake.retains[-1]["document_id"] == "session-2"
    assert _item(fake, -1)["metadata"]["repo"] == "other-main"
    assert json.loads(_item(fake, -1)["content"])[0]["content"] == "User: Permitted new user."


@pytest.mark.parametrize("route", ["automatic", "builtin"])
@pytest.mark.parametrize("started_in_project_mode", [True, False])
def test_queued_validation_requirement_survives_provider_reinitialization(
    provider, project_layout, hermes_env, route, started_in_project_mode
):
    repo, config = project_layout.repo, project_layout.config
    config = dict(config)
    if not started_in_project_mode:
        del config["project_memory"]
        config["observation_scopes"] = "shared"
    instance, fake = provider(config, cwd=str(repo))
    entered, release = threading.Event(), threading.Event()

    def hold_writer():
        entered.set()
        release.wait(10)

    try:
        _note(instance)
        assert len(fake.retains) == 1  # initial binding/mode really reaches transport
        instance._enqueue_retain(hold_writer)
        assert entered.wait(3)
        if route == "automatic":
            instance.sync_turn("Queued before reinit.", "Old synthetic answer.")
        else:
            instance.on_memory_write("add", "memory", "Queued before reinit.")

        # Reinitialize through the native lifecycle, not private policy mutation.
        # Same bank/cwd/client; only project mode is removed. Hold the actual old
        # callback until this complete off-mode configuration has been loaded.
        config_path = hermes_env / "hindsight" / "config.json"
        replacement = json.loads(config_path.read_text())
        replacement.pop("project_memory", None)
        replacement["observation_scopes"] = "shared"
        config_path.write_text(json.dumps(replacement))
        instance.initialize("session-2", cwd=str(repo))
        instance.sync_turn("New legacy turn.", "New synthetic answer.")
    finally:
        release.set()
        instance.shutdown()

    queued = [call for call in fake.retains if "Queued before reinit." in call["items"][0]["content"]]
    assert len(queued) == (0 if started_in_project_mode else 1)
    assert len(fake.retains) == (2 if started_in_project_mode else 3)
    new = [call for call in fake.retains if "New legacy turn." in call["items"][0]["content"]]
    assert len(new) == 1  # positive control: reinitialized legacy writes are allowed
    assert new[0]["document_id"] == "session-2"
    assert not any(tag.startswith("project:") for tag in new[0]["items"][0]["tags"])
