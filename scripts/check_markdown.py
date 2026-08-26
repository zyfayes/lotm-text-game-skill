#!/usr/bin/env python3
"""Check Skill Markdown for portable rendering hazards."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import unquote, urlparse


FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE = re.compile(r"`[^`\n]*`")
RAW_HTML = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^>]*)?>")
ASCII_RANGE = re.compile(r"(?<=[0-9A-Za-z\u3400-\u9fff])~(?=[0-9A-Za-z\u3400-\u9fff])")
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
TABLE_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def markdown_files(paths: Iterable[Path]) -> List[Path]:
    files: List[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() == ".md":
            files.append(path)
        elif path.is_dir():
            files.extend(
                candidate
                for candidate in path.rglob("*.md")
                if ".git" not in candidate.parts and "__pycache__" not in candidate.parts
            )
    return sorted(set(file.resolve() for file in files))


def table_cells(line: str) -> List[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def is_table_separator(line: str) -> bool:
    cells = table_cells(line)
    return bool(cells) and all(TABLE_SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def issue(path: Path, line: int, code: str, message: str) -> Dict[str, Any]:
    return {"path": str(path), "line": line, "code": code, "message": message}


def scan_file(path: Path, max_table_columns: int = 4, max_table_line: int = 240) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    active_fence: str | None = None
    fence_line = 0
    prose: Dict[int, str] = {}

    for line_number, line in enumerate(lines, 1):
        match = FENCE.match(line)
        if match:
            marker = match.group(1)
            if active_fence is None:
                active_fence = marker[0]
                fence_line = line_number
                if marker[0] == "~":
                    findings.append(
                        issue(path, line_number, "tilde-fence", "Use backtick fences; tilde fences are not portable across IM renderers.")
                    )
            elif marker[0] == active_fence:
                active_fence = None
                fence_line = 0
            continue
        if active_fence is not None:
            continue

        visible = INLINE_CODE.sub("", line)
        prose[line_number] = visible
        if "~~" in visible:
            findings.append(
                issue(path, line_number, "strikethrough-risk", "ASCII double tildes can render as unintended strikethrough.")
            )
        elif ASCII_RANGE.search(visible):
            findings.append(
                issue(path, line_number, "ascii-range", "Use an en dash or Chinese range mark instead of ASCII tilde in prose.")
            )
        if RAW_HTML.search(visible):
            findings.append(
                issue(path, line_number, "raw-html", "Raw HTML is not a portable Skill or IM rendering contract.")
            )
        for match in MARKDOWN_LINK.finditer(visible):
            raw_target = match.group(1).strip()
            if raw_target.startswith("<") and ">" in raw_target:
                target = raw_target[1 : raw_target.index(">")]
            else:
                target = raw_target.split(maxsplit=1)[0]
            parsed = urlparse(target)
            if not target or target.startswith("#") or parsed.scheme:
                continue
            local_target = unquote(target.split("#", 1)[0])
            if local_target and not (path.parent / local_target).resolve().exists():
                findings.append(
                    issue(path, line_number, "broken-link", f"Local Markdown target does not exist: {local_target}")
                )

    if active_fence is not None:
        findings.append(issue(path, fence_line, "unclosed-fence", "Code fence is not closed."))

    for line_number in range(2, len(lines) + 1):
        separator = prose.get(line_number)
        header = prose.get(line_number - 1)
        if separator is None or header is None or not is_table_separator(separator):
            continue
        rows = [header, separator]
        cursor = line_number + 1
        while cursor <= len(lines) and table_cells(prose.get(cursor, "")):
            rows.append(prose[cursor])
            cursor += 1
        column_count = len(table_cells(separator))
        if column_count > max_table_columns:
            findings.append(
                issue(path, line_number, "wide-table", f"Table has {column_count} columns; portable limit is {max_table_columns}.")
            )
        for offset, row in enumerate(rows, line_number - 1):
            if len(row) > max_table_line:
                findings.append(
                    issue(path, offset, "long-table-row", f"Table row has {len(row)} characters; portable limit is {max_table_line}.")
                )

    return findings


def scan_paths(paths: Iterable[Path], max_table_columns: int = 4, max_table_line: int = 240) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for path in markdown_files(paths):
        findings.extend(scan_file(path, max_table_columns=max_table_columns, max_table_line=max_table_line))
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["."], help="Markdown files or directories")
    parser.add_argument("--max-table-columns", type=int, default=4)
    parser.add_argument("--max-table-line", type=int, default=240)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    findings = scan_paths(
        (Path(value) for value in args.paths),
        max_table_columns=args.max_table_columns,
        max_table_line=args.max_table_line,
    )
    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        for finding in findings:
            print(f"{finding['path']}:{finding['line']}: {finding['code']}: {finding['message']}")
        if not findings:
            print("Markdown portability check passed.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
