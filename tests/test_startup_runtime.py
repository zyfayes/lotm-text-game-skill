from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import runtime_paths
import self_update


def run_git(directory: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def create_source(root: Path) -> Path:
    source = root / "source"
    source.mkdir()
    run_git(source, "init", "-b", "main")
    run_git(source, "config", "user.email", "test@example.invalid")
    run_git(source, "config", "user.name", "Updater Test")
    (source / "marker.txt").write_text("one\n", encoding="utf-8")
    run_git(source, "add", "marker.txt")
    run_git(source, "commit", "-m", "initial")
    return source


def advance_source(source: Path) -> str:
    (source / "marker.txt").write_text("two\n", encoding="utf-8")
    run_git(source, "add", "marker.txt")
    run_git(source, "commit", "-m", "update")
    return run_git(source, "rev-parse", "HEAD")


class RuntimePathTests(unittest.TestCase):
    def test_local_mode_uses_explicit_workspace_without_cwd_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "project"
            skill_dir = workspace / "skills" / "lotm-text-game"
            skill_dir.mkdir(parents=True)
            result = runtime_paths.resolve_runtime_paths(
                mode="local",
                skill_dir=skill_dir,
                workspace_root=workspace,
                environment={},
                create=True,
            )
            self.assertEqual(Path(result["campaigns_dir"]), (workspace / "campaigns").resolve())
            self.assertTrue((workspace / "campaigns").is_dir())
            self.assertEqual(result["source"], "workspace")

    def test_service_mode_requires_an_explicit_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill_dir = Path(temporary) / "skill"
            skill_dir.mkdir()
            with self.assertRaisesRegex(runtime_paths.RuntimePathError, "requires"):
                runtime_paths.resolve_runtime_paths(
                    mode="service",
                    skill_dir=skill_dir,
                    environment={},
                )

    def test_relative_data_root_is_rejected_instead_of_using_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skill_dir = Path(temporary) / "skill"
            skill_dir.mkdir()
            with self.assertRaisesRegex(runtime_paths.RuntimePathError, "absolute"):
                runtime_paths.resolve_runtime_paths(
                    mode="service",
                    skill_dir=skill_dir,
                    data_root="relative-runtime-data",
                    environment={},
                )

    def test_environment_data_root_is_resolved_and_skill_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_dir = root / "skill"
            skill_dir.mkdir()
            data_root = root / "runtime-data"
            result = runtime_paths.resolve_runtime_paths(
                mode="service",
                skill_dir=skill_dir,
                environment={runtime_paths.DATA_ROOT_ENV: str(data_root)},
            )
            self.assertEqual(Path(result["data_root"]), data_root.resolve())
            self.assertEqual(result["source"], "environment")
            with self.assertRaisesRegex(runtime_paths.RuntimePathError, "skill directory"):
                runtime_paths.resolve_runtime_paths(
                    mode="service",
                    skill_dir=skill_dir,
                    data_root=skill_dir,
                    environment={},
                )


class SelfUpdateTests(unittest.TestCase):
    def test_clean_git_install_fast_forwards_verified_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            installed = root / "installed"
            subprocess.run(["git", "clone", "--quiet", str(source), str(installed)], check=True)
            expected = advance_source(source)

            result = self_update.check_and_update(
                installed,
                expected_repository=str(source),
                min_interval=0,
                candidate_validator=lambda candidate, timeout: None,
            )

            self.assertEqual(result["status"], "updated")
            self.assertTrue(result["reload_required"])
            self.assertEqual(result["current_commit"], expected)
            self.assertEqual((installed / "marker.txt").read_text(encoding="utf-8"), "two\n")

    def test_dirty_git_install_refuses_available_update(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            installed = root / "installed"
            subprocess.run(["git", "clone", "--quiet", str(source), str(installed)], check=True)
            advance_source(source)
            (installed / "marker.txt").write_text("local edit\n", encoding="utf-8")

            result = self_update.check_and_update(
                installed,
                expected_repository=str(source),
                min_interval=0,
                candidate_validator=lambda candidate, timeout: None,
            )

            self.assertEqual(result["status"], "blocked")
            self.assertIn("local changes", result["detail"])
            self.assertEqual((installed / "marker.txt").read_text(encoding="utf-8"), "local edit\n")

    def test_failed_candidate_validation_keeps_installed_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            installed = root / "installed"
            subprocess.run(["git", "clone", "--quiet", str(source), str(installed)], check=True)
            original = run_git(installed, "rev-parse", "HEAD")
            advance_source(source)

            def reject(candidate: Path, timeout: float) -> None:
                raise self_update.UpdateError("candidate rejected")

            result = self_update.check_and_update(
                installed,
                expected_repository=str(source),
                min_interval=0,
                candidate_validator=reject,
            )

            self.assertEqual(result["status"], "blocked")
            self.assertIn("candidate rejected", result["detail"])
            self.assertEqual(run_git(installed, "rev-parse", "HEAD"), original)
            self.assertEqual((installed / "marker.txt").read_text(encoding="utf-8"), "one\n")

    def test_recent_successful_check_uses_git_private_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            installed = root / "installed"
            subprocess.run(["git", "clone", "--quiet", str(source), str(installed)], check=True)

            first = self_update.check_and_update(
                installed,
                expected_repository=str(source),
                min_interval=300,
                now=1000,
                candidate_validator=lambda candidate, timeout: None,
            )
            second = self_update.check_and_update(
                installed,
                expected_repository=str(source),
                min_interval=300,
                now=1001,
                candidate_validator=lambda candidate, timeout: None,
            )

            self.assertEqual(first["status"], "current")
            self.assertEqual(second["status"], "cached_current")

    def test_copied_skill_does_not_attempt_destructive_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self_update.check_and_update(Path(temporary))
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "not_git_install")


if __name__ == "__main__":
    unittest.main()
