"""Comprehensive Unit Tests for Milestone 2: Adapters & Semantic Differ Hardening.

Covers:
1. CAD domain fact propagation in SemanticDifferAgent and SemanticExtractor
2. EDA domain fact propagation (ports, FSM, modules) in SemanticDifferAgent and SemanticExtractor
3. Real .fcstd PKZIP 3-way merge with Document.xml merge and member file preservation
4. Real .fcstd PKZIP dimensional collision detection (cad-parametric MergeConflict)
5. Verilog 3-way merge with #(parameter ...) block preservation
6. Verilog 3-way merge with port collision detection (eda-port MergeConflict)
7. Verilog identical port addition deduplication
8. Verilog preamble preservation (`timescale, `include)
9. schemas.py typing introspection (Optional) and None-safety in validate()
10. StepBrepParser ISO-10303-21 omitted attribute '*' and '$' support
11. Diff line and byte limit guards on massive files in SemanticExtractor
12. SemanticExtractor.analyze_change with pre-extracted DifferInput deduplication
"""

from __future__ import annotations
import io
import typing
import unittest
import zipfile

from vcx.agent.schemas import DifferInput, DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.diff.cad_engine import StepBrepParser
from vcx.diff.merger import SemanticMerger
from vcx.semantic import SemanticExtractor


