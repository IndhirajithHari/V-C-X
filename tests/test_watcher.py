"""Unit tests for WorkspaceWatcher."""

from pathlib import Path
import tempfile
import time
import unittest

from vcx.core.repository import Repository
from vcx.watcher.watcher import WorkspaceWatcher


class TestWorkspaceWatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        self.repo = Repository.init(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_watcher_detects_and_analyzes(self):
        detected = []

        def callback(payload, output):
            detected.append((payload, output))

        watcher = WorkspaceWatcher(
            repo=self.repo,
            debounce_seconds=0.1,
            auto_commit=True,
            on_change_callback=callback,
        )

        test_file = self.repo_dir / "alu.v"
        test_file.write_text("module alu(input clk, output reg [31:0] out);\nendmodule\n")

        # Initial commit so it is tracked
        self.repo.add(["alu.v"])
        self.repo.commit("Initial ALU")

        # Now simulate a file change
        test_file.write_text(
            "module alu(input clk, input [3:0] opcode, output reg [31:0] out);\n"
            "always @(posedge clk) out <= 32'b1;\nendmodule\n"
        )

        # Trigger watcher
        watcher.trigger_change("alu.v")
        time.sleep(0.2)
        watcher._process_debounced_changes()

        self.assertEqual(len(detected), 1)
        payload, output = detected[0]
        self.assertEqual(payload.file_name, "alu.v")
        self.assertEqual(payload.file_type, "eda/verilog")
        self.assertTrue(len(output.action_summary) < 50)
        self.assertIn("eda-hardware", output.tags)

        # Verify auto-commit was recorded
        commits = self.repo.log(limit=5)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0][1].message, output.action_summary)


if __name__ == "__main__":
    unittest.main()
