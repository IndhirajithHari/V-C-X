"""Unit tests validating the EGM audit fixes and security mitigations."""

import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from vcx.core.index import Index
from vcx.core.object_store import ObjectStore
from vcx.core.repository import Repository
from vcx.core.types import ObjectType
from vcx.diff.analyzers.cad_3d import Cad3DAnalyzer
from vcx.diff.analyzers.database_logs import DatabaseLogsAnalyzer
from vcx.diff.analyzers.source_code import SourceCodeAnalyzer
from vcx.diff.detector import detect_file_type


class TestAuditFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = Path(self.temp_dir.name)
        self.repo = Repository.init(self.repo_dir)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_corrupt_index_backup_safety(self):
        index_file = self.repo_dir / ".vcx" / "index"
        index_file.write_text("NOT_VALID_JSON{", encoding="utf-8")

        with self.assertRaises(RuntimeError) as ctx:
            idx = Index(self.repo_dir)

        self.assertIn("Corrupt index file detected", str(ctx.exception))
        # Ensure backup was created
        backups = list((self.repo_dir / ".vcx").glob("index.corrupt.*"))
        self.assertTrue(len(backups) >= 1)

    def test_object_store_checksum_verification(self):
        store = ObjectStore(self.repo_dir)
        sha = store.write_blob(b"valid content payload")

        # Corrupt file on disk
        obj_path = store.objects_dir / sha[:2] / sha[2:]
        import zlib
        # Write valid zlib data but with altered payload
        corrupted_payload = f"blob 21\0tampered content payload".encode("utf-8")
        obj_path.write_bytes(zlib.compress(corrupted_payload))

        with self.assertRaises(ValueError) as ctx:
            store.read_blob(sha)
        self.assertIn("Object corruption detected", str(ctx.exception))

    def test_path_traversal_rejection(self):
        with self.assertRaises(ValueError):
            self.repo._sanitize_path("../../../etc/shadow")
        with self.assertRaises(ValueError):
            self.repo._sanitize_path("/etc/passwd")

    def test_sqlite_injection_safety(self):
        analyzer = DatabaseLogsAnalyzer()
        with tempfile.NamedTemporaryFile(suffix=".db") as f:
            conn = sqlite3.connect(f.name)
            # Create a table with closing bracket and quotes in name
            conn.execute('CREATE TABLE "inject]; DROP TABLE other; --" (id INT, val TEXT);')
            conn.execute('INSERT INTO "inject]; DROP TABLE other; --" VALUES (1, "test");')
            conn.commit()
            conn.close()

            with open(f.name, "rb") as bf:
                data = bf.read()

            res = analyzer.analyze(None, data, "test.db")
            self.assertIn("inject]; DROP TABLE other; --", res.domain_facts["schema_changes"][0])

    def test_freecad_fcstd_zip_container_parsing(self):
        analyzer = Cad3DAnalyzer()
        # Construct an actual FreeCAD PKZIP archive with Document.xml
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            doc_xml = b"""<Document><Object name="Chassis" type="PartDesign::Body">
                <Property name="FilletRadius"><Float value="2.5"/></Property>
            </Object></Document>"""
            zf.writestr("Document.xml", doc_xml)

        zip_bytes = buf.getvalue()
        res = analyzer.analyze(None, zip_bytes, "model.fcstd")
        self.assertTrue(any("2.5" in str(v) for v in res.current_metadata.get("parametric_features", {}).values()))

    def test_step_cad_brep_handling(self):
        analyzer = Cad3DAnalyzer()
        step_content = b"""
        ISO-10303-21;
        HEADER;
        FILE_DESCRIPTION(('FreeCAD Model'),'2;1');
        ENDSEC;
        DATA;
        #1 = MANIFOLD_SOLID_BREP('Body', #2);
        #2 = ADVANCED_FACE('', (#3), #4, .T.);
        /* Thickness: 5.0mm */
        ENDSEC;
        END-ISO-10303-21;
        """
        res = analyzer.analyze(None, step_content, "bracket.step")
        self.assertEqual(res.current_metadata["mesh_stats"]["format"], "STEP_BREP")
        self.assertEqual(res.current_metadata["mesh_stats"]["solids"], 1)

    def test_null_byte_in_python_source(self):
        analyzer = SourceCodeAnalyzer()
        corrupt_py = b"def test():\n    return 'ok'\n\x00\x00\x00corrupt"
        res = analyzer.analyze(None, corrupt_py, "corrupt.py")
        self.assertIn("test", res.current_metadata["functions"])

    def test_plaintext_detection(self):
        f_type = detect_file_type("README.md", b"# Markdown documentation")
        self.assertEqual(f_type, "text/plain")


if __name__ == "__main__":
    unittest.main()
