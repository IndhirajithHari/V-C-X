"""Pluggable Semantic Extractor & Antigravity Hook for VCX (v2.0).

Routes files based on extension to specialized domain extractors before triggering
the Antigravity Semantic Differ LLM:
- Archives & CAD (.fcstd, .docx, .zip): In-memory structural XML/JSON diffing
- Code & EDA (.rs, .c, .py, .v, .sv): Unified text diffs & RTL architecture extraction
- Raw Binaries (.stl, .step, .bin): Chunk drift ratio (e.g. "3 of 140 chunks modified") & size deltas
Formats extracted facts into strict JSON schema for the Semantic Differ Agent and appends
the AI summary into the Commit DAG object.
"""

from __future__ import annotations
import difflib
import io
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import xml.etree.ElementTree as ET
import zipfile

from vcx.adapters.eda_adapter import EDAAdapter
from vcx.adapters.freecad_adapter import FreeCADAdapter
from vcx.agent.schemas import DifferInput, DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.chunker import FileManifest


class SemanticExtractor:
    """Intelligent adapter router extracting structured semantic diffs across domains."""

    def __init__(self, agent: Optional[SemanticDifferAgent] = None):
        self.agent = agent or SemanticDifferAgent()

    def extract(
        self,
        file_name: str,
        base_bytes: Optional[bytes],
        current_bytes: bytes,
        base_manifest: Optional[FileManifest] = None,
        current_manifest: Optional[FileManifest] = None,
    ) -> DifferInput:
        """Route file to appropriate domain extractor and build DifferInput payload."""
        ext = Path(file_name).suffix.lower()

        # 1. FreeCAD Parametric Model
        if ext in (".fcstd", ".fcmacro") or (ext == ".xml" and b"<Document" in current_bytes[:500]):
            return self._extract_freecad(file_name, base_bytes, current_bytes)

        # 2. In-Memory Archive & Office Containers (.docx, .zip, .xlsx, .pptx, .odt)
        if ext in (".zip", ".docx", ".xlsx", ".pptx", ".odt", ".jar"):
            return self._extract_archive(file_name, base_bytes, current_bytes, ext)

        # 3. Hardware EDA RTL (.v, .sv)
        if ext in (".v", ".sv", ".vh", ".svh"):
            return self._extract_eda(file_name, base_bytes, current_bytes)

        # 4. Source Code (.py, .rs, .c, .cpp, .h, .js, .ts, .go, .java, etc.)
        if ext in (
            ".py", ".rs", ".c", ".cpp", ".cc", ".h", ".hpp", ".js", ".ts",
            ".go", ".java", ".rb", ".php", ".sh", ".json", ".yaml", ".yml", ".toml", ".md", ".txt"
        ):
            return self._extract_code(file_name, base_bytes, current_bytes)

        # 5. Raw Binaries & 3D CAD (.stl, .step, .stp, .bin, .blend, etc.)
        return self._extract_binary(file_name, base_bytes, current_bytes, base_manifest, current_manifest)

    # --- DOMAIN ROUTERS ---

    def _extract_freecad(
        self, file_name: str, base_bytes: Optional[bytes], current_bytes: bytes
    ) -> DifferInput:
        fc_diff = FreeCADAdapter.diff(base_bytes, current_bytes, file_name)
        raw_diff_text = "\n".join(fc_diff["technical_bullets"]) if fc_diff["technical_bullets"] else fc_diff["summary"]

        return DifferInput(
            file_name=file_name,
            file_type="cad/freecad",
            previous_metadata={"features_count": len(fc_diff.get("objects_removed", []))},
            current_metadata={"features_count": len(fc_diff.get("objects_added", []))},
            raw_diff=raw_diff_text,
            vision_summary=fc_diff["summary"],
            domain_facts={
                "cad_domain": "FreeCAD",
                "objects_added": fc_diff["objects_added"],
                "objects_removed": fc_diff["objects_removed"],
                "properties_modified": fc_diff["properties_modified"],
                "sketch_changes": fc_diff["sketch_changes"],
            },
        )

    def _extract_archive(
        self, file_name: str, base_bytes: Optional[bytes], current_bytes: bytes, ext: str
    ) -> DifferInput:
        def get_zip_catalog(data: Optional[bytes]) -> Dict[str, int]:
            if not data or not data.startswith(b"PK\x03\x04"):
                return {}
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    return {info.filename: info.file_size for info in zf.infolist()}
            except Exception:
                return {}

        base_cat = get_zip_catalog(base_bytes)
        curr_cat = get_zip_catalog(current_bytes)

        added = [f for f in curr_cat if f not in base_cat]
        removed = [f for f in base_cat if f not in curr_cat]
        modified = [f for f in curr_cat if f in base_cat and curr_cat[f] != base_cat[f]]

        bullets = []
        if added:
            bullets.append(f"Added {len(added)} container item(s): {', '.join(added[:5])}")
        if removed:
            bullets.append(f"Removed {len(removed)} container item(s): {', '.join(removed[:5])}")
        if modified:
            bullets.append(f"Modified {len(modified)} container item(s): {', '.join(modified[:5])}")

        # If docx, extract word/document.xml text delta
        text_delta = ""
        if ext == ".docx":
            try:
                def get_docx_text(data: Optional[bytes]) -> str:
                    if not data:
                        return ""
                    with zipfile.ZipFile(io.BytesIO(data)) as zf:
                        if "word/document.xml" in zf.namelist():
                            xml_bytes = zf.read("word/document.xml")
                            tree = ET.fromstring(xml_bytes)
                            return " ".join([elem.text for elem in tree.iter() if elem.text])
                    return ""

                b_text = get_docx_text(base_bytes)
                c_text = get_docx_text(current_bytes)
                if b_text or c_text:
                    diff_lines = list(
                        difflib.unified_diff(
                            b_text.splitlines(), c_text.splitlines(), lineterm=""
                        )
                    )
                    if diff_lines:
                        text_delta = "\n".join(diff_lines[:50])
                        bullets.append("Document textual content updated")
            except Exception:
                pass

        raw_diff_summary = "\n".join(bullets)
        if text_delta:
            raw_diff_summary += f"\n\n--- Document Text Delta ---\n{text_delta}"

        return DifferInput(
            file_name=file_name,
            file_type="archive/container",
            previous_metadata={"entry_count": len(base_cat), "size": len(base_bytes) if base_bytes else 0},
            current_metadata={"entry_count": len(curr_cat), "size": len(current_bytes)},
            raw_diff=raw_diff_summary or f"Container modified: {len(current_bytes)} bytes",
            domain_facts={
                "container_format": ext,
                "added_entries": added,
                "removed_entries": removed,
                "modified_entries": modified,
            },
        )

    def _extract_eda(
        self, file_name: str, base_bytes: Optional[bytes], current_bytes: bytes
    ) -> DifferInput:
        eda_diff = EDAAdapter.diff(base_bytes, current_bytes, file_name)
        raw_diff_text = "\n".join(eda_diff["technical_bullets"]) if eda_diff["technical_bullets"] else eda_diff["summary"]

        return DifferInput(
            file_name=file_name,
            file_type="eda/verilog",
            previous_metadata={"modules": len(eda_diff.get("modules_removed", []))},
            current_metadata={"modules": len(eda_diff.get("modules_added", []))},
            raw_diff=raw_diff_text,
            vision_summary=eda_diff["summary"],
            domain_facts={
                "hardware_domain": "RTL",
                "modules_added": eda_diff["modules_added"],
                "modules_removed": eda_diff["modules_removed"],
                "port_changes": eda_diff["port_changes"],
                "fsm_changes": eda_diff["fsm_changes"],
            },
        )

    def _extract_code(
        self, file_name: str, base_bytes: Optional[bytes], current_bytes: bytes
    ) -> DifferInput:
        base_lines = (base_bytes or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        curr_lines = current_bytes.decode("utf-8", errors="replace").splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                base_lines,
                curr_lines,
                fromfile=f"a/{file_name}",
                tofile=f"b/{file_name}",
            )
        )
        raw_diff_str = "".join(diff[:500])

        # Simple AST token extraction for Python
        ext = Path(file_name).suffix.lower()
        facts: Dict[str, Any] = {"language": ext}
        if ext == ".py":
            import ast
            def get_funcs(code: bytes) -> Set[str]:
                try:
                    tree = ast.parse(code.decode("utf-8", errors="ignore"))
                    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
                except Exception:
                    return set()

            b_funcs = get_funcs(base_bytes) if base_bytes else set()
            c_funcs = get_funcs(current_bytes)
            added_f = sorted(c_funcs - b_funcs)
            removed_f = sorted(b_funcs - c_funcs)
            if added_f:
                facts["added_functions"] = added_f
            if removed_f:
                facts["removed_functions"] = removed_f

        return DifferInput(
            file_name=file_name,
            file_type="source/code",
            previous_metadata={"lines": len(base_lines)},
            current_metadata={"lines": len(curr_lines)},
            raw_diff=raw_diff_str or "Whitespace or formatting modifications",
            domain_facts=facts,
        )

    def _extract_binary(
        self,
        file_name: str,
        base_bytes: Optional[bytes],
        current_bytes: bytes,
        base_manifest: Optional[FileManifest],
        current_manifest: Optional[FileManifest],
    ) -> DifferInput:
        b_size = len(base_bytes) if base_bytes else 0
        c_size = len(current_bytes)
        size_delta = c_size - b_size
        size_delta_str = f"+{size_delta} bytes" if size_delta >= 0 else f"{size_delta} bytes"

        # Chunk modification ratio from CDC manifests
        chunk_ratio_summary = "Whole-file binary update"
        if current_manifest:
            comparison = current_manifest.compare(base_manifest)
            chunk_ratio_summary = comparison["summary"]

        # Magic header extraction
        header_sample = current_bytes[:64].hex()
        file_type = "binary/unknown"
        ext = Path(file_name).suffix.lower()
        if ext in (".step", ".stp"):
            file_type = "cad/step"
        elif ext == ".stl":
            file_type = "cad/stl"
        elif ext == ".blend":
            file_type = "creative/blender"

        bullets = [
            f"Binary asset update: {file_name} ({size_delta_str})",
            f"CDC drift: {chunk_ratio_summary}",
            f"Header signature: {header_sample[:32]}...",
        ]

        return DifferInput(
            file_name=file_name,
            file_type=file_type,
            previous_metadata={"size": b_size},
            current_metadata={"size": c_size},
            raw_diff="\n".join(bullets),
            vision_summary=chunk_ratio_summary,
            domain_facts={
                "size_delta": size_delta,
                "chunk_analysis": chunk_ratio_summary,
            },
        )

    def analyze_change(
        self,
        file_name: str,
        base_bytes: Optional[bytes],
        current_bytes: bytes,
        base_manifest: Optional[FileManifest] = None,
        current_manifest: Optional[FileManifest] = None,
    ) -> DifferOutput:
        """Run extraction and invoke SemanticDifferAgent to produce strict output schema."""
        diff_input = self.extract(
            file_name=file_name,
            base_bytes=base_bytes,
            current_bytes=current_bytes,
            base_manifest=base_manifest,
            current_manifest=current_manifest,
        )
        return self.agent.analyze(diff_input)
