from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_p0_runtime import initial_event as v16_initial_event
from test_p0_runtime import initial_state as v16_initial_state

import campaign_runtime


def initial_state() -> dict:
    state = copy.deepcopy(v16_initial_state("lotm-p1-test"))
    state["runtime"]["schema_version"] = "1.7"
    state["runtime"]["ruleset_version"] = "1.7"
    state["campaign"]["play_mode"] = "single_protagonist"
    state["social"] = {"statuses": [], "organizations": []}
    state["economy"] = {
        "accounting_unit": "pence",
        "settlement_period": "weekly",
        "next_settlement_at": "1349-07-05 19:00",
        "last_settlement_event_id": None,
        "income_streams": [],
        "recurring_costs": [],
        "debts": [],
        "scarcity": [],
    }
    state["commitments"] = []
    state["preferences"] = {
        "horror": "standard",
        "gore": "restrained",
        "romance": "ask",
        "canon_spoilers": "character_only",
        "hard_limits": [],
        "updated_at_event_id": "evt-000001",
    }
    state["plot"]["chapter"] = {
        "chapter_id": "chapter-001",
        "number": 1,
        "title": None,
        "status": "setup",
        "core_question": None,
        "pressure_source": None,
        "opened_at_event_id": "evt-000001",
        "meaningful_scene_start": 0,
    }
    state["plot"]["chapter_history"] = []
    state["knowledge"]["canon_records"] = []
    return state


def initial_event() -> dict:
    event = copy.deepcopy(v16_initial_event())
    event["schema_version"] = "1.7"
    event["ruleset_version"] = "1.7"
    return event


def next_event(event_type: str = "state_changed") -> dict:
    return {
        "schema_version": "1.7",
        "ruleset_version": "1.7",
        "event_id": "evt-000002",
        "type": event_type,
        "previous_state_revision": 1,
        "state_revision": 2,
        "world_time": "1349-06-28 19:00",
        "action": "应用一项长期状态变化",
        "stakes": None,
        "roll": None,
        "consequences": [],
        "state_patch": [],
        "visible_result": "状态已经更新。",
        "created_at": "2026-08-26T12:01:00+00:00",
    }


