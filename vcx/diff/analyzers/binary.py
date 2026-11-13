"""Binary and unknown file analyzer."""

from __future__ import annotations
import math
from typing import Any, Dict, Optional

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class BinaryAnalyzer(BaseAnalyzer):
    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_size = len(old_content) if old_content else 0
        new_size = len(new_content) if new_content else 0

        old_meta = {
            "size_bytes": old_size,
            "entropy": self._calc_entropy(old_content) if old_content else 0.0,
            "header": old_content[:16].hex() if old_content else "",
        }
        new_meta = {
            "size_bytes": new_size,
            "entropy": self._calc_entropy(new_content) if new_content else 0.0,
            "header": new_content[:16].hex() if new_content else "",
        }

        size_delta = new_size - old_size
        size_str = self._format_size_delta(size_delta, old_size, new_size)

        facts = {
            "size_delta_bytes": size_delta,
            "size_description": size_str,
            "old_size": old_size,
            "new_size": new_size,
        }

        raw_diff = (
            f"Binary file changed: {size_str}\n"
            f"Entropy: {old_meta['entropy']:.2f} -> {new_meta['entropy']:.2f}"
        )

        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary="",
            domain_facts=facts,
        )

    def _calc_entropy(self, data: bytes) -> float:
        if not data:
            return 0.0
        entropy = 0.0
        length = len(data)
        freqs = {}
        for b in data:
            freqs[b] = freqs.get(b, 0) + 1
        for count in freqs.values():
            p = count / length
            entropy -= p * math.log2(p)
        return round(entropy, 3)

    def _format_size_delta(self, delta: int, old_size: int, new_size: int) -> str:
        if old_size == 0:
            return f"Created binary file ({self._human_bytes(new_size)})"
        if new_size == 0:
            return f"Deleted binary file (was {self._human_bytes(old_size)})"

        sign = "+" if delta >= 0 else ""
        abs_delta = abs(delta)
        if abs_delta >= 1024 * 1024:
            mb = delta / (1024 * 1024)
            return f"File size {'increased' if delta > 0 else 'decreased'} by {abs(mb):.1f}MB"
        elif abs_delta >= 1024:
            kb = delta / 1024
            return f"File size {'increased' if delta > 0 else 'decreased'} by {abs(kb):.1f}KB"
        else:
            return f"File size {'increased' if delta > 0 else 'decreased'} by {abs_delta} bytes"

    def _human_bytes(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f}{unit}" if unit != "B" else f"{size}B"
            size /= 1024
        return f"{size:.1f}TB"
