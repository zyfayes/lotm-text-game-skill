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


def validate_state(state: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(state, dict):
        return ["state must be an object"]
    state_keys = ("runtime", "campaign", "player", "relations", "plot", "causality", "world", "knowledge", "discipline", "visuals", "roll_log")
    for key in state_keys:
        add_error(errors, key in state, f"missing state key: {key}")
    add_error(errors, set(state).issubset(state_keys), "state contains an unsupported top-level key")

    runtime = mapping_at(state, "runtime", errors, "")
    require_fields(runtime, ("schema_version", "state_revision", "last_event_id", "updated_at", "ruleset_version", "panel_renderer", "panel_template_version", "rng"), "/runtime", errors)
    add_error(errors, runtime.get("schema_version") == "1.6", "runtime/schema_version must be string 1.6")
    add_error(errors, runtime.get("ruleset_version") == "1.6", "runtime/ruleset_version must be string 1.6")
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
    require_fields(campaign, ("id", "status", "turn", "world_time", "location", "difficulty", "mode_modifier", "opportunity_counter", "pacing_profile", "chapter", "meaningful_scenes"), "/campaign", errors)
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

    plot = mapping_at(state, "plot", errors, "")
    require_fields(plot, ("life_goal", "completed_goals", "main", "current_action", "open_threads", "clues", "investigations", "deadlines"), "/plot", errors)
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
    require_fields(knowledge, ("character_known", "engine_truth", "game_supplements"), "/knowledge", errors)
    for field in ("character_known", "engine_truth", "game_supplements"):
        add_error(errors, isinstance(knowledge.get(field), list), f"knowledge/{field} must be an array")
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


def validate_event(event: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(event, dict):
        return ["event must be an object"]
    required = (
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
    )
    for key in required:
        add_error(errors, key in event, f"event missing key: {key}")
    allowed_event_fields = set(required) | {"transport", "migration"}
    add_error(errors, set(event).issubset(allowed_event_fields), "event contains an unsupported field")
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
    migration = event.get("migration")
    if migration is not None:
        add_error(errors, isinstance(migration, dict), "migration must be an object or null")
        if isinstance(migration, dict):
            migration_fields = {"from_schema_version", "to_schema_version", "from_ruleset_version", "to_ruleset_version", "notes"}
            require_fields(migration, migration_fields, "/migration", errors)
            add_error(errors, set(migration).issubset(migration_fields), "migration contains an unsupported field")
            add_error(errors, migration.get("to_schema_version") == "1.6", "migration/to_schema_version must be 1.6")
            add_error(errors, migration.get("to_ruleset_version") == "1.6", "migration/to_ruleset_version must be 1.6")
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


def validate_event_sequence(events: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    seen_ids = set()
    previous_number: Optional[int] = None
    previous_revision: Optional[int] = None
    previous_world_time: Optional[dt.datetime] = None
    previous_created_at: Optional[dt.datetime] = None
    for index, event in enumerate(events):
        errors.extend(f"events/{index}: {message}" for message in validate_event(event))
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
    return errors


def validate_consistency(state: Dict[str, Any], events: List[Dict[str, Any]], require_full_log: bool = True) -> List[str]:
    errors = validate_state(state)
    errors.extend(validate_event_sequence(events))
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
    raise_if_errors(validate_event(event))
    with campaign_lock(campaign_dir):
        state, events = state_and_events(campaign_dir)
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


def export_anchor(campaign_dir: Path, output: Path, recent_events: int) -> Dict[str, Any]:
    state, events = state_and_events(campaign_dir)
    raise_if_errors(validate_consistency(state, events))
    if recent_events < 1:
        raise RuntimeErrorDetail("recent-events must be positive")
    payload: Dict[str, Any] = {
        "format_version": "1.0",
        "campaign_id": state["campaign"]["id"],
        "state_revision": state["runtime"]["state_revision"],
        "last_event_id": state["runtime"]["last_event_id"],
        "ruleset_version": state["runtime"]["ruleset_version"],
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "contains_hidden_state": True,
        "authoritative_state": state,
        "recent_events": events[-recent_events:],
    }
    payload["integrity"] = {"algorithm": "sha256-canonical-json", "digest": canonical_digest(payload)}
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
    raise_if_errors(validate_state(state))
    raise_if_errors(validate_event_sequence(events))
    anchor_errors: List[str] = []
    add_error(anchor_errors, anchor.get("format_version") == "1.0", "anchor format_version must be 1.0")
    add_error(anchor_errors, anchor.get("contains_hidden_state") is True, "anchor must declare contains_hidden_state")
    add_error(anchor_errors, anchor.get("campaign_id") == state.get("campaign", {}).get("id"), "anchor campaign_id does not match state")
    add_error(anchor_errors, anchor.get("state_revision") == state.get("runtime", {}).get("state_revision"), "anchor state_revision does not match state")
    add_error(anchor_errors, anchor.get("last_event_id") == state.get("runtime", {}).get("last_event_id"), "anchor last_event_id does not match state")
    add_error(anchor_errors, anchor.get("ruleset_version") == state.get("runtime", {}).get("ruleset_version") == "1.6", "anchor ruleset_version does not match state")
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
            output = {
                "status": "valid",
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
