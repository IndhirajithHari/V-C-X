"""Comprehensive Integration & Gap Closure Tests for VCX v2.0 Architecture.

Covers:
1. Reference Transaction Log (reflog recording, reading, limits, and hooks).
2. Single-File Repository Bundles (.vcxpack creation, verification, CRC, tamper detection).
3. VCXEngine .vcxignore integration (untracked status filtering and directory add filtering).
4. Repository merge abort and rollback on conflicts (MERGE_HEAD / ORIG_HEAD lifecycle).
5. Programmatic fsck() verification on both VCXEngine and Repository.
6. CLI subcommand parity across cli.py and vcx.cli.main.
"""

from __future__ import annotations
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
import zipfile

import cli
from vcx.bundle import create_bundle, verify_bundle
from vcx.cli import main as vcx_main
from vcx.core.repository import Repository
from vcx.engine import VCXEngine
from vcx.reflog import ReflogEntry, read_reflog, record_reflog


class TestReflog(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_and_read_reflog(self):
        vcx_dir = self.repo_dir / ".vcx"
        vcx_dir.mkdir(parents=True)

        record_reflog(vcx_dir, "refs/heads/main", "0"*40, "a"*40, "commit", "Initial commit", timestamp=1000.0)
        record_reflog(vcx_dir, "refs/heads/main", "a"*40, "b"*40, "commit", "Second commit", timestamp=2000.0)

        head_entries = read_reflog(vcx_dir, "HEAD")
        self.assertEqual(len(head_entries), 2)
        # Newest first
        self.assertEqual(head_entries[0].new_sha, "b"*40)
        self.assertEqual(head_entries[0].message, "Second commit")
        self.assertEqual(head_entries[0].timestamp, 2000.0)
        self.assertEqual(head_entries[1].new_sha, "a"*40)

        main_entries = read_reflog(vcx_dir, "refs/heads/main")
        self.assertEqual(len(main_entries), 2)
        self.assertEqual(main_entries[0].new_sha, "b"*40)

        # Test limit
        limited = read_reflog(vcx_dir, "HEAD", limit=1)
        self.assertEqual(len(limited), 1)
        self.assertEqual(limited[0].new_sha, "b"*40)

    def test_engine_reflog_hooks(self):
        engine = VCXEngine.init(self.repo_dir)

        # 1. Commit hook
        (self.repo_dir / "code.py").write_text("print('hello')\n")
        engine.add(["code.py"])
        c1_sha, _ = engine.commit("Add code.py")

        entries = read_reflog(engine.vcx_dir, "HEAD")
        self.assertTrue(len(entries) >= 1)
        self.assertEqual(entries[0].action, "commit")
        self.assertEqual(entries[0].new_sha, c1_sha)
        self.assertEqual(entries[0].message, "Add code.py")

        # 2. Branch hook
        engine.create_branch("feature-1")
        branch_entries = read_reflog(engine.vcx_dir, "refs/heads/feature-1")
        self.assertEqual(len(branch_entries), 1)
        self.assertEqual(branch_entries[0].action, "branch")
        self.assertEqual(branch_entries[0].new_sha, c1_sha)

        # 3. Checkout hook
        engine.checkout("feature-1")
        head_entries = read_reflog(engine.vcx_dir, "HEAD")
        self.assertEqual(head_entries[0].action, "checkout")
        self.assertIn("feature-1", head_entries[0].message)

        # 4. Reset hook
        (self.repo_dir / "temp.txt").write_text("temp\n")
        engine.add(["temp.txt"])
        engine.reset(["temp.txt"])
        head_entries = read_reflog(engine.vcx_dir, "HEAD")
        self.assertEqual(head_entries[0].action, "reset")

    def test_repo_reflog_hooks(self):
        repo = Repository.init(self.repo_dir)
        (self.repo_dir / "notes.md").write_text("# Notes\n")
        repo.add(["notes.md"])
        c1_sha, _ = repo.commit("Initial notes")

        entries = read_reflog(repo.vcx_dir, "HEAD")
        self.assertTrue(len(entries) >= 1)
        self.assertEqual(entries[0].action, "commit")
        self.assertEqual(entries[0].new_sha, c1_sha)

        repo.create_branch("docs")
        repo.checkout("docs")
        entries = read_reflog(repo.vcx_dir, "HEAD")
        self.assertEqual(entries[0].action, "checkout")


class TestBundle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir) / "repo"
        self.bundle_dir = Path(self.temp_dir) / "bundles"
        self.bundle_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_and_verify_bundle_engine(self):
        engine = VCXEngine.init(self.repo_dir)
        (self.repo_dir / "file1.txt").write_text("Hello VCX Bundle\n")
        engine.add(["file1.txt"])
        engine.commit("First commit")

        bundle_path = self.bundle_dir / "engine_backup.vcxpack"
        out_path = create_bundle(engine, bundle_path)
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path, bundle_path)

        # Verify bundle contents
        with zipfile.ZipFile(bundle_path, "r") as zf:
            self.assertIn("bundle_manifest.json", zf.namelist())
            manifest = json.loads(zf.read("bundle_manifest.json").decode("utf-8"))
            self.assertEqual(manifest["format"], "VCXPACK-v1")
            self.assertIn("refs/heads/main", manifest["refs"])

        # Programmatic verification
        is_valid, errors = verify_bundle(bundle_path)
        self.assertTrue(is_valid, f"Verification failed with errors: {errors}")
        self.assertEqual(errors, [])

    def test_create_and_verify_bundle_repo(self):
        repo = Repository.init(self.repo_dir)
        (self.repo_dir / "data.json").write_text('{"key": "value"}')
        repo.add(["data.json"])
        repo.commit("Add data.json")

        bundle_path = self.bundle_dir / "repo_backup.vcxpack"
        create_bundle(repo, bundle_path)

        is_valid, errors = verify_bundle(bundle_path)
        self.assertTrue(is_valid, f"Verification failed: {errors}")
        self.assertEqual(errors, [])

    def test_bundle_corruption_detection(self):
        engine = VCXEngine.init(self.repo_dir)
        (self.repo_dir / "test.dat").write_text("Integrity check test\n")
        engine.add(["test.dat"])
        engine.commit("Commit test.dat")

        bundle_path = self.bundle_dir / "tampered.vcxpack"
        create_bundle(engine, bundle_path)

        # Corrupt the zip file by corrupting bytes in the middle
        data = bytearray(bundle_path.read_bytes())
        # Corrupt 30 bytes in the middle
        mid = len(data) // 2
        data[mid:mid+30] = b"\x00" * 30
        bundle_path.write_bytes(bytes(data))

        is_valid, errors = verify_bundle(bundle_path)
        self.assertFalse(is_valid)
        self.assertTrue(len(errors) > 0)

    def test_bundle_missing_file_handling(self):
        non_existent = self.bundle_dir / "ghost.vcxpack"
        is_valid, errors = verify_bundle(non_existent)
        self.assertFalse(is_valid)
        self.assertIn("does not exist", errors[0])

    def test_bundle_filter_refs(self):
        engine = VCXEngine.init(self.repo_dir)
        (self.repo_dir / "f.txt").write_text("base\n")
        engine.add(["f.txt"])
        c1, _ = engine.commit("Base commit")

        engine.create_branch("dev")
        engine.create_branch("release")

        bundle_path = self.bundle_dir / "release_only.vcxpack"
        create_bundle(engine, bundle_path, refs=["release"])

        with zipfile.ZipFile(bundle_path, "r") as zf:
            manifest = json.loads(zf.read("bundle_manifest.json").decode("utf-8"))
            self.assertIn("refs/heads/release", manifest["refs"])
            self.assertNotIn("refs/heads/dev", manifest["refs"])


class TestVCXIgnoreEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_vcxignore_status_filtering(self):
        engine = VCXEngine.init(self.repo_dir)

        # Create .vcxignore
        (self.repo_dir / ".vcxignore").write_text("*.tmp\nbuild_out/\nsecret.key\n")

        # Create files
        (self.repo_dir / "keep.py").write_text("print('hello')\n")
        (self.repo_dir / "scratch.tmp").write_text("temp data\n")
        (self.repo_dir / "secret.key").write_text("private key\n")
        (self.repo_dir / "build_out").mkdir()
        (self.repo_dir / "build_out" / "binary.bin").write_bytes(b"\x01\x02\x03")

        st = engine.status()
        untracked = [u["path"] for u in st["untracked"]]

        self.assertIn("keep.py", untracked)
        self.assertIn(".vcxignore", untracked)
        self.assertNotIn("scratch.tmp", untracked)
        self.assertNotIn("secret.key", untracked)
        self.assertNotIn("build_out/binary.bin", untracked)

    def test_vcxignore_add_filtering(self):
        engine = VCXEngine.init(self.repo_dir)
        (self.repo_dir / ".vcxignore").write_text("*.log\ncache/\n")

        (self.repo_dir / "app.py").write_text("import os\n")
        (self.repo_dir / "debug.log").write_text("debug messages\n")
        (self.repo_dir / "cache").mkdir()
        (self.repo_dir / "cache" / "cached.dat").write_text("cache\n")

        # Stage directory
        staged = engine.add(["."])
        self.assertIn("app.py", staged)
        self.assertIn(".vcxignore", staged)
        self.assertNotIn("debug.log", staged)
        self.assertNotIn("cache/cached.dat", staged)

        # Commit and verify Merkle tree
        commit_sha, _ = engine.commit("Initial app commit")
        _, c_bytes = engine.storage.read_object(commit_sha)
        tree_sha = json.loads(c_bytes.decode("utf-8"))["tree_sha"]
        _, t_bytes = engine.storage.read_object(tree_sha)
        tree_map = json.loads(t_bytes.decode("utf-8"))

        self.assertIn("app.py", tree_map)
        self.assertNotIn("debug.log", tree_map)
        self.assertNotIn("cache/cached.dat", tree_map)


