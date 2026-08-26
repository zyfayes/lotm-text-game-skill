#!/usr/bin/env python3
"""Verify the lossless module map and single-authority index for ruleset v1.7."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List


LEGACY_HEADING = re.compile(r"^## (【(?:卷|附录)[^\n]+】[^\n]*)$")


def load_manifest(reference_dir: Path) -> Dict[str, Any]:
    path = reference_dir / "rules-manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_rules(reference_dir: Path) -> List[str]:
    errors: List[str] = []
    try:
        manifest = load_manifest(reference_dir)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load rules-manifest.json: {exc}"]

    modules = manifest.get("modules")
    if not isinstance(modules, list) or not modules or len(modules) != len(set(modules)):
        return ["manifest modules must be a non-empty unique array"]

    texts: Dict[str, str] = {}
    discovered: Dict[str, List[str]] = {}
    for name in modules:
        if not isinstance(name, str) or Path(name).name != name:
            errors.append(f"invalid module name: {name!r}")
            continue
        path = reference_dir / name
        if not path.is_file():
            errors.append(f"missing module: {name}")
            continue
        text = path.read_text(encoding="utf-8")
        texts[name] = text
        h1_count = sum(1 for line in text.splitlines() if line.startswith("# "))
        if h1_count != 1:
            errors.append(f"{name}: expected exactly one H1, found {h1_count}")
        discovered[name] = [match.group(1) for line in text.splitlines() if (match := LEGACY_HEADING.fullmatch(line))]

    expected_by_module: Dict[str, List[str]] = {name: [] for name in modules}
    section_ids: set[str] = set()
    headings: set[str] = set()
    for section in manifest.get("legacy_sections", []):
        if not isinstance(section, dict):
            errors.append("legacy_sections entries must be objects")
            continue
        section_id = section.get("id")
        module = section.get("module")
        heading = section.get("heading")
        if not isinstance(section_id, str) or section_id in section_ids:
            errors.append(f"duplicate or invalid section id: {section_id!r}")
        else:
            section_ids.add(section_id)
        if module not in expected_by_module or not isinstance(heading, str):
            errors.append(f"invalid section mapping: {section!r}")
            continue
        if heading in headings:
            errors.append(f"duplicate manifest heading: {heading}")
        headings.add(heading)
        expected_by_module[module].append(heading)

    for name in modules:
        if discovered.get(name, []) != expected_by_module.get(name, []):
            errors.append(
                f"{name}: legacy section order or coverage differs; expected {expected_by_module.get(name, [])!r}, found {discovered.get(name, [])!r}"
            )

    always_read = manifest.get("always_read_for_adjudication", [])
    if not isinstance(always_read, list) or any(name not in modules for name in always_read):
        errors.append("always_read_for_adjudication must reference only declared modules")

    authorities = manifest.get("authorities")
    if not isinstance(authorities, dict) or not authorities:
        errors.append("authorities must be a non-empty object")
    elif any(target not in modules for target in authorities.values()):
        errors.append("every authority target must be a declared module")

    index_path = reference_dir / "ruleset.md"
    if not index_path.is_file():
        errors.append("missing ruleset.md index")
    else:
        index_text = index_path.read_text(encoding="utf-8")
        for name in modules:
            if f"]({name})" not in index_text:
                errors.append(f"ruleset.md does not link {name}")

    digest = manifest.get("legacy_body_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        errors.append("legacy_body_sha256 must be a lowercase SHA-256 digest")
    legacy_source = manifest.get("legacy_source")
    if not isinstance(legacy_source, dict):
        errors.append("legacy_source must be an object")
    else:
        add_fields = {"repository", "commit", "path", "body_starts_at_line"}
        if set(legacy_source) != add_fields:
            errors.append("legacy_source fields are invalid")
        if not isinstance(legacy_source.get("commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", legacy_source.get("commit", "")):
            errors.append("legacy_source commit must be a full lowercase git hash")
        if legacy_source.get("path") != "references/ruleset.md" or legacy_source.get("body_starts_at_line") != 11:
            errors.append("legacy_source path or body offset is invalid")
    schema_digests = manifest.get("legacy_schema_sha256")
    expected_schema_names = {
        "campaign-state.v1.6.schema.json",
        "campaign-event.v1.6.schema.json",
        "portable-anchor.v1.6.schema.json",
    }
    if not isinstance(schema_digests, dict) or set(schema_digests) != expected_schema_names:
        errors.append("legacy_schema_sha256 must cover all three archived v1.6 schemas")
    else:
        for name, expected_digest in schema_digests.items():
            path = reference_dir / name
            if not path.is_file():
                errors.append(f"missing archived schema: {name}")
                continue
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected_digest != actual_digest:
                errors.append(f"archived schema digest differs: {name}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references", default=str(Path(__file__).resolve().parent.parent / "references"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = validate_rules(Path(args.references))
    for error in errors:
        print(f"error: {error}")
    if not errors:
        print("Rules module and authority check passed.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
