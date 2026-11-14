"""Tier 1: Comprehensive Core Feature Coverage Test Suite.

Verifies all core VCX v2.0 capabilities in isolation:
- Repository Initialization & Configuration
- File Staging & Unstaging (Add & Reset)
- Merkle DAG Commit Lifecycle
- Status Queries & SQLite Staging Index
- History Logging & Traversal
- Stream Reconstruction & Checkout
- Branching, Tagging, and Reference Management
- Content-Defined Chunking & Manifest Generation
- Zstandard Object Storage & Deduplication
- Domain Adapters (FreeCAD, Verilog, STEP)
- Semantic 3-Way Merging
- Repository Integrity Diagnostics (fsck / verify)
- VID2 Packfile Archival & Garbage Collection
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import unittest
import zipfile

try:
    from tests.e2e.common import (
        VCXBaseTestCase,
        make_binary_file,
        make_fcstd_file,
        make_step_file,
        make_verilog_file,
        run_cli,
    )
except ImportError:
    try:
        from e2e.common import (
            VCXBaseTestCase,
            make_binary_file,
            make_fcstd_file,
            make_step_file,
            make_verilog_file,
            run_cli,
        )
    except ImportError:
        from common import (
            VCXBaseTestCase,
            make_binary_file,
            make_fcstd_file,
            make_step_file,
            make_verilog_file,
            run_cli,
        )

from vcx.adapters.eda_adapter import EDAAdapter
from vcx.adapters.freecad_adapter import FreeCADAdapter
from vcx.chunker import (
    EMPTY_CHUNK_SHA,
    FastCDCEngine,
    FileManifest,
    batch_chunk_files,
    chunk_bytes,
    chunk_file,
)
from vcx.core.object_store import ObjectStore
from vcx.core.pack import PackReader, PackWriter
from vcx.core.repository import Repository
from vcx.core.types import ObjectType
from vcx.diff.cad_engine import StepBrepParser
from vcx.diff.merger import SemanticMerger
from vcx.engine import VCXEngine
from vcx.index import Index, IndexRow
from vcx.storage import ObjectStorage


# ==============================================================================
# 1. Repository Initialization & Configuration
# ==============================================================================

class TestInitFeature(VCXBaseTestCase):
    """Test repository initialization and baseline directory structure."""

    def test_init_creates_vcx_directory_structure(self):
        engine = self.init_v2_repo()
        self.assertTrue((self.repo_dir / ".vcx").is_dir())
        self.assertTrue((self.repo_dir / ".vcx" / "objects").is_dir())
        self.assertTrue((self.repo_dir / ".vcx" / "refs" / "heads").is_dir())
        self.assertTrue((self.repo_dir / ".vcx" / "refs" / "tags").is_dir())

    def test_init_writes_default_head_ref(self):
        engine = self.init_v2_repo()
        head_file = self.repo_dir / ".vcx" / "HEAD"
        self.assertTrue(head_file.is_file())
        self.assertEqual(head_file.read_text(encoding="utf-8").strip(), "ref: refs/heads/main")
        self.assertEqual(engine.head_ref, "refs/heads/main")
        self.assertIsNone(engine.head_commit_sha)

    def test_init_creates_sqlite_index(self):
        engine = self.init_v2_repo()
        db_path = self.repo_dir / ".vcx" / "index.db"
        self.assertTrue(db_path.is_file())
        self.assertIsNotNone(engine.index)
        self.assertEqual(len(engine.index.entries()), 0)

    def test_init_idempotency(self):
        engine1 = self.init_v2_repo()
        self.write_file("keep.txt", "persisted data")
        engine1.add(["keep.txt"])
        sha1, _ = engine1.commit("Initial commit")

        # Re-initializing an existing repo must not wipe committed objects
        engine2 = VCXEngine.init(self.repo_dir)
        self.assertEqual(engine2.head_commit_sha, sha1)
        self.assertTrue(engine2.storage.has_object(sha1))

    def test_init_via_cli(self):
        code, out, err = self.run_cli_cmd(["init"])
        self.assertEqual(code, 0)
        self.assertTrue((self.repo_dir / ".vcx").is_dir())
        self.assertTrue((self.repo_dir / ".vcx" / "index.db").is_file())


# ==============================================================================
# 2. File Staging & Unstaging (Add & Reset)
# ==============================================================================

class TestAddAndStagingFeature(VCXBaseTestCase):
    """Test staging changes into the SQLite index with FastCDC."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_add_single_file(self):
        self.write_file("doc.txt", "VCX Architecture v2.0")
        staged = self.engine.add(["doc.txt"])
        self.assertIn("doc.txt", staged)

        entry = self.engine.index.get("doc.txt")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "staged")
        self.assertEqual(entry.size, 21)
        self.assertTrue(self.engine.storage.has_object(entry.manifest_hash))

    def test_add_multiple_files(self):
        self.write_file("a.txt", "file A")
        self.write_file("b.txt", "file B")
        self.write_file("c.txt", "file C")

        self.engine.add(["a.txt"])
        self.engine.add(["b.txt"])
        staged = self.engine.add(["c.txt"])
        self.assertIn("c.txt", staged)
        self.assertEqual(len(self.engine.index.staged_entries()), 3)

    def test_add_nested_directory_file(self):
        self.write_file("src/modules/core/logic.v", "module logic; endmodule")
        staged = self.engine.add(["src/modules/core/logic.v"])
        self.assertIn("src/modules/core/logic.v", staged)

        entry = self.engine.index.get("src/modules/core/logic.v")
        self.assertIsNotNone(entry)

    def test_add_unchanged_file_skips_rechunking(self):
        self.write_file("static.txt", "unchanged payload")
        self.engine.add(["static.txt"])
        first_entry = self.engine.index.get("static.txt")

        # Second add on identical file
        staged_again = self.engine.add(["static.txt"])
        second_entry = self.engine.index.get("static.txt")
        self.assertEqual(first_entry.manifest_hash, second_entry.manifest_hash)
        self.assertEqual(first_entry.mtime, second_entry.mtime)

    def test_add_modified_file_updates_index(self):
        self.write_file("config.json", '{"version": 1}')
        self.engine.add(["config.json"])
        hash1 = self.engine.index.get("config.json").manifest_hash

        # Modify file
        self.write_file("config.json", '{"version": 2, "updated": true}')
        self.engine.add(["config.json"])
        hash2 = self.engine.index.get("config.json").manifest_hash

        self.assertNotEqual(hash1, hash2)
        self.assertTrue(self.engine.storage.has_object(hash2))

    def test_add_via_cli(self):
        self.write_file("test.txt", "CLI staging content")
        code, out, err = self.run_cli_cmd(["add", "test.txt"])
        self.assertEqual(code, 0)
        self.assertIsNotNone(self.engine.index.get("test.txt"))


