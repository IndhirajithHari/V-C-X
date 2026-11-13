"""Unit tests for Native VCX Standalone Features (Config, Tags, Reset, Show, .vcxignore, Git Importer)."""

from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from vcx.bridge.git_importer import GitImporter
from vcx.core.config import ConfigManager
from vcx.core.repository import Repository


class TestNativeFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vcx_native_test_")
        self.base_path = Path(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_native_config_manager(self):
        repo_dir = self.base_path / "repo_cfg"
        repo = Repository.init(repo_dir)

        # Set and get local config
        repo.config.set("user.name", "Indhirajith Hari")
        repo.config.set("user.email", "indhirajith@example.com")
        self.assertEqual(repo.config.get("user.name"), "Indhirajith Hari")
        self.assertEqual(repo.config.get("user.email"), "indhirajith@example.com")

        # Test commit uses configured author
        (repo_dir / "test.txt").write_text("hello\n")
        repo.add(["test.txt"])
        _, commit = repo.commit("Test commit with configured author")
        self.assertEqual(commit.author, "Indhirajith Hari <indhirajith@example.com>")

    def test_native_vcxignore(self):
        repo_dir = self.base_path / "repo_ignore"
        repo = Repository.init(repo_dir)

        # Create .vcxignore
        (repo_dir / ".vcxignore").write_text("*.tmp\nbuild_out/\nsecret.key\n")

        # Create files
        (repo_dir / "keep.py").write_text("print('hello')\n")
        (repo_dir / "scratch.tmp").write_text("temp\n")
        (repo_dir / "secret.key").write_text("secret\n")
        (repo_dir / "build_out").mkdir()
        (repo_dir / "build_out" / "binary.bin").write_bytes(b"\x00\x01\x02")

        status = repo.status()
        untracked = [u["path"] for u in status["untracked"]]

        self.assertIn("keep.py", untracked)
        self.assertNotIn("scratch.tmp", untracked)
        self.assertNotIn("secret.key", untracked)
        self.assertNotIn("build_out/binary.bin", untracked)

    def test_native_reset_unstage(self):
        repo_dir = self.base_path / "repo_reset"
        repo = Repository.init(repo_dir)

        (repo_dir / "file1.txt").write_text("v1\n")
        repo.add(["file1.txt"])
        repo.commit("Commit 1")

        # Modify file1 and add new file2
        (repo_dir / "file1.txt").write_text("v2\n")
        (repo_dir / "file2.txt").write_text("new\n")
        repo.add(["file1.txt", "file2.txt"])

        st = repo.status()
        self.assertEqual(len(st["staged"]), 2)

        # Reset specific file
        repo.reset(["file2.txt"])
        st_after = repo.status()
        staged_paths = [s["path"] for s in st_after["staged"]]
        self.assertIn("file1.txt", staged_paths)
        self.assertNotIn("file2.txt", staged_paths)

        # Reset all
        repo.reset()
        st_final = repo.status()
        self.assertEqual(len(st_final["staged"]), 0)

    def test_native_tags(self):
        repo_dir = self.base_path / "repo_tag"
        repo = Repository.init(repo_dir)

        (repo_dir / "code.v").write_text("module top; endmodule\n")
        repo.add(["code.v"])
        c1, _ = repo.commit("Commit for release")

        # Create tags
        repo.create_tag("v1.0.0")
        repo.create_tag("release-alpha", target_sha=c1)

        tags = repo.list_tags()
        self.assertEqual(tags, ["release-alpha", "v1.0.0"])

        # Resolve ref
        resolved = repo.resolve_ref("v1.0.0")
        self.assertEqual(resolved, c1)

    def test_git_importer_bridge(self):
        # Create a git repo
        git_dir = self.base_path / "git_source"
        git_dir.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=git_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=git_dir, check=True)
        subprocess.run(["git", "config", "user.email", "user@test.local"], cwd=git_dir, check=True)

        (git_dir / "chip.v").write_text("module chip; endmodule\n")
        subprocess.run(["git", "add", "chip.v"], cwd=git_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Add Verilog chip"], cwd=git_dir, check=True)

        (git_dir / "chassis.step").write_text("ISO-10303-21; DATA; #1=CARTESIAN_POINT('', (0,0,0)); ENDSEC; END-ISO-10303-21;\n")
        subprocess.run(["git", "add", "chassis.step"], cwd=git_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Add chassis CAD model"], cwd=git_dir, check=True)
        subprocess.run(["git", "tag", "v0.1.0"], cwd=git_dir, check=True)

        # Convert to native VCX
        importer = GitImporter(git_dir)
        vcx_repo = importer.import_to_vcx(semantic_enrichment=True)

        # Verify VCX repository structure exists
        self.assertTrue((git_dir / ".vcx").exists())
        self.assertIsNotNone(vcx_repo.head_commit_sha)

        # Verify commits in VCX
        log = vcx_repo.log()
        self.assertEqual(len(log), 2)
        self.assertEqual(log[0][1].message, "Add chassis CAD model")
        self.assertEqual(log[1][1].message, "Add Verilog chip")

        # Verify tag migrated
        self.assertIn("v0.1.0", vcx_repo.list_tags())

        # Verify working tree status in native VCX
        st = vcx_repo.status()
        self.assertEqual(len(st["unstaged"]), 0)


if __name__ == "__main__":
    unittest.main()
