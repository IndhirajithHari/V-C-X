"""Rigorously tests VCX v2.0 Top-Level Features and Patch Verifications.

Test Areas Covered:
1. 0-byte empty file Content-Defined Chunking, staging, committing, and stream checkout reconstruction.
2. Corrupted chunk detection, missing objects, and database corruption during `vcx verify` / `engine.verify_repository_integrity()`.
3. `get_repository_stats()` calculation correctness (deduplication ratio, compression ratio, space savings, database health).
4. Multi-threaded batch chunking equivalence with sequential chunking across diverse file topologies.
5. Non-UTF8 resilient EDA adapter parsing, null byte sanitization, and malformed FreeCAD XML handling.
"""

from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from vcx import chunker
from vcx.adapters.eda_adapter import EDAAdapter
from vcx.adapters.freecad_adapter import FreeCADAdapter
from vcx.chunker import (
    _DEFAULT_CHUNKER,
    EMPTY_CHUNK_SHA,
    FastCDCEngine,
    FileManifest,
    batch_chunk_files,
    chunk_bytes,
    chunk_file,
)
from vcx.cli.main import cmd_stats, cmd_verify
from vcx.engine import VCXEngine
from vcx.index import Index
from vcx.storage import ObjectStorage


class TestEmptyFileOperations(unittest.TestCase):
    """Test 0-byte empty file chunking, staging, committing, and checkout reconstruction."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = VCXEngine(self.temp_dir)
        self.engine.init()
        self.chunker = FastCDCEngine()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_file_chunk_bytes_and_file(self):
        """0-byte data produces valid manifest with file_size=0 and EMPTY_CHUNK_SHA."""
        manifest, chunks = self.chunker.chunk_bytes(b"", path="empty.txt")
        self.assertEqual(manifest.file_size, 0)
        self.assertEqual(manifest.path, "empty.txt")
        self.assertEqual(manifest.total_chunks, 1)
        self.assertEqual(chunks[0][0].hash, EMPTY_CHUNK_SHA)
        self.assertEqual(chunks[0][1], b"")

        # Test chunk_file on actual 0-byte file on disk
        empty_disk_file = Path(self.temp_dir) / "empty_disk.txt"
        empty_disk_file.touch()
        m2, chunks2 = self.chunker.chunk_file(empty_disk_file)
        self.assertEqual(m2.file_size, 0)
        self.assertEqual(m2.path, str(empty_disk_file))
        self.assertEqual(len(chunks2), 1)
        self.assertEqual(chunks2[0][0].hash, EMPTY_CHUNK_SHA)

        # Equivalence when chunk_bytes uses same path
        m_bytes_same_path, _ = self.chunker.chunk_bytes(b"", path=str(empty_disk_file))
        self.assertEqual(m2.manifest_hash, m_bytes_same_path.manifest_hash)

        # JSON serialization roundtrip
        m_json = manifest.to_json()
        m_restored = FileManifest.from_json(m_json)
        self.assertEqual(m_restored.file_size, 0)
        self.assertEqual(m_restored.manifest_hash, manifest.manifest_hash)

        # Manifest comparison between two empty manifests
        diff = manifest.compare(m_restored)
        self.assertEqual(diff["modified_chunks"], 0)
        self.assertEqual(diff["unmodified_chunks"], 1)

    def test_empty_file_staging_committing_and_checkout(self):
        """Empty file stages into index, commits into DAG, and reconstructs on checkout."""
        empty_path = Path(self.temp_dir) / "empty.dat"
        empty_path.touch()

        # 1. Stage empty file
        staged = self.engine.add(["empty.dat"])
        self.assertIn("empty.dat", staged)

        entry = self.engine.index.get("empty.dat")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.size, 0)
        self.assertTrue(self.engine.storage.has_object(entry.manifest_hash))

        # 2. Commit empty file
        commit_sha, _ = self.engine.commit("Add 0-byte empty file")
        self.assertTrue(commit_sha)
        self.assertEqual(self.engine.head_commit_sha, commit_sha)

        # 3. Remove from disk and checkout to reconstruct
        empty_path.unlink()
        self.assertFalse(empty_path.exists())

        reconstructed_bytes = self.engine.checkout(commit_sha)
        self.assertTrue(empty_path.exists())
        self.assertEqual(empty_path.stat().st_size, 0)
        self.assertEqual(empty_path.read_bytes(), b"")

        # 4. Overwrite empty file with non-empty data and verify checkout restores 0-byte size
        empty_path.write_bytes(b"some non-empty noise to overwrite")
        self.assertGreater(empty_path.stat().st_size, 0)
        self.engine.checkout(commit_sha)
        self.assertEqual(empty_path.stat().st_size, 0)
        self.assertEqual(empty_path.read_bytes(), b"")

    def test_nested_empty_files_checkout(self):
        """Nested empty files in subdirectories reconstruct directory tree and 0-byte file."""
        nested_dir = Path(self.temp_dir) / "nested" / "sub" / "deep"
        nested_dir.mkdir(parents=True, exist_ok=True)
        nested_file = nested_dir / "placeholder.keep"
        nested_file.touch()

        self.engine.add(["nested/sub/deep/placeholder.keep"])
        c_sha, _ = self.engine.commit("Add nested placeholder")

        # Delete nested directory tree
        shutil.rmtree(Path(self.temp_dir) / "nested")
        self.assertFalse(nested_file.exists())

        # Checkout reconstruction
        self.engine.checkout(c_sha)
        self.assertTrue(nested_file.exists())
        self.assertEqual(nested_file.stat().st_size, 0)


class TestCorruptedChunkAndIntegrityVerification(unittest.TestCase):
    """Test corrupted chunk detection, missing chunks, and corrupt manifests during fsck / verify."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = VCXEngine(self.temp_dir)
        self.engine.init()

        # Seed repository with diverse test files
        self.file1 = Path(self.temp_dir) / "doc.txt"
        self.file1.write_text("Hello VCX v2.0 World!", encoding="utf-8")

        self.file2 = Path(self.temp_dir) / "large.bin"
        self.file2.write_bytes(os.urandom(128 * 1024))

        self.file3 = Path(self.temp_dir) / "empty.bin"
        self.file3.touch()

        self.engine.add(["doc.txt", "large.bin", "empty.bin"])
        self.commit_sha, _ = self.engine.commit("Initial seed commit")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pristine_repository_integrity(self):
        """Pristine repository passes verification with 0 errors."""
        res = self.engine.verify_repository_integrity()
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["missing_chunks"]), 0)
        self.assertEqual(len(res["corrupted_chunks"]), 0)
        self.assertEqual(len(res["missing_manifests"]), 0)
        self.assertEqual(len(res["corrupted_manifests"]), 0)
        self.assertTrue(res["database_ok"])
        self.assertGreaterEqual(res["files_checked"], 3)
        self.assertGreaterEqual(res["chunks_checked"], 3)
        self.assertEqual(len(res["errors"]), 0)

    def test_corrupted_chunk_detection(self):
        """Corrupting a chunk object on disk is immediately detected by verify_repository_integrity()."""
        # Find a chunk from large.bin manifest
        entry = self.engine.index.get("large.bin")
        manifest = self.engine.storage.read_manifest(entry.manifest_hash)
        target_chunk_hash = manifest.chunks[0].hash

        chunk_path = self.engine.storage._get_object_path(target_chunk_hash)
        self.assertTrue(chunk_path.exists())

        # Overwrite chunk payload with corrupted garbage bytes
        chunk_path.write_bytes(b"CORRUPTED_GARBAGE_PAYLOAD_NOT_ZSTD")

        res = self.engine.verify_repository_integrity()
        self.assertFalse(res["valid"])
        self.assertIn(target_chunk_hash, res["corrupted_chunks"])
        self.assertGreaterEqual(len(res["errors"]), 1)
        self.assertTrue(any(target_chunk_hash in err for err in res["errors"]))

    def test_missing_chunk_detection(self):
        """Deleting a referenced chunk object is flagged as missing_chunk."""
        entry = self.engine.index.get("large.bin")
        manifest = self.engine.storage.read_manifest(entry.manifest_hash)
        target_chunk_hash = manifest.chunks[-1].hash

        chunk_path = self.engine.storage._get_object_path(target_chunk_hash)
        self.assertTrue(chunk_path.exists())
        chunk_path.unlink()

        res = self.engine.verify_repository_integrity()
        self.assertFalse(res["valid"])
        self.assertIn(target_chunk_hash, res["missing_chunks"])
        self.assertTrue(any("Missing chunk" in err for err in res["errors"]))

    def test_corrupted_manifest_detection(self):
        """Corrupting a FileManifest DAG object is flagged as corrupted_manifest."""
        entry = self.engine.index.get("doc.txt")
        manifest_hash = entry.manifest_hash
        manifest_path = self.engine.storage._get_object_path(manifest_hash)
        self.assertTrue(manifest_path.exists())

        # Corrupt manifest file with invalid content
        manifest_path.write_bytes(b"manifest 12\0corrupt_data")

        res = self.engine.verify_repository_integrity()
        self.assertFalse(res["valid"])
        self.assertIn(manifest_hash, res["corrupted_manifests"])
        self.assertTrue(any("Corrupted manifest" in err for err in res["errors"]))

    def test_cli_cmd_verify_exit_codes(self):
        """CLI cmd_verify returns 0 on healthy repo and 1 on corrupt repo."""
        cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            clean_exit = cmd_verify(argparse.Namespace())
            self.assertEqual(clean_exit, 0)

            # Corrupt an object
            entry = self.engine.index.get("large.bin")
            manifest = self.engine.storage.read_manifest(entry.manifest_hash)
            chunk_hash = manifest.chunks[0].hash
            self.engine.storage._get_object_path(chunk_hash).write_bytes(b"broken")

            corrupt_exit = cmd_verify(argparse.Namespace())
            self.assertEqual(corrupt_exit, 1)
        finally:
            os.chdir(cwd)