# ==============================================================================
# 3. Reset Feature
# ==============================================================================

class TestResetFeature(VCXBaseTestCase):
    """Test unstaging changes via reset."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_reset_single_staged_file(self):
        self.write_file("f1.txt", "content 1")
        self.write_file("f2.txt", "content 2")
        self.engine.add(["f1.txt"])
        self.engine.add(["f2.txt"])

        unstaged = self.engine.reset(["f1.txt"])
        self.assertIn("f1.txt", unstaged)
        self.assertEqual(self.engine.index.get("f1.txt").status, "unstaged")
        self.assertEqual(self.engine.index.get("f2.txt").status, "staged")

    def test_reset_all_staged_files(self):
        self.write_file("f1.txt", "content 1")
        self.write_file("f2.txt", "content 2")
        self.engine.add(["f1.txt"])
        self.engine.add(["f2.txt"])

        self.engine.reset()  # Unstage all
        self.assertEqual(len(self.engine.index.staged_entries()), 0)
        self.assertEqual(self.engine.index.get("f1.txt").status, "unstaged")
        self.assertEqual(self.engine.index.get("f2.txt").status, "unstaged")

    def test_reset_via_cli(self):
        self.write_file("f.txt", "content")
        self.engine.add(["f.txt"])
        self.assertEqual(len(self.engine.index.staged_entries()), 1)

        code, out, err = self.run_cli_cmd(["reset", "f.txt"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.engine.index.staged_entries()), 0)


# ==============================================================================
# 4. Merkle DAG Commit Lifecycle
# ==============================================================================

class TestCommitFeature(VCXBaseTestCase):
    """Test recording changes into the Merkle commit DAG."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_commit_creates_commit_and_tree_objects(self):
        self.write_file("hello.txt", "Hello World")
        self.engine.add(["hello.txt"])
        sha, payload = self.engine.commit("Initial hello commit")

        self.assertTrue(self.engine.storage.has_object(sha))
        tree_sha = payload["tree_sha"]
        self.assertTrue(self.engine.storage.has_object(tree_sha))

        # Check tree JSON content
        _, tree_bytes = self.engine.storage.read_object(tree_sha)
        tree_map = json.loads(tree_bytes.decode("utf-8"))
        self.assertIn("hello.txt", tree_map)
        self.assertEqual(tree_map["hello.txt"]["size"], 11)

    def test_commit_updates_head_ref(self):
        self.write_file("test.txt", "Data")
        self.engine.add(["test.txt"])
        sha, _ = self.engine.commit("Update test")

        self.assertEqual(self.engine.head_commit_sha, sha)
        head_file_content = (self.repo_dir / ".vcx" / "refs" / "heads" / "main").read_text().strip()
        self.assertEqual(head_file_content, sha)

    def test_commit_returns_sha_and_payload(self):
        self.write_file("data.bin", b"\x00\x01\x02\x03")
        self.engine.add(["data.bin"])
        sha, payload = self.engine.commit("Binary commit")

        self.assertEqual(len(sha), 64)
        self.assertEqual(payload["message"], "Binary commit")
        self.assertIn("author", payload)
        self.assertIn("timestamp", payload)
        self.assertEqual(payload["parent_shas"], [])

    def test_commit_empty_staging_raises_error(self):
        with self.assertRaises(ValueError):
            self.engine.commit("Should fail with empty staging")

    def test_commit_without_message_raises_error(self):
        self.write_file("a.txt", "text")
        self.engine.add(["a.txt"])
        with self.assertRaises(ValueError):
            self.engine.commit(message=None, auto=False)

    def test_commit_auto_generates_message(self):
        self.write_file("main.py", "def main():\n    return 42\n")
        self.engine.add(["main.py"])
        sha, payload = self.engine.commit(auto=True)
        self.assertTrue(payload["message"])
        self.assertTrue(self.engine.storage.has_object(sha))

    def test_commit_via_cli(self):
        self.write_file("cli_file.txt", "cli staged")
        self.engine.add(["cli_file.txt"])
        code, out, err = self.run_cli_cmd(["commit", "-m", "CLI commit"])
        self.assertEqual(code, 0)
        self.assertIsNotNone(self.engine.head_commit_sha)


