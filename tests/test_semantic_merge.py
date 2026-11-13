"""Unit tests for Multi-Domain 3-Way Semantic Merge Engine."""

from pathlib import Path
import tempfile
import unittest

from vcx.core.repository import Repository
from vcx.diff.merger import SemanticMerger


class TestSemanticMerge(unittest.TestCase):
    def setUp(self):
        self.merger = SemanticMerger()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_verilog_eda_semantic_merge(self):
        base = b"""
        module alu_core (
            input clk,
            input [31:0] a, b,
            output reg [31:0] out
        );
            always @(posedge clk) out <= a + b;
        endmodule
        """
        # Branch A adds opcode port
        ours = b"""
        module alu_core (
            input clk,
            input [31:0] a, b,
            input [3:0] opcode,
            output reg [31:0] out
        );
            always @(posedge clk) out <= a + b;
        endmodule
        """
        # Branch B adds reset port
        theirs = b"""
        module alu_core (
            input clk,
            input rst_n,
            input [31:0] a, b,
            output reg [31:0] out
        );
            always @(posedge clk) out <= a + b;
        endmodule
        """

        success, merged_bytes, notes, conflict = self.merger.merge(
            base, ours, theirs, "alu_core.v", "eda/verilog"
        )
        self.assertTrue(success)
        self.assertIsNone(conflict)
        merged_text = merged_bytes.decode("utf-8")
        self.assertIn("opcode", merged_text)
        self.assertIn("rst_n", merged_text)

    def test_cad_freecad_parametric_merge(self):
        base = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="20.0"/></Property>
        </Object></Document>"""
        # Ours increases extrusion length to 25.0
        ours = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="25.0"/></Property>
        </Object></Document>"""
        # Theirs adds a 2mm fillet radius
        theirs = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="20.0"/></Property>
            <Property name="FilletRadius"><Float value="2.0"/></Property>
        </Object></Document>"""

        success, merged_bytes, notes, conflict = self.merger.merge(
            base, ours, theirs, "chassis.fcstd", "cad/freecad"
        )
        self.assertTrue(success)
        self.assertIsNone(conflict)
        merged_xml = merged_bytes.decode("utf-8")
        self.assertIn('value="25.0"', merged_xml)
        self.assertIn('FilletRadius', merged_xml)
        self.assertIn('value="2.0"', merged_xml)

    def test_cad_conflicting_parametric_dimensions(self):
        base = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="20.0"/></Property>
        </Object></Document>"""
        # Ours sets extrusion to 25.0
        ours = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="25.0"/></Property>
        </Object></Document>"""
        # Theirs sets extrusion to 30.0 (direct collision)
        theirs = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="30.0"/></Property>
        </Object></Document>"""

        success, _, _, conflict = self.merger.merge(
            base, ours, theirs, "chassis.fcstd", "cad/freecad"
        )
        self.assertFalse(success)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.domain, "cad-parametric")

    def test_python_ast_function_merge(self):
        base = b"def common():\n    return 0\n"
        ours = b"def common():\n    return 0\n\ndef func_a():\n    return 'A'\n"
        theirs = b"def common():\n    return 0\n\ndef func_b():\n    return 'B'\n"

        success, merged_bytes, notes, conflict = self.merger.merge(
            base, ours, theirs, "utils.py", "source/python"
        )
        self.assertTrue(success)
        self.assertIsNone(conflict)
        merged_code = merged_bytes.decode("utf-8")
        self.assertIn("func_a", merged_code)
        self.assertIn("func_b", merged_code)

    def test_repository_branch_and_merge_workflow(self):
        repo = Repository.init(self.repo_dir)

        # Baseline commit on main
        f = self.repo_dir / "math.py"
        f.write_text("def base_calc():\n    return 10\n")
        repo.add(["math.py"])
        repo.commit("Baseline on main")

        # Create and checkout feature branch
        repo.create_branch("feature-a")
        repo.checkout("feature-a")

        # Feature A adds multiply function
        f.write_text("def base_calc():\n    return 10\n\ndef multiply(x, y):\n    return x * y\n")
        repo.add(["math.py"])
        repo.commit("Add multiply in feature-a")

        # Switch back to main
        repo.checkout("main")
        # Main adds divide function
        f.write_text("def base_calc():\n    return 10\n\ndef divide(x, y):\n    return x / y\n")
        repo.add(["math.py"])
        repo.commit("Add divide on main")

        # Merge feature-a into main!
        res = repo.merge("feature-a")
        self.assertTrue(res.success)
        self.assertEqual(len(res.conflicts), 0)

        merged_content = f.read_text()
        self.assertIn("multiply", merged_content)
        self.assertIn("divide", merged_content)


if __name__ == "__main__":
    unittest.main()
