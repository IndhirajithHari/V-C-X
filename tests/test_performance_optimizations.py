"""Unit tests for high-performance optimizations (mmap streaming, parallel compression, VID2 binary index)."""

from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zlib

from vcx.core.object_store import ObjectStore
from vcx.core.pack import PackReader, PackWriter
from vcx.core.repository import Repository
from vcx.core.types import ObjectType


class TestPerformanceOptimizations(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vcx_perf_test_")
        self.base_path = Path(self.tmp_dir)
        self.store = ObjectStore(self.base_path)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_mmap_streaming_blob_write_and_read(self):
        # Create a 5MB payload to test streaming mmap storage
        raw_data = bytes((i * 41 + 17) % 256 for i in range(5 * 1024 * 1024))
        test_file = self.base_path / "large_asset.bin"
        test_file.write_bytes(raw_data)

        # 1. Stream write to ObjectStore
        sha = self.store.write_blob_stream(test_file)

        # Verify expected standard Git-compatible SHA
        expected_header = f"blob {len(raw_data)}\0".encode("utf-8")
        expected_sha = hashlib.sha256(expected_header + raw_data).hexdigest()
        self.assertEqual(sha, expected_sha)
        self.assertTrue(self.store.has_object(sha))

        # 2. Verify standard read_blob matches exact bytes
        retrieved = self.store.read_blob(sha)
        self.assertEqual(retrieved, raw_data)

        # 3. Verify chunked read_blob_stream
        stream_chunks = list(self.store.read_blob_stream(sha, chunk_size=65536))
        reconstructed = b"".join(stream_chunks)
        self.assertEqual(reconstructed, raw_data)

    def test_vid2_binary_pack_index_and_parallel_compression(self):
        # Create 20 objects across diverse SHA prefixes
        objects = []
        for i in range(20):
            payload = f"Object content payload {i} -- " + ("A" * 50000)
            data_bytes = payload.encode("utf-8")
            header = f"blob {len(data_bytes)}\0".encode("utf-8")
            sha = hashlib.sha256(header + data_bytes).hexdigest()
            objects.append((sha, ObjectType.BLOB, data_bytes))

        writer = PackWriter(self.store.pack_dir)
        # Test parallel worker compression
        pack_path, idx_path, pack_hash = writer.write_pack(objects, max_workers=4)

        self.assertTrue(pack_path.exists())
        self.assertTrue(idx_path.exists())

        # Verify index starts with VID2 magic
        raw_idx = idx_path.read_bytes()
        self.assertTrue(raw_idx.startswith(b"VID2"))

        # Read back with PackReader
        reader = PackReader(pack_path)
        for sha, expected_type, expected_data in objects:
            self.assertTrue(reader.has_object(sha))
            obj_type, data = reader.read_object(sha)
            self.assertEqual(obj_type, expected_type)
            self.assertEqual(data, expected_data)

    def test_pack_reader_json_backward_compatibility(self):
        # Test that PackReader can read classic JSON-formatted .idx files
        data_bytes = b"Legacy index format payload"
        header = f"blob {len(data_bytes)}\0".encode("utf-8")
        sha = hashlib.sha256(header + data_bytes).hexdigest()

        writer = PackWriter(self.store.pack_dir)
        pack_path, idx_path, pack_hash = writer.write_pack([(sha, ObjectType.BLOB, data_bytes)])

        # Overwrite .idx with legacy JSON format
        legacy_idx = {
            "version": 1,
            "count": 1,
            "entries": {
                sha: {
                    "offset": 8,  # Pack header is 8 bytes
                    "size": len(data_bytes),
                    "type": "blob",
                }
            }
        }
        idx_path.write_text(json.dumps(legacy_idx), encoding="utf-8")

        reader = PackReader(pack_path)
        self.assertTrue(reader.has_object(sha))
        obj_type, read_data = reader.read_object(sha)
        self.assertEqual(obj_type, ObjectType.BLOB)
        self.assertEqual(read_data, data_bytes)

    def test_repository_stages_large_file_via_streaming(self):
        repo = Repository.init(self.base_path / "repo")
        large_file = repo.root / "video_render.raw"

        # 2MB file (exceeds 1MB streaming threshold)
        large_data = b"STREAMED_BLOCK_" * (150 * 1024)
        large_file.write_bytes(large_data)

        staged = repo.add(["video_render.raw"])
        self.assertIn("video_render.raw", staged)

        st = repo.status()
        self.assertEqual(len(st["staged"]), 1)
        self.assertEqual(st["staged"][0]["path"], "video_render.raw")

        commit_sha, commit = repo.commit("Commit large streaming file")
        self.assertTrue(commit_sha)
        self.assertEqual(commit.message, "Commit large streaming file")

    def test_simd_fastcdc_throughput_and_accuracy(self):
        from vcx.diff.analyzers.binary import BinaryAnalyzer
        ba = BinaryAnalyzer()

        # 4MB simulated binary payload
        raw1 = bytes((i * 47 + 19) % 256 for i in range(4 * 1024 * 1024))
        raw2 = bytearray(raw1)
        raw2[10000:10050] = b"ACCELERATED_DIFF_SIMD"
        raw2 = bytes(raw2)

        res = ba.analyze(raw1, raw2, "model.bin")
        facts = res.domain_facts

        self.assertIn("mutation_percentage", facts)
        self.assertIn("similarity_ratio", facts)
        self.assertGreater(facts["similarity_ratio"], 0.9)

    def test_c_native_accelerator_runtime_and_hashing(self):
        import hashlib
        from vcx.core.accelerator import fast_cdc_chunks, fast_sha256, get_accelerator_status

        status = get_accelerator_status()
        self.assertIn("backend", status)
        self.assertIn("has_c_runtime", status)
        self.assertIn("has_crypto_accel", status)

        # Verify hash equivalence between hardware C accelerator and hashlib
        test_payloads = [
            b"",
            b"short string",
            b"0" * 100000,
            bytes(range(256)) * 64,
        ]
        for p in test_payloads:
            expected = hashlib.sha256(p).hexdigest()
            actual = fast_sha256(p)
            self.assertEqual(actual, expected)

        # Verify chunking segmentation
        large_data = bytes((x * 31) % 256 for x in range(256 * 1024))
        chunks = fast_cdc_chunks(large_data, min_chunk=4096, max_chunk=16384)
        self.assertGreater(len(chunks), 0)
        reconstructed_len = sum(c[1] for c in chunks)
        self.assertEqual(reconstructed_len, len(large_data))


if __name__ == "__main__":
    unittest.main()
