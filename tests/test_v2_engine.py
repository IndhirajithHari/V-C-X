"""Comprehensive Unit & System Tests for VCX v2.0 Production Engine.

Verifies:
1. Content-Defined Chunking Engine (FastCDC, Gear rolling hash, FileManifest DAG).
2. Zstandard Object Compression & 2-character fan-out directory storage.
3. Stream-order file reconstruction (checkout_file).
4. SQLite local staging index (index.db) with instant mtime/size unchanged checks.
5. Native FreeCAD (.FCStd) ZIP in-memory parser and parametric property extractor.
6. Native Verilog/EDA (.v, .sv) AST regex parser and hardware hierarchy diffing.
7. Pluggable Semantic Extractor routing and Antigravity Differ Input formatting.
8. End-to-end VCXEngine workflow (init, add, commit --auto, checkout, log).
"""

from __future__ import annotations
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
import zipfile

from vcx.adapters.eda_adapter import EDAAdapter
from vcx.adapters.freecad_adapter import FreeCADAdapter
from vcx.chunker import FastCDCEngine, FileManifest, chunk_bytes, chunk_file
from vcx.engine import VCXEngine
from vcx.index import Index
from vcx.semantic import SemanticExtractor
from vcx.storage import ObjectStorage


class TestChunkerAndManifest(unittest.TestCase):
    """Test Content-Defined Chunking (CDC) and FileManifest DAG."""

    def setUp(self):
        self.chunker = FastCDCEngine(min_size=1024, avg_size=4096, max_size=16384)

    def test_small_file_single_chunk(self):
        """Files <= 64KB use a single chunk."""
        data = b"Short configuration file payload\n"
        manifest, chunks = self.chunker.chunk_bytes(data, path="config.toml")
        self.assertEqual(manifest.total_chunks, 1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][1], data)
        self.assertEqual(manifest.file_size, len(data))
        self.assertTrue(manifest.manifest_hash)

    def test_large_file_variable_chunking_and_reconstruction(self):
        """Files > 64KB are sliced into variable chunks and reassemble bit-for-bit."""
        # 128 KB payload
        large_data = os.urandom(128 * 1024)
        manifest, chunks = self.chunker.chunk_bytes(large_data, path="assets/mesh.blend")
        self.assertGreater(manifest.total_chunks, 1)

        # Reconstructed bytes must equal original
        reconstructed = b"".join(c[1] for c in chunks)
        self.assertEqual(reconstructed, large_data)

    def test_chunk_modification_ratio_and_drift(self):
        """Modifying 1 byte in a large file only modifies local chunks."""
        base_data = os.urandom(128 * 1024)
        m_base, _ = self.chunker.chunk_bytes(base_data, path="model.step")

        # Mutate 1 byte at offset 5000
        curr_data = bytearray(base_data)
        curr_data[5000] ^= 0xFF
        m_curr, _ = self.chunker.chunk_bytes(bytes(curr_data), path="model.step")

        drift = m_curr.compare(m_base)
        self.assertLess(drift["modified_chunks"], drift["total_chunks"])
        self.assertGreaterEqual(drift["unmodified_chunks"], 1)
        self.assertIn("chunks modified", drift["summary"])

    def test_manifest_serialization(self):
        """FileManifest to_json and from_json roundtrip."""
        data = os.urandom(64 * 1024)
        m1, _ = self.chunker.chunk_bytes(data, path="doc.bin")
        json_str = m1.to_json()
        m2 = FileManifest.from_json(json_str)
        self.assertEqual(m1.path, m2.path)
        self.assertEqual(m1.file_size, m2.file_size)
        self.assertEqual(m1.manifest_hash, m2.manifest_hash)
        self.assertEqual(len(m1.chunks), len(m2.chunks))


