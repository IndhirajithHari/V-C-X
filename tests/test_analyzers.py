"""Unit tests for domain-specific diff analyzers."""

import json
import sqlite3
import tempfile
import unittest

from vcx.diff.analyzers.binary import BinaryAnalyzer
from vcx.diff.analyzers.cad_3d import Cad3DAnalyzer
from vcx.diff.analyzers.database_logs import DatabaseLogsAnalyzer
from vcx.diff.analyzers.eda_hardware import EdaHardwareAnalyzer
from vcx.diff.analyzers.source_code import SourceCodeAnalyzer
from vcx.diff.delta_engine import DeltaEngine


class TestAnalyzers(unittest.TestCase):
    def test_source_code_analyzer_python(self):
        analyzer = SourceCodeAnalyzer()
        old_py = b"def calculate(a, b):\n    return a + b\n"
        new_py = b"def calculate(a, b, c=0):\n    return a + b + c\n\ndef multiply(x, y):\n    return x * y\n"

        res = analyzer.analyze(old_py, new_py, "math_utils.py")
        self.assertIn("multiply", res.domain_facts["added_functions"])
        self.assertIn("calculate", res.domain_facts["modified_signatures"])

    def test_eda_hardware_analyzer_verilog(self):
        analyzer = EdaHardwareAnalyzer()
        old_v = b"""
        module alu_pipeline (
            input clk,
            input [31:0] a, b,
            output reg [31:0] alu_out
        );
            always @(posedge clk) begin
                alu_out <= a + b;
            end
        endmodule
        """
        new_v = b"""
        module alu_pipeline (
            input clk,
            input [31:0] a, b,
            input [3:0] alu_opcode,
            output reg [31:0] alu_out
        );
            always @(posedge clk) begin
                case (alu_opcode)
                    4'b0000: alu_out <= a + b;
                    4'b0001: alu_out <= a - b;
                    default: alu_out <= 32'b0;
                endcase
            end
        endmodule
        """
        res = analyzer.analyze(old_v, new_v, "riscv_alu.v")
        self.assertIn("alu_pipeline", res.domain_facts["modified_ports"])
        self.assertTrue(len(res.raw_diff) > 0)

    def test_cad_3d_analyzer_parametric(self):
        analyzer = Cad3DAnalyzer()
        old_xml = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="20.0"/></Property>
        </Object></Document>"""
        new_xml = b"""<Document><Object name="Chassis" type="PartDesign::Body">
            <Property name="ExtrusionLength"><Float value="25.0"/></Property>
            <Property name="FilletRadius"><Float value="2.0"/></Property>
        </Object></Document>"""

        res = analyzer.analyze(old_xml, new_xml, "chassis.fcstd")
        self.assertTrue(any("ExtrusionLength" in c for c in res.domain_facts["parametric_changes"]))

    def test_database_logs_analyzer_sqlite(self):
        analyzer = DatabaseLogsAnalyzer()
        # Create temp sqlite db
        with tempfile.NamedTemporaryFile(suffix=".db") as f1, tempfile.NamedTemporaryFile(suffix=".db") as f2:
            conn1 = sqlite3.connect(f1.name)
            conn1.execute("CREATE TABLE trades (id INT, symbol TEXT, price REAL);")
            conn1.execute("INSERT INTO trades VALUES (1, 'NVDA', 120.5);")
            conn1.commit()
            conn1.close()

            conn2 = sqlite3.connect(f2.name)
            conn2.execute("CREATE TABLE trades (id INT, symbol TEXT, price REAL);")
            conn2.execute("INSERT INTO trades VALUES (1, 'NVDA', 120.5);")
            conn2.execute("INSERT INTO trades VALUES (2, 'TSMC', 180.2);")
            conn2.commit()
            conn2.close()

            with open(f1.name, "rb") as bf1:
                b1 = bf1.read()
            with open(f2.name, "rb") as bf2:
                b2 = bf2.read()

            res = analyzer.analyze(b1, b2, "market.db")
            self.assertEqual(res.domain_facts["table_deltas"].get("trades"), 1)

    def test_binary_analyzer(self):
        analyzer = BinaryAnalyzer()
        old_bin = b"\x00" * 1024
        new_bin = b"\x00" * (1024 + 4 * 1024 * 1024)  # +4MB

        res = analyzer.analyze(old_bin, new_bin, "firmware.bin")
        self.assertIn("File size increased by 4.0MB", res.domain_facts["size_description"])


if __name__ == "__main__":
    unittest.main()
