"""Unit tests for CAD Solid B-Rep, STEP Entity Parser, and 3D Tessellator."""

from __future__ import annotations
import unittest

from vcx.diff.cad_engine import CadTessellator, StepBrepParser


class TestCadEngine(unittest.TestCase):
    def test_step_brep_parser_geometry(self):
        sample_step = """
ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('FreeCAD Model'),'2;1');
ENDSEC;
DATA;
#10 = CARTESIAN_POINT('Origin', (0.0, 0.0, 0.0));
#20 = CARTESIAN_POINT('P1', (50.5, 20.0, 10.0));
#30 = CARTESIAN_POINT('P2', (-10.5, 80.0, 30.0));
#40 = CARTESIAN_POINT('Scientific', (1.5e1, 2.0e1, -5.0));
#50 = CLOSED_SHELL('Shell1', (#60, #70));
#60 = ADVANCED_FACE('Face1', (#80), #90, .T.);
#70 = ADVANCED_FACE('Face2', (#81), #91, .T.);
#100 = MANIFOLD_SOLID_BREP('Solid1', #50);
#110 = EDGE_CURVE('Edge1', #10, #20, #120, .T.);
ENDSEC;
END-ISO-10303-21;
"""
        parser = StepBrepParser(sample_step)

        self.assertEqual(len(parser.points), 4)
        self.assertEqual(parser.solids, 1)
        self.assertEqual(parser.faces, 2)
        self.assertEqual(parser.closed_shells, 1)
        self.assertEqual(parser.edges, 1)

        # Min: (-10.5, 0.0, -5.0), Max: (50.5, 80.0, 30.0)
        # Dimensions: dx = 50.5 - (-10.5) = 61.0, dy = 80.0, dz = 35.0
        dims = parser.dimensions_mm
        self.assertIsNotNone(dims)
        self.assertAlmostEqual(dims[0], 61.0, places=2)
        self.assertAlmostEqual(dims[1], 80.0, places=2)
        self.assertAlmostEqual(dims[2], 35.0, places=2)

    def test_step_brep_empty_and_malformed(self):
        empty_parser = StepBrepParser("RANDOM_TEXT_NO_POINTS")
        self.assertIsNone(empty_parser.bounding_box)
        self.assertIsNone(empty_parser.dimensions_mm)
        self.assertEqual(empty_parser.solids, 0)

    def test_cad_tessellator_step_analysis(self):
        step_bytes = b"""
ISO-10303-21;
DATA;
#1 = CARTESIAN_POINT('', (0.0, 0.0, 0.0));
#2 = CARTESIAN_POINT('', (100.0, 50.0, 25.0));
#3 = MANIFOLD_SOLID_BREP('Solid', #4);
#4 = CLOSED_SHELL('', ());
ENDSEC;
"""
        stats = CadTessellator.analyze_mesh(step_bytes, "enclosure.step")
        self.assertEqual(stats["format"], "STEP_BREP")
        self.assertEqual(stats["solids"], 1)
        self.assertEqual(stats["closed_shells"], 1)
        self.assertTrue(stats["is_manifold"])
        self.assertEqual(stats["bounding_box_mm"], [100.0, 50.0, 25.0])

    def test_cad_tessellator_stl_analysis(self):
        # Minimal ASCII STL solid box
        ascii_stl = b"""solid test
facet normal 0.0 0.0 1.0
  outer loop
    vertex 0.0 0.0 0.0
    vertex 10.0 0.0 0.0
    vertex 10.0 10.0 0.0
  endloop
endfacet
endsolid test
"""
        stats = CadTessellator.analyze_mesh(ascii_stl, "bracket.stl")
        self.assertEqual(stats["format"], "POLYGON_MESH")
        self.assertGreaterEqual(stats["faces"], 1)

    def test_generate_vision_summary(self):
        old_meta = {
            "mesh_stats": {
                "bounding_box_mm": [50.0, 20.0, 10.0],
                "vertices": 120,
                "faces": 240,
                "is_manifold": True,
            },
            "parametric_features": {
                "BaseExtrusion": "10mm",
            },
        }

        new_meta = {
            "mesh_stats": {
                "bounding_box_mm": [50.0, 20.0, 15.0],
                "vertices": 136,
                "faces": 272,
                "is_manifold": True,
            },
            "parametric_features": {
                "BaseExtrusion": "15mm",
                "EdgeFillet": "2mm",
            },
        }

        summary = CadTessellator.generate_vision_summary(old_meta, new_meta, "chassis.step")

        self.assertIn("3D Viewport: Bounding box [50.0 x 20.0 x 15.0] mm", summary)
        self.assertIn("Extents updated from [50.0 x 20.0 x 10.0] mm", summary)
        self.assertIn("Topology delta: +16 vertices, +32 faces", summary)
        self.assertIn("Closed manifold shell verified", summary)
        self.assertIn("Modified BaseExtrusion: 10mm -> 15mm", summary)
        self.assertIn("Added feature EdgeFillet (2mm)", summary)


if __name__ == "__main__":
    unittest.main()
