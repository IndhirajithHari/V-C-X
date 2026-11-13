"""Base class for multi-domain diff analyzers."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
import difflib
from typing import Any, Dict, Optional


@dataclass
class AnalysisResult:
    previous_metadata: Any
    current_metadata: Any
    raw_diff: str
    vision_summary: str = ""
    domain_facts: Optional[Dict[str, Any]] = None


class BaseAnalyzer(ABC):
    @abstractmethod
    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        """Analyze differences between two file states and return structured metadata."""
        pass

    def compute_text_diff(
        self,
        old_text: str,
        new_text: str,
        file_name: str,
    ) -> str:
        """Generate unified diff string."""
        old_lines = old_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_name}",
            tofile=f"b/{file_name}",
        )
        return "".join(diff)
