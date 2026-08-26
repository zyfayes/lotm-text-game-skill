#!/usr/bin/env python3
"""Validate, commit, recover, initialize, and export LOTM campaign records."""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import roll_check


EVENT_ID = re.compile(r"^evt-([0-9]{6,})$")
CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
OUTCOMES = {"大失败", "失败", "险成", "成功", "大成功"}
RISK_LEVELS = {"轻微", "显著", "严重", "致命", "灾难"}
RISK_ORDER = ("轻微", "显著", "严重", "致命", "灾难")
CONSEQUENCE_CATEGORIES = {"伤势", "时间", "资源", "暴露", "关系", "污染", "机会丧失", "世界时钟"}
RNG_METHODS = {"system_csprng", "hmac_sha256_rejection_v1", "platform_verified"}
DIFFICULTY_MODIFIERS = {"爽翻天": 20, "普通": 0, "地狱": -15}
MODE_BY_MODIFIER = {value: key for key, value in roll_check.MODE_MODIFIERS.items()}
BODY_STATES = {"健康", "轻伤", "重伤", "濒死", "失控倾向", "灵性枯竭"}
MIND_STATES = {"清醒", "紧张", "焦虑", "恍惚", "疯狂"}
RELATION_LEVELS = {"敌视", "戒备", "冷淡", "普通", "友好", "亲近", "信赖"}
GOAL_STATUSES = {"pending", "active", "criteria_met", "achieved", "abandoned"}
CLUE_CONFIDENCE = {"传闻", "迹象", "可信", "证实"}
WRITABLE_VERSIONS = {"1.6", "1.7"}
LEGACY_READ_ONLY_VERSIONS = {"1.2", "1.3", "1.4", "1.5"}
V17_STATE_KEYS = {"social", "economy", "commitments", "preferences"}
MEMBERSHIP_STATUSES = {"outsider", "candidate", "member", "suspended", "expelled", "hostile"}
COMMITMENT_KINDS = {"favor", "contract", "oath", "promise", "leverage"}
COMMITMENT_STATUSES = {"open", "fulfilled", "breached", "released", "expired"}
CANON_STATUSES = {
    "primary_canon",
    "official_supplement",
    "licensed_adaptation",
    "secondary_lead",
    "game_supplement",
    "unknown",
    "disputed",
}
CHAPTER_DOMAINS = {"goal", "relations", "clues", "world_clocks", "social", "economy", "commitments"}
PROTECTED_PATCH_PATHS = {
    "/runtime/state_revision",
    "/runtime/last_event_id",
    "/runtime/updated_at",
    "/runtime/rng/next_counter",
}


class RuntimeErrorDetail(ValueError):
    """Raised when a campaign contract or transaction is invalid."""


