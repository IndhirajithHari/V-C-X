"""Unified Delta Engine for multi-domain diff analysis across all software in the world."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from vcx.core.plugins import PluginManager
from vcx.diff.analyzers.binary import BinaryAnalyzer
from vcx.diff.analyzers.cad_3d import Cad3DAnalyzer
from vcx.diff.analyzers.creative_app import CreativeAppAnalyzer
from vcx.diff.analyzers.database_logs import DatabaseLogsAnalyzer
from vcx.diff.analyzers.eda_hardware import EdaHardwareAnalyzer
from vcx.diff.analyzers.media import MediaAnalyzer
from vcx.diff.analyzers.source_code import SourceCodeAnalyzer
from vcx.diff.analyzers.universal_container import UniversalContainerAnalyzer
from vcx.diff.detector import detect_file_type


@dataclass
class WatcherPayload:
    file_name: str
    file_type: str
    previous_metadata: Any
    current_metadata: Any
    raw_diff: str
    vision_summary: str
    domain_facts: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_name": self.file_name,
            "file_type": self.file_type,
            "previous_metadata": self.previous_metadata,
            "current_metadata": self.current_metadata,
            "raw_diff": self.raw_diff,
            "vision_summary": self.vision_summary,
            "domain_facts": self.domain_facts,
        }


class DeltaEngine:
    def __init__(self, repo_dir: Optional[Path | str] = None):
        self.repo_dir = repo_dir
        self.plugin_manager = PluginManager(repo_dir)
        self.code_analyzer = SourceCodeAnalyzer()
        self.eda_analyzer = EdaHardwareAnalyzer()
        self.cad_analyzer = Cad3DAnalyzer()
        self.db_analyzer = DatabaseLogsAnalyzer()
        self.media_analyzer = MediaAnalyzer()
        self.creative_analyzer = CreativeAppAnalyzer()
        self.universal_container = UniversalContainerAnalyzer()
        self.binary_analyzer = BinaryAnalyzer()

    def analyze_change(
        self,
        file_name: str,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        forced_file_type: Optional[str] = None,
    ) -> WatcherPayload:
        """Route file change to the specialized domain analyzer or plugin."""
        active_content = new_content or old_content

        # 1. Custom external or Python plugin check
        plugin_info = self.plugin_manager.find_analyzer_for_file(file_name, active_content)
        if plugin_info:
            plugin_res = self.plugin_manager.execute(plugin_info, file_name, old_content, new_content)
            if plugin_res:
                return WatcherPayload(
                    file_name=file_name,
                    file_type="plugin/custom",
                    previous_metadata=plugin_res.previous_metadata,
                    current_metadata=plugin_res.current_metadata,
                    raw_diff=plugin_res.raw_diff,
                    vision_summary=plugin_res.vision_summary,
                    domain_facts=plugin_res.domain_facts,
                )

        file_type = forced_file_type or detect_file_type(file_name, active_content)

        # 2. Domain routing
        if file_type.startswith("source/") or file_type == "text/plain":
            result = self.code_analyzer.analyze(old_content, new_content, file_name)
        elif file_type.startswith("eda/") and file_type not in ("eda/kicad", "eda/eagle"):
            result = self.eda_analyzer.analyze(old_content, new_content, file_name)
        elif file_type in ("cad/stl", "cad/step", "cad/obj"):
            result = self.cad_analyzer.analyze(old_content, new_content, file_name)
        elif file_type.startswith("media/") or file_type.startswith("video/") or file_type.startswith("audio/") or file_type.startswith("image/"):
            result = self.media_analyzer.analyze(old_content, new_content, file_name)
        elif file_type.startswith("creative/") or file_type.startswith("document/"):
            result = self.creative_analyzer.analyze(old_content, new_content, file_name)
        elif file_type in ("database/sqlite", "database/csv", "log/generic"):
            result = self.db_analyzer.analyze(old_content, new_content, file_name)
        elif (
            file_type.startswith("music/")
            or file_type.startswith("game/")
            or file_type.startswith("design/")
            or file_type.startswith("scientific/")
            or file_type in ("cad/freecad", "cad/dwg", "cad/dxf", "eda/kicad", "eda/eagle", "database/parquet")
            or file_type.startswith("archive/")
        ):
            # Universal container, DAW, game engine, or CAD app analyzer
            result = self.universal_container.analyze(old_content, new_content, file_name)
        else:
            # Universal binary fallback (CDC + string extraction + entropy)
            result = self.binary_analyzer.analyze(old_content, new_content, file_name)

        return WatcherPayload(
            file_name=file_name,
            file_type=file_type,
            previous_metadata=result.previous_metadata,
            current_metadata=result.current_metadata,
            raw_diff=result.raw_diff,
            vision_summary=result.vision_summary,
            domain_facts=result.domain_facts,
        )
