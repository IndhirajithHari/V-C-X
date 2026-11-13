"""Strict schemas for Semantic Differ Agent input and output."""

from __future__ import annotations
from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Union


@dataclass
class DifferInput:
    file_name: str
    file_type: str
    previous_metadata: Union[Dict[str, Any], str]
    current_metadata: Union[Dict[str, Any], str]
    raw_diff: str
    vision_summary: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DifferInput:
        return cls(
            file_name=data.get("file_name", "unknown"),
            file_type=data.get("file_type", "binary/unknown"),
            previous_metadata=data.get("previous_metadata", {}),
            current_metadata=data.get("current_metadata", {}),
            raw_diff=data.get("raw_diff", ""),
            vision_summary=data.get("vision_summary", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_name": self.file_name,
            "file_type": self.file_type,
            "previous_metadata": self.previous_metadata,
            "current_metadata": self.current_metadata,
            "raw_diff": self.raw_diff,
            "vision_summary": self.vision_summary,
        }


@dataclass
class DifferOutput:
    action_summary: str
    technical_delta: List[str]
    inferred_intent: str
    tags: List[str]

    def validate(self) -> None:
        """Validate strict constraints."""
        if len(self.action_summary) >= 50:
            # Enforce < 50 characters constraint
            self.action_summary = self.action_summary[:46] + "..."
        if not isinstance(self.technical_delta, list):
            self.technical_delta = [str(self.technical_delta)]
        if not isinstance(self.tags, list):
            self.tags = [str(self.tags)]

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "action_summary": self.action_summary,
            "technical_delta": self.technical_delta,
            "inferred_intent": self.inferred_intent,
            "tags": self.tags,
        }

    def to_json(self) -> str:
        """Return strictly valid JSON string without markdown formatting."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DifferOutput:
        obj = cls(
            action_summary=data.get("action_summary", "Update file"),
            technical_delta=data.get("technical_delta", []),
            inferred_intent=data.get("inferred_intent", ""),
            tags=data.get("tags", []),
        )
        obj.validate()
        return obj
