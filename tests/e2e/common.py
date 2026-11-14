"""Shared Test Harness & Synthetic Domain Asset Fixtures for VCX E2E Tests.

Provides:
- VCXBaseTestCase: Isolated temporary repository fixture with cwd restoration and safe cleanup.
- run_cli: In-process CLI runner capturing stdout/stderr without subprocess overhead.
- make_fcstd_file: FreeCAD PKZIP archive generator with Document.xml.
- make_verilog_file: Verilog module generator with parameters, ports, and body.
- make_step_file: STEP ISO-10303-21 CAD model generator with CARTESIAN_POINT entities.
- make_binary_file: Deterministic binary payload generator.
"""

from __future__ import annotations
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union
import unittest
import zipfile

from vcx.adapters.eda_adapter import EDAAdapter
from vcx.adapters.freecad_adapter import FreeCADAdapter
from vcx.chunker import (
    EMPTY_CHUNK_SHA,
    FastCDCEngine,
    FileManifest,
    batch_chunk_files,
    chunk_bytes,
    chunk_file,
)
from vcx.core.object_store import ObjectStore
from vcx.core.pack import PackReader, PackWriter
from vcx.core.repository import Repository
from vcx.diff.cad_engine import StepBrepParser
from vcx.diff.merger import SemanticMerger
from vcx.engine import VCXEngine
from vcx.index import Index, IndexRow
from vcx.storage import ObjectStorage


# ==============================================================================
# Synthetic Domain Asset Generators
# ==============================================================================

def make_fcstd_file(
    path: Optional[Union[str, Path]] = None,
    doc_name: str = "Part",
    objects: Optional[List[Dict[str, Any]]] = None,
) -> bytes:
    """Construct a valid FreeCAD PKZIP archive containing Document.xml.

    Args:
        path: Optional file path to write to disk.
        doc_name: Name attribute of Document.
        objects: List of dicts describing objects, e.g.:
            [{
                "name": "Body",
                "type": "PartDesign::Body",
                "properties": {
                    "Length": ("Float", "100.0"),
                    "Count": ("Integer", "4"),
                    "Active": ("Bool", "true"),
                    "Label": ("String", "MainBody")
                }
            }]
    """
    if objects is None:
        objects = [
            {
                "name": "Body",
                "type": "PartDesign::Body",
                "properties": {
                    "FilletRadius": ("Float", "2.5"),
                    "Length": ("Float", "50.0"),
                    "PartName": ("String", "Bracket"),
                },
            }
        ]

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<Document SchemaVersion="4" Name="{doc_name}">',
        "  <Objects>",
    ]

    for obj in objects:
        name = obj.get("name", "Object")
        obj_type = obj.get("type", "PartDesign::Body")
        lines.append(f'    <Object name="{name}" type="{obj_type}">')
        lines.append('      <Properties Count="1">')
        for prop_name, prop_data in obj.get("properties", {}).items():
            if isinstance(prop_data, tuple):
                p_type, p_val = prop_data
            else:
                p_type, p_val = "Float", str(prop_data)

            lines.append(f'        <Property name="{prop_name}" type="App::Property{p_type}">')
            if p_type == "Float":
                lines.append(f'          <Float value="{p_val}"/>')
            elif p_type == "Integer":
                lines.append(f'          <Integer value="{p_val}"/>')
            elif p_type == "Bool":
                lines.append(f'          <Bool value="{str(p_val).lower()}"/>')
            elif p_type == "String":
                lines.append(f'          <String value="{p_val}"/>')
            else:
                lines.append(f'          <{p_type} value="{p_val}"/>')
            lines.append("        </Property>")
        lines.append("      </Properties>")
        lines.append("    </Object>")

    lines.append("  </Objects>")
    lines.append("</Document>")

    doc_xml = "\n".join(lines).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Document.xml", doc_xml)
        zf.writestr(
            "GuiDocument.xml",
            '<?xml version="1.0" encoding="utf-8"?>\n<GuiDocument SchemaVersion="1"/>',
        )

    zip_bytes = buf.getvalue()
    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(zip_bytes)

    return zip_bytes


