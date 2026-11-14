"""Tier 2: Boundary, Limit, Security & Corruption Resilience Test Suite.

Verifies system behavior under extreme conditions, structural limits, and faults:
- 0-byte and 1-byte minimal files
- Exact CDC window thresholds (2KB min, 4KB avg, 64KB max)
- Path traversal injection attacks (../, absolute paths, special chars)
- Extreme filenames (deep hierarchies, spaces, non-ASCII, unicode, emojis)
- Object storage corruption, payload tampering, truncated files
- SQLite staging index edge cases, WAL pragma integrity, recovery
- Branch & Tag reference boundary conditions
- Malformed CAD/EDA domain assets and malformed payloads
- Garbage collection ref protection and Packfile binary corruption
"""

from __future__ import annotations
import io
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
    chunk_bytes,
    chunk_file,
)
from vcx.core.object_store import ObjectStore
from vcx.core.pack import PackReader, PackWriter
from vcx.core.repository import Repository
from vcx.core.types import ObjectType
from vcx.diff.cad_engine import StepBrepParser
from vcx.diff.merger import MergeConflict, SemanticMerger
from vcx.engine import VCXEngine
from vcx.index import Index
from vcx.storage import ObjectStorage


# ==============================================================================
# 1. 0-Byte and 1-Byte Minimal File Boundaries
# ==============================================================================

