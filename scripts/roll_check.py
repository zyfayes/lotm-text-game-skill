#!/usr/bin/env python3
"""Generate and adjudicate auditable d100 checks for the LOTM text game."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any, Iterable, Optional


OUTCOMES = ("大失败", "失败", "险成", "成功", "大成功")
MODE_ALIASES = {
    "favored": "favored",
    "爽翻天": "favored",
    "ordinary": "ordinary",
    "普通": "ordinary",
    "hell": "hell",
    "地狱": "hell",
}
MODE_LABELS = {"favored": "爽翻天", "ordinary": "普通", "hell": "地狱"}
MODE_MODIFIERS = {"favored": 20, "ordinary": 0, "hell": -15}
UINT32_RANGE = 1 << 32
UINT32_ACCEPT_LIMIT = UINT32_RANGE - (UINT32_RANGE % 100)


class RollError(ValueError):
    """Raised for invalid roll input."""


def normalize_mode(value: str) -> str:
    try:
        return MODE_ALIASES[value]
    except KeyError as exc:
        raise RollError("mode must be favored/爽翻天, ordinary/普通, or hell/地狱") from exc


def parse_modifier(value: str) -> dict[str, Any]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("modifier must use NAME=INTEGER")
    name, raw_amount = value.split("=", 1)
    name = name.strip()
    if not name:
        raise argparse.ArgumentTypeError("modifier name cannot be empty")
    try:
        amount = int(raw_amount)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("modifier amount must be an integer") from exc
    return {"name": name, "value": amount}


def base_outcome_index(total: int, target: int) -> int:
    if total >= target + 30:
        return 4
    if total >= target:
        return 3
    if total >= target - 15:
        return 2
    if total >= target - 45:
        return 1
    return 0


def apply_natural_rule(raw: int, mode: str, base_index: int) -> tuple[int, bool, str | None]:
    if raw >= 96:
        if base_index == 4:
            return 4, True, "96～100：已是大成功，获得命运余裕"
        return min(4, base_index + 1), False, "96～100：结果提升一档"

    if mode == "favored":
        if raw == 1:
            return 0, False, "爽翻天原始骰 1：大失败"
        if 2 <= raw <= 5:
            return 1, False, "爽翻天原始骰 2～5：固定为普通失败"
    elif mode == "ordinary":
        if 1 <= raw <= 5:
            return 0, False, "普通原始骰 1～5：大失败"
    elif mode == "hell":
        if 1 <= raw <= 5:
            return 0, False, "地狱原始骰 1～5：大失败"
        if 6 <= raw <= 25:
            return max(0, base_index - 1), False, "地狱原始骰 6～25：结果下调一档"
    return base_index, False, None


def adjudicate(
    raw: int,
    mode: str,
    target: int,
    attribute: int,
    skill: int,
    modifiers: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    mode = normalize_mode(mode)
    if not 1 <= raw <= 100:
        raise RollError("raw d100 must be from 1 to 100")
    if target < 1:
        raise RollError("target must be positive")
    if attribute < 0 or skill < 0:
        raise RollError("attribute and skill cannot be negative")

    modifier_list = list(modifiers)
    situational_total = sum(int(item["value"]) for item in modifier_list)
    if not -40 <= situational_total <= 40:
        raise RollError("situational modifiers must total from -40 to +40")

    mode_modifier = MODE_MODIFIERS[mode]
    total = raw + attribute + skill + mode_modifier + situational_total
    base_index = base_outcome_index(total, target)
    final_index, overflow_edge, natural_rule = apply_natural_rule(raw, mode, base_index)
    return {
        "mode": mode,
        "mode_label": MODE_LABELS[mode],
        "raw": raw,
        "attribute": attribute,
        "skill": skill,
        "mode_modifier": mode_modifier,
        "situational_modifiers": modifier_list,
        "situational_total": situational_total,
        "formula": f"{raw} + {attribute} + {skill} + ({mode_modifier}) + ({situational_total}) = {total}",
        "total": total,
        "target": target,
        "base_result": OUTCOMES[base_index],
        "natural_rule": natural_rule,
        "final_result": OUTCOMES[final_index],
        "overflow_edge": overflow_edge,
    }


def seed_commitment(seed: bytes) -> str:
    return hashlib.sha256(seed).hexdigest()


def create_seed(path: Path) -> dict[str, Any]:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = secrets.token_bytes(32)
    try:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RollError(f"seed file already exists: {path}") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(seed)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "rng_method": "hmac_sha256_rejection_v1",
        "seed_file": str(path),
        "seed_commitment": seed_commitment(seed),
        "next_counter": 0,
    }


def load_seed(path: Path) -> bytes:
    try:
        seed = path.read_bytes()
    except OSError as exc:
        raise RollError(f"cannot read seed file: {exc}") from exc
    if len(seed) != 32:
        raise RollError("seed file must contain exactly 32 bytes")
    return seed


def deterministic_d100(seed: bytes, counter: int, context: str) -> tuple[int, int]:
    if counter < 0:
        raise RollError("counter cannot be negative")
    if not context.strip():
        raise RollError("context cannot be empty")
    attempt = 0
    while True:
        message = f"lotm-d100-v1|{counter}|{context}|{attempt}".encode("utf-8")
        digest = hmac.new(seed, message, hashlib.sha256).digest()
        value = int.from_bytes(digest[:4], "big")
        if value < UINT32_ACCEPT_LIMIT:
            return value % 100 + 1, attempt
        attempt += 1


def generate_raw(seed_file: Optional[Path], counter: Optional[int], context: str) -> tuple[int, dict[str, Any]]:
    if seed_file is None:
        if counter is not None:
            raise RollError("--counter requires --seed-file")
        return secrets.randbelow(100) + 1, {
            "rng_method": "system_csprng",
            "seed_commitment": None,
            "counter": None,
            "platform_result_id": None,
            "context": context,
        }
    if counter is None:
        raise RollError("--seed-file requires --counter")
    seed = load_seed(seed_file)
    raw, attempt = deterministic_d100(seed, counter, context)
    return raw, {
        "rng_method": "hmac_sha256_rejection_v1",
        "seed_commitment": seed_commitment(seed),
        "counter": counter,
        "platform_result_id": None,
        "context": context,
        "rejection_attempt": attempt,
    }


def odds(mode: str, target: int, attribute: int, skill: int, modifiers: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {outcome: 0 for outcome in OUTCOMES}
    overflow_count = 0
    for raw in range(1, 101):
        result = adjudicate(raw, mode, target, attribute, skill, modifiers)
        counts[result["final_result"]] += 1
        overflow_count += int(result["overflow_edge"])
    return {
        "mode": normalize_mode(mode),
        "mode_label": MODE_LABELS[normalize_mode(mode)],
        "attribute": attribute,
        "skill": skill,
        "target": target,
        "situational_modifiers": modifiers,
        "distribution_percent": counts,
        "partial_or_better_percent": sum(counts[name] for name in ("险成", "成功", "大成功")),
        "clean_success_or_better_percent": sum(counts[name] for name in ("成功", "大成功")),
        "overflow_edge_percent": overflow_count,
    }


def common_check_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mode", required=True, help="favored/爽翻天, ordinary/普通, or hell/地狱")
    parser.add_argument("--target", required=True, type=int)
    parser.add_argument("--attribute", required=True, type=int)
    parser.add_argument("--skill", required=True, type=int)
    parser.add_argument("--modifier", action="append", default=[], type=parse_modifier, metavar="NAME=INTEGER")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_seed = subparsers.add_parser("init-seed", help="create a private 256-bit campaign seed")
    init_seed.add_argument("--output", required=True, type=Path)

    roll = subparsers.add_parser("roll", help="generate and adjudicate one d100 check")
    common_check_arguments(roll)
    roll.add_argument("--context", required=True, help="stable event/check context stored with the roll")
    roll.add_argument("--seed-file", type=Path, help="optional private campaign seed")
    roll.add_argument("--counter", type=int, help="required monotonically increasing counter with --seed-file")

    odds_parser = subparsers.add_parser("odds", help="enumerate all 100 raw outcomes without rolling")
    common_check_arguments(odds_parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "init-seed":
            output = create_seed(args.output)
        elif args.command == "roll":
            mode = normalize_mode(args.mode)
            raw, rng = generate_raw(args.seed_file, args.counter, args.context)
            check = adjudicate(raw, mode, args.target, args.attribute, args.skill, args.modifier)
            output = {"rng": rng, "check": check}
        else:
            output = odds(args.mode, args.target, args.attribute, args.skill, args.modifier)
    except (RollError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