def make_verilog_file(
    path: Optional[Union[str, Path]] = None,
    module_name: str = "alu",
    parameters: Optional[Dict[str, Any]] = None,
    ports: Optional[List[Dict[str, str]]] = None,
    body: str = "",
) -> str:
    """Construct a valid Verilog HDL source file.

    Args:
        path: Optional file path to write to disk.
        module_name: Identifier for the module.
        parameters: Dict of parameter name to default value, e.g. {"DATA_WIDTH": 32}.
        ports: List of port definitions, e.g. [{"dir": "input", "width": "[DATA_WIDTH-1:0]", "name": "a"}].
        body: Verilog body statements.
    """
    if parameters is None:
        parameters = {"DATA_WIDTH": 32, "ADDR_WIDTH": 8}

    if ports is None:
        ports = [
            {"dir": "input wire", "width": "", "name": "clk"},
            {"dir": "input wire", "width": "", "name": "reset_n"},
            {"dir": "input wire", "width": "[DATA_WIDTH-1:0]", "name": "a"},
            {"dir": "input wire", "width": "[DATA_WIDTH-1:0]", "name": "b"},
            {"dir": "output reg", "width": "[DATA_WIDTH-1:0]", "name": "out"},
        ]

    lines = []
    # Module header with parameters
    if parameters:
        param_defs = [f"parameter {k} = {v}" for k, v in parameters.items()]
        param_str = ", ".join(param_defs)
        lines.append(f"module {module_name} #(\n    {param_str}\n) (")
    else:
        lines.append(f"module {module_name} (")

    # Port list
    port_defs = []
    for p in ports:
        direction = p.get("dir", "input wire")
        width = p.get("width", "")
        name = p.get("name", "sig")
        if width:
            port_defs.append(f"    {direction} {width} {name}")
        else:
            port_defs.append(f"    {direction} {name}")

    lines.append(",\n".join(port_defs))
    lines.append(");")

    # Body
    if body:
        lines.append(f"    {body}")
    else:
        lines.append("    always @(posedge clk or negedge reset_n) begin")
        lines.append("        if (!reset_n) out <= 0;")
        lines.append("        else out <= a + b;")
        lines.append("    end")

    lines.append("endmodule\n")

    verilog_text = "\n".join(lines)
    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(verilog_text, encoding="utf-8")

    return verilog_text


def make_step_file(
    path: Optional[Union[str, Path]] = None,
    points: Optional[List[Tuple[float, float, float]]] = None,
    include_omitted_star: bool = False,
    solid_name: str = "BaseSolid",
) -> str:
    """Construct a valid STEP ISO-10303-21 CAD file.

    Args:
        path: Optional file path to write to disk.
        points: List of 3D (x, y, z) coordinates for CARTESIAN_POINT entities.
        include_omitted_star: If True, includes a point with omitted attribute `*`.
        solid_name: Identifier for the MANIFOLD_SOLID_BREP entity.
    """
    if points is None:
        points = [
            (0.0, 0.0, 0.0),
            (10.0, 0.0, 0.0),
            (10.0, 20.0, 0.0),
            (0.0, 20.0, 0.0),
        ]

    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('VCX CAD Model'), '2;1');",
        "FILE_NAME('model.step', '2026-11-14T00:00:00', ('Engineer'), ('VCX'), 'VCX STEP Engine', 'VCX', '');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));",
        "ENDSEC;",
        "DATA;",
        "#1 = APPLICATION_CONTEXT('mechanical design');",
        "#2 = APPLICATION_PROTOCOL_DEFINITION('international standard', 'automotive_design', 2000, #1);",
        "#3 = PRODUCT_DEFINITION_CONTEXT('part definition', #1, 'design');",
        "#4 = PRODUCT('Part_001', 'Part_001', '', (#3));",
        f"#5 = MANIFOLD_SOLID_BREP('{solid_name}', #6);",
        "#6 = CLOSED_SHELL('', (#7));",
        "#7 = ADVANCED_FACE('', (#8), #9, .T.);",
        "#8 = FACE_BOUND('', #10, .T.);",
        "#9 = PLANE('', #10);",
    ]

    entity_id = 10
    for i, pt in enumerate(points):
        x, y, z = pt
        lines.append(f"#{entity_id} = CARTESIAN_POINT('pt_{i}', ({x:.4f}, {y:.4f}, {z:.4f}));")
        entity_id += 1

    if include_omitted_star:
        lines.append(f"#{entity_id} = CARTESIAN_POINT(*, (99.0000, 99.0000, 99.0000));")
        entity_id += 1

    lines.append("ENDSEC;")
    lines.append("END-ISO-10303-21;\n")

    step_text = "\n".join(lines)
    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(step_text, encoding="utf-8")

    return step_text


