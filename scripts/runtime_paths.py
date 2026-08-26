#!/usr/bin/env python3
"""Resolve a safe, explicit runtime data root for LOTM campaigns."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


DATA_ROOT_ENV = "LOTM_DATA_ROOT"
MODES = {"local", "service"}


class RuntimePathError(ValueError):
    """Raised when a runtime data location is missing or unsafe."""


def resolved(path: Path | str, field: str) -> Path:
    expanded = Path(path).expanduser()
    if not expanded.is_absolute():
        raise RuntimePathError(f"{field} must be an absolute path")
    return expanded.resolve(strict=False)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def resolve_runtime_paths(
    *,
    mode: str,
    skill_dir: Path | str,
    workspace_root: Optional[Path | str] = None,
    data_root: Optional[Path | str] = None,
    environment: Optional[Mapping[str, str]] = None,
    create: bool = False,
) -> Dict[str, Any]:
    if mode not in MODES:
        raise RuntimePathError(f"mode must be one of: {', '.join(sorted(MODES))}")

    env = os.environ if environment is None else environment
    configured = str(data_root).strip() if data_root is not None else ""
    source = "argument"
    if not configured:
        configured = env.get(DATA_ROOT_ENV, "").strip()
        source = "environment"

    if configured:
        runtime_root = resolved(configured, "data root")
    else:
        if mode == "service":
            raise RuntimePathError(f"service mode requires --data-root or {DATA_ROOT_ENV}")
        if workspace_root is None or not str(workspace_root).strip():
            raise RuntimePathError("local mode requires an explicit workspace root when no data root is configured")
        runtime_root = resolved(workspace_root, "workspace root")
        source = "workspace"

    skill_root = resolved(skill_dir, "skill directory")
    filesystem_root = Path(runtime_root.anchor)
    user_home = Path.home().resolve(strict=False)
    if runtime_root == filesystem_root:
        raise RuntimePathError("data root cannot be the filesystem root")
    if runtime_root == user_home:
        raise RuntimePathError("data root cannot be the user home directory itself")
    if runtime_root == skill_root or is_within(runtime_root, skill_root):
        raise RuntimePathError("data root cannot be the reusable skill directory or a directory inside it")

    campaigns_dir = runtime_root / "campaigns"
    if is_within(campaigns_dir, skill_root):
        raise RuntimePathError("campaign directory would be inside the reusable skill package")

    if create:
        campaigns_dir.mkdir(parents=True, exist_ok=True)

    return {
        "status": "ready",
        "mode": mode,
        "source": source,
        "data_root": str(runtime_root),
        "campaigns_dir": str(campaigns_dir),
        "created": bool(create),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--skill-dir", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--workspace-root")
    parser.add_argument("--data-root")
    parser.add_argument("--create", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = resolve_runtime_paths(
            mode=args.mode,
            skill_dir=args.skill_dir,
            workspace_root=args.workspace_root,
            data_root=args.data_root,
            create=args.create,
        )
    except (OSError, RuntimePathError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