class TestRepositoryStatsAndAnalytics(unittest.TestCase):
    """Test get_repository_stats() deduplication, compression, and index analytics."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = VCXEngine(self.temp_dir)
        self.engine.init()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_repository_stats(self):
        """Stats on empty repository return clean defaults."""
        stats = self.engine.get_repository_stats()
        self.assertEqual(stats["total_files"], 0)
        self.assertEqual(stats["total_chunks"], 0)
        self.assertEqual(stats["unique_chunks"], 0)
        self.assertEqual(stats["deduplication_ratio"], 1.0)
        self.assertEqual(stats["uncompressed_size"], 0)
        self.assertEqual(stats["database_health"], "ok")
        self.assertGreaterEqual(stats["database_size"], 0)

    def test_deduplication_ratio_calculation(self):
        """Identical files generate identical CDC chunks and yield exact dedup ratios."""
        # Create identical 64KB payloads across 3 distinct files
        payload = b"VCX Deduplication Determinism Block\n" * 1500
        for name in ["dup1.bin", "dup2.bin", "dup3.bin"]:
            (Path(self.temp_dir) / name).write_bytes(payload)

        self.engine.add(["dup1.bin", "dup2.bin", "dup3.bin"])
        self.engine.commit("Add deduplicated triad")

        stats = self.engine.get_repository_stats()
        self.assertEqual(stats["total_files"], 3)
        self.assertGreaterEqual(stats["total_chunks"], 3)
        # All 3 files have identical contents, so total_chunks == 3 * unique_chunks
        self.assertEqual(stats["total_chunks"], stats["unique_chunks"] * 3)
        self.assertEqual(stats["deduplication_ratio"], 3.0)

    def test_compression_ratio_and_savings(self):
        """Highly compressible repetitive data achieves high compression ratio and space savings."""
        compressible_payload = b"Repetitive text stream for zstd compressor\n" * 10000  # ~430 KB
        (Path(self.temp_dir) / "compressible.txt").write_bytes(compressible_payload)

        self.engine.add(["compressible.txt"])
        self.engine.commit("Add compressible file")

        stats = self.engine.get_repository_stats()
        self.assertEqual(stats["total_files"], 1)
        self.assertEqual(stats["uncompressed_size"], len(compressible_payload))
        self.assertGreater(stats["uncompressed_size"], stats["compressed_size"])
        self.assertGreater(stats["compression_ratio"], 2.0)
        self.assertGreater(stats["space_savings_pct"], 50.0)
        self.assertEqual(stats["database_health"], "ok")
        self.assertGreater(stats["total_objects"], 0)

    def test_cli_cmd_stats(self):
        """CLI cmd_stats executes cleanly and returns 0."""
        cwd = os.getcwd()
        try:
            os.chdir(self.temp_dir)
            (Path(self.temp_dir) / "test.txt").write_text("Testing CLI stats command")
            self.engine.add(["test.txt"])
            self.engine.commit("Seed for stats test")

            code = cmd_stats(argparse.Namespace())
            self.assertEqual(code, 0)
        finally:
            os.chdir(cwd)


class TestMultiThreadedBatchChunking(unittest.TestCase):
    """Test parallel batch chunking equivalence with sequential chunking."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chunker = FastCDCEngine(min_size=1024, avg_size=4096, max_size=16384)
        self.engine = VCXEngine(self.temp_dir)
        self.engine.init()

        # Generate test files with varied topology and entropy
        self.test_files: list[Path] = []

        # 1. Empty file
        p0 = Path(self.temp_dir) / "f0_empty.dat"
        p0.touch()
        self.test_files.append(p0)

        # 2. Small file (< min_size)
        p1 = Path(self.temp_dir) / "f1_small.txt"
        p1.write_text("A" * 512, encoding="utf-8")
        self.test_files.append(p1)

        # 3. Medium file (32 KB)
        p2 = Path(self.temp_dir) / "f2_medium.bin"
        p2.write_bytes(os.urandom(32 * 1024))
        self.test_files.append(p2)

        # 4. Large random binary (128 KB)
        p3 = Path(self.temp_dir) / "f3_large_random.bin"
        p3.write_bytes(os.urandom(128 * 1024))
        self.test_files.append(p3)

        # 5. Repeated structured pattern (64 KB)
        p4 = Path(self.temp_dir) / "f4_structured.log"
        p4.write_text("INFO: System initialized successfully\n" * 1500, encoding="utf-8")
        self.test_files.append(p4)

        # 6. High entropy file (256 KB)
        p5 = Path(self.temp_dir) / "f5_heavy.dat"
        p5.write_bytes(os.urandom(256 * 1024))
        self.test_files.append(p5)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_batch_vs_sequential_chunking_exact_equivalence(self):
        """Batch chunking produces bit-for-bit, manifest-for-manifest matching outputs to sequential chunking."""
        # 1. Sequential chunking baseline with self.chunker
        sequential_results = [self.chunker.chunk_file(p) for p in self.test_files]

        # 2. Batch chunking with 4 worker threads using self.chunker
        batch_results_4 = self.chunker.batch_chunk_files(self.test_files, max_workers=4)

        # 3. Batch chunking with 1 worker thread using self.chunker
        batch_results_1 = self.chunker.batch_chunk_files(self.test_files, max_workers=1)

        for batch_run in [batch_results_4, batch_results_1]:
            self.assertEqual(len(batch_run), len(sequential_results))
            for (m_batch, chunks_batch), (m_seq, chunks_seq) in zip(batch_run, sequential_results):
                # Verify FileManifest equivalence
                self.assertEqual(m_batch.manifest_hash, m_seq.manifest_hash)
                self.assertEqual(m_batch.file_size, m_seq.file_size)
                self.assertEqual(m_batch.total_chunks, m_seq.total_chunks)
                self.assertEqual(len(m_batch.chunks), len(m_seq.chunks))

                for c_batch, c_seq in zip(m_batch.chunks, m_seq.chunks):
                    self.assertEqual(c_batch.hash, c_seq.hash)
                    self.assertEqual(c_batch.offset, c_seq.offset)
                    self.assertEqual(c_batch.size, c_seq.size)

                # Verify actual chunk byte payload equivalence
                self.assertEqual(len(chunks_batch), len(chunks_seq))
                for (info_b, bytes_b), (info_s, bytes_s) in zip(chunks_batch, chunks_seq):
                    self.assertEqual(info_b.hash, info_s.hash)
                    self.assertEqual(info_b.offset, info_s.offset)
                    self.assertEqual(info_b.size, info_s.size)
                    self.assertEqual(bytes_b, bytes_s)

        # 4. Sequential chunking with default chunker vs module-level and engine batch_chunk_files
        default_seq = [_DEFAULT_CHUNKER.chunk_file(p) for p in self.test_files]
        batch_mod = chunker.batch_chunk_files(self.test_files, max_workers=4)
        engine_batch = self.engine.batch_chunk_files(self.test_files, max_workers=4)

        for batch_run in [batch_mod, engine_batch]:
            self.assertEqual(len(batch_run), len(default_seq))
            for (m_batch, chunks_batch), (m_seq, chunks_seq) in zip(batch_run, default_seq):
                self.assertEqual(m_batch.manifest_hash, m_seq.manifest_hash)
                self.assertEqual(m_batch.file_size, m_seq.file_size)
                self.assertEqual(m_batch.total_chunks, m_seq.total_chunks)
                self.assertEqual(len(m_batch.chunks), len(m_seq.chunks))
                self.assertEqual(len(chunks_batch), len(chunks_seq))
                for (info_b, bytes_b), (info_s, bytes_s) in zip(chunks_batch, chunks_seq):
                    self.assertEqual(info_b.hash, info_s.hash)
                    self.assertEqual(bytes_b, bytes_s)

    def test_batch_chunking_edge_inputs(self):
        """Batch chunking handles empty list and single file cleanly."""
        self.assertEqual(self.chunker.batch_chunk_files([]), [])

        single_res = self.chunker.batch_chunk_files([self.test_files[2]])
        self.assertEqual(len(single_res), 1)
        self.assertEqual(single_res[0][0].file_size, self.test_files[2].stat().st_size)

    def test_engine_add_batch_integration(self):
        """VCXEngine.add() stages multiple files concurrently and correctly caches entries in index.db."""
        relative_paths = [p.name for p in self.test_files]
        staged = self.engine.add(relative_paths)
        self.assertEqual(len(staged), len(self.test_files))

        # Check all files are recorded in SQLite index
        for p in self.test_files:
            rel = p.name
            stat = p.stat()
            self.assertTrue(self.engine.index.is_file_unchanged(rel, stat.st_mtime, stat.st_size))
            entry = self.engine.index.get(rel)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.status, "staged")


