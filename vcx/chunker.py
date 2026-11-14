"""Content-Defined Chunking (CDC) Engine for VCX (v2.0).

Replaces whole-file hashing bottlenecks with variable-sized rolling hash chunking.
Handles multi-gigabyte binary assets (3D CAD, EDA floorplans, video, neural weights)
alongside code, slicing large files so modifying a single byte only re-chunks and
stores the local delta without rewriting unchanged chunks.
"""

from __future__ import annotations
import concurrent.futures
from dataclasses import asdict, dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple, Union

# Try importing fastcdc; fall back to pure-Python Gear rolling hash
try:
    import fastcdc
    _HAS_FASTCDC = True
except ImportError:
    fastcdc = None
    _HAS_FASTCDC = False


# Deterministic 256-entry Gear Hash lookup table for FastCDC rolling hash
# Generated with deterministic Knuth multiplicative hash constants
GEAR_TABLE: Tuple[int, ...] = (
    0x87B64C3B, 0x1A2B3C4D, 0x9E8D7C6B, 0x5F4E3D2C, 0xA1B2C3D4, 0x0F1E2D3C, 0x4B5A6978, 0x8C7B6A59,
    0xD1C2B3A4, 0x3E4D5C6B, 0x7A8B9C0D, 0x2E1F0A9B, 0x6C5B4A39, 0xB8A79685, 0xF2E1D0C9, 0x5D4C3B2A,
    0x9C8B7A69, 0x1E0F3D2C, 0x4A392817, 0x8B7A6958, 0xD0C1B2A3, 0x3F2E1D0C, 0x7E6D5C4B, 0xBFCEAD9C,
    0x0A192837, 0x5E4D3C2B, 0x9B8A7968, 0xDC0B1A29, 0x3B2A1908, 0x8A796857, 0xCFBEAD9C, 0x1E2D3C4B,
    0x6D5C4B3A, 0xAE9D8C7B, 0x0F2E1D3C, 0x4B3A2918, 0x8C7B6A59, 0xCBBAA998, 0x2A1908F7, 0x6E5D4C3B,
    0xB9A89786, 0x0E1F2A3B, 0x4D3C2B1A, 0x9C8B7A69, 0xD8C7B6A5, 0x39281706, 0x7E6D5C4B, 0xB0A19283,
    0x0C1B2A39, 0x5B4A3928, 0x9A897867, 0xDFCEBDAC, 0x2E1D0CFA, 0x6F5E4D3C, 0xB8A79685, 0x07162534,
    0x4E3D2C1B, 0x9D8C7B6A, 0xD0BFCEAD, 0x38271605, 0x7F6E5D4C, 0xB9A89786, 0x0D1C2B3A, 0x5C4B3A29,
    0x9B8A7968, 0xE0CFBEAD, 0x2F1E0DF9, 0x6E5D4C3B, 0xB7A69584, 0x08172635, 0x4D3C2B1A, 0x9C8B7A69,
    0xD1C0BFCE, 0x37261504, 0x7E6D5C4B, 0xB8A79685, 0x0E1D2C3B, 0x5D4C3B2A, 0x9A897867, 0xE1D0CFBE,
    0x2E1D0CFA, 0x6D5C4B3A, 0xB6A59483, 0x09182736, 0x4C3B2A19, 0x9B8A7968, 0xD2C1C0BF, 0x36251403,
    0x7D6C5B4A, 0xB7A69584, 0x0F1E2D3C, 0x5E4D3C2B, 0x99887766, 0xE2D1D0CF, 0x2D1C0BE9, 0x6C5B4A39,
    0xB5A49382, 0x0A192837, 0x4B3A2918, 0x9A897867, 0xD3C2C1C0, 0x35241302, 0x7C5B4A39, 0xB6A59483,
    0x08172635, 0x5D4C3B2A, 0x98877665, 0xE3D2D1D0, 0x2C1B0AD8, 0x6B5A4938, 0xB4A39281, 0x0B1A2938,
    0x4A392817, 0x99887766, 0xD4C3C2C1, 0x34231201, 0x7B4A3928, 0xB5A49382, 0x07162534, 0x5C4B3A29,
    0x97867564, 0xE4D3D2D1, 0x2B1A09C7, 0x6A493827, 0xB3A29180, 0x0C1B2A39, 0x49281706, 0x98776655,
    0xD5C4C3C2, 0x33221100, 0x7A392817, 0xB4A39281, 0x06152433, 0x5B3A2918, 0x96756453, 0xE5D4D3D2,
    0x2A09F8B6, 0x69382716, 0xB291807F, 0x0D1C2B3A, 0x481706F5, 0x97665544, 0xD6C5C4C3, 0x321100FF,
    0x79281706, 0xB3928170, 0x05142332, 0x5A291807, 0x95645342, 0xE6D5D4D3, 0x29F8E7A5, 0x68271605,
    0xB1807F6E, 0x0E1D2C3B, 0x4706F5E4, 0x96554433, 0xD7C6C5C4, 0x3100FFEE, 0x781706F5, 0xB281705F,
    0x04132231, 0x591807F6, 0x94534231, 0xE7D6D5D4, 0x28E7D694, 0x671605F4, 0xB07F6E5D, 0x0F1E2D3C,
    0x46F5E4D3, 0x95443322, 0xD8C7C6C5, 0x30FFEEED, 0x7706F5E4, 0xB1705F4E, 0x03122130, 0x5807F6E5,
    0x93423120, 0xE8D7D6D5, 0x27D6C583, 0x6605F4E3, 0xAF6E5D4C, 0x101F2E3D, 0x45E4D3C2, 0x94332211,
    0xD9C8C7C6, 0x2FFFEDDC, 0x76F5E4D3, 0xB05F4E3D, 0x0211202F, 0x57F6E5D4, 0x9231200F, 0xE9D8D7D6,
    0x26C5B472, 0x65F4E3D2, 0xAE5D4C3B, 0x11202F3E, 0x44D3C2B1, 0x93221100, 0xDAC9C8C7, 0x2EEEEDCB,
    0x75E4D3C2, 0xAF4E3D2C, 0x01101F2E, 0x56E5D4C3, 0x91200FFE, 0xEAD9D8D7, 0x25B4A361, 0x64E3D2C1,
    0xAD4C3B2A, 0x1221303F, 0x43C2B1A0, 0x921100EF, 0xDBCAC9C8, 0x2EDDDCBA, 0x74D3C2B1, 0xAE3D2C1B,
    0x000F1E2D, 0x55D4C3B2, 0x900FFEED, 0xEBDAE9E8, 0x24A39250, 0x63D2C1B0, 0xAC3B2A19, 0x13223140,
    0x42B1A09F, 0x9100EFDE, 0xDCCBCAC9, 0x2DCCBBA9, 0x73C2B1A0, 0xAD2C1B0A, 0xFF0E1D2C, 0x54C3B2A1,
    0x8F0EFDDC, 0xECDBEAE9, 0x2392813F, 0x62C1B09F, 0xAB2A1908, 0x14233241, 0x41A09F8E, 0x90FFDECD,
    0xDDCCBCA8, 0x2CBBBA98, 0x72B1A09F, 0xAC1B0A99, 0xFE0D1C2B, 0x53B2A190, 0x8E0DFCCB, 0xEDCCEBDA,
    0x2281702E, 0x61B09F8E, 0xAA1908F7, 0x15243342, 0x409F8E7D, 0x8FEECDCB, 0xDEBDBBA7, 0x2BAAA987,
)