# ==============================================================================
# 5. Status Queries & Staging State
# ==============================================================================

class TestStatusFeature(VCXBaseTestCase):
    """Test repository status queries under various working tree conditions."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_status_reports_untracked_files(self):
        self.write_file("untracked1.txt", "data 1")
        self.write_file("untracked2.txt", "data 2")
        st = self.engine.status()
        untracked_paths = [u["path"] for u in st["untracked"]]
        self.assertIn("untracked1.txt", untracked_paths)
        self.assertIn("untracked2.txt", untracked_paths)

    def test_status_reports_staged_new_files(self):
        self.write_file("new_file.txt", "content")
        self.engine.add(["new_file.txt"])
        st = self.engine.status()
        self.assertEqual(len(st["staged"]), 1)
        self.assertEqual(st["staged"][0]["path"], "new_file.txt")
        self.assertEqual(st["staged"][0]["type"], "new")

    def test_status_reports_staged_modified_files(self):
        self.write_file("doc.md", "# Heading 1")
        self.engine.add(["doc.md"])
        self.engine.commit("Commit v1")

        # Modify and stage
        self.write_file("doc.md", "# Heading 1\n## Heading 2")
        self.engine.add(["doc.md"])
        st = self.engine.status()
        self.assertEqual(len(st["staged"]), 1)
        self.assertEqual(st["staged"][0]["path"], "doc.md")
        self.assertEqual(len(st["unstaged"]), 0)

    def test_status_reports_unstaged_modifications(self):
        self.write_file("code.py", "x = 1\n")
        self.engine.add(["code.py"])
        self.engine.commit("Initial code")

        # Modify on disk but do not stage
        self.write_file("code.py", "x = 2\n")
        st = self.engine.status()
        unstaged_paths = [u["path"] for u in st["unstaged"]]
        self.assertIn("code.py", unstaged_paths)

    def test_status_reports_clean_working_tree(self):
        self.write_file("f.txt", "clean")
        self.engine.add(["f.txt"])
        self.engine.commit("Clean")
        self.assert_repo_clean()

    def test_status_via_cli(self):
        self.write_file("st.txt", "staged")
        self.engine.add(["st.txt"])
        code, out, err = self.run_cli_cmd(["status"])
        self.assertEqual(code, 0)
        self.assertIn("st.txt", out)


# ==============================================================================
# 6. History Logging & Traversal
# ==============================================================================

class TestLogFeature(VCXBaseTestCase):
    """Test log retrieval across sequential commits."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_log_empty_repo(self):
        log_entries = self.engine.log()
        self.assertEqual(log_entries, [])

    def test_log_single_commit(self):
        self.write_file("f.txt", "first")
        self.engine.add(["f.txt"])
        sha1, _ = self.engine.commit("First commit")

        history = self.engine.log()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["sha"], sha1)
        self.assertEqual(history[0]["message"], "First commit")

    def test_log_multiple_commits_reverse_chronological(self):
        self.write_file("f.txt", "1")
        self.engine.add(["f.txt"])
        sha1, _ = self.engine.commit("Commit 1")

        self.write_file("f.txt", "2")
        self.engine.add(["f.txt"])
        sha2, _ = self.engine.commit("Commit 2")

        self.write_file("f.txt", "3")
        self.engine.add(["f.txt"])
        sha3, _ = self.engine.commit("Commit 3")

        history = self.engine.log()
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["sha"], sha3)
        self.assertEqual(history[1]["sha"], sha2)
        self.assertEqual(history[2]["sha"], sha1)

    def test_log_limit_parameter(self):
        for i in range(5):
            self.write_file("f.txt", f"version {i}")
            self.engine.add(["f.txt"])
            self.engine.commit(f"Commit {i}")

        limited = self.engine.log(limit=2)
        self.assertEqual(len(limited), 2)
        self.assertEqual(limited[0]["message"], "Commit 4")
        self.assertEqual(limited[1]["message"], "Commit 3")

    def test_log_via_cli(self):
        self.write_file("test.txt", "test")
        self.engine.add(["test.txt"])
        self.engine.commit("CLI Log Verification")

        code, out, err = self.run_cli_cmd(["log"])
        self.assertEqual(code, 0)
        self.assertIn("CLI Log Verification", out)