class P1StateContractTests(unittest.TestCase):
    def test_v15_is_recognized_as_legacy_read_only(self) -> None:
        state = copy.deepcopy(v16_initial_state("lotm-legacy-test"))
        state["runtime"]["schema_version"] = 1.5
        state["runtime"]["ruleset_version"] = "1.5"
        state["runtime"].pop("rng")
        event = {
            "event_id": "evt-000001",
            "type": "campaign_created",
            "state_revision": 1,
            "world_time": "1349-06-28 19:00",
            "action": "创建旧格式测试战役",
            "deltas": {"campaign.status": "active"},
            "roll": None,
            "created_at": "2026-08-26T12:00:00+00:00",
        }
        self.assertEqual(campaign_runtime.validate_consistency(state, [event]), [])
        with self.assertRaisesRegex(campaign_runtime.RuntimeErrorDetail, "legacy v1.5"):
            campaign_runtime.require_writable_version(
                campaign_runtime.state_contract_version(state), "commit"
            )
        with tempfile.TemporaryDirectory() as temporary:
            campaign_dir = Path(temporary) / "lotm-legacy-test"
            campaign_dir.mkdir()
            state_text = json.dumps(state, ensure_ascii=False)
            event_text = json.dumps(event, ensure_ascii=False) + "\n"
            (campaign_dir / "state.yaml").write_text(state_text, encoding="utf-8")
            (campaign_dir / "events.jsonl").write_text(event_text, encoding="utf-8")
            with self.assertRaisesRegex(campaign_runtime.RuntimeErrorDetail, "recovery is disabled"):
                campaign_runtime.recover_locked(campaign_dir)
            self.assertEqual((campaign_dir / "state.yaml").read_text(encoding="utf-8"), state_text)
            self.assertEqual((campaign_dir / "events.jsonl").read_text(encoding="utf-8"), event_text)

    def test_v17_baseline_is_valid_and_v16_remains_supported(self) -> None:
        self.assertEqual(campaign_runtime.validate_consistency(initial_state(), [initial_event()]), [])
        self.assertEqual(
            campaign_runtime.validate_consistency(v16_initial_state(), [v16_initial_event()]),
            [],
        )

    def test_v17_portable_anchor_uses_format_11(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign_dir = Path(temporary) / "lotm-p1-test"
            campaign_dir.mkdir()
            (campaign_dir / "state.yaml").write_text(
                json.dumps(initial_state(), ensure_ascii=False), encoding="utf-8"
            )
            (campaign_dir / "events.jsonl").write_text(
                json.dumps(initial_event(), ensure_ascii=False) + "\n", encoding="utf-8"
            )
            anchor_path = Path(temporary) / "anchor.json"
            campaign_runtime.export_anchor(campaign_dir, anchor_path, recent_events=1)
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            self.assertEqual(anchor["format_version"], "1.1")
            self.assertEqual(campaign_runtime.verify_anchor(anchor_path)["status"], "valid")

    def test_no_filesystem_anchor_can_be_built_in_memory(self) -> None:
        anchor = campaign_runtime.build_anchor(
            initial_state(),
            [initial_event()],
            recent_events=1,
            exported_at="2026-08-26T12:00:00+00:00",
        )
        self.assertEqual(anchor["format_version"], "1.1")
        self.assertEqual(anchor["authoritative_state"]["runtime"]["state_revision"], 1)
        unsigned = copy.deepcopy(anchor)
        del unsigned["integrity"]
        self.assertEqual(anchor["integrity"]["digest"], campaign_runtime.canonical_digest(unsigned))

    def test_npc_trust_does_not_grant_organization_permission(self) -> None:
        state = initial_state()
        state["relations"] = [
            {
                "npc": "某位主管",
                "level": "信赖",
                "evidence": "evt-000001",
                "last_interaction": "1349-06-28 19:00",
            }
        ]
        state["social"]["organizations"] = [
            {
                "organization_id": "org-watchers",
                "name": "某组织",
                "membership_status": "outsider",
                "rank": None,
                "title": None,
                "reputation": 20,
                "heat": 0,
                "permissions": [],
                "commitment_ids": [],
                "evidence_event_ids": ["evt-000001"],
                "last_changed_event_id": "evt-000001",
            }
        ]
        self.assertEqual(campaign_runtime.validate_consistency(state, [initial_event()]), [])
        self.assertEqual(state["social"]["organizations"][0]["permissions"], [])

    def test_organization_cannot_reference_missing_commitment(self) -> None:
        state = initial_state()
        state["social"]["organizations"] = [
            {
                "organization_id": "org-example",
                "name": "示例组织",
                "membership_status": "member",
                "rank": 1,
                "title": "见习成员",
                "reputation": 10,
                "heat": 0,
                "permissions": ["进入公共档案室"],
                "commitment_ids": ["commitment-missing"],
                "evidence_event_ids": ["evt-000001"],
                "last_changed_event_id": "evt-000001",
            }
        ]
        errors = campaign_runtime.validate_consistency(state, [initial_event()])
        self.assertTrue(any("unknown commitment" in error for error in errors))

    def test_breached_commitment_requires_event_evidence(self) -> None:
        state = initial_state()
        state["commitments"] = [
            {
                "commitment_id": "commitment-oath",
                "kind": "oath",
                "summary": "守住一个秘密",
                "parties": ["player", "npc-example"],
                "owed_by": "player",
                "owed_to": "npc-example",
                "terms": ["不得向第三方泄露"],
                "status": "breached",
                "due_at": None,
                "linked_organization_id": None,
                "evidence_event_ids": ["evt-000001"],
                "breach_event_id": None,
            }
        ]
        errors = campaign_runtime.validate_state(state)
        self.assertTrue(any("requires breach_event_id" in error for error in errors))

    def test_commitment_direction_must_name_two_recorded_parties(self) -> None:
        state = initial_state()
        state["commitments"] = [
            {
                "commitment_id": "commitment-favor",
                "kind": "favor",
                "summary": "偿还一次帮助",
                "parties": ["player", "npc-example"],
                "owed_by": "player",
                "owed_to": "npc-missing",
                "terms": ["在合理风险内提供一次协助"],
                "status": "open",
                "due_at": None,
                "linked_organization_id": None,
                "evidence_event_ids": ["evt-000001"],
                "breach_event_id": None,
            }
        ]
        errors = campaign_runtime.validate_state(state)
        self.assertTrue(any("owed_to must be a party" in error for error in errors))

    def test_content_preferences_are_explicit_and_validated(self) -> None:
        state = initial_state()
        state["preferences"]["canon_spoilers"] = "surprise_me"
        errors = campaign_runtime.validate_state(state)
        self.assertTrue(any("canon_spoilers" in error for error in errors))

    def test_canon_claim_cannot_be_declared_primary_without_source(self) -> None:
        state = initial_state()
        state["knowledge"]["canon_records"] = [
            {
                "claim_id": "claim-example",
                "claim": "一条精确设定",
                "canon_status": "primary_canon",
                "confidence": "high",
                "verification": "verified",
                "sources": [],
                "character_access": "unknown",
                "recorded_at_event_id": "evt-000001",
                "notes": None,
            }
        ]
        errors = campaign_runtime.validate_state(state)
        self.assertTrue(any("requires a source" in error for error in errors))

    def test_unknown_canon_claim_uses_no_confidence(self) -> None:
        state = initial_state()
        state["knowledge"]["canon_records"] = [
            {
                "claim_id": "claim-unknown",
                "claim": "尚无可靠依据的细节",
                "canon_status": "unknown",
                "confidence": "low",
                "verification": "unverified",
                "sources": [],
                "character_access": "unknown",
                "recorded_at_event_id": None,
                "notes": "等待核验",
            }
        ]
        errors = campaign_runtime.validate_state(state)
        self.assertTrue(any("confidence none" in error for error in errors))


class P1EventContractTests(unittest.TestCase):
    def test_economy_settlement_checks_arithmetic_and_balance(self) -> None:
        state = initial_state()
        state["economy"]["income_streams"] = [
            {
                "flow_id": "flow-wage",
                "name": "周薪",
                "amount_pence": 120,
                "cadence": "weekly",
                "next_due_at": "1349-07-05 19:00",
                "status": "active",
                "evidence_event_id": "evt-000001",
            }
        ]
        state["economy"]["recurring_costs"] = [
            {
                "flow_id": "flow-rent",
                "name": "周租",
                "amount_pence": 60,
                "cadence": "weekly",
                "next_due_at": "1349-07-05 19:00",
                "status": "active",
                "evidence_event_id": "evt-000001",
            }
        ]
        event = next_event("economy_settled")
        event["economy_settlement"] = {
            "period_start": "1349-06-28 19:00",
            "period_end": "1349-07-05 19:00",
            "income_pence": 120,
            "cost_pence": 60,
            "debt_payment_pence": 0,
            "net_pence": 60,
            "resulting_balance_pence": 300,
            "settled_flow_ids": ["flow-wage", "flow-rent"],
            "settled_debt_ids": [],
        }
        event["world_time"] = "1349-07-05 19:00"
        event["state_patch"] = [
            {"op": "replace", "path": "/campaign/world_time", "old": "1349-06-28 19:00", "value": "1349-07-05 19:00"},
            {"op": "replace", "path": "/player/money", "old": {"pounds": 1, "soli": 0, "pence": 0}, "value": {"pounds": 1, "soli": 5, "pence": 0}},
            {"op": "replace", "path": "/economy/last_settlement_event_id", "old": None, "value": "evt-000002"},
        ]
        updated = campaign_runtime.apply_state_patch(state, event["state_patch"])
        campaign_runtime.apply_runtime_metadata(state, updated, event)
        self.assertEqual(campaign_runtime.validate_consistency(updated, [initial_event(), event]), [])

        bad = copy.deepcopy(event)
        bad["economy_settlement"]["net_pence"] = 61
        self.assertTrue(any("net_pence" in error for error in campaign_runtime.validate_event(bad)))

    def test_chapter_close_requires_irreversible_change_and_next_question(self) -> None:
        state = initial_state()
        state["campaign"]["meaningful_scenes"] = 4
        state["plot"]["chapter"].update(
            {
                "title": "第一章",
                "status": "active",
                "core_question": "主角能否解决当前困境？",
                "pressure_source": "一个持续逼近的期限",
            }
        )
        event = next_event("chapter_closed")
        transition = {
            "closed_chapter_id": "chapter-001",
            "closed_number": 1,
            "resolution": "当前困境得到不可逆的回答。",
            "irreversible_changes": ["一个可见关系永久改变"],
            "updated_domains": ["relations"],
            "next_chapter": {
                "chapter_id": "chapter-002",
                "number": 2,
                "core_question": "主角将如何承担上一章的后果？",
                "pressure_source": "旧选择引发的新期限",
            },
        }
        event["chapter_transition"] = transition
        history_entry = {
            "chapter_id": "chapter-001",
            "number": 1,
            "title": "第一章",
            "core_question": "主角能否解决当前困境？",
            "resolution": transition["resolution"],
            "pressure_source": "一个持续逼近的期限",
            "irreversible_changes": transition["irreversible_changes"],
            "opened_at_event_id": "evt-000001",
            "closed_at_event_id": "evt-000002",
            "meaningful_scene_end": 4,
            "updated_domains": transition["updated_domains"],
        }
        next_chapter = {
            "chapter_id": "chapter-002",
            "number": 2,
            "title": None,
            "status": "active",
            "core_question": transition["next_chapter"]["core_question"],
            "pressure_source": transition["next_chapter"]["pressure_source"],
            "opened_at_event_id": "evt-000002",
            "meaningful_scene_start": 4,
        }
        event["state_patch"] = [
            {"op": "replace", "path": "/campaign/chapter", "old": 1, "value": 2},
            {"op": "replace", "path": "/plot/chapter", "old": state["plot"]["chapter"], "value": next_chapter},
            {"op": "add", "path": "/plot/chapter_history/-", "value": history_entry},
        ]
        updated = campaign_runtime.apply_state_patch(state, event["state_patch"])
        campaign_runtime.apply_runtime_metadata(state, updated, event)
        self.assertEqual(campaign_runtime.validate_consistency(updated, [initial_event(), event]), [])

        missing_history = copy.deepcopy(updated)
        missing_history["plot"]["chapter_history"] = []
        self.assertTrue(
            any(
                "missing from chapter_history" in error
                for error in campaign_runtime.validate_consistency(missing_history, [initial_event(), event])
            )
        )

        bad = copy.deepcopy(event)
        bad["chapter_transition"]["irreversible_changes"] = []
        self.assertTrue(any("irreversible_changes" in error for error in campaign_runtime.validate_event(bad)))


if __name__ == "__main__":
    unittest.main()