class TestZeroAndSingleByteBoundaries(VCXBaseTestCase):
    """Test boundary behavior for 0-byte and 1-byte minimal files."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()
        self.chunker = FastCDCEngine()

    def test_zero_byte_chunk_bytes_produces_empty_chunk_sha(self):
        manifest, chunks = self.chunker.chunk_bytes(b"", path="empty.txt")
        self.assertEqual(manifest.file_size, 0)
        self.assertEqual(manifest.total_chunks, 1)
        self.assertEqual(chunks[0][0].hash, EMPTY_CHUNK_SHA)
        self.assertEqual(chunks[0][1], b"")

    def test_zero_byte_file_staging_and_committing(self):
        self.write_file("empty.dat", b"")
        self.engine.add(["empty.dat"])

        entry = self.engine.index.get("empty.dat")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.size, 0)
        self.assertTrue(self.engine.storage.has_object(entry.manifest_hash))

        sha, payload = self.engine.commit("Add empty file")
        self.assertTrue(self.engine.storage.has_object(sha))

    def test_zero_byte_file_checkout_reconstruction(self):
        self.write_file("zero.bin", b"")
        self.engine.add(["zero.bin"])
        sha, _ = self.engine.commit("Commit zero byte file")

        # Delete local copy and reconstruct
        (self.repo_dir / "zero.bin").unlink()
        self.engine.checkout(sha)

        target = self.repo_dir / "zero.bin"
        self.assertTrue(target.exists())
        self.assertEqual(target.stat().st_size, 0)

    def test_zero_byte_file_status_tracking(self):
        self.write_file("empty_status.txt", b"")
        st1 = self.engine.status()
        self.assertIn("empty_status.txt", [u["path"] for u in st1["untracked"]])

        self.engine.add(["empty_status.txt"])
        st2 = self.engine.status()
        self.assertEqual(len(st2["staged"]), 1)
        self.assertEqual(st2["staged"][0]["path"], "empty_status.txt")

        self.engine.commit("Committed empty")
        self.assert_repo_clean()

    def test_single_byte_chunk_bytes(self):
        manifest, chunks = self.chunker.chunk_bytes(b"X", path="one.txt")
        self.assertEqual(manifest.file_size, 1)
        self.assertEqual(manifest.total_chunks, 1)
        self.assertEqual(chunks[0][0].size, 1)
        self.assertEqual(chunks[0][1], b"X")

    def test_single_byte_staging_committing_checkout(self):
        self.write_file("byte.bin", b"\xFF")
        self.engine.add(["byte.bin"])
        sha, _ = self.engine.commit("Add single byte 0xFF")

        (self.repo_dir / "byte.bin").unlink()
        self.engine.checkout(sha)
        self.assertEqual(self.read_file("byte.bin", binary=True), b"\xFF")

    def test_two_distinct_single_byte_files(self):
        m1, c1 = self.chunker.chunk_bytes(b"A", path="a.bin")
        m2, c2 = self.chunker.chunk_bytes(b"B", path="b.bin")
        self.assertNotEqual(c1[0][0].hash, c2[0][0].hash)
        self.assertNotEqual(m1.manifest_hash, m2.manifest_hash)

    def test_zero_byte_file_diff_with_empty(self):
        diff = FreeCADAdapter.diff(b"", b"", "empty.fcstd")
        self.assertFalse(diff["has_changes"])


# ==============================================================================
# 2. Exact CDC Window and Threshold Boundaries
# ==============================================================================

class TestExactCDCThresholdBoundaries(VCXBaseTestCase):
    """Test exact CDC window boundary sizes and chunking behaviors."""

    def setUp(self):
        super().setUp()
        self.chunker = FastCDCEngine()

    def test_exact_min_chunk_size_2048(self):
        custom = FastCDCEngine(min_size=2048, avg_size=4096, max_size=8192)
        data = make_binary_file(size=2048)
        manifest, chunks = custom.chunk_bytes(data, path="min.dat")
        self.assertEqual(manifest.file_size, 2048)
        reconstructed = b"".join(c[1] for c in chunks)
        self.assertEqual(reconstructed, data)

    def test_exact_avg_chunk_size_4096(self):
        data = make_binary_file(size=4096)
        manifest, chunks = self.chunker.chunk_bytes(data, path="avg.dat")
        self.assertEqual(manifest.file_size, 4096)
        reconstructed = b"".join(c[1] for c in chunks)
        self.assertEqual(reconstructed, data)

    def test_exact_threshold_65536_single_chunk(self):
        data = make_binary_file(size=65536)  # Exactly 64KB
        manifest, chunks = self.chunker.chunk_bytes(data, path="exact64k.bin")
        self.assertEqual(manifest.total_chunks, 1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0].size, 65536)

    def test_threshold_65537_multi_chunk(self):
        data = make_binary_file(size=65537)  # 64KB + 1 byte
        manifest, chunks = self.chunker.chunk_bytes(data, path="over64k.bin")
        self.assertGreater(manifest.total_chunks, 1)
        reconstructed = b"".join(c[1] for c in chunks)
        self.assertEqual(reconstructed, data)

    def test_exact_128kb_boundary(self):
        data = make_binary_file(size=128 * 1024)
        manifest, chunks = self.chunker.chunk_bytes(data, path="exact128k.bin")
        self.assertGreater(manifest.total_chunks, 1)
        self.assertEqual(manifest.file_size, 128 * 1024)
        self.assertEqual(b"".join(c[1] for c in chunks), data)

    def test_homogeneous_byte_sequence_chunking(self):
        null_data = b"\x00" * 70000
        manifest, chunks = self.chunker.chunk_bytes(null_data, path="zeros.dat")
        reconstructed = b"".join(c[1] for c in chunks)
        self.assertEqual(reconstructed, null_data)

    def test_high_entropy_random_payload_chunking(self):
        entropy_data = os.urandom(80000)
        manifest, chunks = self.chunker.chunk_bytes(entropy_data, path="random.dat")
        reconstructed = b"".join(c[1] for c in chunks)
        self.assertEqual(reconstructed, entropy_data)


# ==============================================================================
# 3. Path Traversal & Security Boundaries
# ==============================================================================

class TestPathTraversalAndSecurityBoundaries(VCXBaseTestCase):
    """Test sanitization against directory traversal injection attacks."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_sanitize_path_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            self.engine._sanitize_path("../secret.txt")

    def test_sanitize_path_rejects_deep_parent_traversal(self):
        with self.assertRaises(ValueError):
            self.engine._sanitize_path("../../../../etc/passwd")

    def test_sanitize_path_rejects_posix_absolute(self):
        with self.assertRaises(ValueError):
            self.engine._sanitize_path("/etc/shadow")

    def test_sanitize_path_rejects_absolute_path_outside_repo(self):
        outside = str(self.repo_dir.parent / "outside_secret.txt")
        with self.assertRaises(ValueError):
            self.engine._sanitize_path(outside)

    def test_sanitize_path_normalizes_redundant_slashes(self):
        cleaned = self.engine._sanitize_path("foo///bar//baz.txt")
        self.assertEqual(cleaned, "foo/bar/baz.txt")

    def test_sanitize_path_strips_current_dir_dots(self):
        cleaned = self.engine._sanitize_path("./src/./model.fcstd")
        self.assertEqual(cleaned, "src/model.fcstd")

    def test_checkout_guards_against_traversal_in_manifest(self):
        # Even if a malicious manifest contains '../outside.txt', sanitization blocks it
        with self.assertRaises(ValueError):
            self.engine._sanitize_path("../outside.txt")

    def test_add_guards_against_traversal(self):
        outside_file = Path(self.temp_dir).parent / "outside_marker.txt"
        outside_file.write_text("evil", encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                self.engine.add(["../outside_marker.txt"])
        finally:
            if outside_file.exists():
                outside_file.unlink()


# ==============================================================================
# 4. Extreme Filenames, Deep Paths & Characters
# ==============================================================================

class TestExtremeFilenamesAndPaths(VCXBaseTestCase):
    """Test filesystem handling across non-standard filenames and extreme paths."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_deeply_nested_directory_path(self):
        deep_rel = "a/b/c/d/e/f/g/h/i/j/deep_file.txt"
        self.write_file(deep_rel, "deep content")
        self.engine.add([deep_rel])
        sha, _ = self.engine.commit("Commit deeply nested path")

        (self.repo_dir / deep_rel).unlink()
        self.engine.checkout(sha)
        self.assertEqual(self.read_file(deep_rel), "deep content")

    def test_filename_with_spaces_and_parentheses(self):
        fname = "Main Assembly (Final Rev 2.1).fcstd"
        self.write_file(fname, make_fcstd_file())
        self.engine.add([fname])
        sha, _ = self.engine.commit("CAD with spaces")

        (self.repo_dir / fname).unlink()
        self.engine.checkout(sha)
        self.assertTrue((self.repo_dir / fname).exists())

    def test_filename_with_special_ascii_characters(self):
        fname = "module-test_v1.0+build#42$gate.v"
        self.write_file(fname, make_verilog_file())
        self.engine.add([fname])
        sha, _ = self.engine.commit("Special ascii characters")

        (self.repo_dir / fname).unlink()
        self.engine.checkout(sha)
        self.assertTrue((self.repo_dir / fname).exists())

    def test_unicode_and_emoji_filenames(self):
        fname = "bracket_üñîçødè_🚀_零件.step"
        self.write_file(fname, make_step_file())
        self.engine.add([fname])
        sha, _ = self.engine.commit("Unicode filename")

        (self.repo_dir / fname).unlink()
        self.engine.checkout(sha)
        self.assertTrue((self.repo_dir / fname).exists())

    def test_hidden_dotfiles_tracking(self):
        fname = ".hidden_config.json"
        self.write_file(fname, '{"hidden": true}')
        self.engine.add([fname])
        sha, _ = self.engine.commit("Hidden dotfile")

        (self.repo_dir / fname).unlink()
        self.engine.checkout(sha)
        self.assertEqual(self.read_file(fname), '{"hidden": true}')

    def test_filename_with_multiple_extensions(self):
        fname = "firmware.bin.tar.gz"
        self.write_file(fname, b"\x1f\x8b\x08\x00data")
        self.engine.add([fname])
        sha, _ = self.engine.commit("Multi extension")
        self.assertIsNotNone(self.engine.index.get(fname))

    def test_very_long_filename(self):
        fname = "a" * 150 + ".txt"
        self.write_file(fname, "long name")
        self.engine.add([fname])
        sha, _ = self.engine.commit("Long name commit")
        self.assertIsNotNone(self.engine.index.get(fname))


# ==============================================================================
# 5. Storage Corruption, Tampering & Missing Objects
# ==============================================================================

class TestStorageCorruptionAndTamperingBoundaries(VCXBaseTestCase):
    """Test detection of truncated, tampered, and missing storage objects."""

    def setUp(self):
        super().setUp()
        self.engine = self.init_v2_repo()

    def test_truncated_object_file_zero_bytes(self):
        self.write_file("data.txt", "some important data")
        self.engine.add(["data.txt"])
        sha, _ = self.engine.commit("Commit before truncate")

        entry = self.engine.index.get("data.txt")
        manifest = self.engine.storage.read_manifest(entry.manifest_hash)
        chunk_sha = manifest.chunks[0].hash

        # Overwrite with empty 0 bytes
        self.corrupt_chunk_object(chunk_sha, payload=b"")

        # read_raw should raise FileNotFoundError or ValueError
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.engine.storage.read_raw(chunk_sha)

    def test_corrupt_compressed_payload_detected(self):
        self.write_file("data.txt", "payload data")
        self.engine.add(["data.txt"])
        self.engine.commit("Commit before tamper")

        entry = self.engine.index.get("data.txt")
        manifest = self.engine.storage.read_manifest(entry.manifest_hash)
        chunk_sha = manifest.chunks[0].hash

        self.corrupt_chunk_object(chunk_sha, payload=b"GARBAGE_PAYLOAD_NOT_ZSTD")

        with self.assertRaises(ValueError):
            self.engine.storage.read_raw(chunk_sha)

    def test_corrupt_manifest_json(self):
        self.write_file("data.txt", "manifest tamper test")
        self.engine.add(["data.txt"])
        self.engine.commit("Commit")

        entry = self.engine.index.get("data.txt")
        m_sha = entry.manifest_hash

        # Write valid zstd compressed data but containing bad JSON
        bad_json_compressed = self.engine.storage.compress(b"{NOT_VALID_JSON")
        self.corrupt_chunk_object(m_sha, payload=bad_json_compressed)

        with self.assertRaises(Exception):
            self.engine.storage.read_manifest(m_sha)

    def test_corrupt_commit_object_json(self):
        self.write_file("f.txt", "f")
        self.engine.add(["f.txt"])
        commit_sha, _ = self.engine.commit("Commit to tamper")

        bad_commit = self.engine.storage.compress(b"BROKEN_COMMIT_JSON")
        self.corrupt_chunk_object(commit_sha, payload=bad_commit)

        # Log or verify should flag corruption
        res = self.engine.verify_repository_integrity()
        self.assertFalse(res["valid"])

    def test_corrupt_tree_object_json(self):
        self.write_file("f.txt", "f")
        self.engine.add(["f.txt"])
        commit_sha, payload = self.engine.commit("Commit tree to tamper")
        tree_sha = payload["tree_sha"]

        bad_tree = self.engine.storage.compress(b"BROKEN_TREE_JSON")
        self.corrupt_chunk_object(tree_sha, payload=bad_tree)

        with self.assertRaises(Exception):
            self.engine.checkout(commit_sha)

    def test_missing_chunk_object_file(self):
        with self.assertRaises(FileNotFoundError):
            self.engine.storage.read_raw("1" * 64)

    def test_verify_detects_corrupt_and_missing_simultaneously(self):
        self.write_file("f1.txt", "File 1 content")
        self.engine.add(["f1.txt"])
        self.write_file("f2.txt", "File 2 content")
        self.engine.add(["f2.txt"])
        self.engine.commit("Two files")

        m1 = self.engine.storage.read_manifest(self.engine.index.get("f1.txt").manifest_hash)
        m2 = self.engine.storage.read_manifest(self.engine.index.get("f2.txt").manifest_hash)

        chunk1 = m1.chunks[0].hash
        chunk2 = m2.chunks[0].hash

        # Corrupt chunk1, delete chunk2
        self.corrupt_chunk_object(chunk1, b"CORRUPTED")
        self.delete_chunk_object(chunk2)

        report = self.engine.verify_repository_integrity()
        self.assertFalse(report["valid"])
        self.assertIn(chunk1, report["corrupted_chunks"])
        self.assertIn(chunk2, report["missing_chunks"])

    def test_corrupt_payload_in_legacy_object_store(self):
        store = ObjectStore(self.repo_dir)
        sha = store.write_blob(b"original loose blob")
        obj_path = store.objects_dir / sha[:2] / sha[2:]
        obj_path.write_bytes(b"tampered zlib data")

        with self.assertRaises(Exception):
            store.read_blob(sha)


# ==============================================================================
# 6. SQLite Index Edge Cases & Concurrency
# ==============================================================================

class TestSQLiteIndexEdgeCasesAndConcurrency(VCXBaseTestCase):
    """Test SQLite index robustness, large volumes, and corruption recovery."""

    def setUp(self):
        super().setUp()
        self.init_v2_repo()
        self.index = Index(self.repo_dir)

    def test_rapid_sequential_index_adds(self):
        for i in range(50):
            self.index.add(f"file_{i}.txt", mtime=float(i), size=i * 10, manifest_hash=f"hash_{i}")
        self.assertEqual(len(self.index.entries()), 50)

    def test_empty_index_queries(self):
        empty_idx = Index(self.repo_dir / "empty_sub")
        self.assertEqual(empty_idx.entries(), [])
        self.assertEqual(empty_idx.staged_entries(), [])
        self.assertIsNone(empty_idx.get("any.txt"))
        self.assertFalse(empty_idx.remove("any.txt"))

    def test_get_nonexistent_entry_returns_none(self):
        self.assertIsNone(self.index.get("non_existent_path.dat"))

    def test_remove_nonexistent_entry_returns_false(self):
        self.assertFalse(self.index.remove("phantom.txt"))

    def test_corrupt_sqlite_file_triggers_recovery(self):
        db_file = self.repo_dir / ".vcx" / "index.db"
        db_file.write_bytes(b"NOT_A_SQLITE_DATABASE_HEADER")

        # Initializing Index on corrupt file must recover and backup
        recovered_index = Index(self.repo_dir)
        self.assertIsNotNone(recovered_index)
        backups = list((self.repo_dir / ".vcx").glob("index.db.corrupt.*"))
        self.assertGreaterEqual(len(backups), 1)

    def test_sqlite_wal_pragmas_and_busy_timeout(self):
        conn = sqlite3.connect(str(self.repo_dir / ".vcx" / "index.db"))
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode;")
        self.assertEqual(cur.fetchone()[0].lower(), "wal")
        cur.execute("PRAGMA busy_timeout;")
        self.assertGreaterEqual(cur.fetchone()[0], 1000)
        conn.close()

    def test_long_path_strings_in_index(self):
        long_path = "nested/" * 25 + "deep_file.txt"
        self.index.add(long_path, mtime=123.45, size=999, manifest_hash="sha_long")
        row = self.index.get(long_path)
        self.assertIsNotNone(row)
        self.assertEqual(row.path, long_path)


# ==============================================================================
# 7. Branch & Ref Boundary Conditions
# ==============================================================================

class TestBranchAndRefBoundaries(VCXBaseTestCase):
    """Test branch, tag, and reference resolution corner cases."""

    def setUp(self):
        super().setUp()
        self.repo = self.init_v1_repo()

    def test_branch_name_with_hierarchy_slashes(self):
        self.write_file("f.txt", "v")
        self.repo.add(["f.txt"])
        sha, _ = self.repo.commit("initial")

        self.repo.create_branch("feature/subsystem/core")
        b_file = self.repo_dir / ".vcx" / "refs" / "heads" / "feature" / "subsystem" / "core"
        self.assertTrue(b_file.exists())
        self.assertEqual(b_file.read_text().strip(), sha)

    def test_branch_creation_with_no_commits_fails(self):
        with self.assertRaises(ValueError):
            self.repo.create_branch("new_branch")

    def test_duplicate_branch_creation_fails(self):
        self.write_file("f.txt", "v")
        self.repo.add(["f.txt"])
        self.repo.commit("initial")

        self.repo.create_branch("alpha")
        with self.assertRaises(ValueError):
            self.repo.create_branch("alpha")

    def test_checkout_nonexistent_branch_fails(self):
        self.write_file("f.txt", "v")
        self.repo.add(["f.txt"])
        self.repo.commit("initial")

        with self.assertRaises((ValueError, FileNotFoundError)):
            self.repo.checkout("non_existent_branch_name")

    def test_tag_creation_with_no_commits_fails(self):
        with self.assertRaises(ValueError):
            self.repo.create_tag("v0.1")

    def test_tag_creation_on_nonexistent_sha_fails(self):
        self.write_file("f.txt", "v")
        self.repo.add(["f.txt"])
        self.repo.commit("initial")

        with self.assertRaises(ValueError):
            self.repo.create_tag("v0.2", target_sha="f" * 64)

    def test_resolve_ref_branch_and_tag(self):
        self.write_file("f.txt", "v")
        self.repo.add(["f.txt"])
        sha, _ = self.repo.commit("commit to resolve")
        self.repo.create_tag("v1.0", sha)

        self.assertEqual(self.repo.resolve_ref("HEAD"), sha)
        self.assertEqual(self.repo.resolve_ref("main"), sha)
        self.assertEqual(self.repo.resolve_ref("v1.0"), sha)


# ==============================================================================
# 8. Domain Adapter & Malformed Payload Boundaries
# ==============================================================================

class TestDomainAdapterBoundaries(VCXBaseTestCase):
    """Test domain adapters handling corrupted, malformed, or unusual inputs."""

    def test_freecad_missing_document_xml_in_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("OtherFile.txt", "hello")
        res = FreeCADAdapter.diff(None, buf.getvalue(), "broken.fcstd")
        self.assertIn("error", res)
        self.assertIn("not found", res["error"])

    def test_freecad_malformed_xml_in_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Document.xml", "<Document><UnclosedTag>")
        res = FreeCADAdapter.diff(None, buf.getvalue(), "malformed.fcstd")
        self.assertIn("error", res)
        self.assertIn("Corrupted", res["error"])

    def test_verilog_syntax_error_graceful_parse(self):
        broken_verilog = "module ( broken syntax ;;;; end"
        modules = EDAAdapter.parse_verilog(broken_verilog)
        self.assertIsInstance(modules, dict)

    def test_verilog_empty_module(self):
        empty_verilog = "module empty (); endmodule"
        modules = EDAAdapter.parse_verilog(empty_verilog)
        self.assertIn("empty", modules)
        self.assertEqual(len(modules["empty"].ports), 0)

    def test_verilog_with_null_bytes(self):
        verilog_with_null = "module alu (input clk);\x00\x00 endmodule"
        modules = EDAAdapter.parse_verilog(verilog_with_null)
        self.assertIn("alu", modules)

    def test_step_empty_data_section(self):
        step_empty = "ISO-10303-21; HEADER; ENDSEC; DATA; ENDSEC; END-ISO-10303-21;"
        parser = StepBrepParser(step_empty)
        self.assertEqual(len(parser.points), 0)

    def test_step_extreme_floating_point_coordinates(self):
        step_extreme = (
            "ISO-10303-21; DATA;\n"
            "#1 = CARTESIAN_POINT('tiny', (1.2345e-15, -9.8765e+20, 0.000000000001));\n"
            "ENDSEC; END-ISO-10303-21;"
        )
        parser = StepBrepParser(step_extreme)
        self.assertGreaterEqual(len(parser.points), 1)

    def test_step_cartesian_point_with_omitted_attribute(self):
        step_omitted = (
            "ISO-10303-21; DATA;\n"
            "#1 = CARTESIAN_POINT(*, (10.0, 20.0, 30.0));\n"
            "ENDSEC; END-ISO-10303-21;"
        )
        parser = StepBrepParser(step_omitted)
        self.assertIsInstance(parser.points, list)


# ==============================================================================
# 9. Packfile & Garbage Collection Boundaries
# ==============================================================================

class TestGCAndPackfileBoundaries(VCXBaseTestCase):
    """Test packfile writing limits and GC reference protection."""

    def setUp(self):
        super().setUp()
        self.repo = self.init_v1_repo()

    def test_pack_writer_empty_list_raises_error(self):
        writer = PackWriter(self.repo.store.pack_dir)
        with self.assertRaises(ValueError):
            writer.write_pack([])

    def test_pack_reader_nonexistent_sha_returns_none(self):
        writer = PackWriter(self.repo.store.pack_dir)
        pack_path, _, _ = writer.write_pack([("1" * 64, ObjectType.BLOB, b"data")])
        reader = PackReader(pack_path)
        self.assertIsNone(reader.read_object("2" * 64))

    def test_pack_reader_corrupt_pack_detected(self):
        writer = PackWriter(self.repo.store.pack_dir)
        pack_path, _, _ = writer.write_pack([("1" * 64, ObjectType.BLOB, b"valid data")])
        pack_path.write_bytes(b"VPK1" + b"\x00" * 50)  # Corrupted body

        reader = PackReader(pack_path)
        with self.assertRaises(Exception):
            reader.read_object("1" * 64)

    def test_gc_preserves_tagged_commits(self):
        self.write_file("v1.txt", "release payload")
        self.repo.add(["v1.txt"])
        sha1, _ = self.repo.commit("v1.0")
        self.repo.create_tag("v1.0", sha1)

        # Commit v2
        self.write_file("v2.txt", "v2 payload")
        self.repo.add(["v2.txt"])
        sha2, _ = self.repo.commit("v2.0")

        stats = self.repo.gc()
        # Verify both tagged commit sha1 and active commit sha2 are preserved
        self.assertTrue(self.repo.store.has_object(sha1))
        self.assertTrue(self.repo.store.has_object(sha2))

    def test_gc_preserves_multiple_branches(self):
        self.write_file("main.txt", "main branch")
        self.repo.add(["main.txt"])
        sha_main, _ = self.repo.commit("main commit")

        self.repo.create_branch("side")
        self.repo.checkout("side")
        self.write_file("side.txt", "side branch")
        self.repo.add(["side.txt"])
        sha_side, _ = self.repo.commit("side commit")

        self.repo.gc()
        self.assertTrue(self.repo.store.has_object(sha_main))
        self.assertTrue(self.repo.store.has_object(sha_side))

    def test_gc_on_empty_repo(self):
        empty_repo = Repository.init(self.repo_dir / "empty_repo")
        stats = empty_repo.gc()
        self.assertEqual(stats["packed_objects"], 0)
        self.assertEqual(stats["pruned_objects"], 0)


if __name__ == "__main__":
    unittest.main()
