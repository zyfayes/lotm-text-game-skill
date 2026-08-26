#!/usr/bin/env python3
"""Safely fast-forward a git-installed LOTM Skill from its trusted origin."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional
from urllib.parse import urlparse


EXPECTED_REPOSITORY = "github.com/zyfayes/lotm-text-game-skill"
DEFAULT_BRANCH = "main"
DEFAULT_MIN_INTERVAL = 300.0
DEFAULT_CHECK_TIMEOUT = 2.0
DEFAULT_UPDATE_TIMEOUT = 20.0
AUTO_UPDATE_ENV = "LOTM_AUTO_UPDATE"
COMMIT = re.compile(r"[0-9a-f]{40}")


class UpdateError(RuntimeError):
    """Raised when an update cannot be verified or applied safely."""


def git_environment() -> Dict[str, str]:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["LC_ALL"] = "C"
    return environment


def run_command(
    command: List[str],
    *,
    cwd: Path,
    timeout: float,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=git_environment(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"command timed out: {command[0]}") from exc
    except OSError as exc:
        raise UpdateError(f"cannot run {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(detail or f"command failed: {' '.join(command)}")
    return result


def git(skill_dir: Path, arguments: List[str], timeout: float, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_command(["git", *arguments], cwd=skill_dir, timeout=timeout, check=check)


def canonical_repository(value: str) -> str:
    text = value.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    if text.startswith("git@github.com:"):
        return "github.com/" + text.split(":", 1)[1].lower()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https", "ssh"} and parsed.hostname:
        path = parsed.path.lstrip("/")
        if parsed.hostname.lower() == "github.com":
            return f"github.com/{path.lower()}"
        return f"{parsed.scheme}://{parsed.hostname.lower()}/{path}"
    if parsed.scheme == "file":
        return "file://" + str(Path(parsed.path).resolve(strict=False))
    if text.startswith("/") or text.startswith("."):
        return str(Path(text).resolve(strict=False))
    return text.lower()


def read_state(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_state(path: Path, value: Dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def update_lock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        yield False
        return
    try:
        yield True
    finally:
        try:
            path.rmdir()
        except OSError:
            pass


def validate_candidate(candidate: Path, timeout: float) -> None:
    commands = [
        [sys.executable, "scripts/check_rules.py"],
        [sys.executable, "scripts/check_markdown.py", "SKILL.md", "references"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
    ]
    for command in commands:
        run_command(command, cwd=candidate, timeout=timeout)


def check_and_update(
    skill_dir: Path | str,
    *,
    expected_repository: str = EXPECTED_REPOSITORY,
    branch: str = DEFAULT_BRANCH,
    min_interval: float = DEFAULT_MIN_INTERVAL,
    check_timeout: float = DEFAULT_CHECK_TIMEOUT,
    update_timeout: float = DEFAULT_UPDATE_TIMEOUT,
    now: Optional[float] = None,
    candidate_validator: Callable[[Path, float], None] = validate_candidate,
) -> Dict[str, Any]:
    root = Path(skill_dir).resolve(strict=False)
    if not (root / ".git").exists():
        return {
            "status": "unavailable",
            "reason": "not_git_install",
            "reload_required": False,
        }

    try:
        top_level = Path(git(root, ["rev-parse", "--show-toplevel"], check_timeout).stdout.strip()).resolve()
        if top_level != root:
            raise UpdateError("skill directory is not the git checkout root")
        git_dir_text = git(root, ["rev-parse", "--git-dir"], check_timeout).stdout.strip()
        git_dir = (root / git_dir_text).resolve() if not Path(git_dir_text).is_absolute() else Path(git_dir_text)
    except UpdateError as exc:
        return {"status": "blocked", "reason": "invalid_checkout", "detail": str(exc), "reload_required": False}

    with update_lock(git_dir / "lotm-self-update.lock") as acquired:
        if not acquired:
            return {"status": "busy", "reason": "update_in_progress", "reload_required": False}

        timestamp = time.time() if now is None else now
        state_path = git_dir / "lotm-self-update-state.json"
        state = read_state(state_path)
        try:
            current = git(root, ["rev-parse", "HEAD"], check_timeout).stdout.strip()
            branch_name = git(root, ["symbolic-ref", "--short", "HEAD"], check_timeout).stdout.strip()
            if branch_name != branch:
                raise UpdateError(f"checkout branch is {branch_name!r}, expected {branch!r}")
            origin = git(root, ["remote", "get-url", "origin"], check_timeout).stdout.strip()
            if canonical_repository(origin) != canonical_repository(expected_repository):
                raise UpdateError("origin does not match the trusted update repository")
        except UpdateError as exc:
            return {"status": "blocked", "reason": "untrusted_checkout", "detail": str(exc), "reload_required": False}

        last_checked = state.get("checked_at")
        if (
            min_interval > 0
            and isinstance(last_checked, (int, float))
            and timestamp >= last_checked
            and timestamp - last_checked < min_interval
            and state.get("remote_commit") == current
        ):
            return {
                "status": "cached_current",
                "current_commit": current,
                "checked_at": last_checked,
                "reload_required": False,
            }

        try:
            remote_result = git(root, ["ls-remote", "--exit-code", "origin", f"refs/heads/{branch}"], check_timeout)
            remote_line = remote_result.stdout.strip().splitlines()[0]
            remote_commit = remote_line.split()[0]
            if not COMMIT.fullmatch(remote_commit):
                raise UpdateError("remote branch did not return a full commit hash")
        except (IndexError, UpdateError) as exc:
            return {"status": "offline", "reason": "remote_check_failed", "detail": str(exc), "reload_required": False}

        if remote_commit == current:
            write_state(state_path, {"checked_at": timestamp, "remote_commit": remote_commit})
            return {
                "status": "current",
                "current_commit": current,
                "checked_at": timestamp,
                "reload_required": False,
            }

        try:
            dirty = git(root, ["status", "--porcelain", "--untracked-files=normal"], check_timeout).stdout.strip()
            if dirty:
                raise UpdateError("working tree has local changes")

            git(root, ["fetch", "--quiet", "--no-tags", "origin", branch], update_timeout)
            fetched = git(root, ["rev-parse", "FETCH_HEAD"], check_timeout).stdout.strip()
            if fetched != remote_commit:
                raise UpdateError("fetched commit does not match the remote check")
            ancestor = git(root, ["merge-base", "--is-ancestor", current, fetched], check_timeout, check=False)
            if ancestor.returncode != 0:
                raise UpdateError("remote update is not a fast-forward of the installed version")

            with tempfile.TemporaryDirectory(prefix="lotm-skill-update-") as temporary:
                candidate = Path(temporary) / "candidate"
                git(root, ["worktree", "add", "--detach", "--quiet", str(candidate), fetched], update_timeout)
                try:
                    candidate_validator(candidate, update_timeout)
                finally:
                    git(root, ["worktree", "remove", "--force", str(candidate)], update_timeout, check=False)

            git(root, ["merge", "--ff-only", "--no-edit", fetched], update_timeout)
            updated = git(root, ["rev-parse", "HEAD"], check_timeout).stdout.strip()
            if updated != fetched:
                raise UpdateError("fast-forward completed without selecting the verified commit")
            write_state(state_path, {"checked_at": timestamp, "remote_commit": updated})
            return {
                "status": "updated",
                "previous_commit": current,
                "current_commit": updated,
                "checked_at": timestamp,
                "reload_required": True,
            }
        except UpdateError as exc:
            return {"status": "blocked", "reason": "safe_update_refused", "detail": str(exc), "reload_required": False}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL)
    parser.add_argument("--check-timeout", type=float, default=DEFAULT_CHECK_TIMEOUT)
    parser.add_argument("--update-timeout", type=float, default=DEFAULT_UPDATE_TIMEOUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if os.environ.get(AUTO_UPDATE_ENV, "1").strip().lower() in {"0", "false", "no", "off"}:
        print(json.dumps({"status": "disabled", "reload_required": False}, sort_keys=True))
        return 0
    try:
        result = check_and_update(
            args.skill_dir,
            branch=args.branch,
            min_interval=max(0.0, args.min_interval),
            check_timeout=max(0.1, args.check_timeout),
            update_timeout=max(1.0, args.update_timeout),
        )
    except Exception as exc:  # Startup checks must never prevent play on the installed version.
        result = {
            "status": "blocked",
            "reason": "unexpected_update_error",
            "detail": str(exc),
            "reload_required": False,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