def make_binary_file(
    path: Optional[Union[str, Path]] = None,
    size: int = 1024,
    pattern: Optional[bytes] = None,
) -> bytes:
    """Generate deterministic binary data of exact byte length.

    Args:
        path: Optional file path to write to disk.
        size: Desired size in bytes.
        pattern: Repeating byte sequence. Defaults to deterministic token header.
    """
    if pattern is None:
        pattern = b"VCX_V2_DETERMINISTIC_BINARY_PAYLOAD_CHUNK_BLOCK_0123456789ABCDEF_"

    repeats = (size // len(pattern)) + 1
    full_data = (pattern * repeats)[:size]

    if path is not None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(full_data)

    return full_data


# ==============================================================================
# In-Process CLI Runner
# ==============================================================================

def run_cli(args: List[str], use_rich_cli: Optional[bool] = None) -> Tuple[int, str, str]:
    """Execute VCX CLI in-process, capturing return code, stdout, and stderr.

    Args:
        args: Command line argument list (e.g. ["init"], ["add", "."]).
        use_rich_cli: Optional override. If None, auto-routes: v1-only commands
            ("branch", "tag", "pack", "gc", "merge", etc.) use `vcx.cli.main`,
            while core v2 commands use `cli.py`.

    Returns:
        Tuple of (exit_code, stdout_text, stderr_text).
    """
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    code = 0

    # Auto-detect CLI runner if not explicitly specified
    if use_rich_cli is None:
        v1_commands = {
            "branch", "tag", "gc", "pack", "merge", "remote", "clone",
            "fetch", "push", "serve", "config", "show", "import-git",
            "app", "watch", "agent",
        }
        subcmd = next((a for a in args if not a.startswith("-")), None)
        use_rich = subcmd not in v1_commands
    else:
        use_rich = use_rich_cli

    try:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            if use_rich:
                import cli
                code = cli.main(args)
            else:
                from vcx.cli.main import main as vcx_main
                code = vcx_main(args)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception as e:
        err_buf.write(str(e))
        code = 1

    return (code if code is not None else 0), out_buf.getvalue(), err_buf.getvalue()


# ==============================================================================
# Base Test Case Fixture
# ==============================================================================

class VCXBaseTestCase(unittest.TestCase):
    """Hermetic base test case ensuring isolated workspace lifecycle.

    Guarantees:
    - Dedicated temporary directory created on setUp and purged on tearDown.
    - Process working directory (os.getcwd) saved and restored without leakage.
    - SQLite index and object storage handles safely released before cleanup.
    """

    def setUp(self) -> None:
        super().setUp()
        self.orig_cwd = os.getcwd()
        self.temp_dir = tempfile.mkdtemp(prefix="vcx_e2e_")
        self.repo_dir = Path(self.temp_dir)
        os.chdir(self.repo_dir)
        self.engine: Optional[VCXEngine] = None
        self.repo: Optional[Repository] = None

    def tearDown(self) -> None:
        try:
            # Safely release SQLite index connections if instantiated
            if self.engine is not None and hasattr(self.engine, "index") and self.engine.index is not None:
                if hasattr(self.engine.index, "close"):
                    try:
                        self.engine.index.close()
                    except Exception:
                        pass
        finally:
            os.chdir(self.orig_cwd)
            shutil.rmtree(self.temp_dir, ignore_errors=True)
            super().tearDown()

    def init_v2_repo(self) -> VCXEngine:
        """Initialize and return a v2.0 VCXEngine instance in the isolated workspace."""
        self.engine = VCXEngine.init(self.repo_dir)
        return self.engine

    def init_v1_repo(self) -> Repository:
        """Initialize and return a v1.0 Repository instance in the isolated workspace."""
        self.repo = Repository.init(self.repo_dir)
        return self.repo

    def write_file(self, rel_path: Union[str, Path], content: Union[str, bytes]) -> Path:
        """Write text or binary content to a path relative to repo_dir."""
        target = self.repo_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        return target

    def read_file(self, rel_path: Union[str, Path], binary: bool = False) -> Union[str, bytes]:
        """Read text or binary content from a path relative to repo_dir."""
        target = self.repo_dir / rel_path
        if binary:
            return target.read_bytes()
        return target.read_text(encoding="utf-8")

    def run_cli_cmd(self, args: List[str], use_rich_cli: Optional[bool] = None) -> Tuple[int, str, str]:
        """Run CLI in current workspace directory."""
        return run_cli(args, use_rich_cli=use_rich_cli)

    def corrupt_chunk_object(self, chunk_sha: str, payload: bytes = b"TAMPERED_CORRUPTED_BYTES") -> Path:
        """Overwrite an existing object on disk to simulate storage bit-rot/tampering."""
        obj_path = self.repo_dir / ".vcx" / "objects" / chunk_sha[:2] / chunk_sha[2:]
        obj_path.parent.mkdir(parents=True, exist_ok=True)
        obj_path.write_bytes(payload)
        return obj_path

    def delete_chunk_object(self, chunk_sha: str) -> bool:
        """Delete an object file from .vcx/objects/ to simulate missing storage blocks."""
        obj_path = self.repo_dir / ".vcx" / "objects" / chunk_sha[:2] / chunk_sha[2:]
        if obj_path.exists():
            obj_path.unlink()
            return True
        return False

    def assert_repo_clean(self) -> None:
        """Assert that status reports zero staged, unstaged, or untracked changes."""
        if self.engine is not None:
            st = self.engine.status()
            self.assertEqual(len(st["staged"]), 0, f"Expected 0 staged, found {st['staged']}")
            self.assertEqual(len(st["unstaged"]), 0, f"Expected 0 unstaged, found {st['unstaged']}")
            self.assertEqual(len(st["untracked"]), 0, f"Expected 0 untracked, found {st['untracked']}")
