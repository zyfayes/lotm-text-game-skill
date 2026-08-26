#!/usr/bin/env python3
"""Regression tests for v1.6 odds, RNG, schemas, transactions, and recovery."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import campaign_runtime  # noqa: E402
import roll_check  # noqa: E402


def initial_state(campaign_id: str = "lotm-test") -> dict:
    return {
        "runtime": {
            "schema_version": "1.6",
            "state_revision": 1,
            "last_event_id": "evt-000001",
            "updated_at": "2026-08-26T00:00:00+00:00",
            "ruleset_version": "1.6",
            "panel_renderer": "text",
            "panel_template_version": "3.1-engraved",
            "rng": {"method": "system_csprng", "next_counter": 0, "seed_commitment": None},
        },
        "campaign": {
            "id": campaign_id,
            "status": "active",
            "turn": 0,
            "world_time": "1349-06-28 19:00",
            "location": "廷根市",
            "difficulty": "普通",
            "mode_modifier": 0,
            "opportunity_counter": 0,
            "pacing_profile": "标准",
            "chapter": 1,
            "meaningful_scenes": 0,
        },
        "player": {
            "name": "测试者",
            "gender": "男",
            "background": "测试背景",
            "identity": "普通市民",
            "pathway": "未选择",
            "sequence": "凡人",
            "acting": "不适用",
            "attributes": {"physique": 45, "inspiration": 45, "mind": 45, "charm": 45},
            "luck": {"base": 50, "current": 50, "modifiers": []},
            "spirituality": {"current": 10, "max": 10},
            "sanity": 100,
            "pollution": 0,
            "states": {"body": "健康", "mind": "清醒", "effects": []},
            "skills": {"values": {"侦查": 10}, "marks": {}},
            "money": {"pounds": 1, "soli": 0, "pence": 0},
            "inventory": [],
            "sealed_items": [],
        },
        "relations": [],
        "plot": {
            "life_goal": {
                "id": None,
                "text": None,
                "category": None,
                "status": "pending",
                "success_conditions": [],
                "progress_summary": None,
                "change_conditions": [],
                "chosen_at_event_id": None,
                "criteria_met_at_event_id": None,
            },
            "completed_goals": [],
            "main": "开始测试",
            "current_action": "观察街道",
            "open_threads": [],
            "clues": [],
            "investigations": [],
            "deadlines": [],
        },
        "causality": [],
        "world": {"canon_anchor_status": "正典起点", "changed_events": [], "faction_clocks": [], "known_npc_states": []},
        "knowledge": {"character_known": [], "engine_truth": [], "game_supplements": []},
        "discipline": {"cheat_level": 0, "heaven_brand": False, "warnings": []},
        "visuals": {},
        "roll_log": [],
    }


def initial_event() -> dict:
    return {
        "event_id": "evt-000001",
        "type": "campaign_created",
        "previous_state_revision": 0,
        "state_revision": 1,
        "world_time": "1349-06-28 19:00",
        "action": "创建测试战役",
        "stakes": None,
        "roll": None,
        "consequences": [],
        "state_patch": [],
        "visible_result": "战役建立。",
        "created_at": "2026-08-26T00:00:00+00:00",
    }


def rolled_event() -> dict:
    check = roll_check.adjudicate(50, "ordinary", 100, 45, 10, [])
    roll = {
        "rng_method": "system_csprng",
        "seed_commitment": None,
        "counter": None,
        "platform_result_id": None,
        "context": "evt-000002:观察街道",
        "raw": check["raw"],
        "attribute": check["attribute"],
        "skill": check["skill"],
        "mode_modifier": check["mode_modifier"],
        "situational_modifiers": check["situational_modifiers"],
        "total": check["total"],
        "target": check["target"],
        "base_result": check["base_result"],
        "final_result": check["final_result"],
        "overflow_edge": check["overflow_edge"],
    }
    record = {
        "event_id": "evt-000002",
        "context": roll["context"],
        "rng_method": roll["rng_method"],
        "counter": None,
        "seed_commitment": None,
        "platform_result_id": None,
        "raw": roll["raw"],
        "formula": check["formula"],
        "target": roll["target"],
        "base_result": roll["base_result"],
        "final_result": roll["final_result"],
        "overflow_edge": roll["overflow_edge"],
    }
    clue = {
        "clue_id": "clue-street-mark",
        "statement": "墙上有一枚重复出现的粉笔记号。",
        "source": "亲眼观察",
        "confidence": "迹象",
        "status": "open",
        "discovered_event_id": "evt-000002",
        "linked_investigation_ids": [],
        "corroborating_clue_ids": [],
        "verification_basis": None,
    }
    return {
        "event_id": "evt-000002",
        "type": "action_resolved",
        "previous_state_revision": 1,
        "state_revision": 2,
        "world_time": "1349-06-28 19:05",
        "action": "观察街道",
        "stakes": {
            "intent": "发现异常",
            "approach": "从门廊观察",
            "target": 100,
            "risk_level": "轻微",
            "foreseeable_consequences": ["时间"],
            "public_modifiers": [],
        },
        "roll": roll,
        "consequences": [],
        "state_patch": [
            {"op": "replace", "path": "/campaign/turn", "old": 0, "value": 1},
            {"op": "replace", "path": "/campaign/world_time", "old": "1349-06-28 19:00", "value": "1349-06-28 19:05"},
            {"op": "add", "path": "/plot/clues/-", "value": clue},
            {"op": "add", "path": "/roll_log/-", "value": record},
        ],
        "visible_result": "你发现了墙上的粉笔记号。",
        "created_at": "2026-08-26T00:01:00+00:00",
    }


def third_event() -> dict:
    return {
        "event_id": "evt-000003",
        "type": "time_advanced",
        "previous_state_revision": 2,
        "state_revision": 3,
        "world_time": "1349-06-28 19:10",
        "action": "继续观察",
        "stakes": None,
        "roll": None,
        "consequences": [],
        "state_patch": [
            {"op": "replace", "path": "/campaign/turn", "old": 1, "value": 2},
            {"op": "replace", "path": "/campaign/world_time", "old": "1349-06-28 19:05", "value": "1349-06-28 19:10"},
        ],
        "visible_result": "五分钟过去了。",
        "created_at": "2026-08-26T00:02:00+00:00",
    }


class OddsAndRngTests(unittest.TestCase):
    def test_calibration_baseline(self) -> None:
        expected = {
            "favored": (91, 76, 1),
            "ordinary": (71, 56, 5),
            "hell": (56, 41, 25),
        }
        for mode, (partial, clean, critical_failure) in expected.items():
            result = roll_check.odds(mode, 100, 45, 10, [])
            self.assertEqual(result["partial_or_better_percent"], partial)
            self.assertEqual(result["clean_success_or_better_percent"], clean)
            self.assertEqual(result["distribution_percent"]["大失败"], critical_failure)

    def test_high_roll_overflow_edge(self) -> None:
        result = roll_check.adjudicate(100, "ordinary", 100, 45, 10, [])
        self.assertEqual(result["final_result"], "大成功")
        self.assertTrue(result["overflow_edge"])

    def test_deterministic_rng_is_repeatable(self) -> None:
        seed = bytes(range(32))
        first = roll_check.deterministic_d100(seed, 7, "evt-000008:test")
        second = roll_check.deterministic_d100(seed, 7, "evt-000008:test")
        self.assertEqual(first, second)
        self.assertGreaterEqual(first[0], 1)
        self.assertLessEqual(first[0], 100)

    def test_seed_creation_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            seed_path = Path(directory) / "seed.bin"
            metadata = roll_check.create_seed(seed_path)
            self.assertEqual(len(seed_path.read_bytes()), 32)
            self.assertEqual(metadata["seed_commitment"], roll_check.seed_commitment(seed_path.read_bytes()))
            self.assertEqual(os.stat(seed_path).st_mode & 0o777, 0o600)
            with self.assertRaises(roll_check.RollError):
                roll_check.create_seed(seed_path)

    def test_contract_schemas_are_valid_json(self) -> None:
        for name in ("campaign-state.schema.json", "campaign-event.schema.json", "portable-anchor.schema.json"):
            schema = json.loads((SKILL_ROOT / "references" / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")


class CampaignRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "initial-state.json"
        self.event_path = self.root / "initial-event.json"
        self.state_path.write_text(json.dumps(initial_state(), ensure_ascii=False), encoding="utf-8")
        self.event_path.write_text(json.dumps(initial_event(), ensure_ascii=False), encoding="utf-8")
        campaign_runtime.initialize_campaign(self.root / "campaigns", "lotm-test", self.state_path, self.event_path, True)
        self.campaign_dir = self.root / "campaigns" / "lotm-test"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_event(self, event: dict, name: str) -> Path:
        path = self.root / name
        path.write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
        return path

    def test_commit_is_atomic_and_idempotent(self) -> None:
        event = rolled_event()
        event_path = self.write_event(event, "event-2.json")
        result = campaign_runtime.commit_event(self.campaign_dir, event_path)
        self.assertEqual(result["status"], "committed")
        state, events = campaign_runtime.state_and_events(self.campaign_dir)
        self.assertEqual(state["runtime"]["state_revision"], 2)
        self.assertEqual(state["campaign"]["turn"], 1)
        self.assertEqual(state["plot"]["clues"][0]["clue_id"], "clue-street-mark")
        self.assertEqual(len(events), 2)
        self.assertEqual(campaign_runtime.validate_consistency(state, events), [])

        duplicate = campaign_runtime.commit_event(self.campaign_dir, event_path)
        self.assertEqual(duplicate["status"], "already_committed")
        self.assertEqual(len(campaign_runtime.load_events(self.campaign_dir / "events.jsonl")), 2)

    def test_recovery_applies_recorded_patch_without_reroll(self) -> None:
        campaign_runtime.commit_event(self.campaign_dir, self.write_event(rolled_event(), "event-2.json"))
        event = third_event()
        campaign_runtime.append_event(self.campaign_dir / "events.jsonl", event)
        before = campaign_runtime.load_data(self.campaign_dir / "state.yaml")
        self.assertEqual(before["runtime"]["state_revision"], 2)

        with campaign_runtime.campaign_lock(self.campaign_dir):
            recovered = campaign_runtime.recover_locked(self.campaign_dir)
        self.assertEqual(recovered["status"], "recovered")
        after, events = campaign_runtime.state_and_events(self.campaign_dir)
        self.assertEqual(after["runtime"]["state_revision"], 3)
        self.assertEqual(after["campaign"]["turn"], 2)
        self.assertEqual(after["roll_log"][0]["raw"], 50)
        self.assertEqual(campaign_runtime.validate_consistency(after, events), [])

    def test_old_value_mismatch_is_rejected(self) -> None:
        event = rolled_event()
        event["state_patch"][0]["old"] = 99
        with self.assertRaises(campaign_runtime.RuntimeErrorDetail):
            campaign_runtime.commit_event(self.campaign_dir, self.write_event(event, "bad-event.json"))
        self.assertEqual(len(campaign_runtime.load_events(self.campaign_dir / "events.jsonl")), 1)

    def test_tampered_roll_calculation_is_rejected(self) -> None:
        event = rolled_event()
        event["roll"]["total"] += 20
        with self.assertRaises(campaign_runtime.RuntimeErrorDetail):
            campaign_runtime.commit_event(self.campaign_dir, self.write_event(event, "tampered-roll.json"))

    def test_platform_roll_requires_result_identifier(self) -> None:
        event = rolled_event()
        event["roll"]["rng_method"] = "platform_verified"
        errors = campaign_runtime.validate_event(event)
        self.assertTrue(any("platform_result_id" in error for error in errors))

    def test_failure_requires_a_disclosed_bounded_consequence(self) -> None:
        event = rolled_event()
        check = roll_check.adjudicate(20, "ordinary", 100, 45, 10, [])
        for field in ("raw", "attribute", "skill", "mode_modifier", "situational_modifiers", "total", "target", "base_result", "final_result", "overflow_edge"):
            event["roll"][field] = check[field]
        errors = campaign_runtime.validate_event(event)
        self.assertTrue(any("requires at least one committed consequence" in error for error in errors))

        event["consequences"] = [{"category": "污染", "severity": "灾难", "description": "无预兆的污染。"}]
        errors = campaign_runtime.validate_event(event)
        self.assertTrue(any("risk ceiling" in error for error in errors))
        self.assertTrue(any("not disclosed" in error for error in errors))

    def test_patch_cannot_shadow_runtime_metadata_or_use_negative_index(self) -> None:
        event = rolled_event()
        event["state_patch"] = [{"op": "replace", "path": "/runtime", "old": initial_state()["runtime"], "value": {}}]
        self.assertTrue(any("runtime-managed" in error for error in campaign_runtime.validate_event(event)))
        with self.assertRaises(campaign_runtime.RuntimeErrorDetail):
            campaign_runtime.apply_state_patch(initial_state(), [{"op": "remove", "path": "/plot/clues/-1", "old": {}}])

    def test_seeded_counter_is_checked_and_advanced(self) -> None:
        state = campaign_runtime.load_data(self.campaign_dir / "state.yaml")
        commitment = "a" * 64
        state["runtime"]["rng"] = {
            "method": "hmac_sha256_rejection_v1",
            "next_counter": 0,
            "seed_commitment": commitment,
        }
        campaign_runtime.atomic_write(self.campaign_dir / "state.yaml", state)
        event = rolled_event()
        event["roll"]["rng_method"] = "hmac_sha256_rejection_v1"
        event["roll"]["seed_commitment"] = commitment
        event["roll"]["counter"] = 0
        event["state_patch"][-1]["value"]["rng_method"] = "hmac_sha256_rejection_v1"
        event["state_patch"][-1]["value"]["counter"] = 0
        event["state_patch"][-1]["value"]["seed_commitment"] = commitment
        campaign_runtime.commit_event(self.campaign_dir, self.write_event(event, "seeded-event.json"))
        committed = campaign_runtime.load_data(self.campaign_dir / "state.yaml")
        self.assertEqual(committed["runtime"]["rng"]["next_counter"], 1)

    def test_portable_anchor_detects_tampering(self) -> None:
        campaign_runtime.commit_event(self.campaign_dir, self.write_event(rolled_event(), "event-2.json"))
        anchor_path = self.root / "anchor.json"
        campaign_runtime.export_anchor(self.campaign_dir, anchor_path, 20)
        verified = campaign_runtime.verify_anchor(anchor_path)
        self.assertEqual(verified["status"], "valid")

        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        anchor["authoritative_state"]["player"]["sanity"] = 1
        anchor_path.write_text(json.dumps(anchor, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(campaign_runtime.RuntimeErrorDetail):
            campaign_runtime.verify_anchor(anchor_path)

    def test_portable_anchor_rejects_recomputed_mismatched_metadata(self) -> None:
        anchor_path = self.root / "anchor-metadata.json"
        campaign_runtime.export_anchor(self.campaign_dir, anchor_path, 20)
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
        anchor["campaign_id"] = "another-campaign"
        unsigned = copy.deepcopy(anchor)
        del unsigned["integrity"]
        anchor["integrity"]["digest"] = campaign_runtime.canonical_digest(unsigned)
        anchor_path.write_text(json.dumps(anchor, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(campaign_runtime.RuntimeErrorDetail):
            campaign_runtime.verify_anchor(anchor_path)

    def test_goal_cannot_be_criteria_met_without_evidence(self) -> None:
        state = initial_state()
        state["plot"]["life_goal"] = {
            "id": "goal-survive",
            "text": "活过冬天",
            "category": "生存",
            "status": "criteria_met",
            "success_conditions": [
                {
                    "id": "condition-winter",
                    "description": "活到冬季结束",
                    "required": True,
                    "status": "met",
                    "evidence_event_ids": [],
                }
            ],
            "progress_summary": "",
            "change_conditions": [],
            "chosen_at_event_id": "evt-000001",
            "criteria_met_at_event_id": "evt-000001",
        }
        errors = campaign_runtime.validate_state(state)
        self.assertTrue(any("unmet required conditions" in error for error in errors))

    def test_confirmed_clue_requires_verification_basis(self) -> None:
        state = initial_state()
        state["plot"]["clues"] = [
            {
                "clue_id": "clue-confirmed",
                "statement": "门锁从内部打开。",
                "source": "现场",
                "confidence": "证实",
                "status": "resolved",
                "discovered_event_id": "evt-000001",
                "linked_investigation_ids": [],
                "corroborating_clue_ids": [],
                "verification_basis": None,
            }
        ]
        errors = campaign_runtime.validate_state(state)
        self.assertTrue(any("verification_basis" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
