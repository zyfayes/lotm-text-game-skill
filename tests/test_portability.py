from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import check_markdown
import check_rules


class PortabilityChecksTests(unittest.TestCase):
    def test_current_skill_markdown_is_portable(self) -> None:
        self.assertEqual(check_markdown.scan_paths([SKILL_ROOT]), [])

    def test_checker_detects_portability_risks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.md"
            path.write_text(
                "数值 10~20\n\n~~误删~~\n\n<div>raw</div>\n\n[缺失文件](missing.md)\n\n"
                "| A | B | C | D | E |\n|---|---|---|---|---|\n| 1 | 2 | 3 | 4 | 5 |\n\n```json\n{}\n",
                encoding="utf-8",
            )
            codes = {finding["code"] for finding in check_markdown.scan_file(path)}
            expected = {"ascii-range", "strikethrough-risk", "raw-html", "broken-link", "wide-table", "unclosed-fence"}
            self.assertTrue(expected.issubset(codes))

    def test_rules_manifest_covers_every_required_section(self) -> None:
        self.assertEqual(check_rules.validate_rules(SKILL_ROOT / "references"), [])

    def test_runtime_loading_profile_is_digest_bound(self) -> None:
        reference_dir = SKILL_ROOT / "references"
        manifest = check_rules.load_manifest(reference_dir)
        loading = manifest["runtime_loading"]
        self.assertEqual(manifest["always_read_for_adjudication"], ["runtime-core.md"])
        self.assertEqual(
            loading["ruleset_digest"],
            check_rules.build_ruleset_digest(
                reference_dir,
                manifest["ruleset_version"],
                loading["profile_id"],
                loading["cache_files"],
            ),
        )

    def test_runtime_core_drift_invalidates_cached_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "references"
            shutil.copytree(SKILL_ROOT / "references", copied)
            runtime_core = copied / "runtime-core.md"
            runtime_core.write_text(runtime_core.read_text(encoding="utf-8") + "\n缓存漂移测试。\n", encoding="utf-8")
            errors = check_rules.validate_rules(copied)
            self.assertIn("runtime_loading turn_core_sha256 differs from runtime core", errors)
            self.assertIn("runtime_loading ruleset_digest differs from cached rule files", errors)


if __name__ == "__main__":
    unittest.main()
