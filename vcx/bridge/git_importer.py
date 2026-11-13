"""Git to VCX Native Importer and Migration Bridge.

Converts an existing Git repository (commits, trees, blobs, branches, and tags)
into 100% native VCX Content-Addressable Storage (CAS) with Hierarchical Merkle Trees,
domain-aware semantic deltas, and native VCX references.
"""

from __future__ import annotations
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from vcx.core.object_store import ObjectStore
from vcx.core.repository import Repository
from vcx.core.types import Commit, FileMode, IndexEntry, ObjectType, TreeEntry
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type


class GitImporter:
    """Migrates a Git repository into a 100% standalone, native VCX repository."""

    def __init__(self, repo_dir: Path | str):
        self.root = Path(repo_dir).resolve()
        self.git_dir = self.root / ".git"
        if not self.git_dir.exists():
            raise FileNotFoundError(f"No .git directory found at {self.root}")

    def import_to_vcx(self, semantic_enrichment: bool = False) -> Repository:
        """Execute full conversion from Git into native VCX."""
        # 1. Initialize or find VCX repository
        repo = Repository.init(self.root)
        delta_engine = DeltaEngine()

        # 2. Extract Git commit log in chronological order
        # Format: SHA | PARENTS | AUTHOR | TIMESTAMP | SUBJECT
        cmd = [
            "git", "log", "--reverse", "--topo-order",
            "--format=%H%x00%P%x00%an <%ae>%x00%at%x00%B%x00---VCX_COMMIT_END---"
        ]
        proc = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, check=True)
        raw_output = proc.stdout

        git_to_vcx_commits: Dict[str, str] = {}
        commits_data = raw_output.split("---VCX_COMMIT_END---\n")

        for c_block in commits_data:
            c_block = c_block.strip()
            if not c_block:
                continue

            parts = c_block.split("\x00")
            if len(parts) < 5:
                continue

            git_sha = parts[0].strip()
            parent_shas_str = parts[1].strip()
            author = parts[2].strip() or "VCX Developer <dev@vcx.local>"
            timestamp = float(parts[3].strip() or time.time())
            message = parts[4].strip()

            # Map Git parents to their converted VCX parent SHAs
            vcx_parents: List[str] = []
            if parent_shas_str:
                for p_git in parent_shas_str.split():
                    if p_git in git_to_vcx_commits:
                        vcx_parents.append(git_to_vcx_commits[p_git])

            # Get list of files and content at this Git commit
            tree_entries: List[TreeEntry] = []
            ls_cmd = ["git", "ls-tree", "-r", "--full-name", git_sha]
            ls_proc = subprocess.run(ls_cmd, cwd=self.root, capture_output=True, text=True, check=True)

            for line in ls_proc.stdout.splitlines():
                if not line.strip():
                    continue
                # Format: <mode> <type> <git_sha>\t<rel_path>
                meta_part, rel_path = line.split("\t", 1)
                mode_str, obj_type, blob_git_sha = meta_part.split()

                if obj_type != "blob":
                    continue

                # Read blob data from git
                cat_cmd = ["git", "cat-file", "-p", blob_git_sha]
                cat_proc = subprocess.run(cat_cmd, cwd=self.root, capture_output=True, check=True)
                content = cat_proc.stdout

                # Write to native VCX SHA-256 CAS
                vcx_blob_sha = repo.store.write_blob(content)
                file_type = detect_file_type(Path(rel_path), content)
                vcx_mode = FileMode.EXECUTABLE.value if mode_str == "100755" else FileMode.REGULAR.value

                tree_entries.append(
                    TreeEntry(
                        mode=vcx_mode,
                        path=rel_path,
                        sha=vcx_blob_sha,
                        file_type=file_type,
                        obj_type="blob",
                    )
                )

            # Build hierarchical Merkle tree in native VCX
            vcx_root_tree_sha = repo.store.build_hierarchical_tree(tree_entries)

            # Compute semantic delta if requested
            semantic_meta = None
            if semantic_enrichment and vcx_parents:
                try:
                    # Compare against first parent
                    parent_commit = repo.store.read_commit(vcx_parents[0])
                    parent_tree = repo.store.flatten_tree(parent_commit.tree_sha)
                    current_tree = {e.path: e for e in tree_entries}

                    deltas = []
                    tags = set()
                    for p, entry in current_tree.items():
                        if p not in parent_tree or parent_tree[p].sha != entry.sha:
                            old_b = repo.store.read_blob(parent_tree[p].sha) if p in parent_tree else None
                            new_b = repo.store.read_blob(entry.sha)
                            analyzed = delta_engine.analyze_change(p, old_b, new_b, forced_file_type=entry.file_type)
                            agent_out = repo.agent.analyze(analyzed.to_dict())
                            deltas.extend(agent_out.technical_delta)
                            tags.update(agent_out.tags)

                    if deltas:
                        semantic_meta = {
                            "action_summary": message[:48],
                            "technical_delta": deltas[:5],
                            "inferred_intent": "Migrated from Git history with native VCX semantic analysis.",
                            "tags": sorted(list(tags)) if tags else ["migrated", "git-bridge"],
                        }
                except Exception:
                    pass

            if not semantic_meta:
                semantic_meta = {
                    "action_summary": message[:48] if message else "Git migrated commit",
                    "technical_delta": [f"Migrated commit {git_sha[:8]} from Git repository"],
                    "inferred_intent": "Converted from legacy Git history to native VCX Merkle CAS.",
                    "tags": ["migrated", "git-to-vcx"],
                }

            # Write native VCX commit
            vcx_commit = Commit(
                tree_sha=vcx_root_tree_sha,
                parent_shas=vcx_parents,
                author=author,
                committer=author,
                timestamp=timestamp,
                message=message,
                semantic_delta=semantic_meta,
            )
            vcx_commit_sha = repo.store.write_commit(vcx_commit)
            git_to_vcx_commits[git_sha] = vcx_commit_sha

        # 3. Migrate branches (refs/heads/*)
        branches_cmd = ["git", "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads"]
        b_proc = subprocess.run(branches_cmd, cwd=self.root, capture_output=True, text=True, check=True)
        for line in b_proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            b_name, b_git_sha = parts
            if b_git_sha in git_to_vcx_commits:
                b_file = repo.vcx_dir / "refs" / "heads" / b_name
                b_file.parent.mkdir(parents=True, exist_ok=True)
                b_file.write_text(f"{git_to_vcx_commits[b_git_sha]}\n", encoding="utf-8")

        # 4. Migrate tags (refs/tags/*)
        tags_cmd = ["git", "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/tags"]
        t_proc = subprocess.run(tags_cmd, cwd=self.root, capture_output=True, text=True, check=True)
        for line in t_proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            t_name, t_git_sha = parts
            if t_git_sha in git_to_vcx_commits:
                repo.create_tag(t_name, git_to_vcx_commits[t_git_sha])

        # 5. Determine active branch and set HEAD
        head_proc = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=self.root, capture_output=True, text=True)
        active_branch = head_proc.stdout.strip() if head_proc.returncode == 0 else "main"
        (repo.vcx_dir / "HEAD").write_text(f"ref: refs/heads/{active_branch}\n", encoding="utf-8")

        # 6. Initialize VCX staging index from current working tree
        repo.index.clear()
        scanned = repo._scan_working_tree()
        for rel_path in scanned:
            f_path = repo.root / rel_path
            if f_path.is_file():
                content = f_path.read_bytes()
                sha = repo.store.write_blob(content)
                stat = f_path.stat()
                mode = FileMode.EXECUTABLE.value if os.access(f_path, os.X_OK) else FileMode.REGULAR.value
                f_type = detect_file_type(f_path, content)
                repo.index.add(
                    IndexEntry(
                        path=rel_path,
                        sha=sha,
                        size=len(content),
                        mtime=stat.st_mtime,
                        mode=mode,
                        file_type=f_type,
                    )
                )
        repo.index.write()

        return repo
