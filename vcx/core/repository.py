"""Core Repository implementation for VCX."""

from __future__ import annotations
import fnmatch
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from vcx.agent.schemas import DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.core.config import ConfigManager
from vcx.core.index import Index
from vcx.core.object_store import ObjectStore
from vcx.core.types import Commit, FileChangeType, FileMode, IndexEntry, MergeConflict, MergeResult, ObjectType, TreeEntry
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type
from vcx.diff.merger import SemanticMerger


class Repository:
    IGNORE_DIRS = {".vcx", ".git", ".venv", "__pycache__", "build", "dist", ".pytest_cache", ".idea", ".vscode"}

    def __init__(self, root_dir: Path | str):
        self.root = Path(root_dir).resolve()
        self.vcx_dir = self.root / ".vcx"
        self.store = ObjectStore(self.root)
        self.index = Index(self.root)
        self.delta_engine = DeltaEngine()
        self.agent = SemanticDifferAgent()
        self.config = ConfigManager(self.root)

    @property
    def remotes(self):
        from vcx.remote.transport import RemoteManager
        return RemoteManager(self.root)

    def _collect_reachable_shas(self, root_shas: List[str]) -> Set[str]:
        """Collect all reachable commit, tree, and blob SHAs from a list of commit SHAs."""
        reachable: Set[str] = set()
        queue = list(root_shas)
        visited_commits = set()

        while queue:
            c_sha = queue.pop(0)
            if c_sha in visited_commits:
                continue
            visited_commits.add(c_sha)
            reachable.add(c_sha)
            try:
                commit = self.store.read_commit(c_sha)
                queue.extend(commit.parent_shas)

                tree_queue = [commit.tree_sha]
                while tree_queue:
                    t_sha = tree_queue.pop(0)
                    reachable.add(t_sha)
                    try:
                        entries = self.store.read_tree(t_sha)
                        for e in entries:
                            reachable.add(e.sha)
                            if e.obj_type == "tree" or e.mode == FileMode.DIRECTORY.value:
                                tree_queue.append(e.sha)
                    except Exception:
                        pass
            except Exception:
                pass
        return reachable

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
        """Return dict of path -> TreeEntry for the current HEAD commit (recursively flattened)."""
        commit_sha = self.head_commit_sha
        if not commit_sha:
            return {}
        try:
            commit = self.store.read_commit(commit_sha)
            return self.store.flatten_tree(commit.tree_sha)
        except Exception:
            return {}

    def _sanitize_path(self, path_str: str | Path) -> str:
        """Sanitize path and ensure it is strictly confined within the repository root."""
        raw = str(path_str).strip()
        if os.path.isabs(raw) or raw.startswith("/") or raw.startswith("\\"):
            raise ValueError(f"Path traversal detected (absolute path not permitted): {path_str}")
        norm = os.path.normpath(raw)
        if norm.startswith("..") or norm == "..":
            raise ValueError(f"Path traversal detected (directory escape): {path_str}")
        resolved = (self.root / norm).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"Path escapes repository root: {path_str}")
        return str(resolved.relative_to(self.root))

    def add(self, paths: List[str | Path]) -> List[str]:
        """Add files to staging index and store blobs."""
        staged: List[str] = []
        for p in paths:
            try:
                target = (self.root / p).resolve()
                if not target.is_relative_to(self.root):
                    continue
            except Exception:
                continue

            if not target.exists():
                # Handle deleted file
                try:
                    rel = str(target.relative_to(self.root))
                    if rel in self.index:
                        self.index.remove(rel)
                        staged.append(rel)
                except ValueError:
                    pass
                continue

            if target.is_dir():
                dir_rel = str(target.relative_to(self.root))
                found_in_dir = set()
                patterns = self._load_ignore_patterns()
                for root, dirs, files in os.walk(target):
                    dirs[:] = [
                        d for d in dirs
                        if d not in self.IGNORE_DIRS
                        and not self._is_ignored(str((Path(root) / d).relative_to(self.root)), is_dir=True, patterns=patterns)
                    ]
                    for f in files:
                        file_path = Path(root) / f
                        rel_path = str(file_path.relative_to(self.root))
                        if self._is_ignored(rel_path, is_dir=False, patterns=patterns):
                            continue
                        found_in_dir.add(rel_path)
                        self._stage_file(file_path, rel_path)
                        staged.append(rel_path)

                # Prune files deleted from disk under this directory
                for ie in self.index.entries():
                    prefix = dir_rel if dir_rel != "." else ""
                    if not prefix or ie.path.startswith(prefix + "/"):
                        if ie.path not in found_in_dir and (not (self.root / ie.path).exists() or self._is_ignored(ie.path, patterns=patterns)):
                            self.index.remove(ie.path)
                            staged.append(ie.path)
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
            if path not in scanned_files and not (self.root / path).exists():
                unstaged_changes.append(
                    {"path": path, "type": "deleted", "file_type": idx_entry.file_type}
                )

        return {
            "staged": staged_changes,
            "unstaged": unstaged_changes,
            "untracked": untracked_files,
            "branch": self.head_ref.replace("refs/heads/", "") if self.head_ref else "detached",
        }

    def _load_ignore_patterns(self) -> List[str]:
        patterns: List[str] = []
        ignore_file = self.root / ".vcxignore"
        if ignore_file.exists():
            try:
                for line in ignore_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
            except Exception:
                pass
        return patterns

    def _is_ignored(self, rel_path: str, is_dir: bool = False, patterns: Optional[List[str]] = None) -> bool:
        parts = rel_path.split("/")
        if any(p in self.IGNORE_DIRS for p in parts):
            return True
        if patterns is None:
            patterns = self._load_ignore_patterns()
        for pat in patterns:
            if pat.endswith("/"):
                pat_clean = pat.rstrip("/")
                if is_dir and (fnmatch.fnmatch(rel_path, pat_clean) or fnmatch.fnmatch(parts[-1], pat_clean)):
                    return True
                if any(fnmatch.fnmatch(p, pat_clean) for p in parts[:-1]):
                    return True
            else:
                if fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(parts[-1], pat):
                    return True
        return False

    def _scan_working_tree(self) -> Set[str]:
        results: Set[str] = set()
        patterns = self._load_ignore_patterns()
        for root, dirs, files in os.walk(self.root):
            dirs[:] = [
                d for d in dirs
                if not self._is_ignored(str((Path(root) / d).relative_to(self.root)), is_dir=True, patterns=patterns)
            ]
            for f in files:
                p = Path(root) / f
                rel = str(p.relative_to(self.root))
                if not self._is_ignored(rel, is_dir=False, patterns=patterns):
                    results.add(rel)
        return results

    def commit(
        self,
        message: Optional[str] = None,
        auto: bool = False,
        author: Optional[str] = None,
    ) -> Tuple[str, Commit]:
        """Commit staged files, optionally invoking Semantic Differ Agent for commit message."""
        if not author:
            u_name = self.config.get("user.name")
            u_email = self.config.get("user.email")
            if u_name and u_email:
                author = f"{u_name} <{u_email}>"
            elif u_name:
                author = f"{u_name} <{u_name.lower().replace(' ', '')}@vcx.local>"
            else:
                author = "VCX Developer <dev@vcx.local>"
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
                # Skip unchanged files during auto commit
                if old_sha == entry.sha:
                    continue
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

        # Build hierarchical Merkle tree structure
        tree_sha = self.store.build_hierarchical_tree(index_entries)

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

    def create_branch(self, name: str) -> None:
        """Create a new branch pointing to current HEAD commit."""
        head_sha = self.head_commit_sha
        if not head_sha:
            raise ValueError("Cannot create branch: repository has no commits yet")
        branch_file = self.vcx_dir / "refs" / "heads" / name
        if branch_file.exists():
            raise ValueError(f"Branch '{name}' already exists")
        branch_file.parent.mkdir(parents=True, exist_ok=True)
        branch_file.write_text(f"{head_sha}\n", encoding="utf-8")

    def list_branches(self) -> List[Tuple[str, bool]]:
        """List all branch names and whether they are active."""
        heads_dir = self.vcx_dir / "refs" / "heads"
        if not heads_dir.exists():
            return []
        current = self.head_ref.replace("refs/heads/", "") if self.head_ref else None
        branches = []
        for f in sorted(heads_dir.iterdir()):
            if f.is_file():
                branches.append((f.name, f.name == current))
        return branches

    def checkout(self, target: str) -> None:
        """Switch branches or checkout commit, updating working tree and index."""
        branch_file = self.vcx_dir / "refs" / "heads" / target
        if branch_file.exists():
            commit_sha = branch_file.read_text(encoding="utf-8").strip()
            (self.vcx_dir / "HEAD").write_text(f"ref: refs/heads/{target}\n", encoding="utf-8")
        else:
            commit_sha = target
            (self.vcx_dir / "HEAD").write_text(f"{commit_sha}\n", encoding="utf-8")

        commit = self.store.read_commit(commit_sha)
        target_entries = self.store.flatten_tree(commit.tree_sha)

        # Clear index and stage target entries
        self.index.clear()
        for rel_path, entry in target_entries.items():
            full_path = self.root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            blob_content = self.store.read_blob(entry.sha)
            full_path.write_bytes(blob_content)
            stat = full_path.stat()
            self.index.add(
                IndexEntry(
                    path=rel_path,
                    sha=entry.sha,
                    size=len(blob_content),
                    mtime=stat.st_mtime,
                    mode=entry.mode,
                    file_type=entry.file_type,
                )
            )
        self.index.write()

    def merge(
        self,
        target_branch: str,
        author: str = "VCX Semantic Merger <merger@vcx.local>",
    ) -> MergeResult:
        """Perform 3-way semantic merge between current branch (ours) and target_branch (theirs)."""
        branch_file = self.vcx_dir / "refs" / "heads" / target_branch
        if not branch_file.exists():
            raise ValueError(f"Branch '{target_branch}' not found")

        theirs_sha = branch_file.read_text(encoding="utf-8").strip()
        ours_sha = self.head_commit_sha
        if not ours_sha:
            raise ValueError("Current branch has no commits")

        if ours_sha == theirs_sha:
            return MergeResult(success=True, semantic_resolutions=["Already up to date"])

        # Find merge base (common ancestor)
        base_sha = self._find_merge_base(ours_sha, theirs_sha)

        base_entries = {}
        if base_sha:
            base_commit = self.store.read_commit(base_sha)
            base_entries = self.store.flatten_tree(base_commit.tree_sha)

        ours_entries = self.get_head_tree_entries()
        theirs_commit = self.store.read_commit(theirs_sha)
        theirs_entries = self.store.flatten_tree(theirs_commit.tree_sha)

        merger = SemanticMerger()
        all_paths = set(base_entries.keys()) | set(ours_entries.keys()) | set(theirs_entries.keys())

        merged_shas: Dict[str, str] = {}
        conflicts: List[MergeConflict] = []
        resolutions: List[str] = []

        for p in sorted(all_paths):
            b_e = base_entries.get(p)
            o_e = ours_entries.get(p)
            t_e = theirs_entries.get(p)

            # 1. Unchanged in ours, modified in theirs -> fast-forward file to theirs
            if (b_e and o_e and b_e.sha == o_e.sha) or (not b_e and not o_e):
                if t_e:
                    merged_shas[p] = t_e.sha
                    self._write_worktree_blob(p, t_e.sha, t_e.mode, t_e.file_type)
                continue

            # 2. Unchanged in theirs, modified in ours -> keep ours
            if (b_e and t_e and b_e.sha == t_e.sha) or (not b_e and not t_e):
                if o_e:
                    merged_shas[p] = o_e.sha
                continue

            # 3. Identical changes on both branches
            if o_e and t_e and o_e.sha == t_e.sha:
                merged_shas[p] = o_e.sha
                continue

            # 4. Modified on both sides -> 3-way semantic merge!
            b_bytes = self.store.read_blob(b_e.sha) if b_e else None
            o_bytes = self.store.read_blob(o_e.sha) if o_e else b""
            t_bytes = self.store.read_blob(t_e.sha) if t_e else b""
            f_type = (o_e or t_e or b_e).file_type

            success, merged_bytes, notes, conflict = merger.merge(
                b_bytes, o_bytes, t_bytes, p, f_type
            )
            if success:
                new_sha = self.store.write_blob(merged_bytes)
                merged_shas[p] = new_sha
                mode = (o_e or t_e).mode
                self._write_worktree_blob(p, new_sha, mode, f_type)
                resolutions.extend([f"{p}: {note}" for note in notes])
            else:
                if conflict:
                    conflicts.append(conflict)

        if conflicts:
            return MergeResult(
                success=False,
                merged_shas=merged_shas,
                conflicts=conflicts,
                semantic_resolutions=resolutions,
            )

        # Successful merge: commit with two parents [ours, theirs]
        self.index.write()
        tree_sha = self.store.build_hierarchical_tree(self.index.entries())
        summary_msg = f"Merge branch '{target_branch}'"
        commit_sha = self.store.write_commit(
            tree_sha=tree_sha,
            parent_shas=[ours_sha, theirs_sha],
            message=summary_msg,
            author=author,
            semantic_delta={
                "action_summary": summary_msg[:49],
                "technical_delta": resolutions or [f"Merged changes from {target_branch}"],
                "inferred_intent": f"Integrate branch '{target_branch}' features into {self.head_ref or 'HEAD'}.",
                "tags": ["merge", "multi-domain"],
            },
        )
        self.update_head(commit_sha)
        return MergeResult(
            success=True,
            merged_shas=merged_shas,
            conflicts=[],
            semantic_resolutions=resolutions,
        )

    def _write_worktree_blob(self, rel_path: str, blob_sha: str, mode: str, file_type: str) -> None:
        full_path = self.root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.store.read_blob(blob_sha)
        full_path.write_bytes(content)
        stat = full_path.stat()
        self.index.add(
            IndexEntry(
                path=rel_path,
                sha=blob_sha,
                size=len(content),
                mtime=stat.st_mtime,
                mode=mode,
                file_type=file_type,
            )
        )

    def _find_merge_base(self, sha_a: str, sha_b: str) -> Optional[str]:
        """Find common ancestor commit using BFS."""
        ancestors_a = set()
        queue = [sha_a]
        while queue:
            curr = queue.pop(0)
            if curr not in ancestors_a:
                ancestors_a.add(curr)
                try:
                    c = self.store.read_commit(curr)
                    queue.extend(c.parent_shas)
                except Exception:
                    pass

        queue_b = [sha_b]
        visited_b = set()
        while queue_b:
            curr = queue_b.pop(0)
            if curr in ancestors_a:
                return curr
            if curr not in visited_b:
                visited_b.add(curr)
                try:
                    c = self.store.read_commit(curr)
                    queue_b.extend(c.parent_shas)
                except Exception:
                    pass
        return None

    def gc(self) -> Dict[str, Any]:
        """Collect all reachable objects from all refs and execute garbage collection."""
        reachable: Set[str] = set()

        # Find all branch refs
        ref_shas = []
        heads_dir = self.vcx_dir / "refs" / "heads"
        if heads_dir.exists():
            for f in heads_dir.iterdir():
                if f.is_file():
                    try:
                        ref_shas.append(f.read_text(encoding="utf-8").strip())
                    except Exception:
                        pass

        if self.head_commit_sha:
            ref_shas.append(self.head_commit_sha)

        # Walk all commits and collect reachable trees & blobs
        visited_commits = set()
        for ref_sha in set(ref_shas):
            queue = [ref_sha]
            while queue:
                c_sha = queue.pop(0)
                if c_sha in visited_commits:
                    continue
                visited_commits.add(c_sha)
                reachable.add(c_sha)
                try:
                    commit = self.store.read_commit(c_sha)
                    queue.extend(commit.parent_shas)

                    # Collect tree objects
                    tree_queue = [commit.tree_sha]
                    while tree_queue:
                        t_sha = tree_queue.pop(0)
                        reachable.add(t_sha)
                        try:
                            entries = self.store.read_tree(t_sha)
                            for e in entries:
                                reachable.add(e.sha)
                                if e.obj_type == "tree" or e.mode == FileMode.DIRECTORY.value:
                                    tree_queue.append(e.sha)
                        except Exception:
                            pass
                except Exception:
                    pass

        return self.store.gc(reachable)

    def create_tag(self, name: str, target_sha: Optional[str] = None) -> str:
        """Create a tag pointing to a commit SHA (defaults to HEAD)."""
        sha = target_sha or self.head_commit_sha
        if not sha:
            raise ValueError("Cannot create tag: no commits exist in repository")
        if not self.store.has_object(sha):
            raise ValueError(f"Object {sha} does not exist in store")
        tag_file = self.vcx_dir / "refs" / "tags" / name
        tag_file.parent.mkdir(parents=True, exist_ok=True)
        tag_file.write_text(f"{sha}\n", encoding="utf-8")
        return sha

    def list_tags(self) -> List[str]:
        """List all repository tags."""
        tags_dir = self.vcx_dir / "refs" / "tags"
        if not tags_dir.exists():
            return []
        return sorted([f.name for f in tags_dir.iterdir() if f.is_file()])

    def resolve_ref(self, ref_or_sha: str) -> Optional[str]:
        """Resolve a branch, tag, HEAD, or SHA prefix to a full SHA."""
        clean = ref_or_sha.strip()
        if clean == "HEAD":
            return self.head_commit_sha

        # Branch
        b_file = self.vcx_dir / "refs" / "heads" / clean
        if b_file.exists():
            return b_file.read_text().strip()

        # Tag
        t_file = self.vcx_dir / "refs" / "tags" / clean
        if t_file.exists():
            return t_file.read_text().strip()

        # Direct SHA prefix match
        if len(clean) >= 4:
            for sha in self.store.list_loose_objects():
                if sha.startswith(clean):
                    return sha
            for reader in self.store.pack_readers:
                for sha in reader.index.keys():
                    if sha.startswith(clean):
                        return sha
        return None

    def reset(self, paths: Optional[List[str | Path]] = None) -> List[str]:
        """Reset staging index entries to match HEAD, unstaging changes."""
        head_entries = self.get_head_tree_entries()
        reset_paths: List[str] = []

        if paths:
            for p in paths:
                rel = self._sanitize_path(p)
                if rel in head_entries:
                    he = head_entries[rel]
                    self.index.add(
                        IndexEntry(
                            path=rel,
                            sha=he.sha,
                            size=0,
                            mtime=0.0,
                            mode=he.mode,
                            file_type=he.file_type,
                        )
                    )
                else:
                    if rel in self.index:
                        self.index.remove(rel)
                reset_paths.append(rel)
        else:
            self.index.clear()
            for rel, he in head_entries.items():
                self.index.add(
                    IndexEntry(
                        path=rel,
                        sha=he.sha,
                        size=0,
                        mtime=0.0,
                        mode=he.mode,
                        file_type=he.file_type,
                    )
                )
            reset_paths = list(head_entries.keys())

        self.index.write()
        return reset_paths
