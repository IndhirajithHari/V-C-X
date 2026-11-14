"""Core V-C-X Production Engine (v2.0).

Unifies Content-Defined Chunking (CDC), Zstandard fan-out object storage,
SQLite local staging (index.db), and pluggable semantic extractors into a single
high-performance distributed version control engine for files of any size and domain.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from vcx.chunker import FastCDCEngine, FileManifest, chunk_file
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

        for f_path in target_files:
            rel_path = self._sanitize_path(f_path.relative_to(self.repo_dir))
            stat = f_path.stat()
            mtime = stat.st_mtime
            size = stat.st_size

            # Fast check: skip re-chunking if mtime and size in index.db match
            if self.index.is_file_unchanged(rel_path, mtime, size):
                self.index.update_status(rel_path, "staged")
                staged.append(rel_path)
                continue

            # Stream chunk file via CDC engine
            manifest, chunks = self.chunker.chunk_file(f_path)
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
            curr_manifest = self.storage.read_manifest(row.manifest_hash)

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
        branch_file = self.vcx_dir / "refs" / "heads" / target_ref
        if branch_file.exists():
            target_commit_sha = branch_file.read_text(encoding="utf-8").strip()
            (self.vcx_dir / "HEAD").write_text(f"ref: refs/heads/{target_ref}\n")
        elif (self.vcx_dir / "refs" / "tags" / target_ref).exists():
            target_commit_sha = (self.vcx_dir / "refs" / "tags" / target_ref).read_text(encoding="utf-8").strip()
            (self.vcx_dir / "HEAD").write_text(f"{target_commit_sha}\n")
        else:
            target_commit_sha = target_ref

        if not self.storage.has_object(target_commit_sha):
            raise ValueError(f"Commit/ref '{target_ref}' not found in storage")

        _, c_bytes = self.storage.read_object(target_commit_sha)
        c_data = json.loads(c_bytes.decode("utf-8"))
        tree_sha = c_data["tree_sha"]
        _, t_bytes = self.storage.read_object(tree_sha)
        tree_map = json.loads(t_bytes.decode("utf-8"))

        reconstructed_count = 0
        for rel_path, entry in tree_map.items():
            m_hash = entry["manifest_hash"]
            out_p = self.repo_dir / rel_path
            self.storage.checkout_file(m_hash, out_p)
            stat = out_p.stat()
            self.index.add(
                path=rel_path,
                mtime=stat.st_mtime,
                size=stat.st_size,
                manifest_hash=m_hash,
                status="committed",
            )
            reconstructed_count += 1

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
