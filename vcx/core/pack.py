"""Packfile and Pack Index implementation for VCX Object Storage.

Implements compressed packfile archive storage (.pack) and indexed binary
lookup (.idx) for garbage collection and high-performance repository packing.
"""

from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import struct
from typing import Any, Dict, List, Optional, Set, Tuple
import zlib

from vcx.core.types import FileMode, ObjectType


class PackIndexEntry:
    def __init__(self, sha: str, offset: int, size: int, obj_type: ObjectType):
        self.sha = sha
        self.offset = offset
        self.size = size
        self.obj_type = obj_type


class PackWriter:
    """Creates a .pack and .idx file from a collection of objects."""

    MAGIC = b"VPK1"  # VCX Packfile Version 1
    INDEX_MAGIC = b"VIDX"

    def __init__(self, pack_dir: Path):
        self.pack_dir = Path(pack_dir)
        self.pack_dir.mkdir(parents=True, exist_ok=True)

    def write_pack(
        self,
        objects: List[Tuple[str, ObjectType, bytes]],
    ) -> Tuple[Path, Path, str]:
        """Write a list of (sha, obj_type, data) into a new .pack and .idx."""
        if not objects:
            raise ValueError("Cannot write empty packfile")

        # Sort objects by SHA for deterministic indexing
        sorted_objs = sorted(objects, key=lambda x: x[0])
        num_objects = len(sorted_objs)

        pack_buf = io.BytesIO()
        pack_buf.write(self.MAGIC)
        pack_buf.write(struct.pack(">I", num_objects))

        index_entries: List[PackIndexEntry] = []

        for sha, obj_type, raw_data in sorted_objs:
            offset = pack_buf.tell()
            sha_bytes = bytes.fromhex(sha)
            type_byte = {
                ObjectType.BLOB: 1,
                ObjectType.TREE: 2,
                ObjectType.COMMIT: 3,
                ObjectType.TAG: 4,
            }[obj_type]

            # Compress data
            compressed = zlib.compress(raw_data, level=6)
            uncompressed_size = len(raw_data)
            compressed_size = len(compressed)

            # Record entry in pack
            pack_buf.write(sha_bytes)  # 32 bytes
            pack_buf.write(struct.pack(">B", type_byte))  # 1 byte
            pack_buf.write(struct.pack(">Q", uncompressed_size))  # 8 bytes
            pack_buf.write(struct.pack(">Q", compressed_size))  # 8 bytes
            pack_buf.write(compressed)

            index_entries.append(
                PackIndexEntry(
                    sha=sha,
                    offset=offset,
                    size=uncompressed_size,
                    obj_type=obj_type,
                )
            )

        pack_bytes = pack_buf.getvalue()
        pack_hash = hashlib.sha256(pack_bytes).hexdigest()

        pack_path = self.pack_dir / f"pack-{pack_hash[:16]}.pack"
        idx_path = self.pack_dir / f"pack-{pack_hash[:16]}.idx"

        pack_path.write_bytes(pack_bytes)

        # Write index
        idx_data = {
            "version": 1,
            "count": num_objects,
            "entries": {
                e.sha: {
                    "offset": e.offset,
                    "size": e.size,
                    "type": e.obj_type.value,
                }
                for e in index_entries
            },
        }
        idx_path.write_text(json.dumps(idx_data, indent=2), encoding="utf-8")

        return pack_path, idx_path, pack_hash


class PackReader:
    """Reads objects from a .pack file using its .idx index."""

    def __init__(self, pack_path: Path):
        self.pack_path = Path(pack_path)
        self.idx_path = self.pack_path.with_suffix(".idx")
        self._index: Dict[str, Dict[str, Any]] = {}
        self._load_index()

    def _load_index(self) -> None:
        if not self.idx_path.exists():
            return
        try:
            data = json.loads(self.idx_path.read_text(encoding="utf-8"))
            self._index = data.get("entries", {})
        except Exception:
            self._index = {}

    def has_object(self, sha: str) -> bool:
        return sha in self._index

    def read_object(self, sha: str) -> Optional[Tuple[ObjectType, bytes]]:
        if sha not in self._index:
            return None

        info = self._index[sha]
        offset = info["offset"]
        obj_type = ObjectType(info["type"])

        with open(self.pack_path, "rb") as f:
            f.seek(offset)
            stored_sha_bytes = f.read(32)
            stored_sha = stored_sha_bytes.hex()
            if stored_sha != sha:
                raise ValueError(
                    f"Corrupt pack index: expected SHA {sha}, found {stored_sha}"
                )

            type_byte = struct.unpack(">B", f.read(1))[0]
            uncompressed_size = struct.unpack(">Q", f.read(8))[0]
            compressed_size = struct.unpack(">Q", f.read(8))[0]

            compressed_data = f.read(compressed_size)
            raw_data = zlib.decompress(compressed_data)

            if len(raw_data) != uncompressed_size:
                raise ValueError(
                    f"Corrupt pack object: size mismatch for {sha}"
                )

            return obj_type, raw_data

    def list_shas(self) -> Set[str]:
        return set(self._index.keys())
