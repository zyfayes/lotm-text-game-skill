#!/usr/bin/env python3
"""Validate and adapt committed LOTM turn envelopes to transport capabilities."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote


EVENT_ID = re.compile(r"^evt-[0-9]{6,}$")
TEXT_KINDS = {"narrative", "adjudication", "choices", "correction", "status_text"}
OUTBOX_OUTCOMES = {"success", "definite_failure", "timeout"}


class TransportContractError(ValueError):
    """Raised when an envelope or capability profile is invalid."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TransportContractError(message)


def load_json(path: str) -> Any:
    if path == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise TransportContractError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise TransportContractError(f"invalid JSON in {path}: {exc}") from exc


def validate_capabilities(value: Any) -> Dict[str, Any]:
    require(isinstance(value, dict), "capabilities must be an object")
    required = {
        "platform",
        "supports_raster_image",
        "supports_rich_text",
        "supports_buttons",
        "supports_message_edit",
        "max_text_chars",
        "max_caption_chars",
        "button_payload_bytes",
    }
    missing = sorted(required - set(value))
    require(not missing, f"capabilities missing: {', '.join(missing)}")
    require(isinstance(value.get("platform"), str) and bool(value["platform"].strip()), "platform is required")
    for field in ("supports_raster_image", "supports_rich_text", "supports_buttons", "supports_message_edit"):
        require(isinstance(value.get(field), bool), f"{field} must be boolean")
    for field in ("max_text_chars", "max_caption_chars", "button_payload_bytes"):
        require(isinstance(value.get(field), int) and not isinstance(value.get(field), bool) and value[field] > 0, f"{field} must be positive")
    return value


def validate_button(value: Any, payload_limit: int) -> Dict[str, str]:
    require(isinstance(value, dict), "button must be an object")
    require(set(value) == {"label", "payload"}, "button must contain only label and payload")
    label, payload = value.get("label"), value.get("payload")
    require(isinstance(label, str) and bool(label.strip()), "button label is required")
    require(isinstance(payload, str) and bool(payload), "button payload is required")
    require(len(payload.encode("utf-8")) <= payload_limit, "button payload exceeds capability limit")
    return {"label": label, "payload": payload}


def validate_envelope(value: Any, payload_limit: int) -> Dict[str, Any]:
    require(isinstance(value, dict), "envelope must be an object")
    required = {"event_id", "state_revision", "messages"}
    missing = sorted(required - set(value))
    require(not missing, f"envelope missing: {', '.join(missing)}")
    require(isinstance(value.get("event_id"), str) and bool(EVENT_ID.fullmatch(value["event_id"])), "event_id is invalid")
    require(isinstance(value.get("state_revision"), int) and value["state_revision"] >= 1, "state_revision must be positive")
    messages = value.get("messages")
    require(isinstance(messages, list) and bool(messages), "messages must be a non-empty array")
    for index, message in enumerate(messages):
        require(isinstance(message, dict), f"messages/{index} must be an object")
        kind = message.get("kind")
        require(kind in TEXT_KINDS | {"status_media"}, f"messages/{index}/kind is invalid")
        if kind in TEXT_KINDS:
            require(isinstance(message.get("body"), str) and bool(message["body"].strip()), f"messages/{index}/body is required")
        else:
            require(isinstance(message.get("alt"), str) and bool(message["alt"].strip()), f"messages/{index}/alt is required")
            require(isinstance(message.get("fallback_text"), str) and bool(message["fallback_text"].strip()), f"messages/{index}/fallback_text is required")
            require(isinstance(message.get("caption", ""), str), f"messages/{index}/caption must be a string")
            media_ref = message.get("media_ref")
            require(media_ref is None or (isinstance(media_ref, str) and bool(media_ref.strip())), f"messages/{index}/media_ref is invalid")
        buttons = message.get("buttons", [])
        require(isinstance(buttons, list), f"messages/{index}/buttons must be an array")
        for button in buttons:
            validate_button(button, payload_limit)
        target_message_id = message.get("target_message_id")
        require(
            target_message_id is None or (isinstance(target_message_id, str) and bool(target_message_id.strip())),
            f"messages/{index}/target_message_id is invalid",
        )
        require(target_message_id is None or kind == "correction", f"messages/{index}/target_message_id is only valid for correction")
    return value


def best_break(text: str, limit: int) -> int:
    window = text[:limit]
    candidates = []
    for separator in ("\n\n", "\n", "。", "！", "？", ". ", " "):
        position = window.rfind(separator)
        if position > 0:
            candidates.append(position + len(separator))
    return max(candidates) if candidates else limit


def split_text(text: str, limit: int) -> List[str]:
    require(isinstance(text, str), "text must be a string")
    require(isinstance(limit, int) and limit > 0, "limit must be positive")
    remaining = text.strip()
    if not remaining:
        return []
    parts: List[str] = []
    while len(remaining) > limit:
        cut = best_break(remaining, limit)
        part = remaining[:cut].rstrip()
        if not part:
            cut = limit
            part = remaining[:cut]
        parts.append(part)
        remaining = remaining[cut:].lstrip()
    if remaining:
        parts.append(remaining)
    require(all(0 < len(part) <= limit for part in parts), "text splitting exceeded the configured limit")
    return parts


def numbered_choices(buttons: Iterable[Dict[str, str]]) -> str:
    return "\n".join(f"{index}. {button['label']}" for index, button in enumerate(buttons, 1))