class TestMergeAbort(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_merge_abort_no_merge_in_progress(self):
        repo = Repository.init(self.repo_dir)
        (self.repo_dir / "f.txt").write_text("v1\n")
        repo.add(["f.txt"])
        repo.commit("Init")

        self.assertFalse(repo.merge_abort())

    def test_merge_abort_on_conflict(self):
        repo = Repository.init(self.repo_dir)

        # 1. Base commit
        shared_file = self.repo_dir / "shared.txt"
        shared_file.write_text("Line 1: base\nLine 2: base\nLine 3: base\n")
        repo.add(["shared.txt"])
        repo.commit("Base commit")

        # 2. Branch 'branch-feature'
        repo.create_branch("branch-feature")
        repo.checkout("branch-feature")
        shared_file.write_text("Line 1: feature branch edit\nLine 2: base\nLine 3: base\n")
        (self.repo_dir / "feature_only.txt").write_text("New file from feature\n")
        repo.add(["shared.txt", "feature_only.txt"])
        repo.commit("Feature commit")

        # 3. Modify on 'main' creating conflict
        repo.checkout("main")
        shared_file.write_text("Line 1: main branch collision\nLine 2: base\nLine 3: base\n")
        repo.add(["shared.txt"])
        repo.commit("Main commit")

        # 4. Attempt merge -> conflict
        result = repo.merge("branch-feature")
        self.assertFalse(result.success)
        self.assertTrue(len(result.conflicts) > 0)

        # Verify conflict tracking files exist
        merge_head = self.repo_dir / ".vcx" / "MERGE_HEAD"
        orig_head = self.repo_dir / ".vcx" / "ORIG_HEAD"
        self.assertTrue(merge_head.exists())
        self.assertTrue(orig_head.exists())

        # 5. Abort merge
        aborted = repo.merge_abort()
        self.assertTrue(aborted)

        # Verify tracking files are gone
        self.assertFalse(merge_head.exists())
        self.assertFalse(orig_head.exists())

        # Verify working tree is cleanly restored to main state
        self.assertEqual(shared_file.read_text(), "Line 1: main branch collision\nLine 2: base\nLine 3: base\n")
        self.assertFalse((self.repo_dir / "feature_only.txt").exists())

        # Verify reflog recorded the abort
        entries = read_reflog(repo.vcx_dir, "HEAD")
        self.assertEqual(entries[0].action, "merge")
        self.assertIn("abort", entries[0].message)


class TestProgrammaticFsck(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_engine_fsck(self):
        engine = VCXEngine.init(self.repo_dir)
        (self.repo_dir / "f1.txt").write_text("Alpha\n")
        (self.repo_dir / "f2.txt").write_text("Beta\n")
        engine.add(["f1.txt", "f2.txt"])
        engine.commit("Initial two files")

        report = engine.fsck(full=True)
        self.assertTrue(report["valid"])
        self.assertEqual(report["files_checked"], 2)
        self.assertTrue(report["chunks_checked"] >= 2)
        self.assertTrue(report["database_ok"])
        self.assertEqual(len(report["errors"]), 0)

    def test_repo_fsck(self):
        repo = Repository.init(self.repo_dir)
        (self.repo_dir / "model.step").write_text("ISO-10303-21;\nHEADER;\n")
        repo.add(["model.step"])
        repo.commit("Add STEP file")

        report = repo.fsck(full=True)
        self.assertTrue(report["valid"])
        self.assertTrue(report["refs_checked"] >= 1)
        self.assertTrue(report["commits_checked"] >= 1)
        self.assertTrue(report["trees_checked"] >= 1)
        self.assertTrue(report["blobs_checked"] >= 1)
        self.assertEqual(len(report["errors"]), 0)

    def test_repo_fsck_detects_corrupted_blob(self):
        repo = Repository.init(self.repo_dir)
        (self.repo_dir / "doc.txt").write_text("Original content\n")
        repo.add(["doc.txt"])
        repo.commit("Add doc.txt")

        # Corrupt the loose blob on disk
        entry = repo.index.get("doc.txt")
        blob_sha = entry.sha
        blob_path = repo.vcx_dir / "objects" / blob_sha[:2] / blob_sha[2:]
        self.assertTrue(blob_path.exists())
        blob_path.write_bytes(b"corrupted raw data")

        report = repo.fsck(full=True)
        self.assertFalse(report["valid"])
        self.assertTrue(len(report["errors"]) > 0)


class TestCLIPairing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir)
        self.old_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_reflog_and_bundle(self):
        # Test cli.py init, add, commit, reflog, bundle
        self.assertEqual(cli.main(["init"]), 0)
        (self.repo_dir / "test.txt").write_text("CLI test\n")
        self.assertEqual(cli.main(["add", "test.txt"]), 0)
        self.assertEqual(cli.main(["commit", "-m", "CLI commit"]), 0)

        # Reflog
        self.assertEqual(cli.main(["reflog"]), 0)

        # Bundle create & verify
        bundle_file = str(self.repo_dir / "cli_bundle.vcxpack")
        self.assertEqual(cli.main(["bundle", "create", bundle_file]), 0)
        self.assertEqual(cli.main(["bundle", "verify", bundle_file]), 0)

        # Main CLI parity
        self.assertEqual(vcx_main.main(["reflog"]), 0)
        self.assertEqual(vcx_main.main(["bundle", "verify", bundle_file]), 0)


if __name__ == "__main__":
    unittest.main()
