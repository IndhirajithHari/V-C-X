"""Zstandard Object Compression & Fan-Out Object Store for VCX (v2.0).

Organizes .vcx/objects/ using Git's 2-character prefix fan-out structure (ab/cdef1234...)
to prevent filesystem directory scaling bottlenecks. Compresses all BLOB chunks,
Tree manifests, and Commit objects with Zstandard (zstd) high-ratio compression,
with transparent fallback to zlib.
"""

from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union
import zlib

try:
    import zstandard as zstd
    _HAS_ZSTD = True
except ImportError:
    zstd = None
    _HAS_ZSTD = False

from vcx.chunker import ChunkInfo, EMPTY_CHUNK_SHA, FileManifest
EMPTY_SHA = EMPTY_CHUNK_SHA

# Magic header bytes
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
ZLIB_MAGIC = b"\x78"  # 0x7801, 0x789c, 0x78da


class ObjectStorage:
    """Manages compressed content-addressable storage in .vcx/objects/."""

    def __init__(self, repo_dir: Union[str, Path], compression_level: int = 3):
        self.repo_dir = Path(repo_dir)
        self.objects_dir = self.repo_dir / ".vcx" / "objects"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.compression_level = compression_level

        if _HAS_ZSTD and zstd is not None:
            self._cctx = zstd.ZstdCompressor(level=self.compression_level)
            self._dctx = zstd.ZstdDecompressor()
        else:
            self._cctx = None
            self._dctx = None

    def _get_object_path(self, sha: str) -> Path:
        """Get path for object SHA using 2-character fan-out directory."""
        if len(sha) < 3:
            return self.objects_dir / sha
        return self.objects_dir / sha[:2] / sha[2:]

    def has_object(self, sha: str) -> bool:
        """Check if an object or chunk exists in storage."""
        if sha == EMPTY_CHUNK_SHA:
            return True
        p = self._get_object_path(sha)
        return p.exists() and p.stat().st_size > 0

    def compress(self, data: bytes) -> bytes:
        """Compress data using Zstandard or fallback zlib."""
        if _HAS_ZSTD and self._cctx is not None:
            try:
                return self._cctx.compress(data)
            except Exception:
                pass
        return zlib.compress(data, level=6)

    def decompress(self, compressed: bytes) -> bytes:
        """Decompress data, auto-detecting Zstandard vs zlib magic bytes."""
        if not compressed:
            return b""

        # Check for Zstandard magic header
        if compressed.startswith(ZSTD_MAGIC) and _HAS_ZSTD and self._dctx is not None:
            try:
                return self._dctx.decompress(compressed)
            except Exception as e:
                # In case of partial or corrupted zstd
                raise ValueError(f"Failed to decompress Zstandard payload: {e}") from e

        # Fallback to zlib
        try:
            return zlib.decompress(compressed)
        except zlib.error as err:
            # If zlib fails, retry with zstd if not tried yet
            if _HAS_ZSTD and self._dctx is not None:
                try:
                    return self._dctx.decompress(compressed)
                except Exception:
                    pass
            raise ValueError(f"Failed to decompress payload (neither zstd nor zlib): {err}") from err

    def write_raw(self, data: bytes, expected_sha: Optional[str] = None) -> str:
        """Write raw payload compressed with zstd into 2-character fanout directory."""
        sha = expected_sha or hashlib.sha256(data).hexdigest()
        if sha == EMPTY_CHUNK_SHA:
            return sha
        obj_path = self._get_object_path(sha)

        if obj_path.exists() and obj_path.stat().st_size > 0:
            return sha

        obj_path.parent.mkdir(parents=True, exist_ok=True)
        compressed = self.compress(data)

        # Atomic write via temporary file
        tmp_name = f".tmp_{os.getpid()}_{sha[2:10]}_{os.urandom(4).hex()}"
        tmp_path = obj_path.parent / tmp_name
        try:
            tmp_path.write_bytes(compressed)
            tmp_path.replace(obj_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return sha

    def read_raw(self, sha: str, verify_checksum: bool = True) -> bytes:
        """Read and decompress raw payload by SHA, optionally verifying checksum."""
        if sha == EMPTY_CHUNK_SHA:
            return b""
        obj_path = self._get_object_path(sha)
        if not obj_path.exists():
            raise FileNotFoundError(f"Object {sha} not found in storage ({obj_path})")

        compressed = obj_path.read_bytes()
        if not compressed:
            raise ValueError(f"Corrupt zero-byte object in storage: {sha}")

        data = self.decompress(compressed)

        if verify_checksum:
            actual_sha = hashlib.sha256(data).hexdigest()
            # If expected_sha is standard object header, check payload or chunk
            if actual_sha != sha:
                # Might have an object header prefix (e.g. 'blob <len>\0<data>')
                null_idx = data.find(b"\0")
                if null_idx != -1:
                    header = data[:null_idx].decode("utf-8", errors="ignore")
                    payload = data[null_idx + 1 :]
                    # Check if actual sha matches payload without header
                    payload_sha = hashlib.sha256(payload).hexdigest()
                    if payload_sha != sha:
                        raise ValueError(
                            f"Object checksum mismatch for {sha}: computed {actual_sha} (payload: {payload_sha}, header: {header})"
                        )
                else:
                    raise ValueError(
                        f"Object checksum mismatch for {sha}: computed {actual_sha}"
                    )

        return data

    # --- CHUNK OPERATIONS ---

    def write_chunk(self, chunk_bytes: bytes) -> str:
        """Store a single content-defined chunk compressed with Zstandard."""
        return self.write_raw(chunk_bytes)

    def read_chunk(self, chunk_hash: str) -> bytes:
        """Read and decompress a content-defined chunk."""
        if chunk_hash == EMPTY_CHUNK_SHA:
            return b""
        return self.read_raw(chunk_hash, verify_checksum=True)

    # --- MANIFEST OPERATIONS ---

    def write_manifest(self, manifest: FileManifest) -> str:
        """Store a FileManifest Merkle DAG node into objects/."""
        manifest_json = manifest.to_json().encode("utf-8")
        manifest_header = f"manifest {len(manifest_json)}\0".encode("utf-8")
        full_payload = manifest_header + manifest_json
        sha = hashlib.sha256(full_payload).hexdigest()
        self.write_raw(full_payload, expected_sha=sha)
        return sha

    def read_manifest(self, manifest_sha: str) -> FileManifest:
        """Read and reconstruct a FileManifest from objects/."""
        raw = self.read_raw(manifest_sha, verify_checksum=False)
        null_idx = raw.find(b"\0")
        if null_idx != -1 and raw.startswith(b"manifest "):
            json_bytes = raw[null_idx + 1 :]
        else:
            json_bytes = raw
        try:
            return FileManifest.from_json(json_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Corrupted manifest object {manifest_sha}: {e}") from e

    # --- CHECKOUT STREAMING RECONSTRUCTION ---

    def checkout_file(self, manifest_hash: str, output_path: Union[str, Path]) -> int:
        """Reconstruct file from its FileManifest chunk sequence in stream order.

        Decompresses each chunk on the fly and streams it into output_path.
        Returns total bytes written.
        """
        manifest = self.read_manifest(manifest_hash)
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Fast path for empty file (0 bytes) or 0 chunks
        if manifest.file_size == 0 or len(manifest.chunks) == 0:
            dest.touch(exist_ok=True)
            if dest.stat().st_size != 0:
                dest.write_bytes(b"")
            return 0

        total_written = 0
        tmp_dest = dest.with_name(f".tmp_checkout_{dest.name}_{os.getpid()}_{os.urandom(4).hex()}")

        try:
            with open(tmp_dest, "wb") as out_f:
                for chunk_info in manifest.chunks:
                    if chunk_info.size == 0 or chunk_info.hash == EMPTY_CHUNK_SHA:
                        chunk_data = b""
                    else:
                        chunk_data = self.read_chunk(chunk_info.hash)
                    out_f.write(chunk_data)
                    total_written += len(chunk_data)

            if total_written != manifest.file_size:
                raise IOError(
                    f"Checkout integrity mismatch for {manifest.path}: expected {manifest.file_size} bytes, reconstructed {total_written} bytes"
                )

            tmp_dest.replace(dest)
            return total_written
        except Exception:
            tmp_dest.unlink(missing_ok=True)
            raise

    # --- GENERIC COMMIT & TREE OBJECTS ---

    def write_object(self, obj_type: str, data: bytes) -> str:
        """Store generic typed object (commit, tree, tag) with header."""
        header = f"{obj_type} {len(data)}\0".encode("utf-8")
        full_payload = header + data
        sha = hashlib.sha256(full_payload).hexdigest()
        self.write_raw(full_payload, expected_sha=sha)
        return sha

    def read_object(self, sha: str) -> Tuple[str, bytes]:
        """Read and decompress generic typed object; returns (obj_type, payload)."""
        if sha == EMPTY_CHUNK_SHA:
            return "blob", b""
        full_payload = self.read_raw(sha, verify_checksum=False)
        null_idx = full_payload.find(b"\0")
        if null_idx == -1:
            return "blob", full_payload

        header = full_payload[:null_idx].decode("utf-8", errors="ignore")
        parts = header.split(" ", 1)
        obj_type = parts[0] if parts else "blob"
        payload = full_payload[null_idx + 1 :]
        return obj_type, payload
