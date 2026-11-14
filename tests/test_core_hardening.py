"""Unit tests for Milestone 1: Core Engine, Storage, Index & Chunker Hardening.

Covers all 8 hardening features:
1. Merkle Tree History Preservation across incremental commits
2. Path Traversal Defense in checkout and _sanitize_path
3. FastCDC Determinism (stream vs bytes, pure-Python vs C extension) & Streaming Add
4. Legacy Index Migration & Zombie File Resurrection Prevention
5. Storage Checksum Verification (payload matching) & Consistent Empty SHA Handling
6. SQLite Index Optimization (in-memory comparison, batch operations, POSIX mode tracking)
7. Engine Branching APIs, Deletion APIs, and Detached HEAD Status
8. Garbage Collection Reference Protection (tags and uncommitted staged blobs)
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from vcx.chunker import (
    DEFAULT_AVG_CHUNK,
    DEFAULT_MAX_CHUNK,
    DEFAULT_MIN_CHUNK,
    EMPTY_CHUNK_SHA,
    FastCDCEngine,
    WHOLE_FILE_THRESHOLD,
    chunk_bytes,
    chunk_file,
)
import vcx.chunker as chunker_mod
from vcx.core.repository import Repository
from vcx.engine import VCXEngine
from vcx.index import DEFAULT_FILE_MODE, Index, IndexRow
from vcx.storage import ObjectStorage


class TestCoreHardening(unittest.TestCase):
    """Comprehensive unit test suite for Milestone 1 hardening."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="vcx_m1_test_")
        self.repo_dir = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ----------------------------------------------------------------------
    # Feature 1: Merkle Tree History Preservation
    # ----------------------------------------------------------------------
    def test_merkle_tree_history_preservation_across_commits(self):
        """Historical files must not be dropped across incremental commits."""
        engine = VCXEngine.init(self.repo_dir)

        # Commit 1: Add file1.txt
        f1 = self.repo_dir / "file1.txt"
        f1.write_text("Hello from file 1\n", encoding="utf-8")
        engine.add(["file1.txt"])
        sha1, c1 = engine.commit("Commit 1: Add file1")

        # Commit 2: Add file2.txt (incremental commit)
        f2 = self.repo_dir / "file2.txt"
        f2.write_text("Hello from file 2\n", encoding="utf-8")
        engine.add(["file2.txt"])
        sha2, c2 = engine.commit("Commit 2: Add file2")

        # Verify Commit 2 tree contains BOTH file1.txt and file2.txt
        _, t2_bytes = engine.storage.read_object(c2["tree_sha"])
        tree2 = json.loads(t2_bytes.decode("utf-8"))
        self.assertIn("file1.txt", tree2, "file1.txt dropped from commit 2 tree!")
        self.assertIn("file2.txt", tree2)

        # Commit 3: Remove file1.txt, add file3.txt
        engine.remove(["file1.txt"])
        f3 = self.repo_dir / "file3.txt"
        f3.write_text("Hello from file 3\n", encoding="utf-8")
        engine.add(["file3.txt"])
        sha3, c3 = engine.commit("Commit 3: Remove file1, add file3")

        # Verify Commit 3 tree contains file2.txt and file3.txt, but NOT file1.txt
        _, t3_bytes = engine.storage.read_object(c3["tree_sha"])
        tree3 = json.loads(t3_bytes.decode("utf-8"))
        self.assertNotIn("file1.txt", tree3, "file1.txt was not pruned from commit 3 tree!")
        self.assertIn("file2.txt", tree3)
        self.assertIn("file3.txt", tree3)

        # Checkout commit 1: only file1.txt exists
        engine.checkout(sha1)
        self.assertTrue(f1.exists())
        self.assertFalse(f2.exists())
        self.assertFalse(f3.exists())

        # Checkout commit 2: file1.txt and file2.txt exist
        engine.checkout(sha2)
        self.assertTrue(f1.exists())
        self.assertTrue(f2.exists())
        self.assertFalse(f3.exists())

        # Checkout commit 3: file2.txt and file3.txt exist, file1.txt does not
        engine.checkout(sha3)
        self.assertFalse(f1.exists())
        self.assertTrue(f2.exists())
        self.assertTrue(f3.exists())

    # ----------------------------------------------------------------------
    # Feature 2: Path Traversal Sanitization
    # ----------------------------------------------------------------------
    def test_path_traversal_sanitization(self):
        """_sanitize_path and checkout must reject path traversal attempts."""
        engine = VCXEngine.init(self.repo_dir)

        # _sanitize_path should reject dangerous traversal patterns
        with self.assertRaises(ValueError):
            engine._sanitize_path("../escaped.txt")

        with self.assertRaises(ValueError):
            engine._sanitize_path("foo/../../escaped.txt")

        with self.assertRaises(ValueError):
            engine._sanitize_path("/etc/passwd")

        # Normal relative paths should normalize cleanly
        self.assertEqual(engine._sanitize_path("src/./module/../file.txt"), "src/file.txt")

        # Checkout security: Tree manifest containing malicious path traversal
        f_norm = self.repo_dir / "legit.txt"
        f_norm.write_text("Safe file content", encoding="utf-8")
        engine.add(["legit.txt"])
        c_sha, c_data = engine.commit("Initial commit")

        # Craft malicious tree object
        tree_sha = c_data["tree_sha"]
        _, t_bytes = engine.storage.read_object(tree_sha)
        tree_map = json.loads(t_bytes.decode("utf-8"))
        m_hash = tree_map["legit.txt"]["manifest_hash"]

        outside_target = self.repo_dir.parent / "pwned.txt"
        outside_target.unlink(missing_ok=True)

        malicious_tree = {
            "../pwned.txt": {
                "path": "../pwned.txt",
                "manifest_hash": m_hash,
                "size": len("Safe file content"),
            }
        }
        mal_tree_bytes = json.dumps(malicious_tree).encode("utf-8")
        mal_tree_sha = engine.storage.write_object("tree", mal_tree_bytes)

        # Craft malicious commit
        mal_commit = {
            "tree_sha": mal_tree_sha,
            "parent_shas": [c_sha],
            "author": "Attacker",
            "timestamp": time.time(),
            "message": "Exploit traversal",
        }
        mal_commit_bytes = json.dumps(mal_commit).encode("utf-8")
        mal_commit_sha = engine.storage.write_object("commit", mal_commit_bytes)

        # Checkout must raise ValueError and not write outside repository
        with self.assertRaises(ValueError):
            engine.checkout(mal_commit_sha)

        self.assertFalse(outside_target.exists(), "Vulnerability: file was written outside repository!")

    # ----------------------------------------------------------------------
    # Feature 3: FastCDC Chunking Determinism & Streaming Add
    # ----------------------------------------------------------------------
    def test_fastcdc_determinism_and_parity(self):
        """fastcdc and pure-Python Gear hash must yield identical boundaries for chunk_bytes vs chunk_file."""
        chunker = FastCDCEngine()
        test_sizes = [0, 10, 4096, 65536, 65537, 100000, 200000]

        for has_fastcdc in [True, False]:
            orig_setting = chunker_mod._HAS_FASTCDC
            chunker_mod._HAS_FASTCDC = has_fastcdc
            mode = "fastcdc" if has_fastcdc else "pure_python"
            try:
                for sz in test_sizes:
                    data = os.urandom(sz) if sz > 0 else b""
                    temp_file = self.repo_dir / f"test_{mode}_{sz}.bin"
                    temp_file.write_bytes(data)

                    m_bytes, chunks_bytes = chunker.chunk_bytes(data, path=str(temp_file))
                    m_file, chunks_file = chunker.chunk_file(temp_file)

                    self.assertEqual(
                        [c.hash for c, _ in chunks_bytes],
                        [c.hash for c, _ in chunks_file],
                        f"Chunk hashes differ between chunk_bytes and chunk_file in {mode} for size {sz}",
                    )
                    self.assertEqual(
                        [c.offset for c, _ in chunks_bytes],
                        [c.offset for c, _ in chunks_file],
                        f"Chunk offsets differ in {mode} for size {sz}",
                    )
                    self.assertEqual(
                        [c.size for c, _ in chunks_bytes],
                        [c.size for c, _ in chunks_file],
                        f"Chunk sizes differ in {mode} for size {sz}",
                    )
                    self.assertEqual(m_bytes.manifest_hash, m_file.manifest_hash)
            finally:
                chunker_mod._HAS_FASTCDC = orig_setting

    def test_streaming_add_empty_and_large_file(self):
        """Streaming add must handle empty files and store chunks correctly."""
        engine = VCXEngine.init(self.repo_dir)

        # 1. Empty file (0 bytes)
        empty_f = self.repo_dir / "empty.txt"
        empty_f.touch()
        staged = engine.add(["empty.txt"])
        self.assertIn("empty.txt", staged)
        row = engine.index.get("empty.txt")
        self.assertIsNotNone(row)
        self.assertEqual(row.size, 0)
        manifest = engine.storage.read_manifest(row.manifest_hash)
        self.assertEqual(manifest.chunks[0].hash, EMPTY_CHUNK_SHA)

        # 2. Moderately large file (150 KB, exceeds whole file threshold 64KB)
        large_f = self.repo_dir / "large.bin"
        large_payload = os.urandom(150 * 1024)
        large_f.write_bytes(large_payload)
        staged2 = engine.add(["large.bin"])
        self.assertIn("large.bin", staged2)
        row2 = engine.index.get("large.bin")
        self.assertEqual(row2.size, len(large_payload))

        # Check all chunks are present in storage
        m2 = engine.storage.read_manifest(row2.manifest_hash)
        self.assertGreater(len(m2.chunks), 1)
        for c in m2.chunks:
            self.assertTrue(engine.storage.has_object(c.hash))
            chunk_data = engine.storage.read_chunk(c.hash)
            self.assertEqual(hashlib.sha256(chunk_data).hexdigest(), c.hash)

    # ----------------------------------------------------------------------
    # Feature 4: Legacy Index Migration & Zombie Fix
    # ----------------------------------------------------------------------
    def test_legacy_index_migration_and_zombie_prevention(self):
        """Legacy JSON index must be migrated and renamed to index.migrated to prevent zombie resurrections."""
        vcx_dir = self.repo_dir / ".vcx"
        vcx_dir.mkdir(parents=True, exist_ok=True)
        legacy_index = vcx_dir / "index"

        legacy_data = {
            "zombie.txt": {
                "mtime": 123456789.0,
                "size": 42,
                "manifest_hash": "abcd1234efgh5678",
                "status": "staged",
                "mode": "100755",
            }
        }
        legacy_index.write_text(json.dumps(legacy_data), encoding="utf-8")

        # Initialize Index for the first time
        idx1 = Index(self.repo_dir)
        self.assertTrue((vcx_dir / "index.migrated").is_file(), "index was not renamed to index.migrated")
        self.assertFalse(legacy_index.exists(), "Legacy index file still exists on disk")

        # Entry should be in database with mode 0o755
        row = idx1.get("zombie.txt")
        self.assertIsNotNone(row)
        self.assertEqual(row.mode, 0o755)

        # Remove entry from index
        idx1.remove("zombie.txt")
        self.assertIsNone(idx1.get("zombie.txt"))

        # Re-instantiate Index: zombie.txt must NOT be resurrected
        idx2 = Index(self.repo_dir)
        self.assertIsNone(idx2.get("zombie.txt"), "Zombie file was resurrected after index re-instantiation!")

    # ----------------------------------------------------------------------
    # Feature 5: Storage Checksum Validation & Empty Hash Handling
    # ----------------------------------------------------------------------
    def test_storage_checksum_validation_and_empty_sha(self):
        """Storage must consistently handle empty SHA and validate payload checksums."""
        storage = ObjectStorage(self.repo_dir)

        # Empty SHA tests
        self.assertTrue(storage.has_object(EMPTY_CHUNK_SHA))
        self.assertEqual(storage.read_raw(EMPTY_CHUNK_SHA), b"")
        self.assertEqual(storage.read_chunk(EMPTY_CHUNK_SHA), b"")
        self.assertEqual(storage.read_object(EMPTY_CHUNK_SHA), ("blob", b""))
        self.assertEqual(storage.write_raw(b"", expected_sha=EMPTY_CHUNK_SHA), EMPTY_CHUNK_SHA)

        # Payload Checksum Validation on Typed Objects
        payload = b"verifiable payload content for storage hardening"
        payload_sha = hashlib.sha256(payload).hexdigest()
        header = f"blob {len(payload)}\0".encode("utf-8")
        full_object = header + payload

        storage.write_raw(full_object, expected_sha=payload_sha)
        read_back = storage.read_raw(payload_sha, verify_checksum=True)
        self.assertEqual(read_back, full_object)

        # Corrupted Payload should raise ValueError when verify_checksum=True
        corrupt_payload = b"corrupted payload content for storage hardening"
        corrupt_full = header + corrupt_payload
        corrupt_sha = hashlib.sha256(b"intentionally_wrong_sha").hexdigest()
        storage.write_raw(corrupt_full, expected_sha=corrupt_sha)

        with self.assertRaises(ValueError):
            storage.read_raw(corrupt_sha, verify_checksum=True)

    # ----------------------------------------------------------------------
    # Feature 6: SQLite Index Optimization & Mode Tracking
    # ----------------------------------------------------------------------
    def test_sqlite_in_memory_optimization_and_mode_tracking(self):
        """Index must support batch operations, in-memory checks, and POSIX file mode preservation."""
        engine = VCXEngine.init(self.repo_dir)

        # 1. POSIX mode tracking on commit and checkout
        exec_file = self.repo_dir / "script.sh"
        exec_file.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
        os.chmod(exec_file, 0o755)

        normal_file = self.repo_dir / "data.txt"
        normal_file.write_text("read only or data\n", encoding="utf-8")
        os.chmod(normal_file, 0o644)

        engine.add(["script.sh", "data.txt"])

        row_exec = engine.index.get("script.sh")
        row_norm = engine.index.get("data.txt")
        self.assertEqual(row_exec.mode, 0o755)
        self.assertEqual(row_norm.mode, 0o644)

        # Verify in-memory row check
        stat_exec = exec_file.stat()
        self.assertTrue(Index.is_row_unchanged(row_exec, stat_exec.st_mtime, stat_exec.st_size, 0o755))
        self.assertFalse(Index.is_row_unchanged(row_exec, stat_exec.st_mtime, stat_exec.st_size, 0o644))
        self.assertFalse(Index.is_row_unchanged(row_exec, stat_exec.st_mtime + 5.0, stat_exec.st_size))

        c_sha, _ = engine.commit("Add script and data")

        # Checkout and verify mode restored on disk
        exec_file.unlink()
        normal_file.unlink()
        engine.checkout(c_sha)

        self.assertTrue(exec_file.exists())
        self.assertTrue(normal_file.exists())
        if os.name != "nt":
            self.assertEqual(exec_file.stat().st_mode & 0o777, 0o755)
            self.assertEqual(normal_file.stat().st_mode & 0o777, 0o644)

        # 2. Batch APIs
        idx = engine.index
        batch_records = [
            ("batch1.txt", 1.0, 10, "sha_b1", "staged", 0o644),
            {"path": "batch2.txt", "mtime": 2.0, "size": 20, "manifest_hash": "sha_b2", "mode": 0o755},
            IndexRow("batch3.txt", 3.0, 30, "sha_b3", "staged", 0o644),
        ]
        idx.add_batch(batch_records)
        self.assertIsNotNone(idx.get("batch1.txt"))
        self.assertIsNotNone(idx.get("batch2.txt"))
        self.assertIsNotNone(idx.get("batch3.txt"))

        idx.update_status_batch(["batch1.txt", "batch2.txt"], "committed")
        self.assertEqual(idx.get("batch1.txt").status, "committed")
        self.assertEqual(idx.get("batch2.txt").status, "committed")
        self.assertEqual(idx.get("batch3.txt").status, "staged")

    # ----------------------------------------------------------------------
    # Feature 7: Engine Branching, Deletion & Detached HEAD
    # ----------------------------------------------------------------------
    def test_engine_branching_and_detached_head(self):
        """VCXEngine branching, deletion, and detached HEAD status."""
        engine = VCXEngine.init(self.repo_dir)

        f1 = self.repo_dir / "test.txt"
        f1.write_text("v1 content\n", encoding="utf-8")
        engine.add(["test.txt"])
        c1, _ = engine.commit("First commit")

        # 1. Branching APIs
        self.assertEqual(engine.list_branches(), ["main"])
        engine.create_branch("feature/exp")
        self.assertEqual(engine.list_branches(), ["feature/exp", "main"])

        # Prevent duplicate branch creation
        with self.assertRaises(ValueError):
            engine.create_branch("feature/exp")

        # Prevent invalid branch names
        with self.assertRaises(ValueError):
            engine.create_branch("invalid..branch")

        with self.assertRaises(ValueError):
            engine.create_branch("")

        # Prevent deleting active branch
        with self.assertRaises(ValueError):
            engine.delete_branch("main")

        # Delete non-active branch
        engine.delete_branch("feature/exp")
        self.assertEqual(engine.list_branches(), ["main"])

        # 2. Deletion APIs
        f2 = self.repo_dir / "to_delete.txt"
        f2.write_text("delete me\n", encoding="utf-8")
        engine.add(["to_delete.txt"])
        c2, _ = engine.commit("Second commit with to_delete")

        st_before = engine.status()
        self.assertFalse(st_before["detached"])
        self.assertEqual(st_before["branch"], "main")

        removed = engine.remove(["to_delete.txt"])
        self.assertIn("to_delete.txt", removed)
        self.assertFalse(f2.exists())
        st_del = engine.status()
        self.assertTrue(any(item["path"] == "to_delete.txt" and item["type"] == "deleted" for item in st_del["staged"]))

        c3, _ = engine.commit("Third commit without to_delete")
        self.assertEqual(len(engine.status()["staged"]), 0)

        # 3. Detached HEAD
        engine.checkout(c1)
        self.assertTrue(engine.is_detached)
        st_detached = engine.status()
        self.assertTrue(st_detached["detached"])
        self.assertEqual(st_detached["branch"], "detached")
        self.assertEqual(st_detached["head_sha"], c1)

        # Checkout branch again: no longer detached
        engine.checkout("main")
        self.assertFalse(engine.is_detached)
        st_main = engine.status()
        self.assertFalse(st_main["detached"])
        self.assertEqual(st_main["branch"], "main")

    # ----------------------------------------------------------------------
    # Feature 8: GC Reference Protection for Tags and Staged Blobs
    # ----------------------------------------------------------------------
    def test_gc_reference_protection_for_tags_and_staged_blobs(self):
        """Repository.gc must protect objects reachable from tags and uncommitted staged index blobs."""
        repo = Repository.init(self.repo_dir)

        # Commit 1
        f1 = self.repo_dir / "tagged_file.txt"
        f1.write_text("release v1 content\n", encoding="utf-8")
        repo.add(["tagged_file.txt"])
        c1, _ = repo.commit("Release 1.0")

        # Tag Commit 1
        repo.create_tag("v1.0", c1)

        # Commit 2 on main
        f2 = self.repo_dir / "file2.txt"
        f2.write_text("commit 2 content\n", encoding="utf-8")
        repo.add(["file2.txt"])
        c2, _ = repo.commit("Commit 2")

        # Move branch or tag: tag 'v1.0' points to c1.
        # Now stage a file without committing (loose blob in store)
        f_staged = self.repo_dir / "uncommitted.txt"
        f_staged.write_text("staged but uncommitted\n", encoding="utf-8")
        repo.add(["uncommitted.txt"])

        staged_entry = repo.index.get("uncommitted.txt")
        self.assertIsNotNone(staged_entry)
        staged_sha = staged_entry.sha
        self.assertTrue(repo.store.has_object(staged_sha))

        # Create a true orphan blob directly in the object store
        orphan_sha = repo.store.write_blob(b"totally unreferenced orphan blob")
        self.assertTrue(repo.store.has_object(orphan_sha))

        # Run GC
        gc_stats = repo.gc()

        # Tagged commit and its tree/blobs must survive
        self.assertTrue(repo.store.has_object(c1), "Tagged commit c1 was pruned by GC!")

        # Staged loose blob must survive
        self.assertTrue(repo.store.has_object(staged_sha), "Staged loose blob was pruned by GC!")

        # True orphan blob must be collected
        self.assertFalse(repo.store.has_object(orphan_sha), "Orphan blob was not collected by GC!")

        # Committing the staged file must succeed
        c3, _ = repo.commit("Commit uncommitted file")
        self.assertTrue(repo.store.has_object(c3))


if __name__ == "__main__":
    unittest.main()
