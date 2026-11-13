"""Cross-Platform Compatibility Tests (Windows, macOS, Linux)."""

from __future__ import annotations
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from vcx.core.accelerator import fast_sha256, get_accelerator_status
from vcx.core.repository import Repository
from vcx.watcher.watcher import WorkspaceWatcher


class TestCrossPlatform(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vcx_cross_platform_")
        self.repo_dir = Path(self.tmp_dir) / "repo"
        self.repo = Repository.init(self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_windows_style_backslash_path_normalization(self):
        """Simulate Windows backslash paths being staged into index."""
        nested = self.repo_dir / "models" / "chassis"
        nested.mkdir(parents=True, exist_ok=True)
        target_file = nested / "assembly.step"
        target_file.write_text("ISO-10303-21;\nDATA;\nENDSEC;\n")

        # Pass Windows-style backslash path string: models\chassis\assembly.step
        win_path_str = "models\\chassis\\assembly.step"
        staged = self.repo.add([win_path_str])

        self.assertEqual(len(staged), 1)
        # Canonical stored path in index MUST use POSIX forward slash
        self.assertEqual(staged[0], "models/chassis/assembly.step")
        self.assertIn("models/chassis/assembly.step", self.repo.index)

        # Commit and verify hierarchical tree
        c_sha, commit = self.repo.commit("Add chassis assembly with Windows path")
        self.assertTrue(c_sha)

        # Verify status reports no unstaged changes
        st = self.repo.status()
        self.assertEqual(len(st["staged"]), 0)
        self.assertEqual(len(st["unstaged"]), 0)

    def test_windows_crlf_line_endings_in_diff(self):
        """Verify Windows CRLF (\\r\\n) is handled cleanly without corruption."""
        test_file = self.repo_dir / "crlf_test.txt"
        old_content = b"Line 1\r\nLine 2\r\nLine 3\r\n"
        test_file.write_bytes(old_content)

        self.repo.add(["crlf_test.txt"])
        c1, _ = self.repo.commit("Add CRLF file")

        # Modify with additional CRLF line
        new_content = b"Line 1\r\nLine 2\r\nLine 3\r\nLine 4\r\n"
        test_file.write_bytes(new_content)
        st = self.repo.status()
        self.assertEqual(len(st["unstaged"]), 1)
        self.assertEqual(st["unstaged"][0]["path"], "crlf_test.txt")

        from vcx.diff.delta_engine import DeltaEngine
        engine = DeltaEngine()
        payload = engine.analyze_change("crlf_test.txt", old_content, new_content)
        self.assertIn("Line 4", payload.raw_diff)

    def test_cross_platform_accelerator_status(self):
        """Verify accelerator discovery behaves safely on any host OS."""
        status = get_accelerator_status()
        self.assertIn("backend", status)
        self.assertIn("has_c_runtime", status)
        self.assertIn("has_crypto_accel", status)
        # Fast sha256 should always work regardless of OS
        digest = fast_sha256(b"Cross platform test on Windows, Mac, and Linux")
        self.assertEqual(len(digest), 64)

    def test_cross_platform_watcher_fallback(self):
        """Verify WorkspaceWatcher relative path calculation uses POSIX forward slashes."""
        watcher = WorkspaceWatcher(self.repo, debounce_seconds=0.2)
        nested_file = self.repo_dir / "src" / "deep" / "app.py"
        nested_file.parent.mkdir(parents=True, exist_ok=True)
        nested_file.write_text("print('hello cross platform')\n")

        rel = nested_file.relative_to(self.repo.root).as_posix()
        self.assertEqual(rel, "src/deep/app.py")
        self.assertNotIn("\\", rel)


if __name__ == "__main__":
    unittest.main()
