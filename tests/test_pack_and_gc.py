"""Unit tests for Object Packing and Garbage Collection (vcx gc)."""

from pathlib import Path
import tempfile
import unittest

from vcx.core.object_store import ObjectStore
from vcx.core.pack import PackReader, PackWriter
from vcx.core.repository import Repository
from vcx.core.types import ObjectType


class TestPackAndGC(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        self.store = ObjectStore(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pack_writer_and_reader(self):
        objects = [
            ("1" * 64, ObjectType.BLOB, b"hello blob content 1"),
            ("2" * 64, ObjectType.BLOB, b"hello blob content 2"),
            ("3" * 64, ObjectType.TREE, b'[{"name":"f","sha":"1"}]'),
        ]

        writer = PackWriter(self.store.pack_dir)
        pack_path, idx_path, pack_hash = writer.write_pack(objects)

        self.assertTrue(pack_path.exists())
        self.assertTrue(idx_path.exists())

        reader = PackReader(pack_path)
        self.assertTrue(reader.has_object("1" * 64))
        self.assertTrue(reader.has_object("2" * 64))

        obj_type, data = reader.read_object("1" * 64)
        self.assertEqual(obj_type, ObjectType.BLOB)
        self.assertEqual(data, b"hello blob content 1")

    def test_repository_gc(self):
        repo = Repository.init(self.repo_dir)

        # Create two files and commit
        f1 = self.repo_dir / "f1.txt"
        f1.write_text("file 1 content")
        f2 = self.repo_dir / "f2.txt"
        f2.write_text("file 2 content")

        repo.add(["f1.txt", "f2.txt"])
        sha1, commit1 = repo.commit("Commit 1")

        # Create an unreferenced loose blob (orphan)
        orphan_sha = repo.store.write_blob(b"orphan unreferenced data")

        loose_before = repo.store.list_loose_objects()
        self.assertTrue(len(loose_before) >= 3)  # blobs + trees + commit

        # Run GC
        stats = repo.gc()

        self.assertTrue(stats["packed_objects"] >= 3)
        self.assertEqual(stats["pruned_objects"], 1)  # orphan pruned

        # Verify packed objects are still seamlessly readable through store!
        b1_sha = repo.index.get("f1.txt").sha
        data1 = repo.store.read_blob(b1_sha)
        self.assertEqual(data1, b"file 1 content")

        # Verify orphan is deleted
        with self.assertRaises(FileNotFoundError):
            repo.store.read_blob(orphan_sha)


if __name__ == "__main__":
    unittest.main()