def adapt_envelope(envelope: Any, capabilities: Any) -> Dict[str, Any]:
    profile = validate_capabilities(capabilities)
    source = validate_envelope(envelope, profile["button_payload_bytes"])
    planned: List[Dict[str, Any]] = []
    for source_index, message in enumerate(source["messages"]):
        kind = message["kind"]
        if kind == "status_media" and profile["supports_raster_image"] and message.get("media_ref"):
            caption = message.get("caption", "")
            require(isinstance(caption, str), f"messages/{source_index}/caption must be a string")
            require(len(caption) <= profile["max_caption_chars"], f"messages/{source_index}/caption exceeds capability limit")
            planned.append(
                {
                    "kind": "media",
                    "source_kind": kind,
                    "media_ref": message["media_ref"],
                    "caption": caption,
                    "alt": message["alt"],
                    "source_index": source_index,
                }
            )
            continue

        if kind == "status_media":
            body = message["fallback_text"]
            output_kind = "status_fallback"
            buttons: List[Dict[str, str]] = []
        else:
            body = message["body"]
            output_kind = kind
            buttons = [validate_button(button, profile["button_payload_bytes"]) for button in message.get("buttons", [])]

        fallback_choice_lines: List[str] = []
        if buttons and not profile["supports_buttons"]:
            fallback_choice_lines = numbered_choices(buttons).splitlines()
            for choice_line in fallback_choice_lines:
                require(
                    len(choice_line) <= profile["max_text_chars"],
                    "numbered choice exceeds max_text_chars and cannot be split safely",
                )
            buttons = []

        chunks = split_text(body, profile["max_text_chars"])
        for chunk_index, chunk in enumerate(chunks):
            output: Dict[str, Any] = {
                "kind": output_kind,
                "body": chunk,
                "format": "rich_text" if profile["supports_rich_text"] else "text",
                "source_index": source_index,
                "chunk_index": chunk_index,
            }
            if kind == "correction":
                target_message_id = message.get("target_message_id")
                if profile["supports_message_edit"] and target_message_id is not None and len(chunks) == 1:
                    output["delivery_mode"] = "edit"
                    output["target_message_id"] = target_message_id
                else:
                    output["delivery_mode"] = "new_message"
            if buttons and chunk_index == len(chunks) - 1:
                output["buttons"] = buttons
            planned.append(output)

        for choice_index, choice_line in enumerate(fallback_choice_lines, 1):
            planned.append(
                {
                    "kind": "choice_fallback",
                    "body": choice_line,
                    "format": "text",
                    "source_index": source_index,
                    "choice_index": choice_index,
                }
            )

    return {
        "event_id": source["event_id"],
        "state_revision": source["state_revision"],
        "platform": profile["platform"],
        "messages": planned,
        "optional_media_offer": copy.deepcopy(source.get("optional_media_offer")),
    }


def scope_component(value: Any, field: str) -> str:
    require(value is not None and isinstance(value, (str, int)), f"{field} is required")
    text = str(value)
    require(bool(text), f"{field} is required")
    return quote(text, safe="-_.")


def make_scope_key(
    platform: Any,
    agent_id: Any,
    conversation_id: Any,
    thread_id: Any,
    player_scope: Any,
) -> str:
    thread = 0 if thread_id in (None, "", 0, "0") else thread_id
    return ":".join(
        (
            scope_component(platform, "platform"),
            scope_component(agent_id, "agent_id"),
            scope_component(conversation_id, "conversation_id"),
            scope_component(thread, "thread_id"),
            scope_component(player_scope, "player_scope"),
        )
    )


def accept_ingress(
    processed: Dict[Tuple[str, str], Optional[str]],
    scope_key: str,
    ingress_id: str,
    result_event_id: Optional[str] = None,
) -> Dict[str, Any]:
    require(isinstance(processed, dict), "processed ingress ledger must be a mapping")
    require(isinstance(scope_key, str) and bool(scope_key), "scope_key is required")
    require(isinstance(ingress_id, str) and bool(ingress_id), "ingress_id is required")
    key = (scope_key, ingress_id)
    if key in processed:
        return {"accepted": False, "duplicate": True, "result_event_id": processed[key]}
    processed[key] = result_event_id
    return {"accepted": True, "duplicate": False, "result_event_id": result_event_id}


def reconcile_outbox(item: Any, outcome: str, platform_message_id: Optional[str] = None) -> Dict[str, Any]:
    require(isinstance(item, dict), "outbox item must be an object")
    require(outcome in OUTBOX_OUTCOMES, "outbox outcome is invalid")
    updated = copy.deepcopy(item)
    if outcome == "success":
        require(isinstance(platform_message_id, str) and bool(platform_message_id), "success requires platform_message_id")
        updated["status"] = "delivered"
        updated["platform_message_id"] = platform_message_id
    elif outcome == "definite_failure":
        updated["status"] = "retryable"
        updated["platform_message_id"] = None
    else:
        updated["status"] = "pending_unknown"
        updated["platform_message_id"] = None
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="adapt a committed output envelope")
    plan.add_argument("--envelope", required=True, help="JSON path or - for stdin")
    plan.add_argument("--capabilities", required=True, help="JSON path")
    scope = subparsers.add_parser("scope-key", help="build a stable campaign scope key")
    scope.add_argument("--platform", required=True)
    scope.add_argument("--agent-id", required=True)
    scope.add_argument("--conversation-id", required=True)
    scope.add_argument("--thread-id", default="0")
    scope.add_argument("--player-scope", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "plan":
            output = adapt_envelope(load_json(args.envelope), load_json(args.capabilities))
        else:
            output = {
                "scope_key": make_scope_key(
                    args.platform,
                    args.agent_id,
                    args.conversation_id,
                    args.thread_id,
                    args.player_scope,
                )
            }
    except (TransportContractError, OSError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
