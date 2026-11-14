"""VCX: Version Control for Everything (v2.0).

Next-generation distributed version control system with Content-Defined Chunking (CDC),
Zstandard object compression, SQLite local staging index, and multi-domain semantic diffing
for massive CAD models, EDA floorplans, video assets, databases, and source code.
"""

from __future__ import annotations

from vcx.bundle import create_bundle, verify_bundle
from vcx.chunker import ChunkInfo, FastCDCEngine, FileManifest, batch_chunk_files, chunk_bytes, chunk_file
from vcx.engine import VCXEngine
from vcx.index import Index, IndexRow
from vcx.reflog import ReflogEntry, read_reflog, record_reflog
from vcx.semantic import SemanticExtractor
from vcx.storage import ObjectStorage
from vcx.adapters.eda_adapter import EDAAdapter
from vcx.adapters.freecad_adapter import FreeCADAdapter

__version__ = "2.0.0"

__all__ = [
    "__version__",
    "VCXEngine",
    "ObjectStorage",
    "FastCDCEngine",
    "FileManifest",
    "ChunkInfo",
    "Index",
    "IndexRow",
    "SemanticExtractor",
    "FreeCADAdapter",
    "EDAAdapter",
    "chunk_bytes",
    "chunk_file",
    "batch_chunk_files",
    "ReflogEntry",
    "record_reflog",
    "read_reflog",
    "create_bundle",
    "verify_bundle",
]
