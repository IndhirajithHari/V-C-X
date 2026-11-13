"""Content-Addressable Object Store for VCX.

Implements immutable blob, hierarchical Merkle tree, commit storage, packfiles,
and garbage collection with SHA-256 integrity validation and zlib compression.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import zlib

from vcx.core.pack import PackReader, PackWriter
from vcx.core.types import Commit, FileMode, IndexEntry, ObjectType, TreeEntry


class ObjectStore:
    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)
        self.objects_dir = self.repo_dir / ".vcx" / "objects"
        self.pack_dir = self.objects_dir / "pack"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.pack_dir.mkdir(parents=True, exist_ok=True)
        self._pack_readers: Optional[List[PackReader]] = None

    def _get_pack_readers(self) -> List[PackReader]:
        """Lazy load all packfile readers."""
        if self._pack_readers is None:
            self._pack_readers = []
            if self.pack_dir.exists():
                for p in self.pack_dir.glob("*.pack"):
                    try:
                        self._pack_readers.append(PackReader(p))
                    except Exception:
                        pass
        return self._pack_readers

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

        # Also check if already in packed objects
        for reader in self._get_pack_readers():
            if reader.has_object(sha):
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
        if obj_path.exists():
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

        # Check packfiles if not found loose
        for reader in self._get_pack_readers():
            if reader.has_object(sha):
                res = reader.read_object(sha)
                if res:
                    return res

        raise FileNotFoundError(f"VCX object not found: {sha}")

    def has_object(self, sha: str) -> bool:
        """Check if an object exists either loose or in packfiles."""
        obj_path = self.objects_dir / sha[:2] / sha[2:]
        if obj_path.exists() and obj_path.stat().st_size > 0:
            return True
        for reader in self._get_pack_readers():
            if reader.has_object(sha):
                return True
        return False

    def _rebuild_pack_index(self, pack_path: Path) -> Path:
        """Reconstruct .idx index for a .pack file."""
        import io
        import json
        import struct

        idx_path = pack_path.with_suffix(".idx")
        with open(pack_path, "rb") as f:
            magic = f.read(4)
            if magic != b"VPK1":
                raise ValueError("Invalid packfile magic")
            num_objects = struct.unpack(">I", f.read(4))[0]
            entries = {}
            for _ in range(num_objects):
                offset = f.tell()
                sha = f.read(32).hex()
                type_byte = struct.unpack(">B", f.read(1))[0]
                uncompressed_size = struct.unpack(">Q", f.read(8))[0]
                compressed_size = struct.unpack(">Q", f.read(8))[0]
                f.seek(compressed_size, io.SEEK_CUR)

                type_name = {1: "blob", 2: "tree", 3: "commit", 4: "tag"}.get(type_byte, "blob")
                entries[sha] = {
                    "offset": offset,
                    "size": uncompressed_size,
                    "type": type_name,
                }

        idx_data = {"version": 1, "count": num_objects, "entries": entries}
        idx_path.write_text(json.dumps(idx_data, indent=2), encoding="utf-8")
        return idx_path

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
        """Store directory structure as a single tree object."""
        # Canonical sort by entry path/name for deterministic tree hashes
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

    # --- HIERARCHICAL MERKLE TREES ---

    def build_hierarchical_tree(self, index_entries: List[IndexEntry]) -> str:
        """Construct recursive Git-style hierarchical Merkle trees from staged files.

        Returns the root tree SHA. Reuses unchanged subtree SHAs across commits.
        """
        # Group entries into a nested hierarchy tree:
        # tree_dict[dir_path] = { "files": [TreeEntry], "subdirs": { name: sub_dir_path } }
        dir_files: Dict[str, List[TreeEntry]] = {"": []}
        all_dirs: Set[str] = {""}

        for entry in index_entries:
            parts = entry.path.split("/")
            if len(parts) == 1:
                # Root level file
                dir_files[""].append(
                    TreeEntry(
                        mode=entry.mode,
                        path=parts[0],
                        sha=entry.sha,
                        file_type=entry.file_type,
                        obj_type="blob",
                    )
                )
            else:
                # File in a subdirectory
                dir_path = "/".join(parts[:-1])
                file_name = parts[-1]

                # Ensure all parent directory paths exist
                curr = ""
                for p in parts[:-1]:
                    curr = f"{curr}/{p}" if curr else p
                    all_dirs.add(curr)
                    if curr not in dir_files:
                        dir_files[curr] = []

                dir_files[dir_path].append(
                    TreeEntry(
                        mode=entry.mode,
                        path=file_name,
                        sha=entry.sha,
                        file_type=entry.file_type,
                        obj_type="blob",
                    )
                )

        # Build trees bottom-up (deepest directories first)
        def dir_depth(d: str) -> int:
            if not d:
                return 0
            return len(d.split("/"))

        sorted_dirs = sorted(list(all_dirs), key=dir_depth, reverse=True)
        subtree_shas: Dict[str, str] = {}

        for d in sorted_dirs:
            entries: List[TreeEntry] = list(dir_files.get(d, []))

            # Find immediate child subdirectories of directory d
            prefix = f"{d}/" if d else ""
            for other_d in all_dirs:
                if other_d.startswith(prefix) and other_d != d:
                    rel_sub = other_d[len(prefix) :]
                    if "/" not in rel_sub:  # immediate child
                        sub_sha = subtree_shas[other_d]
                        entries.append(
                            TreeEntry(
                                mode=FileMode.DIRECTORY.value,
                                path=rel_sub,
                                sha=sub_sha,
                                file_type="tree/directory",
                                obj_type="tree",
                            )
                        )

            # Write this directory level's tree
            subtree_shas[d] = self.write_tree(entries)

        return subtree_shas[""]

    def flatten_tree(self, root_tree_sha: str, prefix: str = "") -> Dict[str, TreeEntry]:
        """Recursively traverse a hierarchical Merkle tree and return full-path entries."""
        flattened: Dict[str, TreeEntry] = {}
        entries = self.read_tree(root_tree_sha)

        for entry in entries:
            full_path = f"{prefix}{entry.path}" if prefix else entry.path

            if entry.obj_type == "tree" or entry.mode == FileMode.DIRECTORY.value:
                # Recursively flatten child subtree
                sub_entries = self.flatten_tree(entry.sha, prefix=f"{full_path}/")
                flattened.update(sub_entries)
            else:
                # It's a leaf blob entry
                flattened[full_path] = TreeEntry(
                    mode=entry.mode,
                    path=full_path,
                    sha=entry.sha,
                    file_type=entry.file_type,
                    obj_type="blob",
                )

        return flattened

    def write_commit(
        self,
        tree_sha: str | Commit,
        parent_shas: Optional[List[str]] = None,
        message: Optional[str] = None,
        author: Optional[str] = None,
        committer: Optional[str] = None,
        timestamp: Optional[float] = None,
        semantic_delta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Store commit object (accepts Commit instance or separate fields)."""
        import time

        if isinstance(tree_sha, Commit):
            commit = tree_sha
        else:
            commit = Commit(
                tree_sha=tree_sha,
                parent_shas=parent_shas or [],
                author=author or "VCX Developer <dev@vcx.local>",
                committer=committer or author or "VCX Developer <dev@vcx.local>",
                timestamp=timestamp if timestamp is not None else time.time(),
                message=message or "",
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

    # --- PACKING & GARBAGE COLLECTION ---

    def list_loose_objects(self) -> List[Tuple[str, ObjectType, bytes]]:
        """List all loose objects currently on disk."""
        loose = []
        for d in self.objects_dir.iterdir():
            if d.is_dir() and len(d.name) == 2 and d.name != "pa":
                for f in d.iterdir():
                    sha = f"{d.name}{f.name}"
                    try:
                        obj_type, data = self.read_object(sha)
                        loose.append((sha, obj_type, data))
                    except Exception:
                        pass
        return loose

    def gc(self, reachable_shas: Set[str]) -> Dict[str, Any]:
        """Perform garbage collection:

        1. Pack all reachable loose objects into a compressed packfile.
        2. Delete packed loose object files.
        3. Prune unreferenced dangling loose objects.
        """
        loose_objects = self.list_loose_objects()
        to_pack = [obj for obj in loose_objects if obj[0] in reachable_shas]
        unreachable = [obj for obj in loose_objects if obj[0] not in reachable_shas]

        stats = {
            "packed_objects": 0,
            "pruned_objects": len(unreachable),
            "loose_remaining": 0,
            "packfile": None,
        }

        if to_pack:
            writer = PackWriter(self.pack_dir)
            pack_path, idx_path, pack_hash = writer.write_pack(to_pack)
            stats["packed_objects"] = len(to_pack)
            stats["packfile"] = pack_path.name
            # Reset pack readers so new packfile is immediately loaded
            self._pack_readers = None

            # Safely remove packed loose files
            for sha, _, _ in to_pack:
                obj_path = self.objects_dir / sha[:2] / sha[2:]
                if obj_path.exists():
                    try:
                        obj_path.unlink()
                        # Remove directory if empty
                        parent = obj_path.parent
                        if not any(parent.iterdir()):
                            parent.rmdir()
                    except OSError:
                        pass

        # Prune unreachable objects
        for sha, _, _ in unreachable:
            obj_path = self.objects_dir / sha[:2] / sha[2:]
            if obj_path.exists():
                try:
                    obj_path.unlink()
                    parent = obj_path.parent
                    if not any(parent.iterdir()):
                        parent.rmdir()
                except OSError:
                    pass

        return stats