def load_data(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeErrorDetail(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeErrorDetail(
                f"{path} is not JSON-compatible YAML and PyYAML is unavailable"
            ) from exc
        try:
            return yaml.safe_load(text)
        except Exception as exc:
            raise RuntimeErrorDetail(f"cannot parse {path}: {exc}") from exc


def load_events(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeErrorDetail(f"cannot read {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeErrorDetail(f"invalid JSON in {path}:{line_number}: {exc}") from exc
        if not isinstance(event, dict):
            raise RuntimeErrorDetail(f"event at {path}:{line_number} must be an object")
        events.append(event)
    return events


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        fsync_directory(path.parent)
    except Exception:
        with contextlib.suppress(OSError):
            temporary_path.unlink()
        raise


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary_path), str(path))
        fsync_directory(path.parent)
    except Exception:
        with contextlib.suppress(OSError):
            temporary_path.unlink()
        raise


def fsync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    descriptor = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def append_event(path: Path, event: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        fsync_directory(path.parent)


@contextlib.contextmanager
def campaign_lock(campaign_dir: Path) -> Iterator[None]:
    if not campaign_dir.is_dir():
        raise RuntimeErrorDetail(f"campaign directory does not exist: {campaign_dir}")
    lock_path = campaign_dir / ".campaign.lock"
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()


def add_error(errors: List[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def valid_event_id(value: Any) -> bool:
    return isinstance(value, str) and bool(EVENT_ID.fullmatch(value))


def valid_named_id(value: Any, prefix: str) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(rf"{re.escape(prefix)}[A-Za-z0-9._-]+", value))


def valid_commitment(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[a-f0-9]{64}", value))


def enum_value(value: Any, allowed: Iterable[str]) -> bool:
    return isinstance(value, str) and value in allowed


def validate_modifiers(value: Any, path: str, errors: List[str]) -> Optional[List[Dict[str, Any]]]:
    if not isinstance(value, list):
        errors.append(f"{path} must be an array")
        return None
    valid = True
    for index, modifier in enumerate(value):
        if not isinstance(modifier, dict):
            errors.append(f"{path}/{index} must be an object")
            valid = False
            continue
        if set(modifier) != {"name", "value"}:
            errors.append(f"{path}/{index} must contain only name and value")
            valid = False
        if not isinstance(modifier.get("name"), str) or not modifier.get("name", "").strip():
            errors.append(f"{path}/{index}/name is required")
            valid = False
        if not isinstance(modifier.get("value"), int) or isinstance(modifier.get("value"), bool):
            errors.append(f"{path}/{index}/value must be an integer")
            valid = False
    return value if valid else None


def require_fields(value: Dict[str, Any], fields: Iterable[str], path: str, errors: List[str]) -> None:
    for field in fields:
        if field not in value:
            errors.append(f"{path}/{field} is required")


def is_protected_patch_path(pointer: Any) -> bool:
    if not isinstance(pointer, str):
        return False
    for protected in PROTECTED_PATCH_PATHS:
        if pointer == protected or pointer.startswith(protected + "/") or protected.startswith(pointer.rstrip("/") + "/"):
            return True
    return False


def parse_real_timestamp(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def mapping_at(value: Any, key: str, errors: List[str], path: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return {}
    child = value.get(key)
    if not isinstance(child, dict):
        errors.append(f"{path}/{key} must be an object")
        return {}
    return child


def normalize_contract_version(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def state_contract_version(state: Any) -> Optional[str]:
    if not isinstance(state, dict):
        return None
    runtime = state.get("runtime")
    if not isinstance(runtime, dict):
        return None
    return normalize_contract_version(runtime.get("schema_version"))


def event_contract_version(event: Any) -> Optional[str]:
    if not isinstance(event, dict):
        return None
    version = event.get("schema_version")
    if version is None:
        return "1.6"
    return version if isinstance(version, str) else None


def require_writable_version(version: Optional[str], operation: str) -> None:
    if version in LEGACY_READ_ONLY_VERSIONS:
        raise RuntimeErrorDetail(
            f"{operation} is disabled for legacy v{version}; preserve it read-only or explicitly migrate it first"
        )
    if version not in WRITABLE_VERSIONS:
        raise RuntimeErrorDetail(f"{operation} requires a supported campaign contract")


def validate_legacy_state(state: Dict[str, Any], version: str) -> List[str]:
    errors: List[str] = []
    for key in ("runtime", "campaign", "player", "plot", "relations", "causality", "world", "knowledge", "discipline", "visuals", "roll_log"):
        add_error(errors, key in state, f"legacy state missing key: {key}")
    runtime = state.get("runtime")
    if not isinstance(runtime, dict):
        return errors + ["legacy runtime must be an object"]
    add_error(errors, normalize_contract_version(runtime.get("schema_version")) == version, "legacy schema_version is inconsistent")
    ruleset_version = normalize_contract_version(runtime.get("ruleset_version"))
    add_error(errors, ruleset_version is None or ruleset_version == version, "legacy ruleset_version is inconsistent")
    add_error(errors, isinstance(runtime.get("state_revision"), int) and runtime.get("state_revision", 0) >= 1, "legacy state_revision must be positive")
    add_error(errors, valid_event_id(runtime.get("last_event_id")), "legacy last_event_id is invalid")
    add_error(errors, parse_real_timestamp(runtime.get("updated_at")) is not None, "legacy updated_at is invalid")
    campaign = state.get("campaign")
    if not isinstance(campaign, dict):
        errors.append("legacy campaign must be an object")
    else:
        add_error(errors, isinstance(campaign.get("id"), str) and bool(CAMPAIGN_ID.fullmatch(campaign.get("id", ""))), "legacy campaign id is invalid")
        add_error(errors, enum_value(campaign.get("status"), {"active", "paused", "completed"}), "legacy campaign status is invalid")
        add_error(errors, isinstance(campaign.get("turn"), int) and campaign.get("turn", -1) >= 0, "legacy campaign turn is invalid")
        add_error(errors, parse_world_time(campaign.get("world_time")) is not None, "legacy campaign world_time is invalid")
    player = state.get("player")
    add_error(errors, isinstance(player, dict) and isinstance(player.get("name"), str) and bool(player.get("name", "").strip()), "legacy player name is required")
    add_error(errors, isinstance(state.get("plot"), dict), "legacy plot must be an object")
    add_error(errors, isinstance(state.get("relations"), list), "legacy relations must be an array")
    add_error(errors, isinstance(state.get("roll_log"), list), "legacy roll_log must be an array")
    return errors


def validate_legacy_event_sequence(events: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    add_error(errors, bool(events), "legacy event history must not be empty")
    previous_number: Optional[int] = None
    previous_revision = 0
    previous_world_time: Optional[dt.datetime] = None
    previous_created_at: Optional[dt.datetime] = None
    seen_ids = set()
    for index, event in enumerate(events):
        path = f"legacy events/{index}"
        if not isinstance(event, dict):
            errors.append(f"{path} must be an object")
            continue
        event_id = event.get("event_id")
        add_error(errors, valid_event_id(event_id), f"{path}/event_id is invalid")
        if valid_event_id(event_id):
            add_error(errors, event_id not in seen_ids, f"duplicate legacy event id: {event_id}")
            seen_ids.add(event_id)
            number = event_number(event_id)
            if previous_number is not None:
                add_error(errors, number > previous_number, f"legacy event ids are not increasing at {event_id}")
            previous_number = number
        revision = event.get("state_revision")
        add_error(errors, isinstance(revision, int) and revision == previous_revision + 1, f"{path}/state_revision is not contiguous")
        if isinstance(revision, int):
            previous_revision = revision
        add_error(errors, isinstance(event.get("type"), str) and bool(re.fullmatch(r"[a-z][a-z0-9_]*", event.get("type", ""))), f"{path}/type is invalid")
        add_error(errors, isinstance(event.get("action"), str) and bool(event.get("action", "").strip()), f"{path}/action is required")
        add_error(errors, isinstance(event.get("deltas"), dict), f"{path}/deltas must be an object")
        add_error(errors, event.get("roll") is None or isinstance(event.get("roll"), dict), f"{path}/roll is invalid")
        world_time = parse_world_time(event.get("world_time"))
        add_error(errors, world_time is not None, f"{path}/world_time is invalid")
        if world_time is not None and previous_world_time is not None:
            add_error(errors, world_time >= previous_world_time, f"legacy world time moved backward at {event_id}")
        if world_time is not None:
            previous_world_time = world_time
        created_at = parse_real_timestamp(event.get("created_at"))
        add_error(errors, created_at is not None, f"{path}/created_at is invalid")
        if created_at is not None and previous_created_at is not None:
            add_error(errors, created_at >= previous_created_at, f"legacy real time moved backward at {event_id}")
        if created_at is not None:
            previous_created_at = created_at
    return errors


def validate_legacy_consistency(state: Dict[str, Any], events: List[Dict[str, Any]], version: str) -> List[str]:
    errors = validate_legacy_state(state, version)
    errors.extend(validate_legacy_event_sequence(events))
    if events:
        runtime = state.get("runtime", {})
        campaign = state.get("campaign", {})
        last = events[-1]
        add_error(errors, runtime.get("last_event_id") == last.get("event_id"), "legacy state last_event_id does not match final event")
        add_error(errors, runtime.get("state_revision") == last.get("state_revision"), "legacy state_revision does not match final event")
        add_error(errors, campaign.get("world_time") == last.get("world_time"), "legacy campaign world_time does not match final event")
    return errors


def valid_string_list(value: Any, *, minimum: int = 0) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def valid_event_id_list(value: Any, *, minimum: int = 1) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= minimum
        and len(value) == len(set(value))
        and all(valid_event_id(item) for item in value)
    )


def unique_named_ids(items: Any, field: str) -> bool:
    if not isinstance(items, list):
        return False
    values = [item.get(field) for item in items if isinstance(item, dict)]
    return len(values) == len(items) and len(values) == len(set(values))


def money_to_pence(money: Any) -> Optional[int]:
    if not isinstance(money, dict):
        return None
    pounds, soli, pence = money.get("pounds"), money.get("soli"), money.get("pence")
    if not all(isinstance(item, int) and not isinstance(item, bool) for item in (pounds, soli, pence)):
        return None
    return pounds * 240 + soli * 12 + pence


def validate_state(state: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(state, dict):
        return ["state must be an object"]
    version = state_contract_version(state)
    if version in LEGACY_READ_ONLY_VERSIONS:
        return validate_legacy_state(state, version)
    base_state_keys = {"runtime", "campaign", "player", "relations", "plot", "causality", "world", "knowledge", "discipline", "visuals", "roll_log"}
    state_keys = base_state_keys | (V17_STATE_KEYS if version == "1.7" else set())
    for key in state_keys:
        add_error(errors, key in state, f"missing state key: {key}")
    add_error(errors, set(state).issubset(state_keys), "state contains an unsupported top-level key")

    runtime = mapping_at(state, "runtime", errors, "")
    require_fields(runtime, ("schema_version", "state_revision", "last_event_id", "updated_at", "ruleset_version", "panel_renderer", "panel_template_version", "rng"), "/runtime", errors)
    add_error(errors, version in WRITABLE_VERSIONS, "runtime/schema_version must be a supported writable version")
    add_error(errors, runtime.get("ruleset_version") == version, "runtime/ruleset_version must match schema_version")
    revision = runtime.get("state_revision")
    add_error(errors, isinstance(revision, int) and revision >= 1, "runtime/state_revision must be a positive integer")
    add_error(errors, valid_event_id(runtime.get("last_event_id")), "runtime/last_event_id is invalid")
    add_error(errors, parse_real_timestamp(runtime.get("updated_at")) is not None, "runtime/updated_at must be an ISO-8601 timestamp with timezone")
    add_error(errors, enum_value(runtime.get("panel_renderer"), {"html_snapshot", "svg_snapshot", "platform_rich_text", "text"}), "runtime/panel_renderer is invalid")
    add_error(errors, isinstance(runtime.get("panel_template_version"), str) and bool(runtime.get("panel_template_version", "").strip()), "runtime/panel_template_version is required")
    rng = runtime.get("rng")
    add_error(errors, isinstance(rng, dict), "runtime/rng must be an object")
    if isinstance(rng, dict):
        require_fields(rng, ("method", "next_counter", "seed_commitment"), "/runtime/rng", errors)
        add_error(errors, enum_value(rng.get("method"), RNG_METHODS), "runtime/rng/method is invalid")
        add_error(errors, isinstance(rng.get("next_counter"), int) and rng.get("next_counter", -1) >= 0, "runtime/rng/next_counter must be non-negative")
        commitment = rng.get("seed_commitment")
        if rng.get("method") == "hmac_sha256_rejection_v1":
            add_error(errors, valid_commitment(commitment), "HMAC RNG requires a 64-character seed commitment")
        else:
            add_error(errors, commitment is None, "non-HMAC RNG must not store a seed commitment")
            add_error(errors, rng.get("next_counter") == 0, "non-HMAC RNG next_counter must remain 0")

    campaign = mapping_at(state, "campaign", errors, "")
    campaign_fields = ["id", "status", "turn", "world_time", "location", "difficulty", "mode_modifier", "opportunity_counter", "pacing_profile", "chapter", "meaningful_scenes"]
    if version == "1.7":
        campaign_fields.append("play_mode")
    require_fields(campaign, campaign_fields, "/campaign", errors)
    campaign_id = campaign.get("id")
    add_error(errors, isinstance(campaign_id, str) and bool(CAMPAIGN_ID.fullmatch(campaign_id)), "campaign/id is invalid")
    add_error(errors, enum_value(campaign.get("status"), {"active", "paused", "completed"}), "campaign/status is invalid")
    add_error(errors, isinstance(campaign.get("turn"), int) and campaign.get("turn", -1) >= 0, "campaign/turn must be non-negative")
    add_error(errors, parse_world_time(campaign.get("world_time")) is not None, "campaign/world_time must use YYYY-MM-DD HH:MM[:SS]")
    add_error(errors, isinstance(campaign.get("location"), str) and bool(campaign.get("location", "").strip()), "campaign/location is required")
    difficulty = campaign.get("difficulty")
    add_error(errors, enum_value(difficulty, DIFFICULTY_MODIFIERS), "campaign/difficulty is invalid")
    if enum_value(difficulty, DIFFICULTY_MODIFIERS):
        add_error(errors, campaign.get("mode_modifier") == DIFFICULTY_MODIFIERS[difficulty], "campaign/mode_modifier does not match difficulty")
    add_error(errors, enum_value(campaign.get("pacing_profile"), {"紧凑", "标准", "长篇"}), "campaign/pacing_profile is invalid")
    add_error(errors, isinstance(campaign.get("opportunity_counter"), int) and campaign.get("opportunity_counter", -1) >= 0, "campaign/opportunity_counter must be non-negative")
    add_error(errors, isinstance(campaign.get("chapter"), int) and campaign.get("chapter", 0) >= 1, "campaign/chapter must be positive")
    add_error(errors, isinstance(campaign.get("meaningful_scenes"), int) and campaign.get("meaningful_scenes", -1) >= 0, "campaign/meaningful_scenes must be non-negative")
    if version == "1.7":
        add_error(errors, campaign.get("play_mode") == "single_protagonist", "campaign/play_mode must be single_protagonist")

    player = mapping_at(state, "player", errors, "")
    require_fields(player, ("name", "gender", "background", "identity", "pathway", "sequence", "acting", "attributes", "luck", "spirituality", "sanity", "pollution", "states", "skills", "money", "inventory", "sealed_items"), "/player", errors)
    for field in ("name", "gender", "background", "identity", "pathway", "sequence", "acting"):
        add_error(errors, isinstance(player.get(field), str) and bool(player.get(field).strip()), f"player/{field} must be a non-empty string")
    attributes = mapping_at(player, "attributes", errors, "/player")
    for field in ("physique", "inspiration", "mind", "charm"):
        add_error(errors, isinstance(attributes.get(field), int) and attributes.get(field, -1) >= 0, f"player/attributes/{field} must be non-negative")
    luck = mapping_at(player, "luck", errors, "/player")
    require_fields(luck, ("base", "current", "modifiers"), "/player/luck", errors)
    for field in ("base", "current"):
        add_error(errors, isinstance(luck.get(field), int) and 0 <= luck.get(field, -1) <= 100, f"player/luck/{field} must be from 0 to 100")
    add_error(errors, isinstance(luck.get("modifiers"), list), "player/luck/modifiers must be an array")
    spirituality = mapping_at(player, "spirituality", errors, "/player")
    require_fields(spirituality, ("current", "max"), "/player/spirituality", errors)
    current_spirit = spirituality.get("current")
    max_spirit = spirituality.get("max")
    add_error(errors, isinstance(max_spirit, int) and max_spirit >= 1, "player/spirituality/max must be positive")
    add_error(errors, isinstance(current_spirit, int) and isinstance(max_spirit, int) and 0 <= current_spirit <= max_spirit, "player/spirituality/current must be between 0 and max")
    for field in ("sanity", "pollution"):
        add_error(errors, isinstance(player.get(field), int) and 0 <= player.get(field, -1) <= 100, f"player/{field} must be from 0 to 100")
    states = mapping_at(player, "states", errors, "/player")
    require_fields(states, ("body", "mind", "effects"), "/player/states", errors)
    add_error(errors, enum_value(states.get("body"), BODY_STATES), "player/states/body is invalid")
    add_error(errors, enum_value(states.get("mind"), MIND_STATES), "player/states/mind is invalid")
    add_error(errors, isinstance(states.get("effects"), list), "player/states/effects must be an array")
    money = mapping_at(player, "money", errors, "/player")
    require_fields(money, ("pounds", "soli", "pence"), "/player/money", errors)
    pounds, soli, pence = money.get("pounds"), money.get("soli"), money.get("pence")
    add_error(errors, isinstance(pounds, int) and pounds >= 0, "player/money/pounds must be non-negative")
    add_error(errors, isinstance(soli, int) and 0 <= soli < 20, "player/money/soli must be normalized to 0..19")
    add_error(errors, isinstance(pence, int) and 0 <= pence < 12, "player/money/pence must be normalized to 0..11")
    add_error(errors, isinstance(player.get("skills"), dict), "player/skills must be an object")
    add_error(errors, isinstance(player.get("inventory"), list), "player/inventory must be an array")
    add_error(errors, isinstance(player.get("sealed_items"), list), "player/sealed_items must be an array")

    relations = state.get("relations")
    add_error(errors, isinstance(relations, list), "relations must be an array")
    if isinstance(relations, list):
        for index, relation in enumerate(relations):
            if not isinstance(relation, dict):
                errors.append(f"relations/{index} must be an object")
                continue
            add_error(errors, isinstance(relation.get("npc"), str) and bool(relation.get("npc", "").strip()), f"relations/{index}/npc is required")
            add_error(errors, enum_value(relation.get("level"), RELATION_LEVELS), f"relations/{index}/level is invalid")
            add_error(errors, isinstance(relation.get("evidence"), str) and bool(relation.get("evidence", "").strip()), f"relations/{index}/evidence is required")
            add_error(errors, isinstance(relation.get("last_interaction"), str) and bool(relation.get("last_interaction", "").strip()), f"relations/{index}/last_interaction is required")

    if version == "1.7":
        social = mapping_at(state, "social", errors, "")
        require_fields(social, ("statuses", "organizations"), "/social", errors)
        statuses = social.get("statuses")
        organizations = social.get("organizations")
        add_error(errors, isinstance(statuses, list), "social/statuses must be an array")
        add_error(errors, unique_named_ids(statuses, "status_id"), "social status ids must be unique")
        if isinstance(statuses, list):
            for index, status in enumerate(statuses):
                if not isinstance(status, dict):
                    errors.append(f"social/statuses/{index} must be an object")
                    continue
                require_fields(status, ("status_id", "context", "label", "standing", "evidence_event_ids"), f"/social/statuses/{index}", errors)
                add_error(errors, valid_named_id(status.get("status_id"), "status-"), f"social/statuses/{index}/status_id is invalid")
                for field in ("context", "label"):
                    add_error(errors, isinstance(status.get(field), str) and bool(status.get(field, "").strip()), f"social/statuses/{index}/{field} is required")
                add_error(errors, isinstance(status.get("standing"), int) and -100 <= status.get("standing", -101) <= 100, f"social/statuses/{index}/standing must be from -100 to 100")
                add_error(errors, valid_event_id_list(status.get("evidence_event_ids")), f"social/statuses/{index}/evidence_event_ids is invalid")
        add_error(errors, isinstance(organizations, list), "social/organizations must be an array")
        add_error(errors, unique_named_ids(organizations, "organization_id"), "organization ids must be unique")
        if isinstance(organizations, list):
            for index, organization in enumerate(organizations):
                if not isinstance(organization, dict):
                    errors.append(f"social/organizations/{index} must be an object")
                    continue
                require_fields(
                    organization,
                    ("organization_id", "name", "membership_status", "rank", "title", "reputation", "heat", "permissions", "commitment_ids", "evidence_event_ids", "last_changed_event_id"),
                    f"/social/organizations/{index}",
                    errors,
                )
                add_error(errors, valid_named_id(organization.get("organization_id"), "org-"), f"social/organizations/{index}/organization_id is invalid")
                add_error(errors, isinstance(organization.get("name"), str) and bool(organization.get("name", "").strip()), f"social/organizations/{index}/name is required")
                add_error(errors, enum_value(organization.get("membership_status"), MEMBERSHIP_STATUSES), f"social/organizations/{index}/membership_status is invalid")
                add_error(errors, organization.get("rank") is None or (isinstance(organization.get("rank"), int) and organization.get("rank", -1) >= 0), f"social/organizations/{index}/rank is invalid")
                add_error(errors, organization.get("title") is None or isinstance(organization.get("title"), str), f"social/organizations/{index}/title is invalid")
                add_error(errors, isinstance(organization.get("reputation"), int) and -100 <= organization.get("reputation", -101) <= 100, f"social/organizations/{index}/reputation must be from -100 to 100")
                add_error(errors, isinstance(organization.get("heat"), int) and 0 <= organization.get("heat", -1) <= 100, f"social/organizations/{index}/heat must be from 0 to 100")
                add_error(errors, valid_string_list(organization.get("permissions")), f"social/organizations/{index}/permissions must be a string array")
                commitment_ids = organization.get("commitment_ids")
                valid_commitment_ids = isinstance(commitment_ids, list) and len(commitment_ids) == len(set(commitment_ids)) and all(valid_named_id(item, "commitment-") for item in commitment_ids)
                add_error(errors, valid_commitment_ids, f"social/organizations/{index}/commitment_ids is invalid")
                add_error(errors, valid_event_id_list(organization.get("evidence_event_ids")), f"social/organizations/{index}/evidence_event_ids is invalid")
                add_error(errors, valid_event_id(organization.get("last_changed_event_id")), f"social/organizations/{index}/last_changed_event_id is invalid")

        economy = mapping_at(state, "economy", errors, "")
        require_fields(economy, ("accounting_unit", "settlement_period", "next_settlement_at", "last_settlement_event_id", "income_streams", "recurring_costs", "debts", "scarcity"), "/economy", errors)
        add_error(errors, economy.get("accounting_unit") == "pence", "economy/accounting_unit must be pence")
        add_error(errors, enum_value(economy.get("settlement_period"), {"world_turn", "weekly"}), "economy/settlement_period is invalid")
        next_settlement = economy.get("next_settlement_at")
        add_error(errors, next_settlement is None or parse_world_time(next_settlement) is not None, "economy/next_settlement_at must be null or world time")
        add_error(errors, economy.get("last_settlement_event_id") is None or valid_event_id(economy.get("last_settlement_event_id")), "economy/last_settlement_event_id is invalid")
        flow_ids: List[str] = []
        for collection_name in ("income_streams", "recurring_costs"):
            flows = economy.get(collection_name)
            add_error(errors, isinstance(flows, list), f"economy/{collection_name} must be an array")
            if not isinstance(flows, list):
                continue
            for index, flow in enumerate(flows):
                if not isinstance(flow, dict):
                    errors.append(f"economy/{collection_name}/{index} must be an object")
                    continue
                require_fields(flow, ("flow_id", "name", "amount_pence", "cadence", "next_due_at", "status", "evidence_event_id"), f"/economy/{collection_name}/{index}", errors)
                flow_id = flow.get("flow_id")
                add_error(errors, valid_named_id(flow_id, "flow-"), f"economy/{collection_name}/{index}/flow_id is invalid")
                if isinstance(flow_id, str):
                    flow_ids.append(flow_id)
                add_error(errors, isinstance(flow.get("name"), str) and bool(flow.get("name", "").strip()), f"economy/{collection_name}/{index}/name is required")
                add_error(errors, isinstance(flow.get("amount_pence"), int) and flow.get("amount_pence", -1) >= 0, f"economy/{collection_name}/{index}/amount_pence must be non-negative")
                add_error(errors, enum_value(flow.get("cadence"), {"one_time", "world_turn", "weekly", "monthly"}), f"economy/{collection_name}/{index}/cadence is invalid")
                add_error(errors, flow.get("next_due_at") is None or parse_world_time(flow.get("next_due_at")) is not None, f"economy/{collection_name}/{index}/next_due_at is invalid")
                add_error(errors, enum_value(flow.get("status"), {"active", "paused", "ended"}), f"economy/{collection_name}/{index}/status is invalid")
                add_error(errors, valid_event_id(flow.get("evidence_event_id")), f"economy/{collection_name}/{index}/evidence_event_id is invalid")
        add_error(errors, len(flow_ids) == len(set(flow_ids)), "economy flow ids must be unique")
        debts = economy.get("debts")
        add_error(errors, isinstance(debts, list), "economy/debts must be an array")
        add_error(errors, unique_named_ids(debts, "debt_id"), "economy debt ids must be unique")
        if isinstance(debts, list):
            for index, debt in enumerate(debts):
                if not isinstance(debt, dict):
                    errors.append(f"economy/debts/{index} must be an object")
                    continue
                require_fields(debt, ("debt_id", "creditor", "principal_pence", "due_at", "status", "commitment_id", "evidence_event_ids"), f"/economy/debts/{index}", errors)
                add_error(errors, valid_named_id(debt.get("debt_id"), "debt-"), f"economy/debts/{index}/debt_id is invalid")
                add_error(errors, isinstance(debt.get("creditor"), str) and bool(debt.get("creditor", "").strip()), f"economy/debts/{index}/creditor is required")
                add_error(errors, isinstance(debt.get("principal_pence"), int) and debt.get("principal_pence", -1) >= 0, f"economy/debts/{index}/principal_pence must be non-negative")
                add_error(errors, debt.get("due_at") is None or parse_world_time(debt.get("due_at")) is not None, f"economy/debts/{index}/due_at is invalid")
                add_error(errors, enum_value(debt.get("status"), {"current", "overdue", "settled", "defaulted", "forgiven"}), f"economy/debts/{index}/status is invalid")
                add_error(errors, debt.get("commitment_id") is None or valid_named_id(debt.get("commitment_id"), "commitment-"), f"economy/debts/{index}/commitment_id is invalid")
                add_error(errors, valid_event_id_list(debt.get("evidence_event_ids")), f"economy/debts/{index}/evidence_event_ids is invalid")
        scarcity = economy.get("scarcity")
        add_error(errors, isinstance(scarcity, list), "economy/scarcity must be an array")
        if isinstance(scarcity, list):
            categories: List[str] = []
            for index, item in enumerate(scarcity):
                if not isinstance(item, dict):
                    errors.append(f"economy/scarcity/{index} must be an object")
                    continue
                require_fields(item, ("category", "level", "reason", "evidence_event_id"), f"/economy/scarcity/{index}", errors)
                category = item.get("category")
                add_error(errors, isinstance(category, str) and bool(category.strip()), f"economy/scarcity/{index}/category is required")
                if isinstance(category, str):
                    categories.append(category)
                add_error(errors, enum_value(item.get("level"), {"normal", "tight", "scarce", "unavailable"}), f"economy/scarcity/{index}/level is invalid")
                add_error(errors, isinstance(item.get("reason"), str) and bool(item.get("reason", "").strip()), f"economy/scarcity/{index}/reason is required")
                add_error(errors, valid_event_id(item.get("evidence_event_id")), f"economy/scarcity/{index}/evidence_event_id is invalid")
            add_error(errors, len(categories) == len(set(categories)), "economy scarcity categories must be unique")

        commitments = state.get("commitments")
        add_error(errors, isinstance(commitments, list), "commitments must be an array")
        add_error(errors, unique_named_ids(commitments, "commitment_id"), "commitment ids must be unique")
        if isinstance(commitments, list):
            for index, commitment in enumerate(commitments):
                if not isinstance(commitment, dict):
                    errors.append(f"commitments/{index} must be an object")
                    continue
                require_fields(commitment, ("commitment_id", "kind", "summary", "parties", "owed_by", "owed_to", "terms", "status", "due_at", "linked_organization_id", "evidence_event_ids", "breach_event_id"), f"/commitments/{index}", errors)
                add_error(errors, valid_named_id(commitment.get("commitment_id"), "commitment-"), f"commitments/{index}/commitment_id is invalid")
                add_error(errors, enum_value(commitment.get("kind"), COMMITMENT_KINDS), f"commitments/{index}/kind is invalid")
                add_error(errors, isinstance(commitment.get("summary"), str) and bool(commitment.get("summary", "").strip()), f"commitments/{index}/summary is required")
                parties = commitment.get("parties")
                add_error(errors, valid_string_list(parties, minimum=2) and len(parties) == len(set(parties)), f"commitments/{index}/parties requires at least two unique parties")
                for field in ("owed_by", "owed_to"):
                    add_error(errors, isinstance(commitment.get(field), str) and bool(commitment.get(field, "").strip()), f"commitments/{index}/{field} is required")
                if isinstance(parties, list):
                    add_error(errors, commitment.get("owed_by") in parties, f"commitments/{index}/owed_by must be a party")
                    add_error(errors, commitment.get("owed_to") in parties, f"commitments/{index}/owed_to must be a party")
                    add_error(errors, commitment.get("owed_by") != commitment.get("owed_to"), f"commitments/{index} cannot be owed to the same party")
                add_error(errors, valid_string_list(commitment.get("terms"), minimum=1), f"commitments/{index}/terms is invalid")
                add_error(errors, enum_value(commitment.get("status"), COMMITMENT_STATUSES), f"commitments/{index}/status is invalid")
                add_error(errors, commitment.get("due_at") is None or parse_world_time(commitment.get("due_at")) is not None, f"commitments/{index}/due_at is invalid")
                add_error(errors, commitment.get("linked_organization_id") is None or valid_named_id(commitment.get("linked_organization_id"), "org-"), f"commitments/{index}/linked_organization_id is invalid")
                add_error(errors, valid_event_id_list(commitment.get("evidence_event_ids")), f"commitments/{index}/evidence_event_ids is invalid")
                add_error(errors, commitment.get("breach_event_id") is None or valid_event_id(commitment.get("breach_event_id")), f"commitments/{index}/breach_event_id is invalid")
                if commitment.get("status") == "breached":
                    add_error(errors, valid_event_id(commitment.get("breach_event_id")), f"breached commitment {commitment.get('commitment_id')} requires breach_event_id")

        preferences = mapping_at(state, "preferences", errors, "")
        require_fields(preferences, ("horror", "gore", "romance", "canon_spoilers", "hard_limits", "updated_at_event_id"), "/preferences", errors)
        add_error(errors, enum_value(preferences.get("horror"), {"low", "standard", "high"}), "preferences/horror is invalid")
        add_error(errors, enum_value(preferences.get("gore"), {"off", "restrained", "explicit"}), "preferences/gore is invalid")
        add_error(errors, enum_value(preferences.get("romance"), {"off", "ask", "enabled"}), "preferences/romance is invalid")
        add_error(errors, enum_value(preferences.get("canon_spoilers"), {"character_only", "player_confirmed_scope", "full_meta"}), "preferences/canon_spoilers is invalid")
        hard_limits = preferences.get("hard_limits")
        add_error(errors, valid_string_list(hard_limits) and len(hard_limits) == len(set(hard_limits)), "preferences/hard_limits must be unique strings")
        add_error(errors, valid_event_id(preferences.get("updated_at_event_id")), "preferences/updated_at_event_id is invalid")

    plot = mapping_at(state, "plot", errors, "")
    plot_fields = ["life_goal", "completed_goals", "main", "current_action", "open_threads", "clues", "investigations", "deadlines"]
    if version == "1.7":
        plot_fields.extend(("chapter", "chapter_history"))
    require_fields(plot, plot_fields, "/plot", errors)
    add_error(errors, isinstance(plot.get("completed_goals"), list), "plot/completed_goals must be an array")
    add_error(errors, isinstance(plot.get("main"), str), "plot/main must be a string")
    add_error(errors, isinstance(plot.get("current_action"), str), "plot/current_action must be a string")
    add_error(errors, isinstance(plot.get("open_threads"), list) and all(isinstance(item, str) and bool(item.strip()) for item in plot.get("open_threads", [])), "plot/open_threads must be a string array")
    add_error(errors, isinstance(plot.get("deadlines"), list), "plot/deadlines must be an array")
    goal = mapping_at(plot, "life_goal", errors, "/plot")
    require_fields(goal, ("id", "text", "category", "status", "success_conditions", "progress_summary", "change_conditions", "chosen_at_event_id", "criteria_met_at_event_id"), "/plot/life_goal", errors)
    add_error(errors, goal.get("id") is None or valid_named_id(goal.get("id"), "goal-"), "plot/life_goal/id is invalid")
    add_error(errors, goal.get("text") is None or isinstance(goal.get("text"), str), "plot/life_goal/text must be a string or null")
    add_error(errors, goal.get("category") is None or isinstance(goal.get("category"), str), "plot/life_goal/category must be a string or null")
    add_error(errors, goal.get("progress_summary") is None or isinstance(goal.get("progress_summary"), str), "plot/life_goal/progress_summary must be a string or null")
    add_error(errors, goal.get("chosen_at_event_id") is None or valid_event_id(goal.get("chosen_at_event_id")), "plot/life_goal/chosen_at_event_id is invalid")
    add_error(errors, goal.get("criteria_met_at_event_id") is None or valid_event_id(goal.get("criteria_met_at_event_id")), "plot/life_goal/criteria_met_at_event_id is invalid")
    goal_status = goal.get("status")
    add_error(errors, enum_value(goal_status, GOAL_STATUSES), "plot/life_goal/status is invalid")
    conditions = goal.get("success_conditions")
    add_error(errors, isinstance(conditions, list) and len(conditions) <= 3, "plot/life_goal/success_conditions must have at most 3 items")
    condition_ids: List[str] = []
    if isinstance(conditions, list):
        for index, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                errors.append(f"plot/life_goal/success_conditions/{index} must be an object")
                continue
            condition_id = condition.get("id")
            add_error(errors, valid_named_id(condition_id, "condition-"), f"goal condition {index} has invalid id")
            if isinstance(condition_id, str):
                condition_ids.append(condition_id)
            add_error(errors, isinstance(condition.get("description"), str) and bool(condition.get("description", "").strip()), f"goal condition {index} requires a description")
            add_error(errors, enum_value(condition.get("status"), {"open", "met", "waived"}), f"goal condition {index} has invalid status")
            add_error(errors, isinstance(condition.get("required"), bool), f"goal condition {index} requires boolean required")
            add_error(errors, isinstance(condition.get("evidence_event_ids"), list), f"goal condition {index} evidence_event_ids must be an array")
            evidence_ids = condition.get("evidence_event_ids")
            if isinstance(evidence_ids, list):
                valid_evidence_ids = all(valid_event_id(item) for item in evidence_ids)
                add_error(errors, valid_evidence_ids, f"goal condition {index} has an invalid evidence event id")
                if valid_evidence_ids:
                    add_error(errors, len(evidence_ids) == len(set(evidence_ids)), f"goal condition {index} repeats evidence")
                if condition.get("status") == "met":
                    add_error(errors, bool(evidence_ids), f"met goal condition {index} requires event evidence")
        add_error(errors, len(condition_ids) == len(set(condition_ids)), "goal condition ids must be unique")
    if enum_value(goal_status, {"active", "criteria_met", "achieved"}):
        add_error(errors, valid_named_id(goal.get("id"), "goal-"), "active goal requires a valid id")
        add_error(errors, isinstance(goal.get("text"), str) and bool(goal.get("text", "").strip()), "active goal requires text")
        add_error(errors, isinstance(conditions, list) and 1 <= len(conditions) <= 3, "active goal requires 1..3 success conditions")
        add_error(errors, valid_event_id(goal.get("chosen_at_event_id")), "active goal requires chosen_at_event_id")
    if enum_value(goal_status, {"criteria_met", "achieved"}) and isinstance(conditions, list):
        unmet = [item for item in conditions if isinstance(item, dict) and item.get("required") and (item.get("status") != "met" or not item.get("evidence_event_ids"))]
        add_error(errors, not unmet, "criteria_met goal has unmet required conditions")
        add_error(errors, valid_event_id(goal.get("criteria_met_at_event_id")), "criteria_met goal requires criteria_met_at_event_id")
    add_error(errors, isinstance(goal.get("change_conditions"), list), "plot/life_goal/change_conditions must be an array")

    clues = plot.get("clues")
    investigations = plot.get("investigations")
    add_error(errors, isinstance(clues, list), "plot/clues must be an array")
    add_error(errors, isinstance(investigations, list), "plot/investigations must be an array")
    clue_ids: List[str] = []
    if isinstance(clues, list):
        for index, clue in enumerate(clues):
            if not isinstance(clue, dict):
                errors.append(f"plot/clues/{index} must be an object")
                continue
            require_fields(clue, ("clue_id", "statement", "source", "confidence", "status", "discovered_event_id", "linked_investigation_ids", "corroborating_clue_ids", "verification_basis"), f"/plot/clues/{index}", errors)
            clue_id = clue.get("clue_id")
            add_error(errors, valid_named_id(clue_id, "clue-"), f"plot/clues/{index}/clue_id is invalid")
            if isinstance(clue_id, str):
                clue_ids.append(clue_id)
            add_error(errors, isinstance(clue.get("statement"), str) and bool(clue.get("statement", "").strip()), f"plot/clues/{index}/statement is required")
            add_error(errors, isinstance(clue.get("source"), str) and bool(clue.get("source", "").strip()), f"plot/clues/{index}/source is required")
            add_error(errors, enum_value(clue.get("confidence"), CLUE_CONFIDENCE), f"plot/clues/{index}/confidence is invalid")
            add_error(errors, enum_value(clue.get("status"), {"open", "linked", "resolved", "disproved"}), f"plot/clues/{index}/status is invalid")
            add_error(errors, valid_event_id(clue.get("discovered_event_id")), f"plot/clues/{index}/discovered_event_id is invalid")
            linked_investigations = clue.get("linked_investigation_ids")
            corroborating_clues = clue.get("corroborating_clue_ids")
            add_error(errors, isinstance(linked_investigations, list) and all(isinstance(item, str) for item in linked_investigations), f"plot/clues/{index}/linked_investigation_ids must be a string array")
            add_error(errors, isinstance(corroborating_clues, list) and all(isinstance(item, str) for item in corroborating_clues), f"plot/clues/{index}/corroborating_clue_ids must be a string array")
            if clue.get("confidence") == "证实":
                add_error(errors, isinstance(clue.get("verification_basis"), str) and bool(clue.get("verification_basis", "").strip()), f"confirmed clue {clue_id} requires verification_basis")
        add_error(errors, len(clue_ids) == len(set(clue_ids)), "clue ids must be unique")
    investigation_ids: List[str] = []
    if isinstance(investigations, list):
        for index, investigation in enumerate(investigations):
            if not isinstance(investigation, dict):
                errors.append(f"plot/investigations/{index} must be an object")
                continue
            require_fields(investigation, ("investigation_id", "question", "status", "clue_ids", "available_route_ids", "current_conclusion"), f"/plot/investigations/{index}", errors)
            investigation_id = investigation.get("investigation_id")
            add_error(errors, valid_named_id(investigation_id, "investigation-"), f"plot/investigations/{index}/investigation_id is invalid")
            if isinstance(investigation_id, str):
                investigation_ids.append(investigation_id)
            add_error(errors, isinstance(investigation.get("question"), str) and bool(investigation.get("question", "").strip()), f"plot/investigations/{index}/question is required")
            add_error(errors, enum_value(investigation.get("status"), {"open", "provisional", "resolved", "abandoned"}), f"plot/investigations/{index}/status is invalid")
            routes = investigation.get("available_route_ids")
            valid_routes = isinstance(routes, list) and all(isinstance(item, str) and bool(item.strip()) for item in routes)
            add_error(errors, valid_routes, f"plot/investigations/{index}/available_route_ids must be a string array")
            if valid_routes:
                add_error(errors, len(set(routes)) >= 2, f"plot/investigations/{index} needs at least two independent routes")
            linked_clues = investigation.get("clue_ids")
            add_error(errors, isinstance(linked_clues, list), f"plot/investigations/{index}/clue_ids must be an array")
            if isinstance(linked_clues, list):
                add_error(errors, all(item in clue_ids for item in linked_clues), f"plot/investigations/{index} references an unknown clue")
            add_error(errors, investigation.get("current_conclusion") is None or isinstance(investigation.get("current_conclusion"), str), f"plot/investigations/{index}/current_conclusion must be a string or null")
        add_error(errors, len(investigation_ids) == len(set(investigation_ids)), "investigation ids must be unique")
    if isinstance(clues, list) and isinstance(investigations, list):
        known_clues = set(clue_ids)
        known_investigations = set(investigation_ids)
        for clue in clues:
            if not isinstance(clue, dict):
                continue
            clue_id = clue.get("clue_id")
            linked = clue.get("linked_investigation_ids", [])
            corroborating = clue.get("corroborating_clue_ids", [])
            if isinstance(linked, list) and all(isinstance(item, str) for item in linked):
                add_error(errors, all(item in known_investigations for item in linked), f"clue {clue_id} references an unknown investigation")
            if isinstance(corroborating, list) and all(isinstance(item, str) for item in corroborating):
                add_error(errors, all(item in known_clues and item != clue_id for item in corroborating), f"clue {clue_id} has an invalid corroborating clue")

    if version == "1.7":
        chapter = mapping_at(plot, "chapter", errors, "/plot")
        require_fields(chapter, ("chapter_id", "number", "title", "status", "core_question", "pressure_source", "opened_at_event_id", "meaningful_scene_start"), "/plot/chapter", errors)
        chapter_number = chapter.get("number")
        add_error(errors, isinstance(chapter.get("chapter_id"), str) and bool(re.fullmatch(r"chapter-[0-9]{3,}", chapter.get("chapter_id", ""))), "plot/chapter/chapter_id is invalid")
        add_error(errors, isinstance(chapter_number, int) and chapter_number >= 1, "plot/chapter/number must be positive")
        add_error(errors, chapter_number == campaign.get("chapter"), "plot/chapter/number must match campaign/chapter")
        add_error(errors, chapter.get("title") is None or isinstance(chapter.get("title"), str), "plot/chapter/title is invalid")
        add_error(errors, enum_value(chapter.get("status"), {"setup", "active"}), "plot/chapter/status is invalid")
        add_error(errors, chapter.get("core_question") is None or (isinstance(chapter.get("core_question"), str) and bool(chapter.get("core_question", "").strip())), "plot/chapter/core_question is invalid")
        add_error(errors, chapter.get("pressure_source") is None or (isinstance(chapter.get("pressure_source"), str) and bool(chapter.get("pressure_source", "").strip())), "plot/chapter/pressure_source is invalid")
        add_error(errors, valid_event_id(chapter.get("opened_at_event_id")), "plot/chapter/opened_at_event_id is invalid")
        scene_start = chapter.get("meaningful_scene_start")
        add_error(errors, isinstance(scene_start, int) and 0 <= scene_start <= campaign.get("meaningful_scenes", -1), "plot/chapter/meaningful_scene_start is invalid")
        if chapter.get("status") == "active" or campaign.get("meaningful_scenes", 0) > 0:
            add_error(errors, isinstance(chapter.get("core_question"), str) and bool(chapter.get("core_question", "").strip()), "active chapter requires a core question")
            add_error(errors, isinstance(chapter.get("pressure_source"), str) and bool(chapter.get("pressure_source", "").strip()), "active chapter requires a pressure source")
        history = plot.get("chapter_history")
        add_error(errors, isinstance(history, list), "plot/chapter_history must be an array")
        add_error(errors, unique_named_ids(history, "chapter_id"), "chapter history ids must be unique")
        if isinstance(history, list):
            history_numbers: List[int] = []
            for index, entry in enumerate(history):
                if not isinstance(entry, dict):
                    errors.append(f"plot/chapter_history/{index} must be an object")
                    continue
                require_fields(entry, ("chapter_id", "number", "title", "core_question", "resolution", "pressure_source", "irreversible_changes", "opened_at_event_id", "closed_at_event_id", "meaningful_scene_end", "updated_domains"), f"/plot/chapter_history/{index}", errors)
                add_error(errors, isinstance(entry.get("chapter_id"), str) and bool(re.fullmatch(r"chapter-[0-9]{3,}", entry.get("chapter_id", ""))), f"plot/chapter_history/{index}/chapter_id is invalid")
                number = entry.get("number")
                add_error(errors, isinstance(number, int) and number >= 1, f"plot/chapter_history/{index}/number is invalid")
                if isinstance(number, int):
                    history_numbers.append(number)
                for field in ("core_question", "resolution", "pressure_source"):
                    add_error(errors, isinstance(entry.get(field), str) and bool(entry.get(field, "").strip()), f"plot/chapter_history/{index}/{field} is required")
                add_error(errors, valid_string_list(entry.get("irreversible_changes"), minimum=1), f"plot/chapter_history/{index}/irreversible_changes is required")
                add_error(errors, valid_event_id(entry.get("opened_at_event_id")), f"plot/chapter_history/{index}/opened_at_event_id is invalid")
                add_error(errors, valid_event_id(entry.get("closed_at_event_id")), f"plot/chapter_history/{index}/closed_at_event_id is invalid")
                add_error(errors, isinstance(entry.get("meaningful_scene_end"), int) and entry.get("meaningful_scene_end", 0) >= 1, f"plot/chapter_history/{index}/meaningful_scene_end is invalid")
                domains = entry.get("updated_domains")
                add_error(errors, isinstance(domains, list) and bool(domains) and len(domains) == len(set(domains)) and all(item in CHAPTER_DOMAINS for item in domains), f"plot/chapter_history/{index}/updated_domains is invalid")
            if history_numbers:
                add_error(errors, history_numbers == list(range(1, len(history_numbers) + 1)), "chapter history numbers must be contiguous from 1")
                add_error(errors, history_numbers[-1] + 1 == campaign.get("chapter"), "current chapter must follow chapter history")

    world = state.get("world")
    add_error(errors, isinstance(world, dict), "world must be an object")
    if isinstance(world, dict):
        clocks = world.get("faction_clocks", [])
        add_error(errors, isinstance(clocks, list), "world/faction_clocks must be an array")
        if isinstance(clocks, list):
            for index, clock in enumerate(clocks):
                if not isinstance(clock, dict):
                    errors.append(f"world/faction_clocks/{index} must be an object")
                    continue
                current, maximum = clock.get("current"), clock.get("max")
                add_error(errors, isinstance(current, int) and isinstance(maximum, int) and maximum > 0 and 0 <= current <= maximum, f"world/faction_clocks/{index} is out of range")

    causality = state.get("causality")
    add_error(errors, isinstance(causality, list), "causality must be an array")
    if isinstance(causality, list):
        anchors = [item.get("anchor") for item in causality if isinstance(item, dict)]
        add_error(errors, len(anchors) == len(set(anchors)), "causality anchors must be unique")

    discipline = mapping_at(state, "discipline", errors, "")
    require_fields(discipline, ("cheat_level", "heaven_brand", "warnings"), "/discipline", errors)
    add_error(errors, isinstance(discipline.get("cheat_level"), int) and 0 <= discipline.get("cheat_level", -1) <= 4, "discipline/cheat_level must be from 0 to 4")
    add_error(errors, isinstance(discipline.get("heaven_brand"), bool), "discipline/heaven_brand must be boolean")
    add_error(errors, isinstance(discipline.get("warnings"), list), "discipline/warnings must be an array")

    knowledge = mapping_at(state, "knowledge", errors, "")
    knowledge_fields = ["character_known", "engine_truth", "game_supplements"]
    if version == "1.7":
        knowledge_fields.append("canon_records")
    require_fields(knowledge, knowledge_fields, "/knowledge", errors)
    for field in ("character_known", "engine_truth", "game_supplements"):
        add_error(errors, isinstance(knowledge.get(field), list), f"knowledge/{field} must be an array")
    if version == "1.7":
        canon_records = knowledge.get("canon_records")
        add_error(errors, isinstance(canon_records, list), "knowledge/canon_records must be an array")
        add_error(errors, unique_named_ids(canon_records, "claim_id"), "canon claim ids must be unique")
        if isinstance(canon_records, list):
            for index, record in enumerate(canon_records):
                if not isinstance(record, dict):
                    errors.append(f"knowledge/canon_records/{index} must be an object")
                    continue
                require_fields(record, ("claim_id", "claim", "canon_status", "confidence", "verification", "sources", "character_access", "recorded_at_event_id", "notes"), f"/knowledge/canon_records/{index}", errors)
                add_error(errors, valid_named_id(record.get("claim_id"), "claim-"), f"knowledge/canon_records/{index}/claim_id is invalid")
                add_error(errors, isinstance(record.get("claim"), str) and bool(record.get("claim", "").strip()), f"knowledge/canon_records/{index}/claim is required")
                canon_status = record.get("canon_status")
                add_error(errors, enum_value(canon_status, CANON_STATUSES), f"knowledge/canon_records/{index}/canon_status is invalid")
                add_error(errors, enum_value(record.get("confidence"), {"high", "medium", "low", "none"}), f"knowledge/canon_records/{index}/confidence is invalid")
                add_error(errors, enum_value(record.get("verification"), {"verified", "unverified", "conflict"}), f"knowledge/canon_records/{index}/verification is invalid")
                sources = record.get("sources")
                add_error(errors, isinstance(sources, list), f"knowledge/canon_records/{index}/sources must be an array")
                if isinstance(sources, list):
                    for source_index, source in enumerate(sources):
                        if not isinstance(source, dict):
                            errors.append(f"knowledge/canon_records/{index}/sources/{source_index} must be an object")
                            continue
                        require_fields(source, ("kind", "citation"), f"/knowledge/canon_records/{index}/sources/{source_index}", errors)
                        add_error(errors, enum_value(source.get("kind"), {"novel", "author_statement", "official_setting", "licensed_adaptation", "secondary", "game_rules"}), f"knowledge/canon_records/{index}/sources/{source_index}/kind is invalid")
                        add_error(errors, isinstance(source.get("citation"), str) and bool(source.get("citation", "").strip()), f"knowledge/canon_records/{index}/sources/{source_index}/citation is required")
                add_error(errors, enum_value(record.get("character_access"), {"known", "partial", "unknown"}), f"knowledge/canon_records/{index}/character_access is invalid")
                add_error(errors, record.get("recorded_at_event_id") is None or valid_event_id(record.get("recorded_at_event_id")), f"knowledge/canon_records/{index}/recorded_at_event_id is invalid")
                add_error(errors, record.get("notes") is None or isinstance(record.get("notes"), str), f"knowledge/canon_records/{index}/notes is invalid")
                if canon_status in {"primary_canon", "official_supplement", "licensed_adaptation"}:
                    add_error(errors, isinstance(sources, list) and bool(sources), f"verified canon claim {record.get('claim_id')} requires a source")
                    add_error(errors, record.get("verification") == "verified", f"canon claim {record.get('claim_id')} must be verified")
                if canon_status == "unknown":
                    add_error(errors, record.get("confidence") == "none", f"unknown canon claim {record.get('claim_id')} must use confidence none")
    add_error(errors, isinstance(state.get("visuals"), dict), "visuals must be an object")

    roll_log = state.get("roll_log")
    add_error(errors, isinstance(roll_log, list), "roll_log must be an array")
    if isinstance(roll_log, list):
        for index, record in enumerate(roll_log):
            if not isinstance(record, dict):
                errors.append(f"roll_log/{index} must be an object")
                continue
            require_fields(record, ("event_id", "context", "rng_method", "counter", "raw", "formula", "target", "base_result", "final_result", "overflow_edge", "seed_commitment", "platform_result_id"), f"/roll_log/{index}", errors)
            add_error(errors, enum_value(record.get("rng_method"), RNG_METHODS), f"roll_log/{index}/rng_method is invalid")
            add_error(errors, isinstance(record.get("raw"), int) and 1 <= record.get("raw", 0) <= 100, f"roll_log/{index}/raw must be from 1 to 100")
            add_error(errors, valid_event_id(record.get("event_id")), f"roll_log/{index}/event_id is invalid")
            add_error(errors, isinstance(record.get("context"), str) and bool(record.get("context", "").strip()), f"roll_log/{index}/context is required")
            add_error(errors, isinstance(record.get("formula"), str) and bool(record.get("formula", "").strip()), f"roll_log/{index}/formula is required")
            add_error(errors, isinstance(record.get("target"), int) and record.get("target", 0) > 0, f"roll_log/{index}/target must be positive")
            add_error(errors, enum_value(record.get("base_result"), OUTCOMES), f"roll_log/{index}/base_result is invalid")
            add_error(errors, enum_value(record.get("final_result"), OUTCOMES), f"roll_log/{index}/final_result is invalid")
            add_error(errors, isinstance(record.get("overflow_edge"), bool), f"roll_log/{index}/overflow_edge must be boolean")
            if record.get("rng_method") == "hmac_sha256_rejection_v1":
                add_error(errors, isinstance(record.get("counter"), int) and record.get("counter", -1) >= 0, f"roll_log/{index} HMAC counter is invalid")
                add_error(errors, valid_commitment(record.get("seed_commitment")), f"roll_log/{index} HMAC commitment is invalid")
                add_error(errors, record.get("platform_result_id") is None, f"roll_log/{index} HMAC platform_result_id must be null")
            elif record.get("rng_method") == "platform_verified":
                add_error(errors, isinstance(record.get("platform_result_id"), str) and bool(record.get("platform_result_id", "").strip()), f"roll_log/{index} platform_result_id is required")
                add_error(errors, record.get("counter") is None and record.get("seed_commitment") is None, f"roll_log/{index} platform RNG metadata is invalid")
            elif record.get("rng_method") == "system_csprng":
                add_error(errors, record.get("counter") is None and record.get("seed_commitment") is None and record.get("platform_result_id") is None, f"roll_log/{index} system RNG metadata is invalid")
    return errors


def validate_chapter_transition(value: Any, errors: List[str]) -> None:
    if not isinstance(value, dict):
        errors.append("chapter_transition must be an object")
        return
    fields = {"closed_chapter_id", "closed_number", "resolution", "irreversible_changes", "updated_domains", "next_chapter"}
    require_fields(value, fields, "/chapter_transition", errors)
    add_error(errors, set(value) == fields, "chapter_transition contains unsupported fields")
    add_error(errors, isinstance(value.get("closed_chapter_id"), str) and bool(re.fullmatch(r"chapter-[0-9]{3,}", value.get("closed_chapter_id", ""))), "chapter_transition/closed_chapter_id is invalid")
    closed_number = value.get("closed_number")
    add_error(errors, isinstance(closed_number, int) and closed_number >= 1, "chapter_transition/closed_number is invalid")
    add_error(errors, isinstance(value.get("resolution"), str) and bool(value.get("resolution", "").strip()), "chapter_transition/resolution is required")
    add_error(errors, valid_string_list(value.get("irreversible_changes"), minimum=1), "chapter_transition/irreversible_changes is required")
    domains = value.get("updated_domains")
    add_error(errors, isinstance(domains, list) and bool(domains) and len(domains) == len(set(domains)) and all(item in CHAPTER_DOMAINS for item in domains), "chapter_transition/updated_domains is invalid")
    next_chapter = value.get("next_chapter")
    if not isinstance(next_chapter, dict):
        errors.append("chapter_transition/next_chapter must be an object")
        return
    next_fields = {"chapter_id", "number", "core_question", "pressure_source"}
    require_fields(next_chapter, next_fields, "/chapter_transition/next_chapter", errors)
    add_error(errors, set(next_chapter) == next_fields, "chapter_transition/next_chapter contains unsupported fields")
    add_error(errors, isinstance(next_chapter.get("chapter_id"), str) and bool(re.fullmatch(r"chapter-[0-9]{3,}", next_chapter.get("chapter_id", ""))), "chapter_transition/next_chapter/chapter_id is invalid")
    add_error(errors, isinstance(next_chapter.get("number"), int) and isinstance(closed_number, int) and next_chapter.get("number") == closed_number + 1, "chapter_transition/next_chapter/number must follow closed_number")
    for field in ("core_question", "pressure_source"):
        add_error(errors, isinstance(next_chapter.get(field), str) and bool(next_chapter.get(field, "").strip()), f"chapter_transition/next_chapter/{field} is required")


def validate_economy_settlement(value: Any, errors: List[str]) -> None:
    if not isinstance(value, dict):
        errors.append("economy_settlement must be an object")
        return
    fields = {"period_start", "period_end", "income_pence", "cost_pence", "debt_payment_pence", "net_pence", "resulting_balance_pence", "settled_flow_ids", "settled_debt_ids"}
    require_fields(value, fields, "/economy_settlement", errors)
    add_error(errors, set(value) == fields, "economy_settlement contains unsupported fields")
    start = parse_world_time(value.get("period_start"))
    end = parse_world_time(value.get("period_end"))
    add_error(errors, start is not None, "economy_settlement/period_start is invalid")
    add_error(errors, end is not None, "economy_settlement/period_end is invalid")
    if start is not None and end is not None:
        add_error(errors, end >= start, "economy_settlement period moves backward")
    numeric = all(isinstance(value.get(field), int) and not isinstance(value.get(field), bool) for field in ("income_pence", "cost_pence", "debt_payment_pence", "net_pence", "resulting_balance_pence"))
    add_error(errors, numeric, "economy_settlement numeric fields are invalid")
    if numeric:
        for field in ("income_pence", "cost_pence", "debt_payment_pence", "resulting_balance_pence"):
            add_error(errors, value[field] >= 0, f"economy_settlement/{field} must be non-negative")
        expected_net = value["income_pence"] - value["cost_pence"] - value["debt_payment_pence"]
        add_error(errors, value["net_pence"] == expected_net, "economy_settlement/net_pence does not match income minus costs and debt payments")
    flow_ids = value.get("settled_flow_ids")
    debt_ids = value.get("settled_debt_ids")
    add_error(errors, isinstance(flow_ids, list) and len(flow_ids) == len(set(flow_ids)) and all(valid_named_id(item, "flow-") for item in flow_ids), "economy_settlement/settled_flow_ids is invalid")
    add_error(errors, isinstance(debt_ids, list) and len(debt_ids) == len(set(debt_ids)) and all(valid_named_id(item, "debt-") for item in debt_ids), "economy_settlement/settled_debt_ids is invalid")


def validate_event(event: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(event, dict):
        return ["event must be an object"]
    version = event_contract_version(event)
    required = [
        "event_id",
        "type",
        "previous_state_revision",
        "state_revision",
        "world_time",
        "action",
        "stakes",
        "roll",
        "consequences",
        "state_patch",
        "visible_result",
        "created_at",
    ]
    if version == "1.7":
        required[0:0] = ["schema_version", "ruleset_version"]
    for key in required:
        add_error(errors, key in event, f"event missing key: {key}")
    allowed_event_fields = set(required) | {"transport", "migration"}
    if version == "1.7":
        allowed_event_fields |= {"chapter_transition", "economy_settlement"}
    add_error(errors, set(event).issubset(allowed_event_fields), "event contains an unsupported field")
    add_error(errors, version in WRITABLE_VERSIONS, "event schema_version is unsupported")
    if version == "1.7":
        add_error(errors, event.get("ruleset_version") == "1.7", "event ruleset_version must be 1.7")
    event_id = event.get("event_id")
    add_error(errors, valid_event_id(event_id), "event_id is invalid")
    add_error(errors, isinstance(event.get("type"), str) and bool(re.fullmatch(r"[a-z][a-z0-9_]*", event.get("type", ""))), "event type is invalid")
    previous_revision = event.get("previous_state_revision")
    revision = event.get("state_revision")
    add_error(errors, isinstance(previous_revision, int) and previous_revision >= 0, "previous_state_revision must be non-negative")
    add_error(errors, isinstance(revision, int) and isinstance(previous_revision, int) and revision == previous_revision + 1, "state_revision must equal previous_state_revision + 1")
    add_error(errors, isinstance(event.get("action"), str) and bool(event.get("action", "").strip()), "event action is required")
    add_error(errors, isinstance(event.get("visible_result"), str) and bool(event.get("visible_result", "").strip()), "visible_result is required")
    add_error(errors, parse_world_time(event.get("world_time")) is not None, "event world_time must use YYYY-MM-DD HH:MM[:SS]")
    add_error(errors, parse_real_timestamp(event.get("created_at")) is not None, "event created_at must be an ISO-8601 timestamp with timezone")

    stakes = event.get("stakes")
    if stakes is not None:
        add_error(errors, isinstance(stakes, dict), "stakes must be an object or null")
        if isinstance(stakes, dict):
            require_fields(stakes, ("intent", "approach", "target", "risk_level", "foreseeable_consequences", "public_modifiers"), "/stakes", errors)
            add_error(errors, set(stakes).issubset({"intent", "approach", "target", "risk_level", "foreseeable_consequences", "public_modifiers"}), "stakes contains an unsupported field")
            add_error(errors, isinstance(stakes.get("intent"), str) and bool(stakes.get("intent", "").strip()), "stakes/intent is required")
            add_error(errors, isinstance(stakes.get("approach"), str) and bool(stakes.get("approach", "").strip()), "stakes/approach is required")
            add_error(errors, enum_value(stakes.get("risk_level"), RISK_LEVELS), "stakes/risk_level is invalid")
            add_error(errors, isinstance(stakes.get("target"), int) and stakes.get("target", 0) > 0, "stakes/target must be positive")
            foreseeable = stakes.get("foreseeable_consequences")
            add_error(errors, isinstance(foreseeable, list) and all(isinstance(item, str) and item in CONSEQUENCE_CATEGORIES for item in foreseeable), "stakes/foreseeable_consequences is invalid")
            if isinstance(foreseeable, list) and all(isinstance(item, str) for item in foreseeable):
                add_error(errors, len(foreseeable) == len(set(foreseeable)), "stakes/foreseeable_consequences must be unique")
            validate_modifiers(stakes.get("public_modifiers"), "stakes/public_modifiers", errors)

    roll = event.get("roll")
    if roll is not None:
        add_error(errors, isinstance(stakes, dict), "an event with a roll requires stakes")
        add_error(errors, isinstance(roll, dict), "roll must be an object or null")
        if isinstance(roll, dict):
            roll_fields = {"rng_method", "seed_commitment", "counter", "platform_result_id", "context", "raw", "attribute", "skill", "mode_modifier", "situational_modifiers", "total", "target", "base_result", "final_result", "overflow_edge"}
            require_fields(roll, roll_fields, "/roll", errors)
            add_error(errors, set(roll).issubset(roll_fields), "roll contains an unsupported field")
            rng_method = roll.get("rng_method")
            add_error(errors, enum_value(rng_method, RNG_METHODS), "roll/rng_method is invalid")
            add_error(errors, isinstance(roll.get("raw"), int) and 1 <= roll.get("raw", 0) <= 100, "roll/raw must be from 1 to 100")
            add_error(errors, enum_value(roll.get("base_result"), OUTCOMES), "roll/base_result is invalid")
            add_error(errors, enum_value(roll.get("final_result"), OUTCOMES), "roll/final_result is invalid")
            add_error(errors, isinstance(roll.get("overflow_edge"), bool), "roll/overflow_edge must be boolean")
            context = roll.get("context")
            add_error(errors, isinstance(context, str) and bool(context.strip()), "roll/context is required")
            if valid_event_id(event_id) and isinstance(context, str):
                add_error(errors, context.startswith(f"{event_id}:"), "roll/context must be bound to its event_id")
            if rng_method == "hmac_sha256_rejection_v1":
                add_error(errors, isinstance(roll.get("counter"), int) and roll.get("counter", -1) >= 0, "HMAC roll requires a non-negative counter")
                add_error(errors, valid_commitment(roll.get("seed_commitment")), "HMAC roll requires a valid seed commitment")
                add_error(errors, roll.get("platform_result_id") is None, "HMAC roll cannot use platform_result_id")
            elif rng_method == "system_csprng":
                add_error(errors, roll.get("counter") is None, "system CSPRNG roll counter must be null")
                add_error(errors, roll.get("seed_commitment") is None, "system CSPRNG roll commitment must be null")
                add_error(errors, roll.get("platform_result_id") is None, "system CSPRNG roll platform_result_id must be null")
            elif rng_method == "platform_verified":
                add_error(errors, isinstance(roll.get("platform_result_id"), str) and bool(roll.get("platform_result_id", "").strip()), "platform roll requires platform_result_id")
                add_error(errors, roll.get("counter") is None, "platform roll counter must be null")
                add_error(errors, roll.get("seed_commitment") is None, "platform roll commitment must be null")

            modifiers = validate_modifiers(roll.get("situational_modifiers"), "roll/situational_modifiers", errors)
            mode_modifier = roll.get("mode_modifier")
            mode = MODE_BY_MODIFIER.get(mode_modifier) if isinstance(mode_modifier, int) and not isinstance(mode_modifier, bool) else None
            add_error(errors, mode is not None, "roll/mode_modifier is invalid")
            if isinstance(stakes, dict):
                add_error(errors, roll.get("target") == stakes.get("target"), "roll target does not match disclosed stakes")
            numeric_fields = all(
                isinstance(roll.get(field), int) and not isinstance(roll.get(field), bool)
                for field in ("raw", "attribute", "skill", "target", "total")
            )
            add_error(errors, numeric_fields, "roll numeric fields are invalid")
            if modifiers is not None and mode is not None and numeric_fields:
                try:
                    expected = roll_check.adjudicate(
                        roll["raw"], mode, roll["target"], roll["attribute"], roll["skill"], modifiers
                    )
                except roll_check.RollError as exc:
                    errors.append(f"roll calculation is invalid: {exc}")
                else:
                    for field in ("mode_modifier", "total", "base_result", "final_result", "overflow_edge"):
                        add_error(errors, roll.get(field) == expected.get(field), f"roll/{field} does not match the deterministic calculation")

    consequences = event.get("consequences")
    add_error(errors, isinstance(consequences, list) and len(consequences) <= 2, "consequences must have at most two entries")
    if isinstance(consequences, list):
        for index, consequence in enumerate(consequences):
            if not isinstance(consequence, dict):
                errors.append(f"consequences/{index} must be an object")
                continue
            require_fields(consequence, ("category", "severity", "description"), f"/consequences/{index}", errors)
            add_error(errors, set(consequence).issubset({"category", "severity", "description"}), f"consequences/{index} contains an unsupported field")
            add_error(errors, enum_value(consequence.get("category"), CONSEQUENCE_CATEGORIES), f"consequences/{index}/category is invalid")
            add_error(errors, enum_value(consequence.get("severity"), RISK_LEVELS), f"consequences/{index}/severity is invalid")
            add_error(errors, isinstance(consequence.get("description"), str) and bool(consequence.get("description", "").strip()), f"consequences/{index}/description is required")
    if isinstance(roll, dict) and isinstance(stakes, dict) and isinstance(consequences, list):
        final_result = roll.get("final_result")
        if enum_value(final_result, {"险成", "失败", "大失败"}):
            add_error(errors, len(consequences) >= 1, f"{final_result} requires at least one committed consequence")
        risk_level = stakes.get("risk_level")
        foreseeable = stakes.get("foreseeable_consequences")
        if enum_value(risk_level, RISK_LEVELS):
            maximum = RISK_ORDER.index(risk_level) + (1 if final_result == "大失败" else 0)
            maximum = min(maximum, len(RISK_ORDER) - 1)
            for index, consequence in enumerate(consequences):
                if not isinstance(consequence, dict):
                    continue
                severity = consequence.get("severity")
                if enum_value(severity, RISK_LEVELS):
                    add_error(errors, RISK_ORDER.index(severity) <= maximum, f"consequences/{index} exceeds the disclosed risk ceiling")
                if isinstance(foreseeable, list):
                    add_error(errors, consequence.get("category") in foreseeable, f"consequences/{index} category was not disclosed in stakes")

    operations = event.get("state_patch")
    add_error(errors, isinstance(operations, list), "state_patch must be an array")
    if isinstance(operations, list):
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                errors.append(f"state_patch/{index} must be an object")
                continue
            op = operation.get("op")
            path = operation.get("path")
            add_error(errors, enum_value(op, {"add", "replace", "remove"}), f"state_patch/{index}/op is invalid")
            add_error(errors, isinstance(path, str) and path.startswith("/"), f"state_patch/{index}/path is invalid")
            add_error(errors, not is_protected_patch_path(path), f"state_patch/{index} modifies or shadows runtime-managed path {path}")
            allowed_fields = {"op", "path", "value"} if op == "add" else ({"op", "path", "old"} if op == "remove" else {"op", "path", "old", "value"})
            if enum_value(op, {"add", "replace", "remove"}):
                add_error(errors, set(operation) == allowed_fields, f"state_patch/{index} has unexpected fields")
            if op == "add":
                add_error(errors, "value" in operation, f"state_patch/{index} add requires value")
            if enum_value(op, {"replace", "remove"}):
                add_error(errors, "old" in operation, f"state_patch/{index} {op} requires old")
            if op == "replace":
                add_error(errors, "value" in operation, f"state_patch/{index} replace requires value")

    add_error(errors, event.get("transport") is None or isinstance(event.get("transport"), dict), "transport must be an object or null")
    if version == "1.7":
        chapter_transition = event.get("chapter_transition")
        economy_settlement = event.get("economy_settlement")
        if chapter_transition is not None:
            validate_chapter_transition(chapter_transition, errors)
        if economy_settlement is not None:
            validate_economy_settlement(economy_settlement, errors)
        if event.get("type") == "chapter_closed":
            add_error(errors, isinstance(chapter_transition, dict), "chapter_closed event requires chapter_transition")
        else:
            add_error(errors, chapter_transition is None, "only chapter_closed may carry chapter_transition")
        if event.get("type") == "economy_settled":
            add_error(errors, isinstance(economy_settlement, dict), "economy_settled event requires economy_settlement")
        else:
            add_error(errors, economy_settlement is None, "only economy_settled may carry economy_settlement")
    migration = event.get("migration")
    if migration is not None:
        add_error(errors, isinstance(migration, dict), "migration must be an object or null")
        if isinstance(migration, dict):
            migration_fields = {"from_schema_version", "to_schema_version", "from_ruleset_version", "to_ruleset_version", "notes"}
            require_fields(migration, migration_fields, "/migration", errors)
            add_error(errors, set(migration).issubset(migration_fields), "migration contains an unsupported field")
            add_error(errors, migration.get("to_schema_version") == version, f"migration/to_schema_version must be {version}")
            add_error(errors, migration.get("to_ruleset_version") == version, f"migration/to_ruleset_version must be {version}")
            for field in ("from_schema_version", "from_ruleset_version", "notes"):
                add_error(errors, isinstance(migration.get(field), str) and bool(migration.get(field, "").strip()), f"migration/{field} is required")
    if event.get("type") == "ruleset_migrated":
        add_error(errors, isinstance(migration, dict), "ruleset_migrated event requires migration metadata")
    return errors


def event_number(event_id: str) -> int:
    match = EVENT_ID.fullmatch(event_id)
    if not match:
        raise RuntimeErrorDetail(f"invalid event id: {event_id}")
    return int(match.group(1))


def parse_world_time(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str):
        return None
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def validate_event_sequence(events: List[Dict[str, Any]], expected_version: Optional[str] = None) -> List[str]:
    if expected_version in LEGACY_READ_ONLY_VERSIONS:
        return validate_legacy_event_sequence(events)
    errors: List[str] = []
    seen_ids = set()
    previous_number: Optional[int] = None
    previous_revision: Optional[int] = None
    previous_world_time: Optional[dt.datetime] = None
    previous_created_at: Optional[dt.datetime] = None
    seen_v17 = False
    for index, event in enumerate(events):
        errors.extend(f"events/{index}: {message}" for message in validate_event(event))
        version = event_contract_version(event)
        if expected_version == "1.6":
            add_error(errors, version == "1.6", f"v1.6 campaign contains a {version} event")
        elif expected_version == "1.7":
            if version == "1.7" and not seen_v17 and index > 0:
                migration = event.get("migration")
                add_error(errors, event.get("type") == "ruleset_migrated" and isinstance(migration, dict) and migration.get("from_schema_version") == "1.6", "first v1.7 event after legacy history must be a migration from 1.6")
            if seen_v17:
                add_error(errors, version == "1.7", "legacy event appears after v1.7 history began")
            if version == "1.7":
                seen_v17 = True
        event_id = event.get("event_id")
        if isinstance(event_id, str):
            add_error(errors, event_id not in seen_ids, f"duplicate event id: {event_id}")
            seen_ids.add(event_id)
            if EVENT_ID.fullmatch(event_id):
                number = event_number(event_id)
                if previous_number is not None:
                    add_error(errors, number > previous_number, f"event ids are not increasing at {event_id}")
                previous_number = number
        revision = event.get("state_revision")
        event_previous = event.get("previous_state_revision")
        if previous_revision is not None:
            add_error(errors, event_previous == previous_revision, f"event revision gap before {event_id}")
        previous_revision = revision if isinstance(revision, int) else previous_revision
        world_time = parse_world_time(event.get("world_time"))
        if world_time is not None and previous_world_time is not None:
            add_error(errors, world_time >= previous_world_time, f"world time moved backward at {event_id}")
        if world_time is not None:
            previous_world_time = world_time
        created_at = parse_real_timestamp(event.get("created_at"))
        if created_at is not None and previous_created_at is not None:
            add_error(errors, created_at >= previous_created_at, f"real timestamp moved backward at {event_id}")
        if created_at is not None:
            previous_created_at = created_at
    if expected_version == "1.7" and events:
        add_error(errors, event_contract_version(events[-1]) == "1.7", "v1.7 campaign final event must use the v1.7 contract")
    return errors


def validate_consistency(state: Dict[str, Any], events: List[Dict[str, Any]], require_full_log: bool = True) -> List[str]:
    version = state_contract_version(state)
    if version in LEGACY_READ_ONLY_VERSIONS:
        return validate_legacy_consistency(state, events, version)
    errors = validate_state(state)
    errors.extend(validate_event_sequence(events, expected_version=version))
    runtime = state.get("runtime", {})
    if events:
        last = events[-1]
        add_error(errors, runtime.get("last_event_id") == last.get("event_id"), "state last_event_id does not match final event")
        add_error(errors, runtime.get("state_revision") == last.get("state_revision"), "state_revision does not match final event")
        add_error(errors, state.get("campaign", {}).get("world_time") == last.get("world_time"), "campaign world_time does not match final event")
        if require_full_log:
            add_error(errors, events[0].get("previous_state_revision") == 0, "full event log must begin at revision 0")
    event_ids = {event.get("event_id") for event in events}
    plot = state.get("plot", {})
    goal = plot.get("life_goal", {}) if isinstance(plot, dict) else {}
    if isinstance(goal, dict):
        for field in ("chosen_at_event_id", "criteria_met_at_event_id"):
            referenced = goal.get(field)
            if referenced is not None:
                add_error(errors, referenced in event_ids, f"life goal {field} references unknown event {referenced}")
    for condition in goal.get("success_conditions", []) if isinstance(goal, dict) else []:
        if not isinstance(condition, dict):
            continue
        for event_id in condition.get("evidence_event_ids", []):
            add_error(errors, event_id in event_ids, f"goal evidence references unknown event {event_id}")
    for clue in plot.get("clues", []) if isinstance(plot, dict) else []:
        if isinstance(clue, dict):
            event_id = clue.get("discovered_event_id")
            add_error(errors, event_id in event_ids, f"clue {clue.get('clue_id')} references unknown event {event_id}")
    for record in state.get("roll_log", []):
        if isinstance(record, dict):
            add_error(errors, record.get("event_id") in event_ids, f"roll log references unknown event {record.get('event_id')}")
    rolled_events = [event for event in events if isinstance(event.get("roll"), dict)]
    recent_rolled_ids = [event.get("event_id") for event in rolled_events[-20:]]
    roll_records = {
        record.get("event_id"): record
        for record in state.get("roll_log", [])
        if isinstance(record, dict)
    }
    for event in rolled_events[-20:]:
        event_id = event.get("event_id")
        record = roll_records.get(event_id)
        add_error(errors, record is not None, f"rolled event {event_id} is missing from roll_log")
        if isinstance(record, dict):
            add_error(errors, record.get("raw") == event["roll"].get("raw"), f"roll_log raw value differs for {event_id}")
            add_error(errors, record.get("final_result") == event["roll"].get("final_result"), f"roll_log result differs for {event_id}")
            for field in ("context", "rng_method", "counter", "target", "base_result", "overflow_edge", "seed_commitment", "platform_result_id"):
                add_error(errors, record.get(field) == event["roll"].get(field), f"roll_log {field} differs for {event_id}")
            mode_modifier = event["roll"].get("mode_modifier")
            mode = MODE_BY_MODIFIER.get(mode_modifier) if isinstance(mode_modifier, int) and not isinstance(mode_modifier, bool) else None
            modifiers = event["roll"].get("situational_modifiers")
            if mode is not None and isinstance(modifiers, list):
                try:
                    expected = roll_check.adjudicate(
                        event["roll"]["raw"], mode, event["roll"]["target"], event["roll"]["attribute"], event["roll"]["skill"], modifiers
                    )
                except (KeyError, TypeError, roll_check.RollError):
                    pass
                else:
                    add_error(errors, record.get("formula") == expected.get("formula"), f"roll_log formula differs for {event_id}")
    logged_ids = [record.get("event_id") for record in state.get("roll_log", []) if isinstance(record, dict)]
    add_error(errors, len(logged_ids) == len(set(logged_ids)), "roll_log event ids must be unique")
    add_error(errors, all(event_id in logged_ids for event_id in recent_rolled_ids), "roll_log must retain the most recent 20 rolled events")
    seeded_rolls = [event["roll"] for event in rolled_events if event["roll"].get("rng_method") == "hmac_sha256_rejection_v1"]
    streams: Dict[str, List[int]] = {}
    for roll in seeded_rolls:
        commitment, counter = roll.get("seed_commitment"), roll.get("counter")
        if valid_commitment(commitment) and isinstance(counter, int):
            streams.setdefault(commitment, []).append(counter)
    for commitment, counters in streams.items():
        add_error(errors, counters == sorted(set(counters)), f"seeded roll counters must be unique and increasing for commitment {commitment[:8]}")
        if counters:
            add_error(errors, counters == list(range(counters[0], counters[-1] + 1)), f"seeded roll counters contain a gap for commitment {commitment[:8]}")
    current_rng = state.get("runtime", {}).get("rng", {})
    if current_rng.get("method") == "hmac_sha256_rejection_v1":
        current_commitment = current_rng.get("seed_commitment")
        counters = streams.get(current_commitment, [])
        expected_next = counters[-1] + 1 if counters else 0
        add_error(errors, current_rng.get("next_counter") == expected_next, "runtime RNG counter does not follow the latest seeded roll")
    platform_ids = [
        event["roll"].get("platform_result_id")
        for event in rolled_events
        if event["roll"].get("rng_method") == "platform_verified"
    ]
    if all(isinstance(item, str) for item in platform_ids):
        add_error(errors, len(platform_ids) == len(set(platform_ids)), "platform RNG result ids must be unique")
    if version == "1.7":
        event_by_id = {event.get("event_id"): event for event in events}
        preferences = state.get("preferences", {})
        if isinstance(preferences, dict):
            preference_event = preferences.get("updated_at_event_id")
            add_error(errors, preference_event in event_ids, f"preferences reference unknown event {preference_event}")

        commitments = state.get("commitments", [])
        commitment_by_id = {
            item.get("commitment_id"): item
            for item in commitments
            if isinstance(item, dict) and isinstance(item.get("commitment_id"), str)
        }
        organization_ids = set()
        social = state.get("social", {})
        if isinstance(social, dict):
            for status in social.get("statuses", []):
                if not isinstance(status, dict):
                    continue
                for evidence_id in status.get("evidence_event_ids", []):
                    add_error(errors, evidence_id in event_ids, f"social status {status.get('status_id')} references unknown event {evidence_id}")
            for organization in social.get("organizations", []):
                if not isinstance(organization, dict):
                    continue
                organization_id = organization.get("organization_id")
                organization_ids.add(organization_id)
                for evidence_id in organization.get("evidence_event_ids", []):
                    add_error(errors, evidence_id in event_ids, f"organization {organization_id} references unknown event {evidence_id}")
                add_error(errors, organization.get("last_changed_event_id") in event_ids, f"organization {organization_id} has unknown last_changed_event_id")
                for commitment_id in organization.get("commitment_ids", []):
                    add_error(errors, commitment_id in commitment_by_id, f"organization {organization_id} references unknown commitment {commitment_id}")
        for commitment_id, commitment in commitment_by_id.items():
            for evidence_id in commitment.get("evidence_event_ids", []):
                add_error(errors, evidence_id in event_ids, f"commitment {commitment_id} references unknown event {evidence_id}")
            linked_organization = commitment.get("linked_organization_id")
            if linked_organization is not None:
                add_error(errors, linked_organization in organization_ids, f"commitment {commitment_id} references unknown organization {linked_organization}")
            breach_event = commitment.get("breach_event_id")
            if breach_event is not None:
                add_error(errors, breach_event in event_ids, f"commitment {commitment_id} references unknown breach event {breach_event}")

        economy = state.get("economy", {})
        flow_ids = set()
        debt_ids = set()
        if isinstance(economy, dict):
            for collection_name in ("income_streams", "recurring_costs"):
                for flow in economy.get(collection_name, []):
                    if not isinstance(flow, dict):
                        continue
                    flow_ids.add(flow.get("flow_id"))
                    add_error(errors, flow.get("evidence_event_id") in event_ids, f"economy flow {flow.get('flow_id')} references unknown event")
            for debt in economy.get("debts", []):
                if not isinstance(debt, dict):
                    continue
                debt_id = debt.get("debt_id")
                debt_ids.add(debt_id)
                for evidence_id in debt.get("evidence_event_ids", []):
                    add_error(errors, evidence_id in event_ids, f"debt {debt_id} references unknown event {evidence_id}")
                linked_commitment = debt.get("commitment_id")
                if linked_commitment is not None:
                    add_error(errors, linked_commitment in commitment_by_id, f"debt {debt_id} references unknown commitment {linked_commitment}")
            for scarcity in economy.get("scarcity", []):
                if isinstance(scarcity, dict):
                    add_error(errors, scarcity.get("evidence_event_id") in event_ids, f"scarcity {scarcity.get('category')} references unknown event")
            settlement_event_id = economy.get("last_settlement_event_id")
            if settlement_event_id is not None:
                settlement_event = event_by_id.get(settlement_event_id)
                add_error(errors, isinstance(settlement_event, dict) and settlement_event.get("type") == "economy_settled", "economy/last_settlement_event_id must reference an economy_settled event")
        settlement_events: List[Dict[str, Any]] = []
        for event in events:
            settlement = event.get("economy_settlement")
            if not isinstance(settlement, dict):
                continue
            settlement_events.append(event)
            add_error(errors, all(item in flow_ids for item in settlement.get("settled_flow_ids", [])), f"economy settlement {event.get('event_id')} references an unknown flow")
            add_error(errors, all(item in debt_ids for item in settlement.get("settled_debt_ids", [])), f"economy settlement {event.get('event_id')} references an unknown debt")
            if isinstance(economy, dict) and economy.get("last_settlement_event_id") == event.get("event_id") and event is events[-1]:
                balance = money_to_pence(state.get("player", {}).get("money"))
                add_error(errors, settlement.get("resulting_balance_pence") == balance, "latest economy settlement balance does not match player money")
        if isinstance(economy, dict) and settlement_events:
            add_error(
                errors,
                economy.get("last_settlement_event_id") == settlement_events[-1].get("event_id"),
                "economy/last_settlement_event_id must reference the newest economy settlement",
            )

        chapter = plot.get("chapter", {}) if isinstance(plot, dict) else {}
        if isinstance(chapter, dict):
            add_error(errors, chapter.get("opened_at_event_id") in event_ids, f"current chapter references unknown opening event {chapter.get('opened_at_event_id')}")
        raw_chapter_history = plot.get("chapter_history", []) if isinstance(plot, dict) else []
        chapter_history = raw_chapter_history if isinstance(raw_chapter_history, list) else []
        history_by_close = {
            entry.get("closed_at_event_id"): entry
            for entry in chapter_history
            if isinstance(entry, dict)
        }
        for entry in chapter_history:
            if not isinstance(entry, dict):
                continue
            opened_id = entry.get("opened_at_event_id")
            closed_id = entry.get("closed_at_event_id")
            add_error(errors, opened_id in event_ids, f"chapter {entry.get('chapter_id')} references unknown opening event {opened_id}")
            closing_event = event_by_id.get(closed_id)
            add_error(errors, isinstance(closing_event, dict) and closing_event.get("type") == "chapter_closed", f"chapter {entry.get('chapter_id')} has invalid closing event {closed_id}")
            if isinstance(closing_event, dict):
                transition = closing_event.get("chapter_transition")
                if isinstance(transition, dict):
                    add_error(errors, transition.get("closed_chapter_id") == entry.get("chapter_id"), f"chapter transition id differs for {closed_id}")
                    add_error(errors, transition.get("closed_number") == entry.get("number"), f"chapter transition number differs for {closed_id}")
                    add_error(errors, transition.get("resolution") == entry.get("resolution"), f"chapter transition resolution differs for {closed_id}")
                    add_error(errors, transition.get("irreversible_changes") == entry.get("irreversible_changes"), f"chapter transition irreversible changes differ for {closed_id}")
                    add_error(errors, transition.get("updated_domains") == entry.get("updated_domains"), f"chapter transition updated domains differ for {closed_id}")
        for event in events:
            if event.get("type") == "chapter_closed":
                add_error(errors, event.get("event_id") in history_by_close, f"chapter close {event.get('event_id')} is missing from chapter_history")
        if events and events[-1].get("type") == "chapter_closed" and isinstance(chapter, dict):
            transition = events[-1].get("chapter_transition")
            next_chapter = transition.get("next_chapter") if isinstance(transition, dict) else None
            if isinstance(next_chapter, dict):
                for field in ("chapter_id", "number", "core_question", "pressure_source"):
                    add_error(errors, chapter.get(field) == next_chapter.get(field), f"current chapter {field} differs from latest chapter transition")
                add_error(errors, chapter.get("opened_at_event_id") == events[-1].get("event_id"), "current chapter must open at the latest chapter_closed event")

        knowledge = state.get("knowledge", {})
        if isinstance(knowledge, dict):
            for claim in knowledge.get("canon_records", []):
                if not isinstance(claim, dict):
                    continue
                recorded_id = claim.get("recorded_at_event_id")
                if recorded_id is not None:
                    add_error(errors, recorded_id in event_ids, f"canon claim {claim.get('claim_id')} references unknown event {recorded_id}")
    return errors


def decode_pointer_part(part: str) -> str:
    if re.search(r"~(?:[^01]|$)", part):
        raise RuntimeErrorDetail(f"invalid JSON Pointer escape: {part}")
    return part.replace("~1", "/").replace("~0", "~")


def parse_array_index(key: str, length: int, pointer: str, allow_end: bool = False) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", key):
        raise RuntimeErrorDetail(f"invalid array index: {pointer}")
    index = int(key)
    upper_bound = length if allow_end else length - 1
    if index < 0 or index > upper_bound:
        raise RuntimeErrorDetail(f"array index out of range: {pointer}")
    return index


def resolve_parent(document: Any, pointer: str) -> Tuple[Any, str]:
    if not pointer.startswith("/"):
        raise RuntimeErrorDetail(f"patch path must start with '/': {pointer}")
    parts = [decode_pointer_part(part) for part in pointer.split("/")[1:]]
    if not parts:
        raise RuntimeErrorDetail("patching the document root is not allowed")
    parent = document
    for part in parts[:-1]:
        if isinstance(parent, dict):
            if part not in parent:
                raise RuntimeErrorDetail(f"patch path does not exist: {pointer}")
            parent = parent[part]
        elif isinstance(parent, list):
            parent = parent[parse_array_index(part, len(parent), pointer)]
        else:
            raise RuntimeErrorDetail(f"patch traverses a scalar: {pointer}")
    return parent, parts[-1]


def get_existing(parent: Any, key: str, pointer: str) -> Any:
    if isinstance(parent, dict):
        if key not in parent:
            raise RuntimeErrorDetail(f"patch path does not exist: {pointer}")
        return parent[key]
    if isinstance(parent, list):
        return parent[parse_array_index(key, len(parent), pointer)]
    raise RuntimeErrorDetail(f"patch parent is not a container: {pointer}")


def apply_state_patch(state: Dict[str, Any], operations: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    updated = copy.deepcopy(state)
    for operation in operations:
        op = operation["op"]
        pointer = operation["path"]
        if is_protected_patch_path(pointer):
            raise RuntimeErrorDetail(f"patch modifies runtime-managed path: {pointer}")
        parent, key = resolve_parent(updated, pointer)
        if op == "add":
            if isinstance(parent, dict):
                if key in parent:
                    raise RuntimeErrorDetail(f"add target already exists: {pointer}")
                parent[key] = copy.deepcopy(operation["value"])
            elif isinstance(parent, list):
                if key == "-":
                    parent.append(copy.deepcopy(operation["value"]))
                else:
                    index = parse_array_index(key, len(parent), pointer, allow_end=True)
                    parent.insert(index, copy.deepcopy(operation["value"]))
            else:
                raise RuntimeErrorDetail(f"add parent is not a container: {pointer}")
            continue

        existing = get_existing(parent, key, pointer)
        if existing != operation.get("old"):
            raise RuntimeErrorDetail(f"old-value check failed at {pointer}")
        if op == "replace":
            if isinstance(parent, dict):
                parent[key] = copy.deepcopy(operation["value"])
            else:
                parent[parse_array_index(key, len(parent), pointer)] = copy.deepcopy(operation["value"])
        elif op == "remove":
            if isinstance(parent, dict):
                del parent[key]
            else:
                del parent[parse_array_index(key, len(parent), pointer)]
        else:
            raise RuntimeErrorDetail(f"unsupported patch operation: {op}")
    return updated


def apply_runtime_metadata(previous: Dict[str, Any], updated: Dict[str, Any], event: Dict[str, Any]) -> None:
    previous_rng = previous["runtime"]["rng"]
    updated_rng = updated["runtime"]["rng"]
    roll = event.get("roll")
    if isinstance(roll, dict):
        method = roll.get("rng_method")
        if method != previous_rng.get("method"):
            raise RuntimeErrorDetail("event RNG method does not match campaign RNG configuration")
        if method == "hmac_sha256_rejection_v1":
            counter = roll.get("counter")
            expected_counter = previous_rng.get("next_counter")
            if counter != expected_counter:
                raise RuntimeErrorDetail(f"expected RNG counter {expected_counter}, got {counter}")
            if roll.get("seed_commitment") != previous_rng.get("seed_commitment"):
                raise RuntimeErrorDetail("event seed commitment does not match campaign RNG commitment")
            updated_rng["next_counter"] = counter + 1
    updated["runtime"]["state_revision"] = event["state_revision"]
    updated["runtime"]["last_event_id"] = event["event_id"]
    updated["runtime"]["updated_at"] = event["created_at"]


def state_and_events(campaign_dir: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    state = load_data(campaign_dir / "state.yaml")
    if not isinstance(state, dict):
        raise RuntimeErrorDetail("state.yaml must contain an object")
    events = load_events(campaign_dir / "events.jsonl")
    return state, events


def raise_if_errors(errors: List[str]) -> None:
    if errors:
        raise RuntimeErrorDetail("validation failed:\n- " + "\n- ".join(errors))


def recover_locked(campaign_dir: Path) -> Dict[str, Any]:
    state, events = state_and_events(campaign_dir)
    require_writable_version(state_contract_version(state), "recovery")
    raise_if_errors(validate_state(state))
    current_revision = state["runtime"]["state_revision"]
    pending = [event for event in events if event.get("state_revision", -1) > current_revision]
    if not pending:
        raise_if_errors(validate_consistency(state, events))
        return {"status": "clean", "state_revision": current_revision, "last_event_id": state["runtime"]["last_event_id"]}

    updated = state
    applied: List[str] = []
    for event in pending:
        raise_if_errors(validate_event(event))
        if event["previous_state_revision"] != updated["runtime"]["state_revision"]:
            raise RuntimeErrorDetail(f"cannot recover non-contiguous event {event['event_id']}")
        previous = updated
        updated = apply_state_patch(previous, event["state_patch"])
        apply_runtime_metadata(previous, updated, event)
        raise_if_errors(validate_state(updated))
        applied.append(event["event_id"])
    raise_if_errors(validate_consistency(updated, events))
    atomic_write(campaign_dir / "state.yaml", updated)
    return {"status": "recovered", "applied_event_ids": applied, "state_revision": updated["runtime"]["state_revision"]}


def commit_event(campaign_dir: Path, event_path: Path) -> Dict[str, Any]:
    event = load_data(event_path)
    if not isinstance(event, dict):
        raise RuntimeErrorDetail("event file must contain an object")
    with campaign_lock(campaign_dir):
        state, events = state_and_events(campaign_dir)
        require_writable_version(state_contract_version(state), "commit")
        raise_if_errors(validate_event(event))
        if events and events[-1].get("state_revision", -1) > state.get("runtime", {}).get("state_revision", -1):
            recover_locked(campaign_dir)
            state, events = state_and_events(campaign_dir)
        raise_if_errors(validate_consistency(state, events))
        existing = next((item for item in events if item.get("event_id") == event["event_id"]), None)
        if existing is not None:
            if existing != event:
                raise RuntimeErrorDetail(f"event id {event['event_id']} already exists with different content")
            if state["runtime"]["last_event_id"] == event["event_id"]:
                return {"status": "already_committed", "event_id": event["event_id"], "state_revision": event["state_revision"]}
            return recover_locked(campaign_dir)

        current_revision = state["runtime"]["state_revision"]
        if event["previous_state_revision"] != current_revision:
            raise RuntimeErrorDetail(f"expected previous_state_revision {current_revision}")
        if events and event_number(event["event_id"]) <= event_number(events[-1]["event_id"]):
            raise RuntimeErrorDetail("event_id must increase")

        updated = apply_state_patch(state, event["state_patch"])
        apply_runtime_metadata(state, updated, event)
        future_events = events + [event]
        raise_if_errors(validate_consistency(updated, future_events))

        append_event(campaign_dir / "events.jsonl", event)
        atomic_write(campaign_dir / "state.yaml", updated)
        return {"status": "committed", "event_id": event["event_id"], "state_revision": event["state_revision"]}


def initialize_campaign(campaigns_dir: Path, campaign_id: str, state_path: Path, event_path: Path, activate: bool) -> Dict[str, Any]:
    if not CAMPAIGN_ID.fullmatch(campaign_id):
        raise RuntimeErrorDetail("campaign_id may contain only letters, digits, dot, underscore, and hyphen")
    campaign_dir = campaigns_dir / campaign_id
    if campaign_dir.exists():
        raise RuntimeErrorDetail(f"campaign directory already exists: {campaign_dir}")
    state = load_data(state_path)
    event = load_data(event_path)
    if not isinstance(state, dict) or not isinstance(event, dict):
        raise RuntimeErrorDetail("initial state and event must be objects")
    require_writable_version(state_contract_version(state), "initialization")
    raise_if_errors(validate_state(state))
    raise_if_errors(validate_event(event))
    add_errors: List[str] = []
    add_error(add_errors, state.get("campaign", {}).get("id") == campaign_id, "state campaign id does not match")
    add_error(add_errors, event.get("previous_state_revision") == 0 and event.get("state_revision") == 1, "initial event must commit revision 1 from revision 0")
    add_error(add_errors, state.get("runtime", {}).get("state_revision") == 1, "initial state revision must be 1")
    add_error(add_errors, state.get("runtime", {}).get("last_event_id") == event.get("event_id"), "initial state last_event_id must match event")
    raise_if_errors(add_errors)
    raise_if_errors(validate_consistency(state, [event]))

    campaigns_dir.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix=f".{campaign_id}.init.", dir=str(campaigns_dir)))
    try:
        os.chmod(str(temporary_dir), 0o700)
        atomic_write(temporary_dir / "state.yaml", state)
        append_event(temporary_dir / "events.jsonl", event)
        atomic_write_text(temporary_dir / "journal.md", f"# {state['player']['name']}的雾中纪事\n")
        atomic_write_text(temporary_dir / "canon-deviations.md", "# 正典偏移记录\n\n当前无正典偏移。\n")
        atomic_write_text(temporary_dir / "latest-anchor.md", "# 最近记忆之锚\n\n尚未生成。\n")
        os.rename(str(temporary_dir), str(campaign_dir))
        fsync_directory(campaigns_dir)
        if activate:
            atomic_write(
                campaigns_dir / "active.yaml",
                {"campaign_id": campaign_id, "status": state["campaign"]["status"], "state_revision": 1},
            )
    except Exception:
        if temporary_dir.exists():
            for child in temporary_dir.iterdir():
                with contextlib.suppress(OSError):
                    child.unlink()
            with contextlib.suppress(OSError):
                temporary_dir.rmdir()
        raise
    return {"status": "initialized", "campaign_id": campaign_id, "campaign_dir": str(campaign_dir), "activated": activate}


def build_anchor(
    state: Dict[str, Any],
    events: List[Dict[str, Any]],
    recent_events: int,
    exported_at: Optional[str] = None,
) -> Dict[str, Any]:
    require_writable_version(state_contract_version(state), "portable anchor export")
    raise_if_errors(validate_consistency(state, events))
    if recent_events < 1:
        raise RuntimeErrorDetail("recent-events must be positive")
    timestamp = exported_at or dt.datetime.now(dt.timezone.utc).isoformat()
    if parse_real_timestamp(timestamp) is None:
        raise RuntimeErrorDetail("exported_at must be an ISO-8601 timestamp with timezone")
    ruleset_version = state["runtime"]["ruleset_version"]
    payload: Dict[str, Any] = {
        "format_version": "1.1" if ruleset_version == "1.7" else "1.0",
        "campaign_id": state["campaign"]["id"],
        "state_revision": state["runtime"]["state_revision"],
        "last_event_id": state["runtime"]["last_event_id"],
        "ruleset_version": ruleset_version,
        "exported_at": timestamp,
        "contains_hidden_state": True,
        "authoritative_state": state,
        "recent_events": events[-recent_events:],
    }
    payload["integrity"] = {"algorithm": "sha256-canonical-json", "digest": canonical_digest(payload)}
    return payload


def export_anchor(campaign_dir: Path, output: Path, recent_events: int) -> Dict[str, Any]:
    state, events = state_and_events(campaign_dir)
    payload = build_anchor(state, events, recent_events)
    atomic_write(output, payload)
    return {"status": "exported", "output": str(output), "digest": payload["integrity"]["digest"]}


def verify_anchor(path: Path) -> Dict[str, Any]:
    anchor = load_data(path)
    if not isinstance(anchor, dict):
        raise RuntimeErrorDetail("anchor must be an object")
    integrity = anchor.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256-canonical-json":
        raise RuntimeErrorDetail("anchor integrity metadata is missing or unsupported")
    claimed = integrity.get("digest")
    unsigned = copy.deepcopy(anchor)
    del unsigned["integrity"]
    actual = canonical_digest(unsigned)
    if claimed != actual:
        raise RuntimeErrorDetail("anchor digest does not match content")
    state = anchor.get("authoritative_state")
    events = anchor.get("recent_events")
    if not isinstance(state, dict) or not isinstance(events, list):
        raise RuntimeErrorDetail("anchor state or event list is invalid")
    require_writable_version(state_contract_version(state), "portable anchor verification")
    raise_if_errors(validate_state(state))
    version = state_contract_version(state)
    raise_if_errors(validate_event_sequence(events, expected_version=version))
    anchor_errors: List[str] = []
    expected_format = "1.1" if version == "1.7" else "1.0"
    add_error(anchor_errors, anchor.get("format_version") == expected_format, f"anchor format_version must be {expected_format}")
    add_error(anchor_errors, anchor.get("contains_hidden_state") is True, "anchor must declare contains_hidden_state")
    add_error(anchor_errors, anchor.get("campaign_id") == state.get("campaign", {}).get("id"), "anchor campaign_id does not match state")
    add_error(anchor_errors, anchor.get("state_revision") == state.get("runtime", {}).get("state_revision"), "anchor state_revision does not match state")
    add_error(anchor_errors, anchor.get("last_event_id") == state.get("runtime", {}).get("last_event_id"), "anchor last_event_id does not match state")
    add_error(anchor_errors, anchor.get("ruleset_version") == state.get("runtime", {}).get("ruleset_version") == version, "anchor ruleset_version does not match state")
    add_error(anchor_errors, parse_real_timestamp(anchor.get("exported_at")) is not None, "anchor exported_at must be an ISO-8601 timestamp with timezone")
    raise_if_errors(anchor_errors)
    if events:
        add_errors: List[str] = []
        add_error(add_errors, state["runtime"]["last_event_id"] == events[-1].get("event_id"), "anchor final event does not match state")
        add_error(add_errors, state["runtime"]["state_revision"] == events[-1].get("state_revision"), "anchor final revision does not match state")
        raise_if_errors(add_errors)
    return {"status": "valid", "campaign_id": anchor.get("campaign_id"), "state_revision": anchor.get("state_revision"), "digest": actual}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate authoritative state and complete event history")
    validate_parser.add_argument("--campaign-dir", required=True, type=Path)

    commit_parser = subparsers.add_parser("commit", help="append one event and atomically commit its state patch")
    commit_parser.add_argument("--campaign-dir", required=True, type=Path)
    commit_parser.add_argument("--event", required=True, type=Path)

    recover_parser = subparsers.add_parser("recover", help="apply appended but uncommitted event patches")
    recover_parser.add_argument("--campaign-dir", required=True, type=Path)

    init_parser = subparsers.add_parser("init", help="create a new campaign from validated revision-1 records")
    init_parser.add_argument("--campaigns-dir", required=True, type=Path)
    init_parser.add_argument("--campaign-id", required=True)
    init_parser.add_argument("--state", required=True, type=Path)
    init_parser.add_argument("--event", required=True, type=Path)
    init_parser.add_argument("--activate", action="store_true")

    export_parser = subparsers.add_parser("export-anchor", help="export a digest-protected portable anchor")
    export_parser.add_argument("--campaign-dir", required=True, type=Path)
    export_parser.add_argument("--output", required=True, type=Path)
    export_parser.add_argument("--recent-events", type=int, default=20)

    verify_parser = subparsers.add_parser("verify-anchor", help="verify a portable anchor and its digest")
    verify_parser.add_argument("--input", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "validate":
            state, events = state_and_events(args.campaign_dir)
            raise_if_errors(validate_consistency(state, events))
            version = state_contract_version(state)
            output = {
                "status": "valid_legacy_read_only" if version in LEGACY_READ_ONLY_VERSIONS else "valid",
                "contract_version": version,
                "campaign_id": state["campaign"]["id"],
                "state_revision": state["runtime"]["state_revision"],
                "last_event_id": state["runtime"]["last_event_id"],
                "event_count": len(events),
            }
        elif args.command == "commit":
            output = commit_event(args.campaign_dir, args.event)
        elif args.command == "recover":
            with campaign_lock(args.campaign_dir):
                output = recover_locked(args.campaign_dir)
        elif args.command == "init":
            output = initialize_campaign(args.campaigns_dir, args.campaign_id, args.state, args.event, args.activate)
        elif args.command == "export-anchor":
            output = export_anchor(args.campaign_dir, args.output, args.recent_events)
        else:
            output = verify_anchor(args.input)
    except (RuntimeErrorDetail, OSError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
