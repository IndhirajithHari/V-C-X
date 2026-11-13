"""Unified Delta Engine for multi-domain diff analysis."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from vcx.diff.analyzers.binary import BinaryAnalyzer
from vcx.diff.analyzers.cad_3d import Cad3DAnalyzer
from vcx.diff.analyzers.database_logs import DatabaseLogsAnalyzer
from vcx.diff.analyzers.eda_hardware import EdaHardwareAnalyzer
from vcx.diff.analyzers.source_code import SourceCodeAnalyzer
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
    def __init__(self):
        self.code_analyzer = SourceCodeAnalyzer()
        self.eda_analyzer = EdaHardwareAnalyzer()
        self.cad_analyzer = Cad3DAnalyzer()
        self.db_analyzer = DatabaseLogsAnalyzer()
        self.binary_analyzer = BinaryAnalyzer()

    def analyze_change(
        self,
        file_name: str,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        forced_file_type: Optional[str] = None,
    ) -> WatcherPayload:
        """Route file change to the specialized domain analyzer."""
        file_type = forced_file_type or detect_file_type(
            file_name, new_content or old_content
        )

        if file_type.startswith("source/") or file_type == "text/plain":
            result = self.code_analyzer.analyze(old_content, new_content, file_name)
        elif file_type.startswith("eda/"):
            result = self.eda_analyzer.analyze(old_content, new_content, file_name)
        elif file_type.startswith("cad/"):
            result = self.cad_analyzer.analyze(old_content, new_content, file_name)
        elif file_type.startswith("database/") or file_type.startswith("log/"):
            result = self.db_analyzer.analyze(old_content, new_content, file_name)
        else:
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
