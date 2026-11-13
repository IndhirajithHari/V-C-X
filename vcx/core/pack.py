"""Packfile and Pack Index implementation for VCX Object Storage.

Implements compressed packfile archive storage (.pack) and indexed binary
lookup (.idx) for garbage collection and high-performance repository packing.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
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

    MAGIC = b"VPK1"       # VCX Packfile Version 1
    INDEX_MAGIC = b"VID2" # VCX Binary Fanout Index Version 2

    def __init__(self, pack_dir: Path):
        self.pack_dir = Path(pack_dir)
        self.pack_dir.mkdir(parents=True, exist_ok=True)

    def write_pack(
        self,
        objects: List[Tuple[str, ObjectType, bytes]],
        max_workers: Optional[int] = None,
    ) -> Tuple[Path, Path, str]:
        """Write a list of (sha, obj_type, data) into a new .pack and .idx with parallel compression."""
        if not objects:
            raise ValueError("Cannot write empty packfile")

        # Sort objects by SHA for deterministic indexing
        sorted_objs = sorted(objects, key=lambda x: x[0])
        num_objects = len(sorted_objs)

        # Parallel multi-core zlib compression across threads
        def _compress_worker(item: Tuple[str, ObjectType, bytes]) -> Tuple[str, ObjectType, bytes, bytes]:
            sha, obj_type, raw_data = item
            compressed = zlib.compress(raw_data, level=6)
            return sha, obj_type, raw_data, compressed

        if num_objects > 4:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                compressed_results = list(executor.map(_compress_worker, sorted_objs))
        else:
            compressed_results = [_compress_worker(o) for o in sorted_objs]

        pack_buf = io.BytesIO()
        pack_buf.write(self.MAGIC)
        pack_buf.write(struct.pack(">I", num_objects))

        index_entries: List[PackIndexEntry] = []

        for sha, obj_type, raw_data, compressed in compressed_results:
            offset = pack_buf.tell()
            sha_bytes = bytes.fromhex(sha)
            type_byte = {
                ObjectType.BLOB: 1,
                ObjectType.TREE: 2,
                ObjectType.COMMIT: 3,
                ObjectType.TAG: 4,
            }[obj_type]

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

        # Write high-performance VID2 binary fanout index (O(1) prefix lookup)
        fanout = [0] * 256
        for e in index_entries:
            first_byte = int(e.sha[:2], 16)
            fanout[first_byte] += 1
        cum_fanout = [0] * 256
        running = 0
        for i in range(256):
            running += fanout[i]
            cum_fanout[i] = running

        idx_buf = io.BytesIO()
        idx_buf.write(self.INDEX_MAGIC)
        idx_buf.write(struct.pack(">I", 2))  # Version 2
        idx_buf.write(struct.pack(">I", num_objects))
        idx_buf.write(struct.pack(">256I", *cum_fanout))

        for e in index_entries:
            idx_buf.write(bytes.fromhex(e.sha))
            t_byte = {
                ObjectType.BLOB: 1,
                ObjectType.TREE: 2,
                ObjectType.COMMIT: 3,
                ObjectType.TAG: 4,
            }[e.obj_type]
            idx_buf.write(struct.pack(">B", t_byte))
            idx_buf.write(struct.pack(">Q", e.offset))
            idx_buf.write(struct.pack(">Q", e.size))

        idx_path.write_bytes(idx_buf.getvalue())

        return pack_path, idx_path, pack_hash


class PackReader:
    """Reads objects from a .pack file using its .idx index (supporting VID2 binary & JSON)."""

    def __init__(self, pack_path: Path):
        self.pack_path = Path(pack_path)
        self.idx_path = self.pack_path.with_suffix(".idx")
        self._index: Dict[str, Dict[str, Any]] = {}
        self._load_index()

    def _load_index(self) -> None:
        if not self.idx_path.exists():
            return
        raw = self.idx_path.read_bytes()
        if not raw:
            return

        if raw.startswith(b"VID2"):
            self._load_binary_index(raw)
        else:
            try:
                data = json.loads(raw.decode("utf-8"))
                self._index = data.get("entries", {})
            except Exception:
                self._index = {}

    def _load_binary_index(self, raw: bytes) -> None:
        """Parse VID2 binary fanout index in microseconds."""
        try:
            _, ver, count = struct.unpack_from(">4sII", raw, 0)
            fanout = struct.unpack_from(">256I", raw, 12)
            pos = 12 + 256 * 4
            entries: Dict[str, Dict[str, Any]] = {}
            for _ in range(count):
                sha_bytes = raw[pos : pos + 32]
                sha = sha_bytes.hex()
                type_b = raw[pos + 32]
                offset = struct.unpack_from(">Q", raw, pos + 33)[0]
                size = struct.unpack_from(">Q", raw, pos + 41)[0]
                type_str = {
                    1: ObjectType.BLOB.value,
                    2: ObjectType.TREE.value,
                    3: ObjectType.COMMIT.value,
                    4: ObjectType.TAG.value,
                }.get(type_b, "blob")
                entries[sha] = {"offset": offset, "size": size, "type": type_str}
                pos += 49
            self._index = entries
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
