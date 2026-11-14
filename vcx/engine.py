"""Core V-C-X Production Engine (v2.0).

Unifies Content-Defined Chunking (CDC), Zstandard fan-out object storage,
SQLite local staging (index.db), and pluggable semantic extractors into a single
high-performance distributed version control engine for files of any size and domain.
"""

from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from vcx.chunker import (
    ChunkInfo,
    EMPTY_CHUNK_SHA,
    FastCDCEngine,
    FileManifest,
    batch_chunk_files,
    chunk_file,
)
from vcx.index import Index, IndexRow
from vcx.semantic import SemanticExtractor
from vcx.storage import ObjectStorage


class VCXEngine:
    """Next-generation version control engine with CDC, Zstd, and SQLite index."""

    def __init__(self, repo_dir: Union[str, Path]):
        self.repo_dir = Path(repo_dir).resolve()
        self.vcx_dir = self.repo_dir / ".vcx"
        self.storage = ObjectStorage(self.repo_dir)
        self.index = Index(self.repo_dir)
        self.chunker = FastCDCEngine()
        self.semantic = SemanticExtractor()

    @classmethod
    def init(cls, target_dir: Union[str, Path] = ".") -> VCXEngine:
        """Initialize a new VCX v2.0 repository."""
        target = Path(target_dir).resolve()
        vcx_path = target / ".vcx"
        vcx_path.mkdir(parents=True, exist_ok=True)
        (vcx_path / "objects").mkdir(exist_ok=True)
        (vcx_path / "refs" / "heads").mkdir(parents=True, exist_ok=True)
        (vcx_path / "refs" / "tags").mkdir(parents=True, exist_ok=True)

        head_file = vcx_path / "HEAD"
        if not head_file.exists():
            head_file.write_text("ref: refs/heads/main\n", encoding="utf-8")

        # Create or update default config
        cfg_file = vcx_path / "config"
        if not cfg_file.exists():
            cfg_file.write_text(
                "[core]\n\tversion = 2.0\n\tformat = cdc-zstd\n[user]\n\tname = VCX Developer\n\temail = dev@vcx.local\n",
                encoding="utf-8",
            )

        # Initialize SQLite index.db
        Index(target)
        return cls(target)

    @classmethod
    def find(cls, start_path: Optional[Union[str, Path]] = None) -> VCXEngine:
        """Find the root of the containing VCX repository."""
        curr = Path(start_path or os.getcwd()).resolve()
        while True:
            if (curr / ".vcx").is_dir():
                return cls(curr)
            if curr.parent == curr:
                raise FileNotFoundError("Not a VCX repository (or any parent up to mount point)")
            curr = curr.parent

    # --- REF MANAGEMENT ---

    @property
    def head_ref(self) -> Optional[str]:
        """Read active branch reference from HEAD."""
        head_file = self.vcx_dir / "HEAD"
        if not head_file.exists():
            return None
        content = head_file.read_text(encoding="utf-8").strip()
        if content.startswith("ref: "):
            return content[5:]
        return None

    @property
    def head_commit_sha(self) -> Optional[str]:
        """Get the commit SHA of the current HEAD."""
        h_ref = self.head_ref
        if h_ref:
            ref_path = self.vcx_dir / h_ref
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()
        else:
            head_file = self.vcx_dir / "HEAD"
            if head_file.exists():
                sha = head_file.read_text(encoding="utf-8").strip()
                if sha and not sha.startswith("ref:"):
                    return sha
        return None

    def update_head(self, commit_sha: str) -> None:
        """Update active HEAD reference to a new commit SHA."""
        h_ref = self.head_ref
        if h_ref:
            ref_path = self.vcx_dir / h_ref
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_text(f"{commit_sha}\n", encoding="utf-8")
        else:
            (self.vcx_dir / "HEAD").write_text(f"{commit_sha}\n", encoding="utf-8")

    # --- STAGING (ADD / RESET) VIA CDC & ZSTD ---

    def _sanitize_path(self, path: Union[str, Path]) -> str:
        raw = str(path).strip().replace("\\", "/")
        if os.path.isabs(raw):
            try:
                rel = Path(raw).resolve().relative_to(self.repo_dir)
                raw = str(rel).replace("\\", "/")
            except ValueError:
                raise ValueError(f"Path outside repository: {path}")
        norm = os.path.normpath(raw).replace("\\", "/")
        if norm.startswith(".."):
            raise ValueError(f"Path traversal detected: {path}")
        return norm if norm != "." else ""

    def add(self, paths: List[Union[str, Path]]) -> List[str]:
        """Stage files using Content-Defined Chunking and Zstandard compression.

        Only modified chunks are written to .vcx/objects/; unchanged chunks are reused.
        """
        staged: List[str] = []

        target_files: List[Path] = []
        for p_input in paths:
            clean_str = self._sanitize_path(p_input)
            full_p = self.repo_dir / clean_str
            if not full_p.exists():
                raise FileNotFoundError(f"Path does not exist: {p_input}")
            if full_p.is_file():
                target_files.append(full_p)
            elif full_p.is_dir():
                for root, _, files in os.walk(full_p):
                    if ".vcx" in Path(root).parts or ".git" in Path(root).parts:
                        continue
                    for f in files:
                        target_files.append(Path(root) / f)

        files_to_chunk = []
        for f_path in target_files:
            rel_path = self._sanitize_path(f_path.relative_to(self.repo_dir))
            try:
                stat = f_path.stat()
            except OSError:
                continue
            mtime = stat.st_mtime
            size = stat.st_size

            # Fast check: skip re-chunking if mtime and size in index.db match AND manifest + chunks exist
            if self.index.is_file_unchanged(rel_path, mtime, size):
                cached_row = self.index.get(rel_path)
                if cached_row and self.storage.has_object(cached_row.manifest_hash):
                    try:
                        cached_manifest = self.storage.read_manifest(cached_row.manifest_hash)
                        missing_chunks = [c.hash for c in cached_manifest.chunks if not self.storage.has_object(c.hash)]
                        if not missing_chunks:
                            self.index.update_status(rel_path, "staged")
                            staged.append(rel_path)
                            continue
                    except Exception:
                        pass
                # Cached manifest or chunk is missing/corrupted; fall through to re-chunk and repair

            files_to_chunk.append((f_path, rel_path, mtime, size))

        if not files_to_chunk:
            return staged

        # Parallel batch chunking via ThreadPoolExecutor across multi-core systems
        if len(files_to_chunk) == 1:
            chunk_results = [self.chunker.chunk_file(files_to_chunk[0][0])]
        else:
            chunk_results = self.chunker.batch_chunk_files([item[0] for item in files_to_chunk])

        for (f_path, rel_path, mtime, size), (manifest, chunks) in zip(files_to_chunk, chunk_results):
            manifest.path = rel_path

            # Store only new chunks into .vcx/objects/ (compressed with zstd)
            for c_info, c_bytes in chunks:
                if not self.storage.has_object(c_info.hash):
                    self.storage.write_chunk(c_bytes)

            # Store manifest DAG object
            manifest_sha = self.storage.write_manifest(manifest)

            # Update SQLite index.db
            self.index.add(
                path=rel_path,
                mtime=mtime,
                size=size,
                manifest_hash=manifest_sha,
                status="staged",
            )
            staged.append(rel_path)

        return staged

    def reset(self, paths: Optional[List[Union[str, Path]]] = None) -> List[str]:
        """Unstage specified paths or all staged files."""
        unstaged = []
        if paths:
            for p in paths:
                clean = self._sanitize_path(p)
                row = self.index.get(clean)
                if row and row.status == "staged":
                    self.index.update_status(clean, "unstaged")
                    unstaged.append(clean)
        else:
            for row in self.index.staged_entries():
                self.index.update_status(row.path, "unstaged")
                unstaged.append(row.path)
        return unstaged

    # --- FAST STATUS VIA SQLITE INDEX ---

    def status(self) -> Dict[str, Any]:
        """Determine working tree state with instant SQLite mtime/size checks."""
        active_branch = (self.head_ref or "main").replace("refs/heads/", "")
        staged: List[Dict[str, Any]] = []
        unstaged: List[Dict[str, Any]] = []
        untracked: List[Dict[str, Any]] = []

        indexed_entries = {row.path: row for row in self.index.entries()}
        seen_worktree: Set[str] = set()

        for root, dirs, files in os.walk(self.repo_dir):
            rel_dir = Path(root).relative_to(self.repo_dir)
            if ".vcx" in rel_dir.parts or ".git" in rel_dir.parts:
                continue

            for f in files:
                full_f = Path(root) / f
                rel_f = str((full_f.relative_to(self.repo_dir))).replace("\\", "/")
                seen_worktree.add(rel_f)
                stat = full_f.stat()

                if rel_f in indexed_entries:
                    row = indexed_entries[rel_f]
                    # Instant mtime & size comparison
                    is_unchanged = self.index.is_file_unchanged(rel_f, stat.st_mtime, stat.st_size)
                    if row.status == "staged":
                        staged.append({"path": rel_f, "type": "modified" if not is_unchanged else "new", "size": stat.st_size})
                    elif not is_unchanged:
                        unstaged.append({"path": rel_f, "type": "modified", "size": stat.st_size})
                else:
                    untracked.append({"path": rel_f, "type": "untracked", "size": stat.st_size})

        # Check for deleted files
        for path, row in indexed_entries.items():
            if path not in seen_worktree:
                if row.status == "staged":
                    staged.append({"path": path, "type": "deleted", "size": row.size})
                else:
                    unstaged.append({"path": path, "type": "deleted", "size": row.size})

        return {
            "branch": active_branch,
            "staged": staged,
            "unstaged": unstaged,
            "untracked": untracked,
        }

    # --- COMMIT WITH ANTIGRAVITY SEMANTIC AGENT HOOK ---

    def commit(
        self,
        message: Optional[str] = None,
        auto: bool = False,
    ) -> Tuple[str, Dict[str, Any]]:
        """Commit staged files into Merkle DAG with optional Antigravity AI summary."""
        staged_rows = self.index.staged_entries()
        if not staged_rows:
            raise ValueError("No changes staged for commit (use 'vcx add' to stage files)")

        # 1. Build Merkle Tree Manifest
        tree_entries = []
        head_commit_sha = self.head_commit_sha
        head_tree = {}
        if head_commit_sha:
            try:
                head_obj_type, head_commit_bytes = self.storage.read_object(head_commit_sha)
                head_commit_data = json.loads(head_commit_bytes.decode("utf-8"))
                head_tree_sha = head_commit_data.get("tree_sha")
                if head_tree_sha:
                    _, t_bytes = self.storage.read_object(head_tree_sha)
                    head_tree = json.loads(t_bytes.decode("utf-8"))
            except Exception:
                pass

        # 2. Extract semantic diffs for each staged file
        differ_inputs = []
        differ_outputs = []
        for row in staged_rows:
            tree_entries.append({
                "path": row.path,
                "manifest_hash": row.manifest_hash,
                "size": row.size,
            })

            # Fetch base file bytes from previous commit if available
            base_bytes = None
            base_manifest = None
            if row.path in head_tree:
                old_m_hash = head_tree[row.path].get("manifest_hash")
                if old_m_hash and self.storage.has_object(old_m_hash):
                    try:
                        base_manifest = self.storage.read_manifest(old_m_hash)
                        # Reconstruct base file in memory
                        buf = io.BytesIO()
                        for c in base_manifest.chunks:
                            buf.write(self.storage.read_chunk(c.hash))
                        base_bytes = buf.getvalue()
                    except Exception:
                        pass

            # Read current file bytes
            curr_path = self.repo_dir / row.path
            current_bytes = curr_path.read_bytes() if curr_path.exists() else b""
            try:
                curr_manifest = self.storage.read_manifest(row.manifest_hash)
            except Exception as e:
                raise ValueError(
                    f"Staged file '{row.path}' manifest '{row.manifest_hash}' is missing or corrupted: {e}"
                ) from e

            diff_input = self.semantic.extract(
                file_name=row.path,
                base_bytes=base_bytes,
                current_bytes=current_bytes,
                base_manifest=base_manifest,
                current_manifest=curr_manifest,
            )
            differ_inputs.append(diff_input)

            if auto:
                d_out = self.semantic.analyze_change(
                    file_name=row.path,
                    base_bytes=base_bytes,
                    current_bytes=current_bytes,
                    base_manifest=base_manifest,
                    current_manifest=curr_manifest,
                )
                differ_outputs.append(d_out)

        # Build tree object and write to storage
        tree_map = {e["path"]: e for e in tree_entries}
        tree_bytes = json.dumps(tree_map, indent=2, sort_keys=True).encode("utf-8")
        tree_sha = self.storage.write_object("tree", tree_bytes)

        # 3. Determine commit message and semantic delta
        semantic_delta = {}
        if auto:
            # Aggregate differ outputs
            if differ_outputs:
                first = differ_outputs[0]
                all_bullets = []
                all_tags = set()
                for do in differ_outputs:
                    all_bullets.extend(do.technical_delta)
                    all_tags.update(do.tags)

                commit_message = first.action_summary if len(differ_outputs) == 1 else f"Update {len(differ_outputs)} files across project"
                semantic_delta = {
                    "action_summary": commit_message,
                    "technical_delta": all_bullets[:15],
                    "inferred_intent": first.inferred_intent or "Advance project deliverables per requirements.",
                    "tags": sorted(all_tags),
                }
            else:
                commit_message = "feat: automated semantic commit"
        else:
            if not message:
                raise ValueError("Commit message required unless --auto is specified")
            commit_message = message

        # 4. Create Commit DAG Object
        commit_payload = {
            "tree_sha": tree_sha,
            "parent_shas": [head_commit_sha] if head_commit_sha else [],
            "author": "VCX Developer <dev@vcx.local>",
            "timestamp": time.time(),
            "message": commit_message,
            "semantic_delta": semantic_delta,
            "v2_architecture": True,
        }

        commit_bytes = json.dumps(commit_payload, indent=2, sort_keys=True).encode("utf-8")
        commit_sha = self.storage.write_object("commit", commit_bytes)

        # Update HEAD
        self.update_head(commit_sha)

        # Mark staged files as committed in SQLite index.db
        for row in staged_rows:
            self.index.update_status(row.path, "committed")

        return commit_sha, commit_payload

    # --- CHECKOUT STREAMING RECONSTRUCTION ---

    def checkout(self, target_ref: str) -> int:
        """Checkout a branch or commit, reconstructing all files streamingly."""
        # Resolve ref to commit SHA
        target_commit_sha = None
        new_head_content = None
        branch_file = self.vcx_dir / "refs" / "heads" / target_ref
        tag_file = self.vcx_dir / "refs" / "tags" / target_ref
        if branch_file.exists():
            target_commit_sha = branch_file.read_text(encoding="utf-8").strip()
            new_head_content = f"ref: refs/heads/{target_ref}\n"
        elif tag_file.exists():
            target_commit_sha = tag_file.read_text(encoding="utf-8").strip()
            new_head_content = f"{target_commit_sha}\n"
        else:
            target_commit_sha = target_ref
            new_head_content = f"{target_commit_sha}\n"

        if not target_commit_sha or not self.storage.has_object(target_commit_sha):
            raise ValueError(f"Commit/ref '{target_ref}' not found in storage")

        try:
            _, c_bytes = self.storage.read_object(target_commit_sha)
            c_data = json.loads(c_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Corrupted commit object '{target_commit_sha}': {e}") from e

        tree_sha = c_data.get("tree_sha")
        if not tree_sha or not self.storage.has_object(tree_sha):
            raise ValueError(f"Missing tree object '{tree_sha}' for commit '{target_commit_sha}'")

        try:
            _, t_bytes = self.storage.read_object(tree_sha)
            tree_map = json.loads(t_bytes.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Corrupted tree object '{tree_sha}': {e}") from e

        if not isinstance(tree_map, dict):
            raise ValueError(f"Invalid tree payload in tree object '{tree_sha}'")

        reconstructed_count = 0
        for rel_path, entry in tree_map.items():
            m_hash = entry.get("manifest_hash")
            if not m_hash:
                raise ValueError(f"Invalid tree entry for '{rel_path}': missing manifest_hash")
            if not self.storage.has_object(m_hash):
                raise FileNotFoundError(f"Missing manifest object '{m_hash}' for file '{rel_path}'")

            out_p = self.repo_dir / rel_path
            try:
                self.storage.checkout_file(m_hash, out_p)
            except Exception as e:
                raise RuntimeError(f"Failed to reconstruct '{rel_path}' from manifest '{m_hash}': {e}") from e

            stat = out_p.stat()
            self.index.add(
                path=rel_path,
                mtime=stat.st_mtime,
                size=stat.st_size,
                manifest_hash=m_hash,
                status="committed",
            )
            reconstructed_count += 1

        # Only update HEAD after checkout succeeds
        if new_head_content:
            (self.vcx_dir / "HEAD").write_text(new_head_content, encoding="utf-8")

        return reconstructed_count

    # --- LOG & INSPECTION ---

    def log(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Walk commit DAG backward from HEAD and return commit log."""
        commits = []
        curr_sha = self.head_commit_sha
        count = 0

        while curr_sha and count < limit:
            if not self.storage.has_object(curr_sha):
                break
            _, c_bytes = self.storage.read_object(curr_sha)
            c_data = json.loads(c_bytes.decode("utf-8"))
            c_data["sha"] = curr_sha
            commits.append(c_data)
            count += 1
            parents = c_data.get("parent_shas", [])
            curr_sha = parents[0] if parents else None

        return commits

    # --- TOP-LEVEL BATCH CHUNKING, STATS & INTEGRITY VERIFICATION ---

    def batch_chunk_files(
        self,
        file_paths: Sequence[Union[str, Path]],
        max_workers: Optional[int] = None,
    ) -> List[Tuple[FileManifest, List[Tuple[ChunkInfo, bytes]]]]:
        """Slice multiple files into CDC chunks concurrently using ThreadPoolExecutor."""
        return self.chunker.batch_chunk_files(file_paths, max_workers=max_workers)

    def get_repository_stats(self) -> Dict[str, Any]:
        """Compute comprehensive repository statistics, deduplication, and compression analytics.

        Returns:
            Dictionary containing:
            - total_files: number of tracked files
            - total_chunks: sum of all chunk references across tracked manifests
            - unique_chunks: number of distinct chunk hashes stored
            - deduplication_ratio: total_chunks / unique_chunks (e.g., 2.8)
            - uncompressed_size: total uncompressed byte size of tracked files
            - compressed_size: total size on disk of compressed objects in .vcx/objects/
            - compression_ratio: uncompressed_size / compressed_size
            - space_savings_pct: percentage of disk space saved
            - database_size: size of SQLite index.db (+ wal/shm) in bytes
            - database_health: SQLite integrity status ('ok' or error string)
            - total_objects: total count of stored objects in .vcx/objects/
        """
        tracked_files: Dict[str, Dict[str, Any]] = {}

        for row in self.index.entries():
            tracked_files[row.path] = {
                "size": row.size,
                "manifest_hash": row.manifest_hash,
                "status": row.status,
            }

        # If index is empty, attempt to read from HEAD commit tree
        if not tracked_files and self.head_commit_sha and self.storage.has_object(self.head_commit_sha):
            try:
                _, c_bytes = self.storage.read_object(self.head_commit_sha)
                c_data = json.loads(c_bytes.decode("utf-8"))
                tree_sha = c_data.get("tree_sha")
                if tree_sha and self.storage.has_object(tree_sha):
                    _, t_bytes = self.storage.read_object(tree_sha)
                    tree_map = json.loads(t_bytes.decode("utf-8"))
                    for p, entry in tree_map.items():
                        tracked_files[p] = {
                            "size": entry.get("size", 0),
                            "manifest_hash": entry.get("manifest_hash", ""),
                            "status": "committed",
                        }
            except Exception:
                pass

        total_files = len(tracked_files)
        total_chunks = 0
        all_chunk_hashes: List[str] = []
        unique_chunks_set: Set[str] = set()
        uncompressed_size = 0

        for p, finfo in tracked_files.items():
            uncompressed_size += int(finfo.get("size", 0))
            m_hash = finfo.get("manifest_hash")
            if m_hash and self.storage.has_object(m_hash):
                try:
                    manifest = self.storage.read_manifest(m_hash)
                    total_chunks += len(manifest.chunks)
                    for c in manifest.chunks:
                        all_chunk_hashes.append(c.hash)
                        unique_chunks_set.add(c.hash)
                except Exception:
                    pass

        unique_chunks = len(unique_chunks_set)
        if unique_chunks > 0:
            deduplication_ratio = round(total_chunks / unique_chunks, 2)
        else:
            deduplication_ratio = 1.0

        # Calculate compressed storage size on disk
        compressed_size = 0
        total_objects = 0
        if self.storage.objects_dir.exists():
            for root, _, files in os.walk(self.storage.objects_dir):
                for f in files:
                    if f.startswith(".tmp"):
                        continue
                    p_file = Path(root) / f
                    try:
                        sz = p_file.stat().st_size
                        compressed_size += sz
                        total_objects += 1
                    except OSError:
                        pass

        if uncompressed_size > 0 and compressed_size > 0:
            compression_ratio = round(uncompressed_size / compressed_size, 2)
            if uncompressed_size >= compressed_size:
                space_savings_pct = round(((uncompressed_size - compressed_size) / uncompressed_size) * 100, 2)
            else:
                space_savings_pct = 0.0
        else:
            compression_ratio = 1.0
            space_savings_pct = 0.0

        # Calculate database size
        db_size = 0
        for db_f in [
            self.index.db_path,
            Path(str(self.index.db_path) + "-wal"),
            Path(str(self.index.db_path) + "-shm"),
        ]:
            if db_f.exists():
                try:
                    db_size += db_f.stat().st_size
                except OSError:
                    pass

        # Check database health
        db_health = "ok"
        try:
            db_health = self.index.quick_check()
        except Exception as e:
            db_health = f"error: {e}"

        return {
            "total_files": total_files,
            "total_chunks": total_chunks,
            "unique_chunks": unique_chunks,
            "deduplication_ratio": deduplication_ratio,
            "uncompressed_size": uncompressed_size,
            "compressed_size": compressed_size,
            "compression_ratio": compression_ratio,
            "space_savings_pct": space_savings_pct,
            "database_size": db_size,
            "database_health": db_health,
            "total_objects": total_objects,
        }

    def verify_repository_integrity(self) -> Dict[str, Any]:
        """Verify integrity of all tracked file manifests, chunks, and index database.

        Checks:
        1. That every manifest exists and decompresses cleanly.
        2. That every chunk referenced by manifests exists in .vcx/objects/.
        3. Decompresses every chunk and verifies its SHA-256 integrity.
        4. Verifies SQLite index.db quick_check/integrity_check.

        Returns:
            Dictionary containing:
            - valid: bool, True if repository has 0 corruptions and 0 missing objects
            - files_checked: int, count of files checked
            - chunks_checked: int, count of chunk references checked
            - missing_chunks: List[str], chunk hashes that are missing from objects/
            - corrupted_chunks: List[str], chunk hashes that fail decompression or SHA-256
            - missing_manifests: List[str], manifest hashes that are missing
            - corrupted_manifests: List[str], manifest hashes that are corrupted
            - database_ok: bool, True if SQLite integrity check passed
            - errors: List[str], descriptive error strings for each problem found
        """
        missing_chunks: List[str] = []
        corrupted_chunks: List[str] = []
        missing_manifests: List[str] = []
        corrupted_manifests: List[str] = []
        errors: List[str] = []

        # Collect tracked manifests from index and commits
        tracked_manifests: Dict[str, str] = {}

        for row in self.index.entries():
            tracked_manifests[row.path] = row.manifest_hash

        # Check HEAD commit tree as well
        if self.head_commit_sha and self.storage.has_object(self.head_commit_sha):
            try:
                _, c_bytes = self.storage.read_object(self.head_commit_sha)
                c_data = json.loads(c_bytes.decode("utf-8"))
                tree_sha = c_data.get("tree_sha")
                if tree_sha and self.storage.has_object(tree_sha):
                    _, t_bytes = self.storage.read_object(tree_sha)
                    tree_map = json.loads(t_bytes.decode("utf-8"))
                    for p, entry in tree_map.items():
                        if p not in tracked_manifests and entry.get("manifest_hash"):
                            tracked_manifests[p] = entry["manifest_hash"]
            except Exception as e:
                errors.append(f"Corrupted commit/tree in HEAD DAG: {e}")

        files_checked = len(tracked_manifests)
        chunks_checked = 0
        verified_chunk_hashes: Set[str] = set()

        for file_path, m_hash in tracked_manifests.items():
            if not m_hash:
                continue

            if not self.storage.has_object(m_hash):
                if m_hash not in missing_manifests:
                    missing_manifests.append(m_hash)
                errors.append(f"Missing manifest {m_hash} for file '{file_path}'")
                continue

            try:
                manifest = self.storage.read_manifest(m_hash)
            except Exception as e:
                if m_hash not in corrupted_manifests:
                    corrupted_manifests.append(m_hash)
                errors.append(f"Corrupted manifest {m_hash} for file '{file_path}': {e}")
                continue

            # Verify chunks referenced in manifest
            for chunk_info in manifest.chunks:
                chunks_checked += 1
                c_hash = chunk_info.hash

                if c_hash == EMPTY_CHUNK_SHA:
                    continue

                if c_hash in verified_chunk_hashes:
                    continue

                if not self.storage.has_object(c_hash):
                    if c_hash not in missing_chunks:
                        missing_chunks.append(c_hash)
                    errors.append(f"Missing chunk {c_hash} in file '{file_path}' (offset: {chunk_info.offset}, size: {chunk_info.size})")
                    continue

                try:
                    chunk_bytes = self.storage.read_chunk(c_hash)
                    if len(chunk_bytes) != chunk_info.size:
                        if c_hash not in corrupted_chunks:
                            corrupted_chunks.append(c_hash)
                        errors.append(f"Chunk size mismatch for {c_hash} in file '{file_path}': expected {chunk_info.size}, got {len(chunk_bytes)}")
                    else:
                        verified_chunk_hashes.add(c_hash)
                except Exception as e:
                    if c_hash not in corrupted_chunks:
                        corrupted_chunks.append(c_hash)
                    errors.append(f"Corrupted chunk {c_hash} in file '{file_path}': {e}")

        # Scan objects directory for any directly corrupted object files on disk
        if self.storage.objects_dir.exists():
            for root, _, files in os.walk(self.storage.objects_dir):
                parent_name = Path(root).name
                if len(parent_name) != 2:
                    continue
                for f in files:
                    if f.startswith(".tmp") or len(f) != 62:
                        continue
                    # Object SHA is parent directory name (2 chars) + file name (62 chars)
                    full_sha = parent_name + f
                    if full_sha in verified_chunk_hashes or full_sha in corrupted_chunks:
                        continue
                    # Verify readable and valid
                    try:
                        self.storage.read_raw(full_sha, verify_checksum=True)
                    except Exception as e:
                        if full_sha not in corrupted_chunks:
                            corrupted_chunks.append(full_sha)
                        errors.append(f"Corrupted object file {full_sha} in storage: {e}")

        # Check SQLite database integrity
        db_ok = True
        try:
            qc = self.index.quick_check()
            if qc != "ok":
                db_ok = False
                errors.append(f"Database integrity check failed: {qc}")
        except Exception as e:
            db_ok = False
            errors.append(f"Database integrity check error: {e}")

        is_valid = (
            len(missing_chunks) == 0
            and len(corrupted_chunks) == 0
            and len(missing_manifests) == 0
            and len(corrupted_manifests) == 0
            and db_ok
        )

        return {
            "valid": is_valid,
            "files_checked": files_checked,
            "chunks_checked": chunks_checked,
            "missing_chunks": missing_chunks,
            "corrupted_chunks": corrupted_chunks,
            "missing_manifests": missing_manifests,
            "corrupted_manifests": corrupted_manifests,
            "database_ok": db_ok,
            "errors": errors,
        }