# ==============================================================================
# 7. Stream Reconstruction & Checkout
# ==============================================================================

class TestCheckoutFeature(VCXBaseTestCase):
    """Test streaming file reconstruction and workspace restoration."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_checkout_reconstructs_single_file(self):
        payload = "Deterministic payload for checkout test\n"
        self.write_file("test.txt", payload)
        self.engine.add(["test.txt"])
        sha, _ = self.engine.commit("Commit test.txt")

        # Delete local working copy
        (self.repo_dir / "test.txt").unlink()
        self.assertFalse((self.repo_dir / "test.txt").exists())

        # Checkout commit
        reconstructed_count = self.engine.checkout(sha)
        self.assertEqual(reconstructed_count, 1)
        self.assertEqual(self.read_file("test.txt"), payload)

    def test_checkout_reconstructs_nested_directory_files(self):
        self.write_file("sub/dir/a.txt", "Content A")
        self.write_file("sub/other/b.txt", "Content B")
        self.engine.add(["sub/dir/a.txt"])
        self.engine.add(["sub/other/b.txt"])
        sha, _ = self.engine.commit("Nested files")

        # Delete entire sub folder
        import shutil
        shutil.rmtree(self.repo_dir / "sub")

        self.engine.checkout(sha)
        self.assertEqual(self.read_file("sub/dir/a.txt"), "Content A")
        self.assertEqual(self.read_file("sub/other/b.txt"), "Content B")

    def test_checkout_restores_deleted_file(self):
        self.write_file("keep.txt", "I will survive")
        self.engine.add(["keep.txt"])
        sha, _ = self.engine.commit("Survive")

        (self.repo_dir / "keep.txt").unlink()
        self.engine.checkout("main")
        self.assertTrue((self.repo_dir / "keep.txt").exists())

    def test_checkout_overwrites_modified_file(self):
        self.write_file("target.txt", "Original version")
        self.engine.add(["target.txt"])
        sha, _ = self.engine.commit("Original")

        # Overwrite with dirty data
        self.write_file("target.txt", "Dirty modified data")
        self.engine.checkout(sha)
        self.assertEqual(self.read_file("target.txt"), "Original version")

    def test_checkout_returns_reconstructed_file_count(self):
        self.write_file("f1.txt", "1")
        self.write_file("f2.txt", "2")
        self.write_file("f3.txt", "3")
        self.engine.add(["f1.txt"])
        self.engine.add(["f2.txt"])
        self.engine.add(["f3.txt"])
        sha, _ = self.engine.commit("3 files")

        count = self.engine.checkout(sha)
        self.assertEqual(count, 3)

    def test_checkout_via_cli(self):
        self.write_file("f.txt", "v1")
        self.engine.add(["f.txt"])
        sha, _ = self.engine.commit("Commit v1")

        self.write_file("f.txt", "v2 dirty")
        code, out, err = self.run_cli_cmd(["checkout", sha])
        self.assertEqual(code, 0)
        self.assertEqual(self.read_file("f.txt"), "v1")


# ==============================================================================
# 8. Branching, Tagging, and Reference Management
# ==============================================================================

class TestBranchAndTagFeature(VCXBaseTestCase):
    """Test branch creation, listing, switching, and tag management."""

    def setUp(self):
        super().setUp()
        self.repo = self.init_v1_repo()

    def test_create_branch_creates_ref(self):
        self.write_file("f.txt", "data")
        self.repo.add(["f.txt"])
        sha, _ = self.repo.commit("Init")

        self.repo.create_branch("feature-1")
        branch_ref = self.repo_dir / ".vcx" / "refs" / "heads" / "feature-1"
        self.assertTrue(branch_ref.exists())
        self.assertEqual(branch_ref.read_text().strip(), sha)

    def test_list_branches_returns_branches(self):
        self.write_file("f.txt", "data")
        self.repo.add(["f.txt"])
        self.repo.commit("Init")

        self.repo.create_branch("alpha")
        self.repo.create_branch("beta")

        branches = [b[0] for b in self.repo.list_branches()]
        self.assertIn("main", branches)
        self.assertIn("alpha", branches)
        self.assertIn("beta", branches)

    def test_checkout_branch(self):
        self.write_file("base.txt", "base")
        self.repo.add(["base.txt"])
        self.repo.commit("Base commit")

        self.repo.create_branch("dev")
        self.repo.checkout("dev")
        self.assertEqual(self.repo.head_ref, "refs/heads/dev")

    def test_create_tag_points_to_commit(self):
        self.write_file("rel.txt", "release payload")
        self.repo.add(["rel.txt"])
        sha, _ = self.repo.commit("Release v1.0")

        self.repo.create_tag("v1.0")
        tag_file = self.repo_dir / ".vcx" / "refs" / "tags" / "v1.0"
        self.assertTrue(tag_file.exists())
        self.assertEqual(tag_file.read_text().strip(), sha)

    def test_list_tags_returns_tags(self):
        self.write_file("f.txt", "d")
        self.repo.add(["f.txt"])
        self.repo.commit("init")

        self.repo.create_tag("v1.0")
        self.repo.create_tag("v2.0")

        tags = self.repo.list_tags()
        self.assertEqual(tags, ["v1.0", "v2.0"])

    def test_branch_via_cli(self):
        self.write_file("f.txt", "d")
        self.repo.add(["f.txt"])
        self.repo.commit("init")

        code, out, err = self.run_cli_cmd(["branch", "experiment"])
        self.assertEqual(code, 0)
        self.assertTrue((self.repo_dir / ".vcx" / "refs" / "heads" / "experiment").exists())

    def test_tag_via_cli(self):
        self.write_file("f.txt", "d")
        self.repo.add(["f.txt"])
        self.repo.commit("init")

        code, out, err = self.run_cli_cmd(["tag", "v0.9"])
        self.assertEqual(code, 0)
        self.assertTrue((self.repo_dir / ".vcx" / "refs" / "tags" / "v0.9").exists())


# ==============================================================================
# 9. Zstandard Object Storage & Deduplication
# ==============================================================================

class TestStorageAndZstandardFeature(VCXBaseTestCase):
    """Test Zstandard compressed fanout object storage."""

    def setUp(self):
        super().setUp()
        self.init_v2_repo()
        self.storage = ObjectStorage(self.repo_dir)

    def test_storage_write_raw_stores_zstd_compressed(self):
        data = b"Arbitrary binary string content repeated " * 50
        sha = self.storage.write_raw(data)
        self.assertEqual(len(sha), 64)

        # Confirm file is compressed on disk
        obj_file = self.repo_dir / ".vcx" / "objects" / sha[:2] / sha[2:]
        self.assertTrue(obj_file.is_file())
        self.assertLess(obj_file.stat().st_size, len(data))

    def test_storage_read_raw_decompresses_and_verifies_sha(self):
        data = b"Testing roundtrip decompression and checksum verification"
        sha = self.storage.write_raw(data)
        restored = self.storage.read_raw(sha)
        self.assertEqual(restored, data)

    def test_storage_has_object(self):
        data = b"Existence test data"
        sha = self.storage.write_raw(data)
        self.assertTrue(self.storage.has_object(sha))
        self.assertFalse(self.storage.has_object("0" * 64))

    def test_storage_fanout_directory_structure(self):
        sha = self.storage.write_raw(b"fanout test")
        dir_prefix = self.repo_dir / ".vcx" / "objects" / sha[:2]
        self.assertTrue(dir_prefix.is_dir())
        self.assertEqual(len(sha[:2]), 2)

    def test_storage_deduplication(self):
        data = b"Shared chunk byte pattern" * 100
        sha1 = self.storage.write_raw(data)
        sha2 = self.storage.write_raw(data)
        self.assertEqual(sha1, sha2)


# ==============================================================================
# 10. FastCDC Chunking Engine
# ==============================================================================

class TestFastCDCChunkerFeature(VCXBaseTestCase):
    """Test Content-Defined Chunking, boundary detection, and manifest metadata."""

    def setUp(self):
        super().setUp()
        self.chunker = FastCDCEngine()

    def test_chunk_bytes_small_file_single_chunk(self):
        data = b"Short configuration file string\n"
        manifest, chunks = self.chunker.chunk_bytes(data, path="small.cfg")
        self.assertEqual(manifest.total_chunks, 1)
        self.assertEqual(manifest.file_size, len(data))
        self.assertEqual(chunks[0][1], data)

    def test_chunk_bytes_large_file_multi_chunk(self):
        large_data = make_binary_file(size=128 * 1024)
        manifest, chunks = self.chunker.chunk_bytes(large_data, path="large.bin")
        self.assertGreater(manifest.total_chunks, 1)

        # Full reconstruction
        reconstructed = b"".join(c[1] for c in chunks)
        self.assertEqual(reconstructed, large_data)

    def test_chunk_bytes_deterministic_hashes(self):
        data = make_binary_file(size=64 * 1024)
        m1, c1 = self.chunker.chunk_bytes(data, path="test.bin")
        m2, c2 = self.chunker.chunk_bytes(data, path="test.bin")
        self.assertEqual(m1.manifest_hash, m2.manifest_hash)
        self.assertEqual([x[0].hash for x in c1], [x[0].hash for x in c2])

    def test_chunk_file_stream_reconstruction(self):
        target = self.write_file("stream_test.dat", make_binary_file(size=80 * 1024))
        generator = self.chunker.chunk_file_stream(target)
        chunks_collected = []
        try:
            while True:
                chunks_collected.append(next(generator))
        except StopIteration as e:
            manifest = e.value

        reconstructed = b"".join(c[1] for c in chunks_collected)
        self.assertEqual(reconstructed, target.read_bytes())
        self.assertEqual(manifest.file_size, target.stat().st_size)

    def test_batch_chunk_files(self):
        f1 = self.write_file("b1.txt", "batch file 1")
        f2 = self.write_file("b2.txt", "batch file 2")
        results = batch_chunk_files([str(f1), str(f2)])
        self.assertEqual(len(results), 2)
        paths = [r[0].path for r in results]
        self.assertIn(str(f1), paths)
        self.assertIn(str(f2), paths)

    def test_manifest_compare_detects_chunks(self):
        data1 = b"AAAA" * 1000
        data2 = b"BBBB" * 1000
        m1, _ = self.chunker.chunk_bytes(data1, path="f.txt")
        m2, _ = self.chunker.chunk_bytes(data2, path="f.txt")
        diff = m1.compare(m2)
        self.assertIn("modified_chunks", diff)


# ==============================================================================
# 11. SQLite Staging Index
# ==============================================================================

class TestSQLiteIndexFeature(VCXBaseTestCase):
    """Test SQLite index CRUD operations, WAL pragma, and unchanged stat cache."""

    def setUp(self):
        super().setUp()
        self.init_v2_repo()
        self.index = Index(self.repo_dir)

    def test_index_add_and_get_entry(self):
        self.index.add("file1.txt", mtime=12345.67, size=100, manifest_hash="sha1", status="staged")
        row = self.index.get("file1.txt")
        self.assertIsNotNone(row)
        self.assertEqual(row.path, "file1.txt")
        self.assertEqual(row.size, 100)
        self.assertEqual(row.manifest_hash, "sha1")
        self.assertEqual(row.status, "staged")

    def test_index_staged_entries_filter(self):
        self.index.add("s.txt", mtime=1.0, size=10, manifest_hash="sha1", status="staged")
        self.index.add("c.txt", mtime=1.0, size=10, manifest_hash="sha2", status="committed")
        self.index.add("u.txt", mtime=1.0, size=10, manifest_hash="sha3", status="unstaged")

        staged = self.index.staged_entries()
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].path, "s.txt")

    def test_index_is_file_unchanged(self):
        self.index.add("check.txt", mtime=1000.0, size=50, manifest_hash="sha_x", status="staged")
        self.assertTrue(self.index.is_file_unchanged("check.txt", current_mtime=1000.0, current_size=50))
        self.assertFalse(self.index.is_file_unchanged("check.txt", current_mtime=1001.0, current_size=50))
        self.assertFalse(self.index.is_file_unchanged("check.txt", current_mtime=1000.0, current_size=51))

    def test_index_remove_entry(self):
        self.index.add("del.txt", mtime=1.0, size=1, manifest_hash="x", status="staged")
        removed = self.index.remove("del.txt")
        self.assertTrue(removed)
        self.assertIsNone(self.index.get("del.txt"))

    def test_index_wal_mode(self):
        conn = sqlite3.connect(str(self.repo_dir / ".vcx" / "index.db"))
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(mode.lower(), "wal")


# ==============================================================================
# 12. Domain Adapters & Specialized Parsers
# ==============================================================================

class TestAdaptersAndDomainDiffFeature(VCXBaseTestCase):
    """Test FreeCAD, Verilog, and STEP domain adapters."""

    def test_freecad_adapter_extracts_properties(self):
        fcstd_bytes = make_fcstd_file(
            objects=[{
                "name": "ChassisBody",
                "type": "PartDesign::Body",
                "properties": {
                    "FilletRadius": ("Float", "3.14"),
                    "HoleCount": ("Integer", "8"),
                },
            }]
        )
        res = FreeCADAdapter.diff(None, fcstd_bytes, "chassis.fcstd")
        self.assertTrue(res["has_changes"])
        self.assertEqual(len(res["objects_added"]), 1)
        self.assertEqual(res["objects_added"][0]["name"], "ChassisBody")

    def test_freecad_adapter_diff_detects_changes(self):
        v1 = make_fcstd_file(objects=[{"name": "Part", "properties": {"Width": ("Float", "10.0")}}])
        v2 = make_fcstd_file(objects=[{"name": "Part", "properties": {"Width": ("Float", "20.0")}}])
        res = FreeCADAdapter.diff(v1, v2, "model.fcstd")
        self.assertTrue(res["has_changes"])
        self.assertEqual(len(res["properties_modified"]), 1)
        self.assertEqual(res["properties_modified"][0]["property"], "Width")

    def test_verilog_adapter_parses_ports_and_params(self):
        verilog_code = make_verilog_file(
            module_name="counter",
            parameters={"WIDTH": 16},
            ports=[
                {"dir": "input wire", "name": "clk"},
                {"dir": "output reg", "width": "[WIDTH-1:0]", "name": "count"},
            ],
        )
        modules = EDAAdapter.parse_verilog(verilog_code)
        self.assertIn("counter", modules)
        self.assertIn("clk", modules["counter"].ports)
        self.assertIn("count", modules["counter"].ports)

    def test_verilog_adapter_diff_detects_port_changes(self):
        v1 = "module dff (input clk, input d, output q); endmodule"
        v2 = "module dff (input clk, input d, input reset_n, output q); endmodule"
        diff = EDAAdapter.diff(v1.encode("utf-8"), v2.encode("utf-8"), "dff.v")
        self.assertTrue(diff["has_changes"])
        added_ports = [p["port"] for p in diff.get("port_changes", []) if p.get("type") == "added"]
        self.assertIn("reset_n", added_ports)

    def test_step_parser_parses_cartesian_points(self):
        step_text = make_step_file(points=[(0.0, 0.0, 0.0), (1.0, 2.0, 3.0)])
        parser = StepBrepParser(step_text)
        self.assertGreaterEqual(len(parser.points), 1)


# ==============================================================================
# 13. Semantic 3-Way Merger
# ==============================================================================

class TestSemanticMergerFeature(VCXBaseTestCase):
    """Test 3-way line and domain semantic merging."""

    def setUp(self):
        super().setUp()
        self.merger = SemanticMerger()

    def test_text_3way_merge_clean(self):
        base = b"header\n"
        ours = b"header\nline added by us\n"
        theirs = b"header\nline added by them\n"

        ok, merged, expl, conflict = self.merger.merge(base, ours, theirs, "notes.txt", "text/plain")
        self.assertTrue(ok)
        self.assertIsNone(conflict)
        self.assertIn(b"line added by us", merged)
        self.assertIn(b"line added by them", merged)

    def test_text_3way_merge_conflict(self):
        base = b"line 1\nline 2\n"
        ours = b"line 1 ours\nline 2\n"
        theirs = b"line 1 theirs\nline 2\n"

        ok, merged, expl, conflict = self.merger.merge(base, ours, theirs, "conflict.txt", "text/plain")
        self.assertFalse(ok)
        self.assertIsNotNone(conflict)

    def test_verilog_3way_merge_compatible_ports(self):
        base = b"module core (input clk); endmodule"
        ours = b"module core (input clk, input rst); endmodule"
        theirs = b"module core (input clk, output valid); endmodule"

        ok, merged, expl, conflict = self.merger.merge(base, ours, theirs, "core.v", "eda/verilog")
        self.assertTrue(ok)
        merged_str = merged.decode("utf-8")
        self.assertIn("rst", merged_str)
        self.assertIn("valid", merged_str)

    def test_freecad_xml_3way_merge_parametric(self):
        base = b"""<Document><Object name="O"><Property name="L"><Float value="10"/></Property><Property name="W"><Float value="20"/></Property></Object></Document>"""
        ours = b"""<Document><Object name="O"><Property name="L"><Float value="15"/></Property><Property name="W"><Float value="20"/></Property></Object></Document>"""
        theirs = b"""<Document><Object name="O"><Property name="L"><Float value="10"/></Property><Property name="W"><Float value="25"/></Property></Object></Document>"""

        ok, merged, expl, conflict = self.merger.merge(base, ours, theirs, "part.xml", "cad/freecad")
        self.assertTrue(ok)
        merged_str = merged.decode("utf-8")
        self.assertIn('value="15"', merged_str)
        self.assertIn('value="25"', merged_str)


# ==============================================================================
# 14. Repository Integrity Diagnostics (fsck / verify)
# ==============================================================================

class TestDiagnosticsAndIntegrityFeature(VCXBaseTestCase):
    """Test engine integrity verification against corruption and missing objects."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_verify_repository_integrity_clean(self):
        self.write_file("valid.txt", "clean payload")
        self.engine.add(["valid.txt"])
        self.engine.commit("Valid commit")

        result = self.engine.verify_repository_integrity()
        self.assertTrue(result["valid"])
        self.assertEqual(len(result["errors"]), 0)
        self.assertEqual(len(result["missing_chunks"]), 0)
        self.assertEqual(len(result["corrupted_chunks"]), 0)
        self.assertTrue(result["database_ok"])

    def test_verify_detects_missing_chunk(self):
        self.write_file("target.txt", "data to be missing")
        self.engine.add(["target.txt"])
        self.engine.commit("Commit before chunk delete")

        entry = self.engine.index.get("target.txt")
        manifest = self.engine.storage.read_manifest(entry.manifest_hash)
        chunk_sha = manifest.chunks[0].hash

        # Delete chunk from disk
        self.delete_chunk_object(chunk_sha)

        result = self.engine.verify_repository_integrity()
        self.assertFalse(result["valid"])
        self.assertIn(chunk_sha, result["missing_chunks"])

    def test_verify_detects_corrupt_chunk(self):
        self.write_file("target.txt", "data to be corrupted")
        self.engine.add(["target.txt"])
        self.engine.commit("Commit before corrupt")

        entry = self.engine.index.get("target.txt")
        manifest = self.engine.storage.read_manifest(entry.manifest_hash)
        chunk_sha = manifest.chunks[0].hash

        # Corrupt chunk on disk
        self.corrupt_chunk_object(chunk_sha)

        result = self.engine.verify_repository_integrity()
        self.assertFalse(result["valid"])
        self.assertIn(chunk_sha, result["corrupted_chunks"])

    def test_verify_detects_missing_manifest(self):
        self.write_file("f.txt", "manifest data")
        self.engine.add(["f.txt"])
        self.engine.commit("Commit manifest")

        entry = self.engine.index.get("f.txt")
        m_sha = entry.manifest_hash
        self.delete_chunk_object(m_sha)

        result = self.engine.verify_repository_integrity()
        self.assertFalse(result["valid"])
        self.assertIn(m_sha, result["missing_manifests"])

    def test_fsck_via_cli(self):
        self.write_file("ok.txt", "ok data")
        self.engine.add(["ok.txt"])
        self.engine.commit("OK commit")

        code, out, err = self.run_cli_cmd(["fsck"])
        self.assertEqual(code, 0)
        self.assertTrue("Repository integrity verified: OK" in out or "100% OK" in out)