class TestZstandardStorageAndCheckout(unittest.TestCase):
    """Test Zstandard compression and stream reconstruction."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = ObjectStorage(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_zstd_compression_and_fanout(self):
        """Objects are compressed and stored with 2-char prefix fanout."""
        payload = b"High-entropy CAD surface vertex stream " * 1000
        sha = self.storage.write_chunk(payload)

        # Fanout directory check
        obj_file = Path(self.temp_dir) / ".vcx" / "objects" / sha[:2] / sha[2:]
        self.assertTrue(obj_file.exists())
        self.assertLess(obj_file.stat().st_size, len(payload))

        # Read back
        decompressed = self.storage.read_chunk(sha)
        self.assertEqual(decompressed, payload)

    def test_checkout_file_stream_reconstruction(self):
        """Reconstruct full file from manifest chunk stream."""
        original = os.urandom(200 * 1024)
        manifest, chunks = chunk_bytes(original, "output/binary.dat")

        for c_info, c_bytes in chunks:
            self.storage.write_chunk(c_bytes)

        m_sha = self.storage.write_manifest(manifest)

        out_path = Path(self.temp_dir) / "reconstructed.dat"
        bytes_written = self.storage.checkout_file(m_sha, out_path)
        self.assertEqual(bytes_written, len(original))
        self.assertEqual(out_path.read_bytes(), original)


class TestSQLiteLocalStagingIndex(unittest.TestCase):
    """Test SQLite index.db fast stat checks and ACID staging."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.index = Index(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sqlite_staging_and_mtime_skip(self):
        """Index accurately skips unchanged files based on OS mtime and size."""
        now = time.time()
        self.index.add("src/core.py", now, 2048, "hash_manifest_001")

        # Exact match
        self.assertTrue(self.index.is_file_unchanged("src/core.py", now, 2048))

        # Changed mtime
        self.assertFalse(self.index.is_file_unchanged("src/core.py", now + 1.0, 2048))

        # Changed size
        self.assertFalse(self.index.is_file_unchanged("src/core.py", now, 2049))

        # Untracked file
        self.assertFalse(self.index.is_file_unchanged("untracked.txt", now, 100))


class TestFreeCADAdapter(unittest.TestCase):
    """Test in-memory ZIP inspection and parametric XML diffing."""

    def test_freecad_parametric_changes_extraction(self):
        # Base FCStd ZIP
        b_buf = io.BytesIO()
        with zipfile.ZipFile(b_buf, "w") as zf:
            zf.writestr(
                "Document.xml",
                '<Document><Object name="Chassis" type="PartDesign::Body">'
                '<Property name="Length"><Float value="100.0"/></Property>'
                '<Property name="Width"><Float value="50.0"/></Property>'
                "</Object></Document>",
            )

        # Updated FCStd ZIP
        c_buf = io.BytesIO()
        with zipfile.ZipFile(c_buf, "w") as zf:
            zf.writestr(
                "Document.xml",
                '<Document><Object name="Chassis" type="PartDesign::Body">'
                '<Property name="Length"><Float value="125.0"/></Property>'
                '<Property name="Width"><Float value="50.0"/></Property>'
                "</Object>"
                '<Object name="Fillet" type="PartDesign::Fillet">'
                '<Property name="Radius"><Float value="3.5"/></Property>'
                "</Object></Document>",
            )

        res = FreeCADAdapter.diff(b_buf.getvalue(), c_buf.getvalue(), "chassis.fcstd")
        self.assertTrue(res["has_changes"])
        self.assertEqual(len(res["objects_added"]), 1)
        self.assertEqual(res["objects_added"][0]["name"], "Fillet")
        self.assertEqual(len(res["properties_modified"]), 1)
        self.assertEqual(res["properties_modified"][0]["property"], "Length")
        self.assertEqual(res["properties_modified"][0]["new_value"], "125.0")
        self.assertTrue(any("Modified Chassis.Length: 100.0 -> 125.0" in b for b in res["technical_bullets"]))


class TestEDAAdapter(unittest.TestCase):
    """Test Verilog/SystemVerilog RTL regex AST parsing."""

    def test_verilog_ports_and_fsm_extraction(self):
        v_base = """
        module uart_tx #(parameter CLK_HZ = 50000000) (
            input clk,
            input [7:0] data_in,
            output reg tx
        );
        localparam S_IDLE = 2'b00;
        always_ff @(posedge clk) begin
            tx <= 1;
        end
        endmodule
        """

        v_curr = """
        module uart_tx #(parameter CLK_HZ = 100000000) (
            input clk,
            input [15:0] data_in,
            input enable,
            output reg tx,
            output reg busy
        );
        localparam S_IDLE = 2'b00;
        localparam S_TRANSMIT = 2'b01;
        always_ff @(posedge clk) begin
            tx <= 1;
        end
        always_comb begin
            busy = 0;
        end
        endmodule
        """

        res = EDAAdapter.diff(v_base.encode(), v_curr.encode(), "uart_tx.v")
        self.assertTrue(res["has_changes"])
        # Check port width update
        mod_ports = [p for p in res["port_changes"] if p.get("type") == "modified"]
        self.assertTrue(len(mod_ports) >= 1)
        # Check added ports (enable, busy)
        added_ports = [p["port"] for p in res["port_changes"] if p.get("type") == "added"]
        self.assertIn("enable", added_ports)
        self.assertIn("busy", added_ports)
        # Check FSM state addition
        self.assertTrue(len(res["fsm_changes"]) >= 1)


