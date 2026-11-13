"""Unit tests for VCX core object store and repository."""

from pathlib import Path
import tempfile
import unittest

from vcx.core.object_store import ObjectStore
from vcx.core.repository import Repository
from vcx.core.types import FileMode, ObjectType, TreeEntry


class TestCoreObjectStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        self.store = ObjectStore(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_blob_storage(self):
        data = b"module alu(input [31:0] a, b, output [31:0] out);\nendmodule"
        sha = self.store.write_blob(data)
        self.assertTrue(len(sha) == 64)

        read_data = self.store.read_blob(sha)
        self.assertEqual(read_data, data)

    def test_tree_storage(self):
        entries = [
            TreeEntry(mode=FileMode.REGULAR.value, path="src/alu.v", sha="a" * 64, file_type="eda/verilog"),
            TreeEntry(mode=FileMode.REGULAR.value, path="src/main.rs", sha="b" * 64, file_type="source/rust"),
        ]
        tree_sha = self.store.write_tree(entries)
        read_entries = self.store.read_tree(tree_sha)
        self.assertEqual(len(read_entries), 2)
        self.assertEqual(read_entries[0].path, "src/alu.v")
        self.assertEqual(read_entries[1].path, "src/main.rs")

    def test_commit_storage(self):
        commit_sha = self.store.write_commit(
            tree_sha="t" * 64,
            parent_shas=[],
            message="Initial commit",
            author="Dev <dev@test.local>",
            semantic_delta={"action_summary": "Initial commit", "technical_delta": ["Added initial files"], "tags": ["init"]},
        )
        commit = self.store.read_commit(commit_sha)
        self.assertEqual(commit.message, "Initial commit")
        self.assertEqual(commit.author, "Dev <dev@test.local>")
        self.assertIsNotNone(commit.semantic_delta)


class TestRepositoryOperations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        self.repo = Repository.init(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_init_creates_structure(self):
        self.assertTrue((self.repo_dir / ".vcx").exists())
        self.assertTrue((self.repo_dir / ".vcx" / "objects").exists())
        self.assertTrue((self.repo_dir / ".vcx" / "HEAD").exists())

    def test_add_and_commit(self):
        test_file = self.repo_dir / "test.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        staged = self.repo.add(["test.py"])
        self.assertIn("test.py", staged)

        st = self.repo.status()
        self.assertEqual(len(st["staged"]), 1)
        self.assertEqual(st["staged"][0]["path"], "test.py")

        sha, commit = self.repo.commit(message="Add hello function")
        self.assertEqual(commit.message, "Add hello function")
        self.assertEqual(self.repo.head_commit_sha, sha)

        # Working tree is clean now
        st2 = self.repo.status()
        self.assertEqual(len(st2["staged"]), 0)
        self.assertEqual(len(st2["unstaged"]), 0)


if __name__ == "__main__":
    unittest.main()