# Standard default thresholds
DEFAULT_MIN_CHUNK = 4096      # 4 KB
DEFAULT_AVG_CHUNK = 16384     # 16 KB
DEFAULT_MAX_CHUNK = 65536     # 64 KB
WHOLE_FILE_THRESHOLD = 65536  # Files <= 64KB use single chunk
EMPTY_CHUNK_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@dataclass(slots=True)
class ChunkInfo:
    """Metadata describing a single variable-sized content chunk."""
    hash: str
    offset: int
    size: int

    def to_dict(self) -> Dict[str, Any]:
        return {"hash": self.hash, "offset": self.offset, "size": self.size}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChunkInfo:
        return cls(hash=data["hash"], offset=int(data["offset"]), size=int(data["size"]))


@dataclass
class FileManifest:
    """Merkle DAG manifest storing ordered chunks required to reconstruct a file."""
    path: str
    file_size: int
    chunks: List[ChunkInfo] = field(default_factory=list)
    manifest_hash: str = ""

    def __post_init__(self):
        if not self.manifest_hash:
            self.manifest_hash = self.compute_manifest_hash()

    @property
    def total_chunks(self) -> int:
        return len(self.chunks)

    def chunk_hashes(self) -> List[str]:
        return [c.hash for c in self.chunks]

    def compute_manifest_hash(self) -> str:
        """Compute deterministic SHA-256 hash over the chunk sequence."""
        h = hashlib.sha256()
        h.update(f"{self.path}:{self.file_size}:{len(self.chunks)}\n".encode("utf-8"))
        for c in self.chunks:
            h.update(f"{c.hash}:{c.offset}:{c.size}\n".encode("utf-8"))
        return h.hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "file_size": self.file_size,
            "manifest_hash": self.manifest_hash or self.compute_manifest_hash(),
            "total_chunks": len(self.chunks),
            "chunks": [c.to_dict() for c in self.chunks],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FileManifest:
        chunks = [ChunkInfo.from_dict(c) for c in data.get("chunks", [])]
        manifest = cls(
            path=data.get("path", ""),
            file_size=int(data.get("file_size", 0)),
            chunks=chunks,
            manifest_hash=data.get("manifest_hash", ""),
        )
        if not manifest.manifest_hash:
            manifest.manifest_hash = manifest.compute_manifest_hash()
        return manifest

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> FileManifest:
        return cls.from_dict(json.loads(json_str))

    def compare(self, base_manifest: Optional[FileManifest]) -> Dict[str, Any]:
        """Compute chunk modification ratio against a previous manifest."""
        current_hashes = set(self.chunk_hashes())
        if not base_manifest or not base_manifest.chunks:
            if not self.chunks:
                return {
                    "total_chunks": 0,
                    "modified_chunks": 0,
                    "unmodified_chunks": 0,
                    "modification_ratio": 0.0,
                    "summary": "Empty file (0 chunks)",
                }
            return {
                "total_chunks": len(self.chunks),
                "modified_chunks": len(self.chunks),
                "unmodified_chunks": 0,
                "modification_ratio": 1.0,
                "summary": f"{len(self.chunks)} of {len(self.chunks)} chunks new (100.0%)",
            }

        base_hashes = set(base_manifest.chunk_hashes())
        identical = current_hashes & base_hashes
        modified = len(current_hashes - identical)
        total = max(len(self.chunks), 1)
        ratio = modified / total

        return {
            "total_chunks": len(self.chunks),
            "base_total_chunks": len(base_manifest.chunks),
            "modified_chunks": modified,
            "unmodified_chunks": len(identical),
            "modification_ratio": ratio,
            "summary": f"{modified} of {len(self.chunks)} chunks modified ({ratio * 100:.1f}% chunk drift)",
        }