class TestSemanticExtractor(unittest.TestCase):
    """Test pluggable adapter router and Antigravity hook."""

    def setUp(self):
        self.extractor = SemanticExtractor()

    def test_router_handles_archive_docx_in_memory(self):
        """In-memory docx inspection without disk extraction."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Project Spec v2</w:t></w:r></w:p></w:body></w:document>")

        diff_input = self.extractor.extract("specification.docx", base_bytes=None, current_bytes=buf.getvalue())
        self.assertEqual(diff_input.file_type, "archive/container")
        self.assertIn("specification.docx", diff_input.file_name)


class TestVCXEngineV2Lifecycle(unittest.TestCase):
    """Test complete end-to-end v2.0 workflow with VCXEngine."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = VCXEngine.init(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_v2_add_commit_checkout(self):
        # 1. Create multi-domain files
        (Path(self.temp_dir) / "app.py").write_text("print('VCX v2')\n")
        (Path(self.temp_dir) / "chip.v").write_text("module chip(input clk, output q); endmodule\n")
        (Path(self.temp_dir) / "binary.dat").write_bytes(os.urandom(80 * 1024))

        # 2. Add
        staged = self.engine.add(["app.py", "chip.v", "binary.dat"])
        self.assertEqual(len(staged), 3)

        # 3. Status
        st = self.engine.status()
        self.assertEqual(len(st["staged"]), 3)
        self.assertEqual(len(st["unstaged"]), 0)

        # 4. Commit with auto semantic diff
        c_sha, c_data = self.engine.commit(auto=True)
        self.assertEqual(c_sha, self.engine.head_commit_sha)
        self.assertTrue(c_data["message"])

        # 5. Modify binary file and verify CDC drift
        curr_bin = bytearray((Path(self.temp_dir) / "binary.dat").read_bytes())
        curr_bin[100] ^= 0xFF
        (Path(self.temp_dir) / "binary.dat").write_bytes(bytes(curr_bin))

        st2 = self.engine.status()
        self.assertEqual(len(st2["unstaged"]), 1)
        self.assertEqual(st2["unstaged"][0]["path"], "binary.dat")

        # 6. Checkout
        (Path(self.temp_dir) / "app.py").unlink()
        restored = self.engine.checkout(c_sha)
        self.assertEqual(restored, 3)
        self.assertTrue((Path(self.temp_dir) / "app.py").exists())


