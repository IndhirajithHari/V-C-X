"""Unit tests for Git-style Hierarchical Merkle Trees and Subtree Reuse."""

from pathlib import Path
import tempfile
import unittest

from vcx.core.object_store import ObjectStore
from vcx.core.repository import Repository
from vcx.core.types import FileMode, IndexEntry, TreeEntry


class TestHierarchicalTrees(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        self.store = ObjectStore(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_hierarchical_tree_creation_and_flattening(self):
        entries = [
            IndexEntry(path="README.md", sha="1" * 64, size=10, mtime=0, file_type="text/plain"),
            IndexEntry(path="src/main.rs", sha="2" * 64, size=20, mtime=0, file_type="source/rust"),
            IndexEntry(path="src/alu/core.v", sha="3" * 64, size=30, mtime=0, file_type="eda/verilog"),
            IndexEntry(path="src/alu/pipe.v", sha="4" * 64, size=40, mtime=0, file_type="eda/verilog"),
            IndexEntry(path="docs/guide.md", sha="5" * 64, size=50, mtime=0, file_type="text/plain"),
        ]

        root_tree_sha = self.store.build_hierarchical_tree(entries)
        self.assertTrue(len(root_tree_sha) == 64)

        # Inspect root tree entries directly: should only have immediate children!
        root_entries = self.store.read_tree(root_tree_sha)
        names = {e.path: e for e in root_entries}

        self.assertIn("README.md", names)
        self.assertEqual(names["README.md"].obj_type, "blob")

        self.assertIn("src", names)
        self.assertEqual(names["src"].obj_type, "tree")
        self.assertEqual(names["src"].mode, FileMode.DIRECTORY.value)

        self.assertIn("docs", names)
        self.assertEqual(names["docs"].obj_type, "tree")

        # Now test flatten_tree
        flattened = self.store.flatten_tree(root_tree_sha)
        self.assertEqual(len(flattened), 5)
        self.assertEqual(flattened["src/alu/core.v"].sha, "3" * 64)
        self.assertEqual(flattened["src/main.rs"].sha, "2" * 64)
        self.assertEqual(flattened["docs/guide.md"].sha, "5" * 64)

    def test_subtree_reuse_across_commits(self):
        # 1. First commit with docs/ and src/
        entries_v1 = [
            IndexEntry(path="docs/spec.md", sha="a" * 64, size=10, mtime=0, file_type="text/plain"),
            IndexEntry(path="src/alu.v", sha="b" * 64, size=20, mtime=0, file_type="eda/verilog"),
        ]
        root_v1 = self.store.build_hierarchical_tree(entries_v1)
        root_entries_v1 = {e.path: e for e in self.store.read_tree(root_v1)}
        docs_sha_v1 = root_entries_v1["docs"].sha

        # 2. Modify only src/alu.v (docs/ unchanged)
        entries_v2 = [
            IndexEntry(path="docs/spec.md", sha="a" * 64, size=10, mtime=0, file_type="text/plain"),
            IndexEntry(path="src/alu.v", sha="c" * 64, size=25, mtime=0, file_type="eda/verilog"),
        ]
        root_v2 = self.store.build_hierarchical_tree(entries_v2)
        root_entries_v2 = {e.path: e for e in self.store.read_tree(root_v2)}
        docs_sha_v2 = root_entries_v2["docs"].sha

        # The docs subtree SHA MUST BE IDENTICAL! (Merkle subtree reuse)
        self.assertEqual(docs_sha_v1, docs_sha_v2)
        # The src subtree SHA MUST BE DIFFERENT
        self.assertNotEqual(root_entries_v1["src"].sha, root_entries_v2["src"].sha)


if __name__ == "__main__":
    unittest.main()
