from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import check_markdown
import check_rules
import transport_contract


def capabilities(**overrides: object) -> dict:
    value = {
        "platform": "test-im",
        "supports_raster_image": True,
        "supports_rich_text": True,
        "supports_buttons": True,
        "supports_message_edit": True,
        "max_text_chars": 80,
        "max_caption_chars": 40,
        "button_payload_bytes": 64,
    }
    value.update(overrides)
    return value


def envelope() -> dict:
    return {
        "event_id": "evt-000128",
        "state_revision": 128,
        "messages": [
            {"kind": "narrative", "body": "第一段。\n\n第二段包含已经提交的游戏事实。"},
            {
                "kind": "status_media",
                "media_ref": "media://status-128",
                "caption": "状态 128",
                "alt": "状态摘要",
                "fallback_text": "状态：健康；位置：廷根。",
            },
            {
                "kind": "choices",
                "body": "你也可以直接输入任何合理的自由行动。",
                "buttons": [
                    {"label": "检查门锁", "payload": "g:demo:128:1"},
                    {"label": "悄悄离开", "payload": "g:demo:128:2"},
                ],
            },
        ],
    }


class TransportCapabilityTests(unittest.TestCase):
    def test_no_image_uses_same_revision_fallback(self) -> None:
        planned = transport_contract.adapt_envelope(
            envelope(), capabilities(supports_raster_image=False)
        )
        self.assertEqual(planned["event_id"], "evt-000128")
        self.assertEqual(planned["state_revision"], 128)
        status = [message for message in planned["messages"] if message["kind"] == "status_fallback"]
        self.assertEqual([message["body"] for message in status], ["状态：健康；位置：廷根。"])
        self.assertFalse(any(message["kind"] == "media" for message in planned["messages"]))

    def test_no_buttons_keeps_each_numbered_option_atomic(self) -> None:
        planned = transport_contract.adapt_envelope(
            envelope(), capabilities(supports_buttons=False, max_text_chars=20)
        )
        choices = [message for message in planned["messages"] if message["kind"] == "choice_fallback"]
        self.assertEqual([message["body"] for message in choices], ["1. 检查门锁", "2. 悄悄离开"])
        self.assertTrue(any("自由行动" in message.get("body", "") for message in planned["messages"]))
        self.assertTrue(all(len(message.get("body", "")) <= 20 for message in planned["messages"] if "body" in message))

    def test_choice_too_long_is_rejected_instead_of_split(self) -> None:
        source = envelope()
        source["messages"][-1]["buttons"][0]["label"] = "一段无法在平台限制内完整发送的选项文本"
        with self.assertRaisesRegex(transport_contract.TransportContractError, "cannot be split safely"):
            transport_contract.adapt_envelope(
                source, capabilities(supports_buttons=False, max_text_chars=12)
            )

    def test_media_timeout_does_not_mutate_committed_envelope(self) -> None:
        source = envelope()
        before = copy.deepcopy(source)
        outbox = {"event_id": source["event_id"], "state_revision": source["state_revision"], "status": "sending"}
        updated = transport_contract.reconcile_outbox(outbox, "timeout")
        self.assertEqual(source, before)
        self.assertEqual(updated["status"], "pending_unknown")
        self.assertEqual(updated["event_id"], source["event_id"])
        self.assertEqual(updated["state_revision"], source["state_revision"])

    def test_correction_becomes_new_message_when_editing_is_unavailable(self) -> None:
        source = {
            "event_id": "evt-000128",
            "state_revision": 128,
            "messages": [
                {
                    "kind": "correction",
                    "body": "更正：上一条消息的显示值有误；权威状态未改变。",
                    "target_message_id": "message-41",
                }
            ],
        }
        no_edit = transport_contract.adapt_envelope(source, capabilities(supports_message_edit=False))
        self.assertEqual(no_edit["messages"][0]["delivery_mode"], "new_message")
        editable = transport_contract.adapt_envelope(source, capabilities(supports_message_edit=True))
        self.assertEqual(editable["messages"][0]["delivery_mode"], "edit")
        self.assertEqual(editable["messages"][0]["target_message_id"], "message-41")

    def test_duplicate_ingress_is_accepted_only_once(self) -> None:
        ledger: dict = {}
        first = transport_contract.accept_ingress(ledger, "telegram:bot:a:0:user-a", "update:42", "evt-000128")
        second = transport_contract.accept_ingress(ledger, "telegram:bot:a:0:user-a", "update:42", "evt-999999")
        self.assertTrue(first["accepted"])
        self.assertFalse(second["accepted"])
        self.assertEqual(second["result_event_id"], "evt-000128")

    def test_scope_key_isolates_conversation_thread_and_controller(self) -> None:
        first = transport_contract.make_scope_key("telegram", "bot", "group", 7, "controller-a")
        second = transport_contract.make_scope_key("telegram", "bot", "group", 8, "controller-a")
        third = transport_contract.make_scope_key("telegram", "bot", "group", 7, "controller-b")
        self.assertEqual(len({first, second, third}), 3)

    def test_no_filesystem_planning_is_pure_and_in_memory(self) -> None:
        source = envelope()
        profile = capabilities(supports_raster_image=False, supports_buttons=False)
        before = json.dumps(source, ensure_ascii=False, sort_keys=True)
        planned = transport_contract.adapt_envelope(source, profile)
        self.assertEqual(json.dumps(source, ensure_ascii=False, sort_keys=True), before)
        self.assertEqual(planned["state_revision"], 128)


class PortabilityChecksTests(unittest.TestCase):
    def test_current_skill_markdown_is_portable(self) -> None:
        self.assertEqual(check_markdown.scan_paths([SKILL_ROOT]), [])

    def test_checker_detects_im_risks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.md"
            path.write_text(
                "数值 10~20\n\n~~误删~~\n\n<div>raw</div>\n\n[缺失文件](missing.md)\n\n| A | B | C | D | E |\n|---|---|---|---|---|\n| 1 | 2 | 3 | 4 | 5 |\n\n```json\n{}\n",
                encoding="utf-8",
            )
            codes = {finding["code"] for finding in check_markdown.scan_file(path)}
            self.assertTrue({"ascii-range", "strikethrough-risk", "raw-html", "broken-link", "wide-table", "unclosed-fence"}.issubset(codes))

    def test_rules_manifest_covers_every_legacy_volume(self) -> None:
        self.assertEqual(check_rules.validate_rules(SKILL_ROOT / "references"), [])