# ==============================================================================
# 15. VID2 Packfile Archival & Garbage Collection
# ==============================================================================

class TestPackfileAndGCFeature(VCXBaseTestCase):
    """Test packfile writing, binary fanout indexing, and garbage collection."""

    def setUp(self):
        super().setUp()
        self.repo = self.init_v1_repo()

    def test_pack_writer_and_pack_reader_roundtrip(self):
        writer = PackWriter(self.repo.store.pack_dir)
        objs = [
            ("a" * 64, ObjectType.BLOB, b"Payload object A"),
            ("b" * 64, ObjectType.BLOB, b"Payload object B"),
        ]
        pack_path, idx_path, pack_hash = writer.write_pack(objs)
        self.assertTrue(pack_path.exists())
        self.assertTrue(idx_path.exists())

        reader = PackReader(pack_path)
        self.assertTrue(reader.has_object("a" * 64))
        obj_type, data = reader.read_object("a" * 64)
        self.assertEqual(obj_type, ObjectType.BLOB)
        self.assertEqual(data, b"Payload object A")

    def test_repository_gc_packs_and_prunes(self):
        self.write_file("f1.txt", "active content")
        self.repo.add(["f1.txt"])
        self.repo.commit("Active commit")

        # Create an orphaned loose blob
        orphan_sha = self.repo.store.write_blob(b"orphan unreachable content")

        stats = self.repo.gc()
        self.assertGreaterEqual(stats["packed_objects"], 1)
        self.assertGreaterEqual(stats["pruned_objects"], 1)

        # Orphan should no longer exist
        with self.assertRaises(FileNotFoundError):
            self.repo.store.read_blob(orphan_sha)

    def test_repository_pack_returns_paths(self):
        self.write_file("file.txt", "packable")
        self.repo.add(["file.txt"])
        self.repo.commit("Pack commit")

        pack_path, idx_path = self.repo.pack()
        self.assertIsNotNone(pack_path)
        self.assertIsNotNone(idx_path)
        self.assertTrue(pack_path.exists())
        self.assertTrue(idx_path.exists())


if __name__ == "__main__":
    unittest.main()