class TestV2EngineEdgeCasesAndAudits(unittest.TestCase):
    """Test the 5 critical edge cases audited in v2.0."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.engine = VCXEngine.init(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_file_chunking_and_checkout(self):
        """1. Empty file (0 bytes) chunking produces valid manifest and checkout recreates 0-byte file."""
        # Test raw chunker
        manifest, chunks = chunk_bytes(b"", path="empty.txt")
        self.assertEqual(manifest.file_size, 0)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0].size, 0)
        self.assertEqual(chunks[0][1], b"")

        # Test storage checkout
        m_sha = self.engine.storage.write_manifest(manifest)
        self.engine.storage.write_chunk(b"")
        out_path = Path(self.temp_dir) / "empty_out.txt"
        written = self.engine.storage.checkout_file(m_sha, out_path)
        self.assertEqual(written, 0)
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.stat().st_size, 0)

        # Test end-to-end engine add, commit, checkout with empty file
        empty_file = Path(self.temp_dir) / "zero.txt"
        empty_file.write_bytes(b"")
        self.engine.add(["zero.txt"])
        c_sha, _ = self.engine.commit("Add empty file")

        empty_file.unlink()
        self.assertFalse(empty_file.exists())
        self.engine.checkout(c_sha)
        self.assertTrue(empty_file.exists())
        self.assertEqual(empty_file.stat().st_size, 0)

    def test_missing_or_corrupt_object_handling(self):
        """2. Handling of missing or corrupted objects during checkout or staging."""
        # Create and commit a file
        test_file = Path(self.temp_dir) / "data.bin"
        test_file.write_bytes(b"Sample payload for corruption test")
        self.engine.add(["data.bin"])
        c_sha, _ = self.engine.commit("Add data.bin")

        # Corrupt the chunk on disk
        row = self.engine.index.get("data.bin")
        manifest = self.engine.storage.read_manifest(row.manifest_hash)
        chunk_hash = manifest.chunks[0].hash
        chunk_path = self.engine.storage._get_object_path(chunk_hash)
        self.assertTrue(chunk_path.exists())
        # Overwrite chunk with corrupted data
        chunk_path.write_bytes(b"bad zstd data \x00\xff")

        # Checkout should detect corruption, fail safely, and clean up temporary files
        test_file.unlink()
        with self.assertRaises((RuntimeError, ValueError)):
            self.engine.checkout(c_sha)
        # Ensure no dangling tmp files
        tmp_files = list(Path(self.temp_dir).glob(".tmp_checkout_*"))
        self.assertEqual(len(tmp_files), 0)

        # Test staging resilience: if cached manifest was deleted, add should re-chunk and repair
        manifest_path = self.engine.storage._get_object_path(row.manifest_hash)
        manifest_path.unlink()
        # Recreate test_file with original content
        test_file.write_bytes(b"Sample payload for corruption test")
        # index has file_unchanged match, but object is missing
        staged = self.engine.add(["data.bin"])
        self.assertIn("data.bin", staged)
        # Verify manifest was recreated in storage
        new_row = self.engine.index.get("data.bin")
        self.assertTrue(self.engine.storage.has_object(new_row.manifest_hash))

    def test_sqlite_index_concurrency_and_busy_timeout(self):
        """3. SQLite index connection timeout and busy_timeout (WAL mode) resilience."""
        with self.engine.index._get_connection() as conn:
            cur = conn.execute("PRAGMA busy_timeout;")
            busy_timeout = cur.fetchone()[0]
            self.assertEqual(busy_timeout, 30000)

            cur2 = conn.execute("PRAGMA journal_mode;")
            journal_mode = cur2.fetchone()[0].upper()
            self.assertEqual(journal_mode, "WAL")

        # Test corrupt database recovery
        db_path = self.engine.index.db_path
        for f in db_path.parent.glob(f"{db_path.name}*"):
            f.unlink()
        db_path.write_bytes(b"SQLite format 3\000" + b"\xff" * 500)
        recovered_idx = Index(self.temp_dir)
        # Should initialize clean DB without crashing
        self.assertEqual(len(recovered_idx), 0)
        # And corrupt backup was preserved
        backups = list((self.engine.vcx_dir).glob("index.db.corrupt.*"))
        self.assertTrue(len(backups) >= 1)

    def test_freecad_encrypted_or_corrupt_xml_fallback(self):
        """4. Safe fallback in FreeCAD adapter if a zip file is encrypted or corrupted ElementTree XML."""
        # 1. Malformed ElementTree XML
        corrupt_xml = b"<Document><Object name='Part'><UnclosedTag></Document>"
        diff_corrupt = FreeCADAdapter.diff(None, corrupt_xml, "broken.fcstd")
        self.assertTrue(diff_corrupt["has_changes"])
        self.assertIn("Corrupted ElementTree XML", diff_corrupt.get("error", ""))
        self.assertTrue(len(diff_corrupt["technical_bullets"]) >= 1)

        # 2. Encrypted / password-protected zip file
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("Document.xml", b"<Document/>")
        raw_zip = bytearray(buf.getvalue())
        cd_idx = raw_zip.find(b"PK\x01\x02")
        raw_zip[cd_idx + 8] |= 0x1  # Set general purpose bit 0 (encrypted)

        diff_enc = FreeCADAdapter.diff(None, bytes(raw_zip), "secret.fcstd")
        self.assertTrue(diff_enc["has_changes"])
        self.assertIn("Encrypted", diff_enc.get("error", ""))
        self.assertEqual(len(diff_enc["objects_removed"]), 0)

    def test_eda_adapter_invalid_utf8_and_null_bytes(self):
        """5. Error handling in EDA adapter if a file has invalid UTF-8 bytes or null bytes."""
        # Verilog with invalid UTF-8 sequences and null bytes
        invalid_bytes = b"module alu (input clk, input [7:0] a, output [7:0] y);\n\xff\xfe\x80\x81\x00\x00\nendmodule\n"
        mods = EDAAdapter.parse_verilog(invalid_bytes)
        self.assertIn("alu", mods)
        self.assertIn("clk", mods["alu"].ports)
        self.assertIn("a", mods["alu"].ports)

        # Diff with invalid UTF-8
        base_v = b"module alu (input clk, output [7:0] y);\nendmodule\n"
        diff_res = EDAAdapter.diff(base_v, invalid_bytes, "alu.v")
        self.assertTrue(diff_res["has_changes"])
        added = [p["port"] for p in diff_res["port_changes"] if p.get("type") == "added"]
        self.assertIn("a", added)


if __name__ == "__main__":
    unittest.main()
