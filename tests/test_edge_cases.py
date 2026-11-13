"""Edge case and stress tests for VCX."""

from pathlib import Path
import tempfile
import unittest

from vcx.agent.schemas import DifferInput, DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.core.repository import Repository
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type


class TestEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        self.repo = Repository.init(self.repo_dir)
        self.agent = SemanticDifferAgent()
        self.engine = DeltaEngine()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_file_diff(self):
        payload = self.engine.analyze_change("empty.py", b"", b"")
        res = self.agent.analyze(payload.to_dict())
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIsInstance(res.technical_delta, list)

    def test_file_deletion_and_addition(self):
        f = self.repo_dir / "temp.rs"
        f.write_text("pub fn main() {}\n")
        self.repo.add(["temp.rs"])
        self.repo.commit("Add temp.rs")

        # Delete from disk
        f.unlink()
        st = self.repo.status()
        self.assertTrue(any(u["path"] == "temp.rs" and u["type"] == "deleted" for u in st["unstaged"]))

        # Stage deletion
        self.repo.add(["temp.rs"])
        self.assertNotIn("temp.rs", self.repo.index)

    def test_corrupt_or_malformed_freecad_xml(self):
        corrupt_xml = b"<Document><UnclosedTag>"
        payload = self.engine.analyze_change("broken.fcstd", b"", corrupt_xml)
        res = self.agent.analyze(payload.to_dict())
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIn("cad-geometry", res.tags)

    def test_corrupt_sqlite_db(self):
        corrupt_db = b"SQLite format 3\000\xff\xff\xff\xffGarbageData"
        payload = self.engine.analyze_change("broken.db", b"", corrupt_db)
        res = self.agent.analyze(payload.to_dict())
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIn("database", res.tags)

    def test_long_action_summary_truncation(self):
        output = DifferOutput(
            action_summary="This is an extremely excessively verbose action summary that is much longer than fifty characters limit",
            technical_delta=["Fact 1"],
            inferred_intent="Intent",
            tags=["tag"],
        )
        d = output.to_dict()
        self.assertTrue(len(d["action_summary"]) < 50)
        self.assertTrue(d["action_summary"].endswith("..."))

    def test_untracked_and_ignored_directories(self):
        # Create ignored dirs
        (self.repo_dir / ".git").mkdir()
        (self.repo_dir / ".git" / "dummy").write_text("ignore me")
        (self.repo_dir / "__pycache__").mkdir()
        (self.repo_dir / "__pycache__" / "temp.pyc").write_text("ignore me")

        st = self.repo.status()
        self.assertEqual(len(st["untracked"]), 0)


if __name__ == "__main__":
    unittest.main()