class TestAdaptersHardening(unittest.TestCase):
    def setUp(self):
        self.agent = SemanticDifferAgent()
        self.merger = SemanticMerger()
        self.extractor = SemanticExtractor(agent=self.agent)

    # -------------------------------------------------------------------------
    # 1. CAD Domain Fact Propagation
    # -------------------------------------------------------------------------
    def test_cad_domain_fact_propagation(self):
        """Verify that properties_modified, objects_added/removed, and sketch_changes propagate to delta."""
        payload = DifferInput(
            file_name="chassis.fcstd",
            file_type="cad/freecad",
            previous_metadata={},
            current_metadata={},
            raw_diff="Parametric update",
            vision_summary="Updated chassis dimensions",
            domain_facts={
                "cad_domain": "FreeCAD",
                "properties_modified": [
                    {"object": "Chassis", "property": "Length", "old_value": "100.0", "new_value": "125.0"}
                ],
                "objects_added": [
                    {"name": "Fillet001", "type": "PartDesign::Fillet"}
                ],
                "objects_removed": [
                    {"name": "OldPocket", "type": "PartDesign::Pocket"}
                ],
                "sketch_changes": [
                    "Constraints modified in Sketch001 (4 -> 6)"
                ],
            },
        )
        res = self.agent.analyze(payload)
        self.assertIn("cad-geometry", res.tags)
        self.assertIn("freecad", res.tags)
        self.assertLess(len(res.action_summary), 50)

        # Must contain concrete modified properties
        delta_str = " ".join(res.technical_delta)
        self.assertIn("Chassis.Length", delta_str)
        self.assertIn("125.0", delta_str)
        self.assertIn("Fillet001", delta_str)
        self.assertIn("OldPocket", delta_str)
        self.assertIn("Sketch001", delta_str)
        self.assertNotIn("0 geometric features & bodies", delta_str)

    def test_cad_extractor_to_differ_fact_propagation(self):
        """End-to-end test from FreeCAD ZIP bytes through SemanticExtractor to DifferOutput."""
        b_buf = io.BytesIO()
        with zipfile.ZipFile(b_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "Document.xml",
                '<Document><Object name="Chassis" type="PartDesign::Body"><Property name="Length"><Float value="100.0"/></Property></Object></Document>',
            )
        c_buf = io.BytesIO()
        with zipfile.ZipFile(c_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "Document.xml",
                '<Document><Object name="Chassis" type="PartDesign::Body"><Property name="Length"><Float value="125.0"/></Property></Object></Document>',
            )

        out = self.extractor.analyze_change("chassis.fcstd", b_buf.getvalue(), c_buf.getvalue())
        self.assertTrue(any("Length" in d and "100.0" in d and "125.0" in d for d in out.technical_delta))
        self.assertNotIn("0 geometric features", str(out.technical_delta))

    # -------------------------------------------------------------------------
    # 2. EDA Domain Fact Propagation
    # -------------------------------------------------------------------------
    def test_eda_domain_fact_propagation(self):
        """Verify that port_changes, fsm_changes, and modules_added/removed propagate to RTL delta."""
        payload = DifferInput(
            file_name="uart_tx.v",
            file_type="eda/verilog",
            previous_metadata={},
            current_metadata={},
            raw_diff="RTL update",
            vision_summary="Updated UART interface",
            domain_facts={
                "hardware_domain": "RTL",
                "modules_added": ["uart_baud_gen"],
                "modules_removed": ["legacy_timer"],
                "port_changes": [
                    {"module": "uart_tx", "type": "added", "port": "enable", "direction": "input", "width": ""},
                    {"module": "uart_tx", "type": "modified", "port": "data_in", "old": "input [7:0]", "new": "input [15:0]"},
                    {"module": "uart_tx", "type": "removed", "port": "legacy_strobe"},
                ],
                "fsm_changes": [
                    "Module 'uart_tx': Added FSM states: IDLE, TRANSMIT"
                ],
            },
        )
        res = self.agent.analyze(payload)
        self.assertIn("eda-hardware", res.tags)
        self.assertLess(len(res.action_summary), 50)

        delta_str = " ".join(res.technical_delta)
        self.assertIn("enable", delta_str)
        self.assertIn("data_in", delta_str)
        self.assertIn("legacy_strobe", delta_str)
        self.assertIn("IDLE, TRANSMIT", delta_str)
        self.assertIn("uart_baud_gen", delta_str)
        self.assertIn("legacy_timer", delta_str)

    def test_eda_extractor_to_differ_fact_propagation(self):
        """End-to-end test from Verilog source code through SemanticExtractor to DifferOutput."""
        v_base = """
        module uart_tx (
            input clk,
            input [7:0] data_in,
            output reg tx
        );
        endmodule
        """
        v_curr = """
        module uart_tx (
            input clk,
            input [15:0] data_in,
            input enable,
            output reg tx,
            output reg busy
        );
        localparam S_IDLE = 2'b00;
        localparam S_TRANSMIT = 2'b01;
        endmodule
        """
        out = self.extractor.analyze_change("uart_tx.v", v_base.encode("utf-8"), v_curr.encode("utf-8"))
        deltas = " ".join(out.technical_delta)
        self.assertIn("data_in", deltas)
        self.assertIn("15:0", deltas)
        self.assertIn("enable", deltas)
        self.assertIn("busy", deltas)
        self.assertIn("S_TRANSMIT", deltas)
        self.assertNotIn("Refactored uart_tx module logic and port mappings", out.technical_delta)

    # -------------------------------------------------------------------------
    # 3. Real .fcstd PKZIP 3-Way Merge
    # -------------------------------------------------------------------------
    def test_real_fcstd_pkzip_3way_merge(self):
        """Verify 3-way merge on valid binary PKZIP .fcstd files with member preservation."""
        def make_zip(xml_content: str, extra_files: dict[str, bytes] | None = None) -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("Document.xml", xml_content)
                zf.writestr("GuiDocument.xml", '<GuiDocument version="1.0"/>')
                if extra_files:
                    for name, data in extra_files.items():
                        zf.writestr(name, data)
            return buf.getvalue()

        base_xml = '<Document><Object name="Chassis" type="PartDesign::Body"><Property name="Length"><Float value="100.0"/></Property></Object></Document>'
        ours_xml = '<Document><Object name="Chassis" type="PartDesign::Body"><Property name="Length"><Float value="125.0"/></Property></Object></Document>'
        theirs_xml = '<Document><Object name="Chassis" type="PartDesign::Body"><Property name="Length"><Float value="100.0"/></Property><Property name="Fillet"><Float value="2.0"/></Property></Object></Document>'

        base = make_zip(base_xml)
        ours = make_zip(ours_xml, {"thumbnails/Thumbnail.png": b"PNG_DATA_OURS"})
        theirs = make_zip(theirs_xml, {"textures/metal.jpg": b"JPG_DATA_THEIRS"})

        success, merged_bytes, notes, conflict = self.merger.merge(
            base, ours, theirs, "chassis.fcstd", "cad/freecad"
        )
        self.assertTrue(success, f"Merge failed: {conflict}")
        self.assertIsNone(conflict)
        self.assertTrue(merged_bytes.startswith(b"PK\x03\x04"), "Must be a valid PKZIP file")

        # Inspect merged contents
        with zipfile.ZipFile(io.BytesIO(merged_bytes)) as zf:
            names = zf.namelist()
            self.assertIn("Document.xml", names)
            self.assertIn("GuiDocument.xml", names)
            self.assertIn("thumbnails/Thumbnail.png", names)
            self.assertIn("textures/metal.jpg", names)

            doc_merged = zf.read("Document.xml").decode("utf-8")
            self.assertIn('value="125.0"', doc_merged)
            self.assertIn("Fillet", doc_merged)
            self.assertIn('value="2.0"', doc_merged)

    def test_real_fcstd_pkzip_collision(self):
        """Verify that conflicting dimensions in real .fcstd produce cad-parametric MergeConflict."""
        def make_zip(xml_content: str) -> bytes:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("Document.xml", xml_content)
            return buf.getvalue()

        base = make_zip('<Document><Object name="Chassis"><Property name="Length"><Float value="100.0"/></Property></Object></Document>')
        ours = make_zip('<Document><Object name="Chassis"><Property name="Length"><Float value="125.0"/></Property></Object></Document>')
        theirs = make_zip('<Document><Object name="Chassis"><Property name="Length"><Float value="150.0"/></Property></Object></Document>')

        success, _, _, conflict = self.merger.merge(
            base, ours, theirs, "chassis.fcstd", "cad/freecad"
        )
        self.assertFalse(success)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.domain, "cad-parametric")
        self.assertIn("Length", conflict.description)

    # -------------------------------------------------------------------------
    # 4. Verilog Parameter Preservation, Port Collision, & Preamble
    # -------------------------------------------------------------------------
    def test_verilog_parameter_preservation(self):
        """Verify that #(parameter ...) blocks are preserved during 3-way Verilog merge."""
        base = b"""module uart_tx #(parameter CLK_HZ = 50000000, parameter BAUD = 115200) (
            input clk,
            output reg tx
        );
            always @(posedge clk) tx <= 1;
        endmodule"""

        ours = b"""module uart_tx #(parameter CLK_HZ = 50000000, parameter BAUD = 115200) (
            input clk,
            input enable,
            output reg tx
        );
            always @(posedge clk) tx <= 1;
        endmodule"""

        theirs = b"""module uart_tx #(parameter CLK_HZ = 50000000, parameter BAUD = 115200) (
            input clk,
            output reg tx,
            output reg busy
        );
            always @(posedge clk) tx <= 1;
        endmodule"""

        success, merged_bytes, notes, conflict = self.merger.merge(
            base, ours, theirs, "uart_tx.v", "eda/verilog"
        )
        self.assertTrue(success, f"Merge failed: {conflict}")
        self.assertIsNone(conflict)

        text = merged_bytes.decode("utf-8")
        self.assertIn("parameter CLK_HZ = 50000000", text)
        self.assertIn("parameter BAUD = 115200", text)
        self.assertIn("enable", text)
        self.assertIn("busy", text)

    def test_verilog_port_collision_detection(self):
        """Verify that adding colliding port definitions triggers an eda-port MergeConflict."""
        base = b"""module bus_interface (
            input clk
        );
            assign out = 0;
        endmodule"""

        # Ours adds 16-bit data port
        ours = b"""module bus_interface (
            input clk,
            input [15:0] data
        );
            assign out = 0;
        endmodule"""

        # Theirs adds 32-bit data port with colliding name
        theirs = b"""module bus_interface (
            input clk,
            input [31:0] data
        );
            assign out = 0;
        endmodule"""

        success, _, _, conflict = self.merger.merge(
            base, ours, theirs, "bus_interface.v", "eda/verilog"
        )
        self.assertFalse(success)
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.domain, "eda-port")
        self.assertIn("data", conflict.description)

    def test_verilog_identical_port_addition_deduplication(self):
        """Verify that identical non-conflicting port additions on both branches are deduplicated."""
        base = b"""module bus_interface (input clk);
            assign out = 0;
        endmodule"""
        ours = b"""module bus_interface (input clk, input rst_n);
            assign out = 0;
        endmodule"""
        theirs = b"""module bus_interface (input clk, input rst_n);
            assign out = 0;
        endmodule"""

        success, merged_bytes, _, conflict = self.merger.merge(
            base, ours, theirs, "bus_interface.v", "eda/verilog"
        )
        self.assertTrue(success)
        self.assertIsNone(conflict)
        text = merged_bytes.decode("utf-8")
        self.assertEqual(text.count("rst_n"), 1, "Duplicate port declaration was generated!")

    def test_verilog_preamble_preservation(self):
        """Verify that preamble compiler directives like `timescale are preserved."""
        base = b"""`timescale 1ns/1ps

module top (
    input clk
);
    assign q = clk;
endmodule"""
        ours = b"""`timescale 1ns/1ps

module top (
    input clk,
    input enable
);
    assign q = clk;
endmodule"""
        theirs = b"""`timescale 1ns/1ps

module top (
    input clk,
    output ready
);
    assign q = clk;
endmodule"""

        success, merged_bytes, _, conflict = self.merger.merge(
            base, ours, theirs, "top.v", "eda/verilog"
        )
        self.assertTrue(success)
        self.assertIsNone(conflict)
        text = merged_bytes.decode("utf-8")
        self.assertIn("`timescale 1ns/1ps", text)
        self.assertIn("enable", text)
        self.assertIn("ready", text)

    # -------------------------------------------------------------------------
    # 5. Schema Type Hint & None Safety
    # -------------------------------------------------------------------------
    def test_schemas_typing_and_none_safety(self):
        """Verify typing.get_type_hints succeeds and None action_summary is guarded."""
        hints = typing.get_type_hints(DifferInput)
        self.assertIn("domain_facts", hints)

        # Test from_dict with None action_summary
        out = DifferOutput.from_dict({
            "action_summary": None,
            "technical_delta": None,
            "inferred_intent": None,
            "tags": None,
        })
        self.assertIsNotNone(out.action_summary)
        self.assertEqual(out.action_summary, "Update file")
        self.assertLess(len(out.action_summary), 50)
        self.assertEqual(out.inferred_intent, "")

        # Test direct validate() with None
        raw_out = DifferOutput(None, ["Delta"], None, ["tag"])
        raw_out.validate()
        self.assertIsNotNone(raw_out.action_summary)
        self.assertEqual(raw_out.action_summary, "Update file")
        self.assertEqual(raw_out.inferred_intent, "")

    # -------------------------------------------------------------------------
    # 6. StepBrepParser Omitted Attribute Support
    # -------------------------------------------------------------------------
    def test_step_brep_omitted_attributes(self):
        """Verify StepBrepParser handles ISO-10303-21 '*' and '$' omitted attributes."""
        step_text = """ISO-10303-21;
DATA;
#10 = CARTESIAN_POINT('Origin', (0.0, 0.0, 0.0));
#20 = CARTESIAN_POINT('', (10.0, 20.0, 30.0));
#30 = CARTESIAN_POINT(*, (50.0, 60.0, 70.0));
#40 = CARTESIAN_POINT($, (-10.0, -20.0, -30.0));
#50 = CARTESIAN_POINT ( * , ( 100.0 , 200.0 , 300.0 ) );
#60 = MANIFOLD_SOLID_BREP(*, #70);
#70 = CLOSED_SHELL(*, ());
#80 = ADVANCED_FACE(*, (), #90, .T.);
#90 = EDGE_CURVE(*, #10, #20, #100, .T.);
ENDSEC;
END-ISO-10303-21;"""

        parser = StepBrepParser(step_text)
        self.assertEqual(len(parser.points), 5)
        self.assertEqual(parser.solids, 1)
        self.assertEqual(parser.closed_shells, 1)
        self.assertEqual(parser.faces, 1)
        self.assertEqual(parser.edges, 1)

        dims = parser.dimensions_mm
        self.assertIsNotNone(dims)
        # min_x = -10.0, max_x = 100.0 -> dx = 110.0
        # min_y = -20.0, max_y = 200.0 -> dy = 220.0
        # min_z = -30.0, max_z = 300.0 -> dz = 330.0
        self.assertAlmostEqual(dims[0], 110.0, places=1)
        self.assertAlmostEqual(dims[1], 220.0, places=1)
        self.assertAlmostEqual(dims[2], 330.0, places=1)

    # -------------------------------------------------------------------------
    # 7. Diff Line & Byte Limit Guard
    # -------------------------------------------------------------------------
    def test_diff_line_limit_guard_large_files(self):
        """Verify that diffing large text files (> 5000 lines) bypasses difflib unified_diff."""
        base_lines = [f"line {i}\n" for i in range(6000)]
        curr_lines = [f"line {i}\n" for i in range(6000)]
        curr_lines[100] = "modified line 100\n"

        base_bytes = "".join(base_lines).encode("utf-8")
        curr_bytes = "".join(curr_lines).encode("utf-8")

        diff_input = self.extractor._extract_code("large_netlist.v", base_bytes, curr_bytes)
        self.assertIn("large file", diff_input.raw_diff)
        self.assertIn("6000 lines", diff_input.raw_diff)

    def test_diff_byte_size_limit_guard(self):
        """Verify that diffing huge files (> 2MB) triggers size delta fallback."""
        base_bytes = b"0" * (2500000)
        curr_bytes = b"1" * (2600000)

        diff_input = self.extractor._extract_code("giant_data.txt", base_bytes, curr_bytes)
        self.assertIn("large file", diff_input.raw_diff)
        self.assertIn("bytes", diff_input.raw_diff)

    # -------------------------------------------------------------------------
    # 8. Extraction Deduplication in analyze_change
    # -------------------------------------------------------------------------
    def test_semantic_analyze_change_deduplication(self):
        """Verify analyze_change accepts pre-extracted DifferInput and does not re-extract."""
        extracted = DifferInput(
            file_name="logic.v",
            file_type="eda/verilog",
            previous_metadata={},
            current_metadata={},
            raw_diff="always @(posedge clk)",
        )
        # Calling analyze_change with pre-extracted diff_input
        out = self.extractor.analyze_change("logic.v", diff_input=extracted)
        self.assertIn("eda-hardware", out.tags)


if __name__ == "__main__":
    unittest.main()
