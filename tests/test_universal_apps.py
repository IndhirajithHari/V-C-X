"""Comprehensive unit tests for universal application support across all software in the world."""

from __future__ import annotations
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

from vcx.agent.schemas import DifferInput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.core.config import ConfigManager
from vcx.core.plugins import PluginManager, register_plugin
from vcx.diff.analyzers.binary import BinaryAnalyzer
from vcx.diff.analyzers.universal_container import UniversalContainerAnalyzer
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type


class TestUniversalApps(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vcx_univ_test_")
        self.base_path = Path(self.tmp_dir)
        self.delta_engine = DeltaEngine(repo_dir=self.base_path)
        self.agent = SemanticDifferAgent()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_ableton_live_als_project(self):
        # Create minimal Ableton Live gzipped XML
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="11.0_11300" SchemaChangeCount="4" Creator="Ableton Live 11.3">
    <LiveSet>
        <Tempo><Manual Value="128.0"/></Tempo>
        <Tracks>
            <AudioTrack Id="1"><Name><UserName Value="Lead Vocal"/></Name></AudioTrack>
            <MidiTrack Id="2"><Name><UserName Value="Sub Bass"/></Name></MidiTrack>
            <AudioTrack Id="3"><Name><UserName Value="Drum Kit"/></Name></AudioTrack>
        </Tracks>
    </LiveSet>
</Ableton>"""
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(xml_content.encode("utf-8"))
        als_bytes = buf.getvalue()

        f_type = detect_file_type("drop_sequence.als", als_bytes)
        self.assertEqual(f_type, "music/ableton")

        payload = self.delta_engine.analyze_change("drop_sequence.als", None, als_bytes)
        self.assertEqual(payload.domain_facts.get("daw"), "Ableton Live")
        self.assertEqual(payload.domain_facts.get("tempo_bpm"), 128.0)
        self.assertEqual(payload.domain_facts.get("tracks_count"), 3)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("ableton-live", out.tags)
        self.assertTrue(any("128" in d for d in out.technical_delta))

    def test_reaper_rpp_session(self):
        rpp_content = """<REAPER_PROJECT 0.1 "6.80/linux-x86_64" 1680000000
  RIPPLE 0
  GROUPOVERRIDE 0 0 0
  TEMPO 140 4 4
  <TRACK {A1B2C3D4-0001}
    NAME "Guitar Lead"
    PEAKCOL 16576
  >
  <TRACK {A1B2C3D4-0002}
    NAME "Bassline"
    PEAKCOL 16576
  >
>"""
        rpp_bytes = rpp_content.encode("utf-8")
        f_type = detect_file_type("metal_track.rpp", rpp_bytes)
        self.assertEqual(f_type, "music/reaper")

        payload = self.delta_engine.analyze_change("metal_track.rpp", None, rpp_bytes)
        self.assertEqual(payload.domain_facts.get("tracks_count"), 2)
        self.assertEqual(payload.domain_facts.get("bpm"), 140.0)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("reaper", out.tags)

    def test_unity_scene_and_prefab(self):
        unity_content = """%YAML 1.1
%TAG !u! tag:unity3d.com,2011:
--- !u!1 &1001000
GameObject:
  m_ObjectHideFlags: 0
  m_CorrespondingSourceObject: {fileID: 0}
  m_PrefabInstance: {fileID: 0}
  m_PrefabAsset: {fileID: 0}
  serializedVersion: 6
  m_Component:
  - component: {fileID: 1001001}
  - component: {fileID: 1001002}
  m_Name: MainCharacter
--- !u!4 &1001001
Transform:
  m_GameObject: {fileID: 1001000}
--- !u!114 &1001002
MonoBehaviour:
  m_GameObject: {fileID: 1001000}
  m_Enabled: 1
  m_EditorHideFlags: 0
  m_Script: {fileID: 11500000, guid: a1b2c3d4, type: 3}
  m_Name: PlayerController
"""
        unity_bytes = unity_content.encode("utf-8")
        f_type = detect_file_type("Level01.unity", unity_bytes)
        self.assertEqual(f_type, "game/unity")

        payload = self.delta_engine.analyze_change("Level01.unity", None, unity_bytes)
        self.assertEqual(payload.domain_facts.get("engine"), "Unity")
        self.assertEqual(payload.domain_facts.get("game_objects_count"), 1)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("unity", out.tags)
        self.assertTrue(any("GameObjects" in d for d in out.technical_delta))

    def test_godot_scene(self):
        godot_content = """[gd_scene load_steps=3 format=3 uid="uid://c1x2y3z4"]

[ext_resource type="Script" path="res://player.gd" id="1_abc"]

[node name="World" type="Node3D"]

[node name="Player" type="CharacterBody3D" parent="."]
script = ExtResource("1_abc")

[node name="Camera3D" type="Camera3D" parent="Player"]
"""
        godot_bytes = godot_content.encode("utf-8")
        f_type = detect_file_type("world.tscn", godot_bytes)
        self.assertEqual(f_type, "game/godot")

        payload = self.delta_engine.analyze_change("world.tscn", None, godot_bytes)
        self.assertEqual(payload.domain_facts.get("engine"), "Godot")
        self.assertEqual(payload.domain_facts.get("nodes_count"), 3)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("godot", out.tags)

    def test_sketch_design_file(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            meta = {
                "pagesAndArtboards": {
                    "page-1": {
                        "name": "Page 1",
                        "artboards": {
                            "art-1": {"name": "LandingPage-Desktop"},
                            "art-2": {"name": "Mobile-Nav"},
                        }
                    }
                }
            }
            zf.writestr("meta.json", json.dumps(meta))
        sketch_bytes = buf.getvalue()

        f_type = detect_file_type("design_system.sketch", sketch_bytes)
        self.assertEqual(f_type, "design/sketch")

        payload = self.delta_engine.analyze_change("design_system.sketch", None, sketch_bytes)
        self.assertEqual(payload.domain_facts.get("design_tool"), "Sketch")
        self.assertEqual(len(payload.domain_facts.get("artboards", [])), 2)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("sketch", out.tags)

    def test_krita_painting_file(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            maindoc = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE DOC PUBLIC '-//KDE//DTD krita 2.0//EN' 'http://www.calligra.org/dtd/krita-2.0.dtd'>
<DOC xmlns="http://www.calligra.org/dtd/krita">
 <IMAGE width="3840" height="2160" name="ConceptArt">
  <LAYERS>
   <LAYER name="Background" visible="1" opacity="255"/>
   <LAYER name="LineArt" visible="1" opacity="255"/>
   <LAYER name="Highlights" visible="1" opacity="200"/>
  </LAYERS>
 </IMAGE>
</DOC>"""
            zf.writestr("maindoc.xml", maindoc)
        kra_bytes = buf.getvalue()

        f_type = detect_file_type("hero_illustration.kra", kra_bytes)
        self.assertEqual(f_type, "design/krita")

        payload = self.delta_engine.analyze_change("hero_illustration.kra", None, kra_bytes)
        self.assertEqual(payload.domain_facts.get("width"), 3840)
        self.assertEqual(payload.domain_facts.get("height"), 2160)
        self.assertEqual(payload.domain_facts.get("layers_count"), 3)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("krita", out.tags)

    def test_kicad_pcb_eda(self):
        kicad_content = """(kicad_pcb (version 20221018) (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
  (net 0 "")
  (net 1 "+3V3")
  (net 2 "GND")
  (net 3 "SPI_CLK")
  (footprint "Resistor_SMD:R_0603_1608Metric" (layer "F.Cu"))
  (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm" (layer "F.Cu"))
)"""
        kicad_bytes = kicad_content.encode("utf-8")
        f_type = detect_file_type("mainboard.kicad_pcb", kicad_bytes)
        self.assertEqual(f_type, "eda/kicad")

        payload = self.delta_engine.analyze_change("mainboard.kicad_pcb", None, kicad_bytes)
        self.assertEqual(payload.domain_facts.get("nets_count"), 4)
        self.assertEqual(payload.domain_facts.get("footprints_count"), 2)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("kicad", out.tags)

    def test_autocad_dxf(self):
        dxf_content = """0
SECTION
2
ENTITIES
0
LINE
8
WALLS
10
0.0
20
0.0
11
100.0
21
0.0
0
CIRCLE
8
COLUMNS
10
50.0
20
50.0
40
15.0
0
ENDSEC
0
EOF
"""
        dxf_bytes = dxf_content.encode("utf-8")
        f_type = detect_file_type("floorplan.dxf", dxf_bytes)
        self.assertEqual(f_type, "cad/dxf")

        payload = self.delta_engine.analyze_change("floorplan.dxf", None, dxf_bytes)
        self.assertEqual(payload.domain_facts.get("entities_count"), 2)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("autocad", out.tags)

    def test_apache_parquet_detection(self):
        parquet_bytes = b"PAR1" + b"\x00" * 256 + b"PAR1"
        f_type = detect_file_type("analytics.parquet", parquet_bytes)
        self.assertEqual(f_type, "database/parquet")

        payload = self.delta_engine.analyze_change("analytics.parquet", None, parquet_bytes)
        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("parquet", out.tags)

    def test_universal_container_fallback_zip(self):
        # Test an arbitrary app container created by an unknown software
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.manifest", "version=1.0\napp=CustomCADSuite")
            zf.writestr("geometry/mesh.bin", b"\x01\x02\x03\x04" * 100)
        v1_bytes = buf.getvalue()

        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("project.manifest", "version=2.0\napp=CustomCADSuite")
            zf.writestr("geometry/mesh.bin", b"\x01\x02\x03\x04" * 200)
            zf.writestr("materials/shader.glsl", "void main() { gl_FragColor = vec4(1.0); }")
        v2_bytes = buf2.getvalue()

        f_type = detect_file_type("assembly.custombundle", v1_bytes)
        self.assertEqual(f_type, "archive/zip")

        payload = self.delta_engine.analyze_change("assembly.custombundle", v1_bytes, v2_bytes)
        facts = payload.domain_facts
        self.assertEqual(facts.get("container_type"), "ZIP Archive")
        self.assertIn("materials/shader.glsl", facts.get("added_items", []))

    def test_universal_binary_cdc_and_string_dissection(self):
        # Test an opaque proprietary binary file from unknown enterprise software (64KB payload)
        raw_seed = bytes((i * 31 + 7) % 256 for i in range(65536))
        old_data = bytearray(b"\x7fELF" + raw_seed)
        old_data[100:130] = b"AppVersion: 2025.1.0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        old_data[500:525] = b"TargetProfile: Desktop-Pro"
        old_bytes = bytes(old_data)

        new_data = bytearray(old_data)
        # Modify 30 bytes in chunk 1, leave other chunks untouched
        new_data[100:130] = b"AppVersion: 2026.2.0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        new_data[2000:2020] = b"EnabledHardwareOpt:1"
        new_bytes = bytes(new_data)

        bin_analyzer = BinaryAnalyzer()
        res = bin_analyzer.analyze(old_bytes, new_bytes, "firmware.bin")

        facts = res.domain_facts
        self.assertIn("mutation_percentage", facts)
        self.assertIn("similarity_ratio", facts)
        self.assertGreater(facts["similarity_ratio"], 0.5)

        # Check that semantic differ accurately outputs CDC facts
        differ_input = DifferInput(
            file_name="firmware.bin",
            file_type="binary/unknown",
            previous_metadata=res.previous_metadata,
            current_metadata=res.current_metadata,
            raw_diff=res.raw_diff,
            domain_facts=facts,
        )
        out = self.agent.analyze(differ_input)
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("binary", out.tags)
        self.assertTrue(any("similarity" in d.lower() or "mutation" in d.lower() for d in out.technical_delta))

    def test_custom_plugin_registration(self):
        # Register a Python plugin dynamically for an imaginary software extension .magicapp
        @register_plugin(name="magic_app_plugin", patterns=["*.magicapp"])
        def magic_analyzer(old, new, name):
            from vcx.diff.analyzers.base import AnalysisResult
            return AnalysisResult(
                previous_metadata={},
                current_metadata={},
                raw_diff="MagicApp transformation: 42 procedural nodes evaluated",
                domain_facts={"procedural_nodes": 42},
            )

        payload = self.delta_engine.analyze_change("flow.magicapp", b"old", b"new")
        self.assertEqual(payload.file_type, "plugin/custom")
        self.assertEqual(payload.domain_facts.get("procedural_nodes"), 42)

        out = self.agent.analyze(payload.to_dict())
        self.assertLess(len(out.action_summary), 50)
        self.assertIn("plugin", out.tags)


if __name__ == "__main__":
    unittest.main()
