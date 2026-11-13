"""Unit tests for VCX Semantic Differ Agent schema compliance and accuracy."""

import json
import unittest

from vcx.agent.schemas import DifferInput, DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent


class TestSemanticDifferAgent(unittest.TestCase):
    def setUp(self):
        self.agent = SemanticDifferAgent()

    def test_schema_validity(self):
        output = DifferOutput(
            action_summary="Update RISC-V ALU pipeline logic",
            technical_delta=[
                "Added 4-bit opcode decoding logic to execution stage",
                "Modified always @(posedge clk) datapath registers",
            ],
            inferred_intent="Improve ALU execution stage throughput and instruction decode timing.",
            tags=["eda-hardware", "risc-v", "pipeline"],
        )
        json_str = output.to_json()
        data = json.loads(json_str)

        self.assertIn("action_summary", data)
        self.assertIn("technical_delta", data)
        self.assertIn("inferred_intent", data)
        self.assertIn("tags", data)
        self.assertTrue(len(data["action_summary"]) < 50)
        self.assertIsInstance(data["technical_delta"], list)
        self.assertIsInstance(data["tags"], list)

    def test_hardware_eda_analysis(self):
        payload = {
            "file_name": "riscv_alu.v",
            "file_type": "eda/verilog",
            "previous_metadata": {"modules": {"alu": {"ports": ["input clk", "input [31:0] a, b"]}}},
            "current_metadata": {"modules": {"alu": {"ports": ["input clk", "input [31:0] a, b", "input [3:0] opcode"]}}},
            "raw_diff": "+ input [3:0] opcode\n+ always @(posedge clk) case (opcode)",
            "vision_summary": "",
        }
        res = self.agent.analyze(payload)
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIn("eda-hardware", res.tags)
        self.assertTrue(len(res.technical_delta) > 0)
        self.assertTrue(len(res.inferred_intent) > 0)

    def test_cad_3d_fillet_analysis(self):
        payload = {
            "file_name": "chassis.fcstd",
            "file_type": "cad/freecad",
            "previous_metadata": {"parametric_features": {"Extrusion": "20mm"}},
            "current_metadata": {"parametric_features": {"Extrusion": "20mm", "Fillet": "2mm"}},
            "raw_diff": "+ Fillet: 2mm",
            "vision_summary": "Added 2mm fillet to chassis edge",
        }
        res = self.agent.analyze(payload)
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIn("cad-geometry", res.tags)
        self.assertTrue(any("2mm fillet" in d.lower() for d in res.technical_delta))

    def test_cad_3d_extrusion_analysis(self):
        payload = {
            "file_name": "base_plate.step",
            "file_type": "cad/step",
            "previous_metadata": {"parametric_features": {"Thickness": "10mm"}},
            "current_metadata": {"parametric_features": {"Thickness": "15mm"}},
            "raw_diff": "+ extrusion thickness +5mm",
            "vision_summary": "Base extrusion thickness increased by 5mm",
        }
        res = self.agent.analyze(payload)
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIn("cad-geometry", res.tags)
        self.assertTrue(any("thickness by 5mm" in d.lower() or "extrusion" in d.lower() for d in res.technical_delta))

    def test_database_logs_analysis(self):
        payload = {
            "file_name": "trade_executions.csv",
            "file_type": "database/csv",
            "previous_metadata": {"total_rows": 100},
            "current_metadata": {"total_rows": 115},
            "raw_diff": "+ 15 rows appended",
            "vision_summary": "",
        }
        res = self.agent.analyze(payload)
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIn("database", res.tags)
        self.assertTrue(any("15 new" in d for d in res.technical_delta))

    def test_binary_file_system_analysis(self):
        payload = {
            "file_name": "firmware.bin",
            "file_type": "binary/unknown",
            "previous_metadata": {"size_bytes": 1048576},
            "current_metadata": {"size_bytes": 5242880},  # +4MB
            "raw_diff": "Binary file size increased by 4MB",
            "vision_summary": "",
        }
        res = self.agent.analyze(payload)
        self.assertTrue(len(res.action_summary) < 50)
        self.assertIn("binary", res.tags)
        self.assertTrue(any("4MB" in d or "increased" in d for d in res.technical_delta))


if __name__ == "__main__":
    unittest.main()
