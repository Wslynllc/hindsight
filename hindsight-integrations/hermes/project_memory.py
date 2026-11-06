"""Owned project-writer guard. File-only policy; no network or transcript reads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .settings import _main_repository, _repository_root

_BLOCKED = "Project memory write blocked: binding unavailable, changed, or excluded."


class ProjectMemoryDenied(ValueError):
    """Terminal capture-policy denial; never retry this queued payload."""


@dataclass(frozen=True)
class CaptureStamp:
    tag: str
    metadata: dict[str, str]


def _absolute(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(_BLOCKED)
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(_BLOCKED)
    return path.resolve(strict=True)


def _within(path: Path, prefix: Path) -> bool:
    return path == prefix or prefix in path.parents


def capture_stamp(policy: dict, cwd: str) -> CaptureStamp:
    """Bind explicit session origin to pinned capture policy and exclusions.

    All failures expose one static message. No basename fallback outside git, no
    process-cwd fallback, no repository-controlled configuration or shell commands.
    Re-read on dispatch so removing/changing the exclusion file blocks queued writes.
    """
    try:
        return _capture_stamp(policy, cwd)
    except Exception:
        raise ProjectMemoryDenied(_BLOCKED) from None


def _capture_stamp(policy: dict, cwd: str) -> CaptureStamp:
    keys = {"bank_id", "exclusion_config", "exclusion_config_sha256", "excluded_path_ids"}
    if not isinstance(policy, dict):
        raise ValueError(_BLOCKED)
    capture_policy = policy.get("capture_policy") == "coding-agent"
    selector = "capture_policy" if capture_policy else "approved_roots"
    if set(policy) != keys | {selector}:
        raise ValueError(_BLOCKED)
    if not isinstance(policy["bank_id"], str) or not policy["bank_id"]:
        raise ValueError(_BLOCKED)
    approved = None
    if not capture_policy:
        roots = policy["approved_roots"]
        if not isinstance(roots, list) or not roots:
            raise ValueError(_BLOCKED)
        approved = {_absolute(root) for root in roots}
        if any(root in {Path(root.anchor), Path.home().resolve()} for root in approved):
            raise ValueError(_BLOCKED)
    origin = _absolute(cwd)
    if not origin.is_dir() or (approved is not None and not any(_within(origin, root) for root in approved)):
        raise ValueError(_BLOCKED)
    data = _absolute(policy["exclusion_config"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != policy["exclusion_config_sha256"]:
        raise ValueError(_BLOCKED)
    config = json.loads(data)
    if not isinstance(config, dict) or config.get("disabled", False) is not False:
        raise ValueError(_BLOCKED)
    if config.get("retainSessions", True) is not True or config.get("banks"):
        raise ValueError(_BLOCKED)
    # This binding supports the existing default-capture policy, not a second
    # opt-in/routing interpreter. Refuse narrower/redirected policies explicitly.
    if config.get("optInOnly", False) is not False or config.get("mapPathToBank"):
        raise ValueError(_BLOCKED)
    # This adapter binds the preflight's top-level path exclusions. A new scoped
    # disabling policy needs review, rather than silently approximating precedence.
    harnesses = config.get("harnesses", {})
    if not isinstance(harnesses, dict) or any(
        not isinstance(section, dict) or "disabled" in section or "paths" in section
        or section.get("retainSessions", True) is not True
        or section.get("optInOnly", False) is not False or section.get("banks")
        or section.get("mapPathToBank")
        for section in harnesses.values()
    ):
        raise ValueError(_BLOCKED)
    paths = config.get("paths")
    if not isinstance(paths, dict):
        raise ValueError(_BLOCKED)
    excluded, ids = [], set()
    for prefix, section in paths.items():
        if not isinstance(section, dict) or not isinstance(section.get("disabled", False), bool):
            raise ValueError(_BLOCKED)
        if section.get("retainSessions", True) is not True:
            raise ValueError(_BLOCKED)
        if section.get("disabled") is True:
            # Same ID convention as the preflight, without exposing private prefixes.
            ids.add(hashlib.sha256(json.dumps(prefix).encode()).hexdigest()[:16])
            excluded.append(_absolute(prefix))
    expected = policy["excluded_path_ids"]
    if not isinstance(expected, list) or not expected or ids != set(expected):
        raise ValueError(_BLOCKED)
    if any(_within(origin, prefix) for prefix in excluded):
        raise ValueError(_BLOCKED)
    root = _repository_root(str(origin))
    if root is None or (approved is not None and root not in approved):
        raise ValueError(_BLOCKED)
    # Native helper deliberately falls back for malformed worktree links. The
    # writer must instead refuse those links (and unqualified submodule layouts).
    git = root / ".git"
    if git.is_file():
        text = git.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:") or not text[7:].strip():
            raise ValueError(_BLOCKED)
        gitdir = (root / text[7:].strip()).resolve(strict=True)
        if not (gitdir / "commondir").is_file():
            raise ValueError(_BLOCKED)
    main = _main_repository(root)
    if not main.path.is_dir() or (approved is not None and main.path not in approved):
        raise ValueError(_BLOCKED)
    if not main.bare and not (main.path / ".git").is_dir():
        raise ValueError(_BLOCKED)
    # Main-checkout exclusions also protect worktrees outside the excluded tree.
    if any(_within(path, prefix) for path in (root, main.path) for prefix in excluded):
        raise ValueError(_BLOCKED)
    project = main.path.name.removesuffix(".git") if main.bare else main.path.name
    if not project or any(char in project for char in "{}*?[]"):
        raise ValueError(_BLOCKED)
    return CaptureStamp(
        tag=f"project:{project}",
        metadata={
            "repo": project,
            "project": project,
            "worktree_id": hashlib.sha256(str(root).encode()).hexdigest(),
        },
    )
