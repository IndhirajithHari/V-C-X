"""Core data types and structures for the VCX storage engine."""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ObjectType(str, Enum):
    BLOB = "blob"
    TREE = "tree"
    COMMIT = "commit"
    TAG = "tag"


class FileMode(str, Enum):
    REGULAR = "100644"
    EXECUTABLE = "100755"
    SYMLINK = "120000"
    DIRECTORY = "040000"


@dataclass
class TreeEntry:
    mode: str
    path: str
    sha: str
    file_type: str = "binary/unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "path": self.path,
            "sha": self.sha,
            "file_type": self.file_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TreeEntry:
        return cls(
            mode=data["mode"],
            path=data["path"],
            sha=data["sha"],
            file_type=data.get("file_type", "binary/unknown"),
        )


@dataclass
class Commit:
    tree_sha: str
    parent_shas: List[str]
    author: str
    committer: str
    timestamp: float
    message: str
    semantic_delta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tree_sha": self.tree_sha,
            "parent_shas": self.parent_shas,
            "author": self.author,
            "committer": self.committer,
            "timestamp": self.timestamp,
            "message": self.message,
            "semantic_delta": self.semantic_delta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Commit:
        return cls(
            tree_sha=data["tree_sha"],
            parent_shas=data.get("parent_shas", []),
            author=data.get("author", "VCX User <user@vcx.local>"),
            committer=data.get("committer", "VCX User <user@vcx.local>"),
            timestamp=data.get("timestamp", 0.0),
            message=data.get("message", ""),
            semantic_delta=data.get("semantic_delta"),
        )


@dataclass
class IndexEntry:
    path: str
    sha: str
    size: int
    mtime: float
    mode: str = FileMode.REGULAR.value
    file_type: str = "binary/unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "sha": self.sha,
            "size": self.size,
            "mtime": self.mtime,
            "mode": self.mode,
            "file_type": self.file_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IndexEntry:
        return cls(
            path=data["path"],
            sha=data["sha"],
            size=data["size"],
            mtime=data["mtime"],
            mode=data.get("mode", FileMode.REGULAR.value),
            file_type=data.get("file_type", "binary/unknown"),
        )


class FileChangeType(str, Enum):
    ADDED = "A"
    MODIFIED = "M"
    DELETED = "D"
    UNTRACKED = "?"
