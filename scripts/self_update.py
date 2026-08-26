#!/usr/bin/env python3
"""Fast-forward a clean Git-installed Skill without delaying play on failure."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_BRANCH = "main"
AUTO_UPDATE_ENV = "LOTM_AUTO_UPDATE"


class UpdateError(RuntimeError):
    pass


def git(root: Path, arguments: List[str], timeout: float, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError(str(exc)) from exc
    if check and result.returncode != 0:
        raise UpdateError((result.stderr or result.stdout).strip() or "git command failed")
    return result


def check_and_update(skill_dir: Path | str, *, branch: str = DEFAULT_BRANCH, timeout: float = 5.0) -> Dict[str, Any]:
    root = Path(skill_dir).resolve(strict=False)
    if not (root / ".git").exists():
        return {"status": "unavailable", "reason": "not_git_install", "reload_required": False}

    try:
        top_level = Path(git(root, ["rev-parse", "--show-toplevel"], timeout).stdout.strip()).resolve()
        if top_level != root:
            raise UpdateError("skill directory is not the checkout root")
        current_branch = git(root, ["branch", "--show-current"], timeout).stdout.strip()
        if current_branch != branch:
            raise UpdateError(f"checkout branch is {current_branch!r}, expected {branch!r}")
        if git(root, ["status", "--porcelain"], timeout).stdout.strip():
            raise UpdateError("working tree has local changes")

        current = git(root, ["rev-parse", "HEAD"], timeout).stdout.strip()
        git(root, ["fetch", "--quiet", "--no-tags", "origin", branch], timeout)
        fetched = git(root, ["rev-parse", "FETCH_HEAD"], timeout).stdout.strip()
        if fetched == current:
            return {"status": "current", "current_commit": current, "reload_required": False}
        if git(root, ["merge-base", "--is-ancestor", current, fetched], timeout, check=False).returncode != 0:
            raise UpdateError("remote update is not a fast-forward")
        git(root, ["merge", "--ff-only", "--quiet", fetched], timeout)
        return {
            "status": "updated",
            "previous_commit": current,
            "current_commit": fetched,
            "reload_required": True,
        }
    except UpdateError as exc:
        return {"status": "blocked", "reason": str(exc), "reload_required": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    if os.environ.get(AUTO_UPDATE_ENV, "1").strip().lower() in {"0", "false", "no", "off"}:
        result: Dict[str, Any] = {"status": "disabled", "reload_required": False}
    else:
        try:
            result = check_and_update(args.skill_dir, branch=args.branch, timeout=max(0.1, args.timeout))
        except Exception as exc:
            result = {"status": "blocked", "reason": str(exc), "reload_required": False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
