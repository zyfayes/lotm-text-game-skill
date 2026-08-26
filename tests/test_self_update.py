from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import self_update


def run_git(directory: Path, *arguments: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=check,
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


def advance_source(source: Path, value: str = "two\n") -> str:
    (source / "marker.txt").write_text(value, encoding="utf-8")
    run_git(source, "add", "marker.txt")
    run_git(source, "commit", "-m", "update")
    return run_git(source, "rev-parse", "HEAD")


class SelfUpdateTests(unittest.TestCase):
    def test_clean_install_fast_forwards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            installed = root / "installed"
            subprocess.run(["git", "clone", "--quiet", str(source), str(installed)], check=True)
            expected = advance_source(source)

            result = self_update.check_and_update(installed)

            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["current_commit"], expected)
            self.assertEqual((installed / "marker.txt").read_text(encoding="utf-8"), "two\n")

    def test_dirty_install_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            installed = root / "installed"
            subprocess.run(["git", "clone", "--quiet", str(source), str(installed)], check=True)
            advance_source(source)
            (installed / "marker.txt").write_text("local edit\n", encoding="utf-8")

            result = self_update.check_and_update(installed)

            self.assertEqual(result["status"], "blocked")
            self.assertIn("local changes", result["reason"])
            self.assertEqual((installed / "marker.txt").read_text(encoding="utf-8"), "local edit\n")

    def test_non_fast_forward_is_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create_source(root)
            installed = root / "installed"
            subprocess.run(["git", "clone", "--quiet", str(source), str(installed)], check=True)
            run_git(installed, "config", "user.email", "test@example.invalid")
            run_git(installed, "config", "user.name", "Updater Test")
            (installed / "local.txt").write_text("local\n", encoding="utf-8")
            run_git(installed, "add", "local.txt")
            run_git(installed, "commit", "-m", "local commit")
            installed_head = run_git(installed, "rev-parse", "HEAD")
            advance_source(source)

            result = self_update.check_and_update(installed)

            self.assertEqual(result["status"], "blocked")
            self.assertIn("not a fast-forward", result["reason"])
            self.assertEqual(run_git(installed, "rev-parse", "HEAD"), installed_head)

    def test_copied_install_stays_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = self_update.check_and_update(Path(temporary))
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "not_git_install")


if __name__ == "__main__":
    unittest.main()