class FastCDCEngine:
    """High-performance Content-Defined Chunking using Gear rolling hash."""

    def __init__(
        self,
        min_size: int = DEFAULT_MIN_CHUNK,
        avg_size: int = DEFAULT_AVG_CHUNK,
        max_size: int = DEFAULT_MAX_CHUNK,
    ):
        self.min_size = min_size
        self.avg_size = avg_size
        self.max_size = max_size

        # Mask corresponding to average chunk size (e.g. 16384 -> 14 bits -> 0x3FFF)
        # FastCDC normalization: compute mask bit-width from avg_size
        bits = (avg_size - 1).bit_length()
        self.mask_normal = (1 << bits) - 1

    def chunk_bytes(
        self, data: bytes, path: str = ""
    ) -> Tuple[FileManifest, List[Tuple[ChunkInfo, bytes]]]:
        """Slice byte array into CDC chunks and return FileManifest + chunk payloads."""
        n = len(data)

        # Empty file (0 bytes) optimization
        if n == 0:
            chunk_info = ChunkInfo(hash=EMPTY_CHUNK_SHA, offset=0, size=0)
            manifest = FileManifest(path=path, file_size=0, chunks=[chunk_info])
            return manifest, [(chunk_info, b"")]

        # Optimization: Files <= WHOLE_FILE_THRESHOLD use single chunk
        if n <= WHOLE_FILE_THRESHOLD:
            chunk_hash = hashlib.sha256(data).hexdigest()
            chunk_info = ChunkInfo(hash=chunk_hash, offset=0, size=n)
            manifest = FileManifest(path=path, file_size=n, chunks=[chunk_info])
            return manifest, [(chunk_info, data)]

        # Try fastcdc library if available
        if _HAS_FASTCDC and fastcdc is not None:
            try:
                chunks: List[Tuple[ChunkInfo, bytes]] = []
                c_infos: List[ChunkInfo] = []
                for chunk in fastcdc.fastcdc(
                    data,
                    min_size=self.min_size,
                    avg_size=self.avg_size,
                    max_size=self.max_size,
                    fat=True,
                ):
                    c_data = chunk.data if hasattr(chunk, "data") else data[chunk.offset : chunk.offset + chunk.length]
                    c_hash = hashlib.sha256(c_data).hexdigest()
                    c_info = ChunkInfo(hash=c_hash, offset=chunk.offset, size=len(c_data))
                    c_infos.append(c_info)
                    chunks.append((c_info, c_data))

                manifest = FileManifest(path=path, file_size=n, chunks=c_infos)
                return manifest, chunks
            except Exception:
                pass  # Fall back to pure-Python Gear Hash

        # Pure-Python Gear rolling hash implementation
        chunks = []
        c_infos = []
        pos = 0
        table = GEAR_TABLE
        mask = self.mask_normal

        while pos < n:
            remaining = n - pos
            if remaining <= self.min_size:
                c_data = data[pos:]
                c_hash = hashlib.sha256(c_data).hexdigest()
                c_info = ChunkInfo(hash=c_hash, offset=pos, size=len(c_data))
                c_infos.append(c_info)
                chunks.append((c_info, c_data))
                break

            limit = min(pos + self.max_size, n)
            cut = limit
            fingerprint = 0

            # Scan from min_size boundary up to max_size
            curr = pos + self.min_size
            while curr < limit:
                fingerprint = ((fingerprint << 1) + table[data[curr]]) & 0xFFFFFFFF
                if (fingerprint & mask) == 0:
                    cut = curr + 1
                    break
                curr += 1

            c_data = data[pos:cut]
            c_hash = hashlib.sha256(c_data).hexdigest()
            c_info = ChunkInfo(hash=c_hash, offset=pos, size=len(c_data))
            c_infos.append(c_info)
            chunks.append((c_info, c_data))
            pos = cut

        manifest = FileManifest(path=path, file_size=n, chunks=c_infos)
        return manifest, chunks

    def chunk_file_stream(
        self, file_path: Union[str, Path]
    ) -> Generator[Tuple[ChunkInfo, bytes], None, FileManifest]:
        """Streamingly chunk a file from disk, yielding (ChunkInfo, bytes) pairs.

        Returns the completed FileManifest upon generator completion.
        Prevents high memory usage for multi-gigabyte 3D CAD or video files.
        """
        p = Path(file_path)
        file_size = p.stat().st_size
        rel_path = str(file_path)

        # Empty file (0 bytes)
        if file_size == 0:
            c_info = ChunkInfo(hash=EMPTY_CHUNK_SHA, offset=0, size=0)
            yield c_info, b""
            return FileManifest(path=rel_path, file_size=0, chunks=[c_info])

        # Small files
        if file_size <= WHOLE_FILE_THRESHOLD:
            data = p.read_bytes()
            c_hash = hashlib.sha256(data).hexdigest()
            c_info = ChunkInfo(hash=c_hash, offset=0, size=file_size)
            yield c_info, data
            return FileManifest(path=rel_path, file_size=file_size, chunks=[c_info])

        # 1. Try fastcdc library on binary file handle if available
        if _HAS_FASTCDC and fastcdc is not None:
            c_infos: List[ChunkInfo] = []
            try:
                with open(p, "rb") as fp:
                    it = fastcdc.fastcdc(
                        fp,
                        min_size=self.min_size,
                        avg_size=self.avg_size,
                        max_size=self.max_size,
                        fat=True,
                    )
                    for chunk in it:
                        c_data = chunk.data if hasattr(chunk, "data") else b""
                        c_hash = hashlib.sha256(c_data).hexdigest()
                        c_info = ChunkInfo(hash=c_hash, offset=chunk.offset, size=len(c_data))
                        c_infos.append(c_info)
                        yield c_info, c_data
                return FileManifest(path=rel_path, file_size=file_size, chunks=c_infos)
            except Exception:
                if c_infos:
                    # Partial chunks were already yielded; do not re-yield via fallback
                    raise
                # Fall through to pure-Python Gear Hash streaming

        # 2. Pure-Python Gear rolling hash streaming implementation
        c_infos = []
        pos = 0
        buffer = bytearray()
        table = GEAR_TABLE
        mask = self.mask_normal
        read_chunk_size = 256 * 1024  # 256 KB read buffer

        with open(p, "rb") as f:
            eof = False
            while not eof or buffer:
                # Ensure buffer has at least max_size bytes unless EOF is reached
                while len(buffer) < self.max_size and not eof:
                    chunk_read = f.read(read_chunk_size)
                    if not chunk_read:
                        eof = True
                        break
                    buffer.extend(chunk_read)

                n_buf = len(buffer)
                if n_buf == 0:
                    break

                # If at EOF and remaining buffer <= min_size, emit final tail chunk
                if eof and n_buf <= self.min_size:
                    c_data = bytes(buffer)
                    c_hash = hashlib.sha256(c_data).hexdigest()
                    c_info = ChunkInfo(hash=c_hash, offset=pos, size=len(c_data))
                    c_infos.append(c_info)
                    yield c_info, c_data
                    buffer.clear()
                    pos += len(c_data)
                    break

                limit = min(self.max_size, n_buf)
                cut = limit
                fingerprint = 0
                curr = self.min_size

                # Scan from min_size boundary up to max_size limit
                while curr < limit:
                    fingerprint = ((fingerprint << 1) + table[buffer[curr]]) & 0xFFFFFFFF
                    if (fingerprint & mask) == 0:
                        cut = curr + 1
                        break
                    curr += 1

                # Extract and yield chunk
                c_data = bytes(buffer[:cut])
                c_hash = hashlib.sha256(c_data).hexdigest()
                c_info = ChunkInfo(hash=c_hash, offset=pos, size=len(c_data))
                c_infos.append(c_info)
                yield c_info, c_data
                pos += cut
                del buffer[:cut]

        return FileManifest(path=rel_path, file_size=file_size, chunks=c_infos)

    def chunk_file(
        self, file_path: Union[str, Path]
    ) -> Tuple[FileManifest, List[Tuple[ChunkInfo, bytes]]]:
        """Convenience method to chunk entire file and return manifest + all chunks."""
        p = Path(file_path)
        gen = self.chunk_file_stream(p)
        chunks: List[Tuple[ChunkInfo, bytes]] = []
        try:
            while True:
                chunks.append(next(gen))
        except StopIteration as e:
            manifest = e.value
        return manifest, chunks

    def batch_chunk_files(
        self,
        file_paths: Sequence[Union[str, Path]],
        max_workers: Optional[int] = None,
    ) -> List[Tuple[FileManifest, List[Tuple[ChunkInfo, bytes]]]]:
        """Chunk multiple files concurrently using ThreadPoolExecutor.

        Returns results in the exact same order as file_paths, perfectly
        equivalent to sequential chunk_file calls.
        """
        paths = [Path(p) for p in file_paths]
        if not paths:
            return []

        if len(paths) == 1:
            return [self.chunk_file(paths[0])]

        workers = max_workers or min(32, (os.cpu_count() or 4) + 4)
        workers = min(len(paths), workers)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(self.chunk_file, paths))


# Module-level default singleton
_DEFAULT_CHUNKER = FastCDCEngine()


def chunk_bytes(data: bytes, path: str = "") -> Tuple[FileManifest, List[Tuple[ChunkInfo, bytes]]]:
    """Slice raw bytes into CDC chunks."""
    return _DEFAULT_CHUNKER.chunk_bytes(data, path=path)


def chunk_file(file_path: Union[str, Path]) -> Tuple[FileManifest, List[Tuple[ChunkInfo, bytes]]]:
    """Slice a file on disk into CDC chunks."""
    return _DEFAULT_CHUNKER.chunk_file(file_path)


def batch_chunk_files(
    file_paths: Sequence[Union[str, Path]],
    max_workers: Optional[int] = None,
) -> List[Tuple[FileManifest, List[Tuple[ChunkInfo, bytes]]]]:
    """Slice multiple files into CDC chunks concurrently using ThreadPoolExecutor."""
    return _DEFAULT_CHUNKER.batch_chunk_files(file_paths, max_workers=max_workers)
