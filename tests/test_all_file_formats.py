"""Unit tests for universal multimedia, creative app, and multi-domain file format support in VCX."""

from __future__ import annotations
import gzip
import io
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import unittest
import zipfile

from vcx.agent.schemas import DifferInput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.diff.analyzers.creative_app import CreativeAppAnalyzer
from vcx.diff.analyzers.media import MediaAnalyzer
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type


class TestAllFileFormats(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vcx_formats_test_")
        self.base_path = Path(self.tmp_dir)
        self.delta_engine = DeltaEngine()
        self.agent = SemanticDifferAgent()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_audio_wav_detection_and_analysis(self):
        # Create minimal 44-byte standard RIFF WAV header
        # PCM 16-bit Stereo 44100 Hz, 88200 bytes/sec
        wav_header = bytearray(44)
        wav_header[0:4] = b"RIFF"
        struct.pack_into("<I", wav_header, 4, 44 + 88200 - 8)
        wav_header[8:12] = b"WAVE"
        wav_header[12:16] = b"fmt "
        struct.pack_into("<I", wav_header, 16, 16)  # Subchunk1Size
        struct.pack_into("<H", wav_header, 20, 1)   # AudioFormat (PCM)
        struct.pack_into("<H", wav_header, 22, 2)   # NumChannels (2 = Stereo)
        struct.pack_into("<I", wav_header, 24, 44100) # SampleRate
        struct.pack_into("<I", wav_header, 28, 44100 * 4) # ByteRate
        struct.pack_into("<H", wav_header, 32, 4)   # BlockAlign
        struct.pack_into("<H", wav_header, 34, 16)  # BitsPerSample
        wav_header[36:40] = b"data"
        struct.pack_into("<I", wav_header, 40, 88200) # 1 second of data
        wav_bytes = bytes(wav_header) + b"\x00" * 88200

        f_type = detect_file_type("soundtrack.wav", wav_bytes)
        self.assertEqual(f_type, "audio/wav")

        payload = self.delta_engine.analyze_change("soundtrack.wav", None, wav_bytes)
        self.assertEqual(payload.current_metadata.get("sample_rate_hz"), 44100)
        self.assertEqual(payload.current_metadata.get("channels"), 2)
        self.assertEqual(payload.current_metadata.get("bit_depth"), 16)

        output = self.agent.analyze(payload.to_dict())
        self.assertLess(len(output.action_summary), 50)
        self.assertIn("audio-engineering", output.tags)
        self.assertTrue(any("44100" in d for d in output.technical_delta))

    def test_image_png_and_svg(self):
        # Create minimal 100x50 PNG using Pillow
        from PIL import Image
        im = Image.new("RGBA", (100, 50), color=(255, 0, 0, 255))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        f_type = detect_file_type("banner.png", png_bytes)
        self.assertEqual(f_type, "image/png")

        payload = self.delta_engine.analyze_change("banner.png", None, png_bytes)
        self.assertEqual(payload.current_metadata.get("width"), 100)
        self.assertEqual(payload.current_metadata.get("height"), 50)
        self.assertEqual(payload.current_metadata.get("mode"), "RGBA")

        output = self.agent.analyze(payload.to_dict())
        self.assertLess(len(output.action_summary), 50)
        self.assertIn("image-asset", output.tags)

        # SVG Vector image
        svg_content = b"""<svg width="200" height="150" viewBox="0 0 200 150">
        <path d="M10 10 H 90 V 90 H 10 L 10 10"/>
        <path d="M20 20 H 80 V 80 H 20 Z"/>
        </svg>"""
        svg_type = detect_file_type("icon.svg", svg_content)
        self.assertEqual(svg_type, "image/svg")

        svg_payload = self.delta_engine.analyze_change("icon.svg", None, svg_content)
        self.assertEqual(svg_payload.current_metadata.get("paths_count"), 2)

    def test_adobe_premiere_pro_project(self):
        # Create mock Premiere Pro gzipped XML project
        xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<PremiereData Version="3">
    <ProjectItem ObjectID="1">
        <Name>Feature Documentary</Name>
    </ProjectItem>
    <Sequence ObjectID="10">
        <Name>Rough Cut Assembly</Name>
        <VideoClipTrack ObjectID="20"/>
        <VideoClipTrack ObjectID="21"/>
        <AudioClipTrack ObjectID="30"/>
        <AudioClipTrack ObjectID="31"/>
    </Sequence>
    <ClipProjectItem ObjectID="40"/>
    <ClipProjectItem ObjectID="41"/>
    <ClipProjectItem ObjectID="42"/>
</PremiereData>"""
        gz_buf = io.BytesIO()
        with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
            gz.write(xml_text.encode("utf-8"))
        prproj_bytes = gz_buf.getvalue()

        f_type = detect_file_type("project.prproj", prproj_bytes)
        self.assertEqual(f_type, "creative/premiere")

        payload = self.delta_engine.analyze_change("project.prproj", None, prproj_bytes)
        meta = payload.current_metadata
        self.assertEqual(meta.get("project_type"), "adobe_premiere")
        self.assertIn("Rough Cut Assembly", meta.get("sequences", []))
        self.assertEqual(meta.get("tracks", {}).get("video_tracks"), 2)
        self.assertEqual(meta.get("tracks", {}).get("audio_tracks"), 2)

        output = self.agent.analyze(payload.to_dict())
        self.assertLess(len(output.action_summary), 50)
        self.assertIn("adobe-premiere", output.tags)
        self.assertTrue(any("Rough Cut Assembly" in d for d in output.technical_delta))

    def test_adobe_photoshop_psd(self):
        # Create minimal 8BPS header (Photoshop format)
        # Magic: 8BPS, Version: 1, Channels: 4, Height: 1080, Width: 1920, Depth: 8, Mode: 3 (RGB)
        psd_header = bytearray(30)
        psd_header[0:4] = b"8BPS"
        struct.pack_into(">H", psd_header, 4, 1)    # version 1
        # bytes 6-12 are reserved
        struct.pack_into(">H", psd_header, 12, 4)   # 4 channels (RGBA)
        struct.pack_into(">I", psd_header, 14, 1080)# height
        struct.pack_into(">I", psd_header, 18, 1920)# width
        struct.pack_into(">H", psd_header, 22, 8)   # 8-bit depth
        struct.pack_into(">H", psd_header, 24, 3)   # RGB Color mode
        psd_bytes = bytes(psd_header)

        f_type = detect_file_type("artwork.psd", psd_bytes)
        self.assertEqual(f_type, "creative/photoshop")

        payload = self.delta_engine.analyze_change("artwork.psd", None, psd_bytes)
        meta = payload.current_metadata
        self.assertEqual(meta.get("width"), 1920)
        self.assertEqual(meta.get("height"), 1080)
        self.assertEqual(meta.get("color_mode"), "RGB")
        self.assertEqual(meta.get("channels"), 4)

        output = self.agent.analyze(payload.to_dict())
        self.assertLess(len(output.action_summary), 50)
        self.assertIn("photoshop", output.tags)
        self.assertTrue(any("1920x1080" in d for d in output.technical_delta))

    def test_blender_3d_project(self):
        # Create minimal Blender 3D header
        # BLENDER + pointer size ('-') + endian ('v') + version ('402') -> Blender v4.2
        blend_header = b"BLENDER-v402" + b"\x00" * 64
        f_type = detect_file_type("character.blend", blend_header)
        self.assertEqual(f_type, "creative/blender")

        payload = self.delta_engine.analyze_change("character.blend", None, blend_header)
        meta = payload.current_metadata
        self.assertEqual(meta.get("project_type"), "blender_3d")
        self.assertEqual(meta.get("blender_version"), "v4.02")
        self.assertEqual(meta.get("pointer_bits"), 64)

        output = self.agent.analyze(payload.to_dict())
        self.assertLess(len(output.action_summary), 50)
        self.assertIn("blender-3d", output.tags)

    def test_audacity_audio_session(self):
        # Create mock Audacity .aup3 SQLite database
        db_path = self.base_path / "podcast.aup3"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY, name TEXT, rate REAL, channels INTEGER);")
        cur.execute("INSERT INTO tracks (name, rate, channels) VALUES ('Host Voice', 48000.0, 1);")
        cur.execute("INSERT INTO tracks (name, rate, channels) VALUES ('Music Bed', 48000.0, 2);")
        conn.commit()
        conn.close()
        aup3_bytes = db_path.read_bytes()

        f_type = detect_file_type("podcast.aup3", aup3_bytes)
        self.assertEqual(f_type, "creative/audacity")

        payload = self.delta_engine.analyze_change("podcast.aup3", None, aup3_bytes)
        meta = payload.current_metadata
        self.assertEqual(meta.get("project_type"), "audacity_session")
        self.assertEqual(len(meta.get("tracks", [])), 2)

        output = self.agent.analyze(payload.to_dict())
        self.assertLess(len(output.action_summary), 50)
        self.assertIn("audacity", output.tags)

    def test_office_docx_and_pdf(self):
        # Create minimal DOCX ZIP package
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            core_xml = """<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Hardware Specification</dc:title>
    <dc:creator>Indhirajith Hari</dc:creator>
    <cp:revision>3</cp:revision>
</cp:coreProperties>"""
            zf.writestr("docProps/core.xml", core_xml)
            zf.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>VCX is version control for everything.</w:t></w:r></w:p></w:body></w:document>")
        docx_bytes = buf.getvalue()

        f_type = detect_file_type("spec.docx", docx_bytes)
        self.assertEqual(f_type, "document/office")

        payload = self.delta_engine.analyze_change("spec.docx", None, docx_bytes)
        meta = payload.current_metadata
        self.assertEqual(meta.get("title"), "Hardware Specification")
        self.assertEqual(meta.get("creator"), "Indhirajith Hari")
        self.assertGreater(meta.get("word_count", 0), 0)

        output = self.agent.analyze(payload.to_dict())
        self.assertLess(len(output.action_summary), 50)
        self.assertIn("documentation", output.tags)

        # PDF Document
        pdf_bytes = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page >>\nendobj\n%%EOF\n"
        pdf_type = detect_file_type("manual.pdf", pdf_bytes)
        self.assertEqual(pdf_type, "document/pdf")

        pdf_payload = self.delta_engine.analyze_change("manual.pdf", None, pdf_bytes)
        self.assertEqual(pdf_payload.current_metadata.get("pdf_version"), "1.7")
        self.assertEqual(pdf_payload.current_metadata.get("estimated_pages"), 1)


if __name__ == "__main__":
    unittest.main()