class TestEDAAndFreeCADResilience(unittest.TestCase):
    """Test non-UTF8 and malformed container resilience in EDA and FreeCAD adapters."""

    def test_eda_non_utf8_binary_noise(self):
        """EDA adapter parses Verilog containing non-UTF8 bytes without raising UnicodeDecodeError."""
        # Verilog module with raw invalid UTF-8 bytes and null bytes inside comments and identifiers
        verilog_payload = (
            b"// Header with invalid non-UTF8 bytes: \xff\xfe\xc0\xc1\n"
            b"module axi_stream_fifo #(\n"
            b"    parameter DATA_WIDTH = 32,\n"
            b"    parameter STATE_IDLE = 2'b00,\n"
            b"    parameter STATE_TRANSMIT = 2'b01\n"
            b") (\n"
            b"    input wire aclk,\n"
            b"    input wire aresetn,\n"
            b"    input wire [DATA_WIDTH-1:0] s_axis_tdata,\n"
            b"    output reg m_axis_tvalid\n"
            b");\n"
            b"    // Embedded null bytes and non-utf8: \x00\x00\x80\x90\n"
            b"    always_ff @(posedge aclk) begin\n"
            b"        if (!aresetn) m_axis_tvalid <= 0;\n"
            b"    end\n"
            b"endmodule\n"
        )

        modules = EDAAdapter.parse_verilog(verilog_payload)
        self.assertIn("axi_stream_fifo", modules)
        mod = modules["axi_stream_fifo"]
        self.assertIn("aclk", mod.ports)
        self.assertIn("s_axis_tdata", mod.ports)
        self.assertIn("m_axis_tvalid", mod.ports)
        self.assertEqual(mod.ports["s_axis_tdata"].direction, "input")
        self.assertEqual(mod.ports["m_axis_tvalid"].direction, "output")
        self.assertEqual(mod.parameters["DATA_WIDTH"], "32")
        self.assertEqual(len(mod.fsm_states), 2)

    def test_eda_diff_with_non_utf8_bytes(self):
        """EDAAdapter.diff handles non-UTF8 input bytes gracefully."""
        v1 = b"module core (input clk, output [7:0] data);\nendmodule\n"
        v2 = b"module core (input clk, input enable, output [7:0] data);\n// Noise: \xff\xfe\x00\nendmodule\n"

        diff_res = EDAAdapter.diff(v1, v2, "core.v")
        self.assertTrue(diff_res["has_changes"])
        added_ports = [p["port"] for p in diff_res["port_changes"] if p["type"] == "added"]
        self.assertIn("enable", added_ports)

    def test_freecad_malformed_xml_handling(self):
        """FreeCADAdapter handles corrupted and unclosed ElementTree XML safely."""
        malformed_xml = "<Document><Object name='Pad'><Properties><Property name='Length'><Float value='25.0'>"
        parsed = FreeCADAdapter.parse_document_xml(malformed_xml)
        self.assertEqual(parsed["objects"], {})
        self.assertIsNotNone(parsed["error"])
        self.assertIn("Corrupted ElementTree XML", parsed["error"])

    def test_freecad_corrupt_zip_container(self):
        """FreeCADAdapter handles corrupted and non-zip containers without crashing."""
        corrupted_zip_bytes = b"PK\x03\x04" + b"\x00" * 20 + b"\xff" * 50
        doc_xml, gui_xml, err = FreeCADAdapter._extract_xml_contents(corrupted_zip_bytes)
        self.assertIsNone(doc_xml)
        self.assertIsNotNone(err)
        self.assertTrue(
            "Corrupted ZIP container" in err or "ZIP extraction error" in err
        )

    def test_freecad_diff_fallback_on_corrupted_container(self):
        """FreeCADAdapter.diff provides safe fallback diff when a container is corrupted."""
        valid_buf = io.BytesIO()
        with zipfile.ZipFile(valid_buf, "w") as zf:
            zf.writestr(
                "Document.xml",
                "<Document><Object name='Box' type='Part::Box'><Property name='Width'><Float value='10'/></Property></Object></Document>",
            )

        corrupt_buf = b"NOT_A_VALID_ZIP_CONTAINER"

        diff_res = FreeCADAdapter.diff(valid_buf.getvalue(), corrupt_buf, "model.fcstd")
        self.assertTrue(diff_res["has_changes"])
        self.assertIn("error", diff_res)
        self.assertGreaterEqual(len(diff_res["technical_bullets"]), 1)


if __name__ == "__main__":
    unittest.main()
