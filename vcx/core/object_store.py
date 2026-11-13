"""Content-Addressable Object Store for VCX.

Implements immutable blob, tree, and commit object storage with SHA-256
hashing and zlib compression, following Git's content-addressable architecture.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import zlib

from vcx.core.types import Commit, FileMode, ObjectType, TreeEntry


class ObjectStore:
    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)
        self.objects_dir = self.repo_dir / ".vcx" / "objects"
        self.objects_dir.mkdir(parents=True, exist_ok=True)

    def hash_data(self, obj_type: ObjectType, data: bytes) -> Tuple[str, bytes]:
        """Format header and calculate SHA-256 hash."""
        header = f"{obj_type.value} {len(data)}\0".encode("utf-8")
        full_payload = header + data
        sha = hashlib.sha256(full_payload).hexdigest()
        return sha, full_payload

    def write_object(self, obj_type: ObjectType, data: bytes) -> str:
        """Write compressed object to storage and return its SHA-256 hash."""
        sha, full_payload = self.hash_data(obj_type, data)
        obj_dir = self.objects_dir / sha[:2]
        obj_path = obj_dir / sha[2:]

        if obj_path.exists() and obj_path.stat().st_size > 0:
            return sha

        obj_dir.mkdir(parents=True, exist_ok=True)
        compressed = zlib.compress(full_payload, level=6)
        tmp_path = obj_dir / f".tmp_{os.getpid()}_{sha[2:]}"
        tmp_path.write_bytes(compressed)
        tmp_path.replace(obj_path)
        return sha

    def read_object(self, sha: str) -> Tuple[ObjectType, bytes]:
        """Read and decompress an object by SHA, verifying checksum integrity."""
        obj_path = self.objects_dir / sha[:2] / sha[2:]
        if not obj_path.exists():
            raise FileNotFoundError(f"VCX object not found: {sha}")

        compressed = obj_path.read_bytes()
        if not compressed:
            raise ValueError(f"Corrupt zero-byte object in storage: {sha}")

        try:
            full_payload = zlib.decompress(compressed)
        except zlib.error as err:
            raise ValueError(f"Failed to decompress object {sha}: {err}") from err

        actual_sha = hashlib.sha256(full_payload).hexdigest()
        if actual_sha != sha:
            raise ValueError(
                f"Object corruption detected for {sha}: computed checksum was {actual_sha}"
            )

        null_idx = full_payload.find(b"\0")
        if null_idx == -1:
            raise ValueError(f"Corrupt object: missing null separator in {sha}")

        header = full_payload[:null_idx].decode("utf-8")
        obj_type_str, size_str = header.split(" ")
        expected_size = int(size_str)
        data = full_payload[null_idx + 1 :]

        if len(data) != expected_size:
            raise ValueError(
                f"Object length mismatch for {sha}: expected {expected_size}, got {len(data)}"
            )

        return ObjectType(obj_type_str), data

    def write_blob(self, content: bytes) -> str:
        """Store raw file content as a blob."""
        return self.write_object(ObjectType.BLOB, content)

    def read_blob(self, sha: str) -> bytes:
        """Read blob content."""
        obj_type, data = self.read_object(sha)
        if obj_type != ObjectType.BLOB:
            raise ValueError(f"Expected blob for {sha}, found {obj_type.value}")
        return data

    def write_tree(self, entries: List[TreeEntry]) -> str:
        """Store directory structure as a tree object."""
        # Canonical sort by path for deterministic tree hashes
        sorted_entries = sorted(entries, key=lambda e: e.path)
        payload = json.dumps(
            [e.to_dict() for e in sorted_entries],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.write_object(ObjectType.TREE, payload)

    def read_tree(self, sha: str) -> List[TreeEntry]:
        """Read and parse tree entries."""
        obj_type, data = self.read_object(sha)
        if obj_type != ObjectType.TREE:
            raise ValueError(f"Expected tree for {sha}, found {obj_type.value}")
        entries_data = json.loads(data.decode("utf-8"))
        return [TreeEntry.from_dict(d) for d in entries_data]

    def write_commit(
        self,
        tree_sha: str,
        parent_shas: List[str],
        message: str,
        author: str,
        committer: Optional[str] = None,
        timestamp: Optional[float] = None,
        semantic_delta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store commit object."""
        import time

        commit = Commit(
            tree_sha=tree_sha,
            parent_shas=parent_shas,
            author=author,
            committer=committer or author,
            timestamp=timestamp if timestamp is not None else time.time(),
            message=message,
            semantic_delta=semantic_delta,
        )
        payload = json.dumps(
            commit.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return self.write_object(ObjectType.COMMIT, payload)

    def read_commit(self, sha: str) -> Commit:
        """Read and parse commit object."""
        obj_type, data = self.read_object(sha)
        if obj_type != ObjectType.COMMIT:
            raise ValueError(f"Expected commit for {sha}, found {obj_type.value}")
        data_dict = json.loads(data.decode("utf-8"))
        return Commit.from_dict(data_dict)
