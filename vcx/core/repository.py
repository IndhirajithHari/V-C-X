"""Core Repository implementation for VCX."""

from __future__ import annotations
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from vcx.agent.schemas import DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.core.index import Index
from vcx.core.object_store import ObjectStore
from vcx.core.types import Commit, FileChangeType, FileMode, IndexEntry, ObjectType, TreeEntry
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type


class Repository:
    IGNORE_DIRS = {".vcx", ".git", ".venv", "__pycache__", "build", "dist", ".pytest_cache", ".idea", ".vscode"}

    def __init__(self, root_dir: Path | str):
        self.root = Path(root_dir).resolve()
        self.vcx_dir = self.root / ".vcx"
        self.store = ObjectStore(self.root)
        self.index = Index(self.root)
        self.delta_engine = DeltaEngine()
        self.agent = SemanticDifferAgent()

    @classmethod
    def init(cls, root_dir: Path | str) -> Repository:
        """Initialize a new VCX repository."""
        root = Path(root_dir).resolve()
        vcx_dir = root / ".vcx"
        if vcx_dir.exists():
            return cls(root)

        vcx_dir.mkdir(parents=True, exist_ok=True)
        (vcx_dir / "objects").mkdir(exist_ok=True)
        (vcx_dir / "refs" / "heads").mkdir(parents=True, exist_ok=True)

        head_file = vcx_dir / "HEAD"
        head_file.write_text("ref: refs/heads/main\n", encoding="utf-8")

        config_file = vcx_dir / "config"
        config_file.write_text(
            "[core]\n\trepositoryformatversion = 1\n\tfilemode = true\n\tbare = false\n",
            encoding="utf-8",
        )

        repo = cls(root)
        repo.index.write()
        return repo

    @classmethod
    def find(cls, start_path: Optional[Path | str] = None) -> Repository:
        """Find the root of the containing VCX repository."""
        current = Path(start_path or os.getcwd()).resolve()
        while True:
            if (current / ".vcx").is_dir():
                return cls(current)
            if current.parent == current:
                raise FileNotFoundError("Not a VCX repository (or any parent up to mount point)")
            current = current.parent

    @property
    def head_ref(self) -> Optional[str]:
        """Read target ref from HEAD."""
        head_file = self.vcx_dir / "HEAD"
        if not head_file.exists():
            return None
        content = head_file.read_text(encoding="utf-8").strip()
        if content.startswith("ref: "):
            return content[5:]
        return None

    @property
    def head_commit_sha(self) -> Optional[str]:
        """Get the SHA of the current HEAD commit."""
        head_ref = self.head_ref
        if head_ref:
            ref_path = self.vcx_dir / head_ref
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
        """Update HEAD ref to point to the new commit SHA."""
        head_ref = self.head_ref
        if head_ref:
            ref_path = self.vcx_dir / head_ref
            ref_path.parent.mkdir(parents=True, exist_ok=True)
            ref_path.write_text(f"{commit_sha}\n", encoding="utf-8")
        else:
            (self.vcx_dir / "HEAD").write_text(f"{commit_sha}\n", encoding="utf-8")

    def get_head_tree_entries(self) -> Dict[str, TreeEntry]:
        """Return dict of path -> TreeEntry for the current HEAD commit."""
        commit_sha = self.head_commit_sha
        if not commit_sha:
            return {}
        try:
            commit = self.store.read_commit(commit_sha)
            entries = self.store.read_tree(commit.tree_sha)
            return {e.path: e for e in entries}
        except Exception:
            return {}

    def add(self, paths: List[str | Path]) -> List[str]:
        """Add files to staging index and store blobs."""
        staged: List[str] = []
        for p in paths:
            target = (self.root / p).resolve()
            if not target.exists():
                # Check if it was deleted from disk
                rel = str(Path(p))
                if rel in self.index:
                    self.index.remove(rel)
                    staged.append(rel)
                continue

            if target.is_dir():
                for root, dirs, files in os.walk(target):
                    dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]
                    for f in files:
                        file_path = Path(root) / f
                        rel_path = str(file_path.relative_to(self.root))
                        self._stage_file(file_path, rel_path)
                        staged.append(rel_path)
            else:
                rel_path = str(target.relative_to(self.root))
                self._stage_file(target, rel_path)
                staged.append(rel_path)

        self.index.write()
        return staged

    def _stage_file(self, full_path: Path, rel_path: str) -> None:
        content = full_path.read_bytes()
        sha = self.store.write_blob(content)
        stat = full_path.stat()
        mode = FileMode.EXECUTABLE.value if os.access(full_path, os.X_OK) else FileMode.REGULAR.value
        f_type = detect_file_type(full_path, content)

        self.index.add(
            IndexEntry(
                path=rel_path,
                sha=sha,
                size=len(content),
                mtime=stat.st_mtime,
                mode=mode,
                file_type=f_type,
            )
        )

    def status(self) -> Dict[str, Any]:
        """Compare HEAD vs Index vs Working Directory."""
        head_entries = self.get_head_tree_entries()
        index_entries = {e.path: e for e in self.index.entries()}

        staged_changes: List[Dict[str, str]] = []
        unstaged_changes: List[Dict[str, str]] = []
        untracked_files: List[Dict[str, str]] = []

        # 1. Staged vs HEAD
        for path, idx_entry in index_entries.items():
            if path not in head_entries:
                staged_changes.append({"path": path, "type": "new", "file_type": idx_entry.file_type})
            elif head_entries[path].sha != idx_entry.sha:
                staged_changes.append({"path": path, "type": "modified", "file_type": idx_entry.file_type})

        for path, head_entry in head_entries.items():
            if path not in index_entries:
                staged_changes.append({"path": path, "type": "deleted", "file_type": head_entry.file_type})

        # 2. Working Tree vs Index
        scanned_files = self._scan_working_tree()
        for rel_path in scanned_files:
            full_path = self.root / rel_path
            if rel_path in index_entries:
                stat = full_path.stat()
                idx_entry = index_entries[rel_path]
                if stat.st_size != idx_entry.size or stat.st_mtime != idx_entry.mtime:
                    content = full_path.read_bytes()
                    disk_sha = self.store.hash_data(ObjectType.BLOB, content)[0]
                    if disk_sha != idx_entry.sha:
                        unstaged_changes.append(
                            {"path": rel_path, "type": "modified", "file_type": idx_entry.file_type}
                        )
            else:
                f_type = detect_file_type(full_path)
                untracked_files.append({"path": rel_path, "type": "untracked", "file_type": f_type})

        for path, idx_entry in index_entries.items():
            if path not in scanned_files:
                unstaged_changes.append(
                    {"path": path, "type": "deleted", "file_type": idx_entry.file_type}
                )

        return {
            "staged": staged_changes,
            "unstaged": unstaged_changes,
            "untracked": untracked_files,
            "branch": self.head_ref.replace("refs/heads/", "") if self.head_ref else "detached",
        }

    def _scan_working_tree(self) -> Set[str]:
        results: Set[str] = set()
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]
            for f in files:
                p = Path(root) / f
                rel = str(p.relative_to(self.root))
                results.add(rel)
        return results

    def commit(
        self,
        message: Optional[str] = None,
        auto: bool = False,
        author: str = "VCX Developer <dev@vcx.local>",
    ) -> Tuple[str, Commit]:
        """Commit staged files, optionally invoking Semantic Differ Agent for commit message."""
        head_entries = self.get_head_tree_entries()
        index_entries = self.index.entries()
        if not index_entries:
            raise ValueError("No changes added to commit (staging index is empty)")

        # Generate semantic diff if auto or no message provided
        semantic_delta_meta: Optional[Dict[str, Any]] = None
        if auto or not message:
            agent_outputs: List[DifferOutput] = []
            for entry in index_entries:
                old_sha = head_entries[entry.path].sha if entry.path in head_entries else None
                old_bytes = self.store.read_blob(old_sha) if old_sha else None
                new_bytes = self.store.read_blob(entry.sha)

                payload = self.delta_engine.analyze_change(
                    entry.path, old_bytes, new_bytes, forced_file_type=entry.file_type
                )
                output = self.agent.analyze(payload.to_dict())
                agent_outputs.append(output)

            if agent_outputs:
                first = agent_outputs[0]
                message = first.action_summary
                all_technical_deltas = []
                all_tags = set()
                intents = []
                for o in agent_outputs:
                    all_technical_deltas.extend(o.technical_delta)
                    all_tags.update(o.tags)
                    intents.append(o.inferred_intent)

                semantic_delta_meta = {
                    "action_summary": message,
                    "technical_delta": all_technical_deltas,
                    "inferred_intent": intents[0] if intents else "",
                    "tags": sorted(list(all_tags)),
                }

        # Build tree entries
        tree_entries = [
            TreeEntry(
                mode=e.mode,
                path=e.path,
                sha=e.sha,
                file_type=e.file_type,
            )
            for e in index_entries
        ]
        tree_sha = self.store.write_tree(tree_entries)

        parent_shas = [self.head_commit_sha] if self.head_commit_sha else []
        commit_sha = self.store.write_commit(
            tree_sha=tree_sha,
            parent_shas=parent_shas,
            message=message or "Commit changes",
            author=author,
            semantic_delta=semantic_delta_meta,
        )

        self.update_head(commit_sha)
        commit = self.store.read_commit(commit_sha)
        return commit_sha, commit

    def log(self, limit: int = 20) -> List[Tuple[str, Commit]]:
        """Walk commit history starting from HEAD."""
        commits: List[Tuple[str, Commit]] = []
        curr_sha = self.head_commit_sha
        visited = set()

        while curr_sha and len(commits) < limit and curr_sha not in visited:
            visited.add(curr_sha)
            try:
                commit = self.store.read_commit(curr_sha)
                commits.append((curr_sha, commit))
                curr_sha = commit.parent_shas[0] if commit.parent_shas else None
            except Exception:
                break

        return commits
