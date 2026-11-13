"""Smart Remote Transfer Protocol and Network Transport for VCX.

Supports cloning, fetching, pushing, and remote synchronization across local
paths, filesystems, and HTTP network endpoints.
"""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, List, Optional, Set, Tuple
import urllib.error
import urllib.request

from vcx.core.object_store import ObjectStore
from vcx.core.pack import PackReader, PackWriter
from vcx.core.repository import Repository
from vcx.core.types import FileMode, ObjectType


class RemoteManager:
    """Manages remote repository URLs in .vcx/remotes.json."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = Path(repo_dir)
        self.remotes_file = self.repo_dir / ".vcx" / "remotes.json"

    def load_remotes(self) -> Dict[str, str]:
        if not self.remotes_file.exists():
            return {}
        try:
            return json.loads(self.remotes_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_remotes(self, remotes: Dict[str, str]) -> None:
        self.remotes_file.parent.mkdir(parents=True, exist_ok=True)
        self.remotes_file.write_text(json.dumps(remotes, indent=2), encoding="utf-8")

    def add(self, name: str, url: str) -> None:
        remotes = self.load_remotes()
        remotes[name] = url
        self.save_remotes(remotes)

    def get(self, name: str) -> Optional[str]:
        return self.load_remotes().get(name)

    def remove(self, name: str) -> None:
        remotes = self.load_remotes()
        remotes.pop(name, None)
        self.save_remotes(remotes)

    def list_all(self) -> Dict[str, str]:
        return self.load_remotes()


class RemoteTransport:
    """Implements smart push, fetch, and clone operations."""

    @classmethod
    def clone(cls, source_url: str, dest_dir: Path | str) -> Repository:
        """Clone a remote repository (local path or HTTP) into dest_dir."""
        dest = Path(dest_dir).resolve()
        if dest.exists() and any(dest.iterdir()):
            raise ValueError(f"Destination '{dest}' already exists and is not empty")

        # 1. Local Filesystem / Path Clone
        if not source_url.startswith(("http://", "https://")):
            src_path = Path(source_url.replace("file://", "")).resolve()
            if not (src_path / ".vcx").exists():
                raise FileNotFoundError(f"Source repository not found at {src_path}")

            src_repo = Repository(src_path)
            head_sha = src_repo.head_commit_sha
            if not head_sha:
                raise ValueError("Source repository has no commits to clone")

            dest_repo = Repository.init(dest)
            dest_repo.remotes.add("origin", str(src_path))

            # Transfer all reachable objects into a packfile
            reachable = src_repo._collect_reachable_shas([head_sha])
            loose_and_packed = []
            for sha in reachable:
                obj_type, data = src_repo.store.read_object(sha)
                loose_and_packed.append((sha, obj_type, data))

            if loose_and_packed:
                writer = PackWriter(dest_repo.store.pack_dir)
                writer.write_pack(loose_and_packed)
                dest_repo.store._pack_readers = None

            # Copy head ref and branch
            active_branch = src_repo.head_ref.replace("refs/heads/", "") if src_repo.head_ref else "main"
            (dest_repo.vcx_dir / "refs" / "heads" / active_branch).write_text(f"{head_sha}\n")
            (dest_repo.vcx_dir / "HEAD").write_text(f"ref: refs/heads/{active_branch}\n")

            # Check out working tree
            dest_repo.checkout(active_branch)
            return dest_repo

        # 2. HTTP Clone
        dest_repo = Repository.init(dest)
        dest_repo.remotes.add("origin", source_url)

        # GET /info/refs
        refs_url = source_url.rstrip("/") + "/info/refs"
        req = urllib.request.Request(refs_url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        remote_refs = data.get("refs", {})
        head_sha = data.get("HEAD")
        active_branch = data.get("active_branch", "main")

        if not head_sha:
            raise ValueError("Remote repository has no commits to clone")

        # POST /vcx-upload-pack
        upload_url = source_url.rstrip("/") + "/vcx-upload-pack"
        req_body = json.dumps({"want": [head_sha], "have": []}).encode("utf-8")
        pack_req = urllib.request.Request(
            upload_url, data=req_body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(pack_req, timeout=30) as resp:
            pack_data = resp.read()

        # Ingest pack into destination
        import hashlib
        pack_hash = hashlib.sha256(pack_data).hexdigest()
        dest_pack = dest_repo.store.pack_dir / f"pack-{pack_hash[:16]}.pack"
        dest_pack.write_bytes(pack_data)

        # Build index for received pack
        dest_repo.store._rebuild_pack_index(dest_pack)
        dest_repo.store._pack_readers = None

        (dest_repo.vcx_dir / "refs" / "heads" / active_branch).write_text(f"{head_sha}\n")
        (dest_repo.vcx_dir / "HEAD").write_text(f"ref: refs/heads/{active_branch}\n")
        dest_repo.checkout(active_branch)
        return dest_repo

    @classmethod
    def fetch(cls, repo: Repository, remote_name: str = "origin") -> Dict[str, str]:
        """Fetch remote refs and transfer missing objects into remote-tracking refs."""
        remote_url = repo.remotes.get(remote_name)
        if not remote_url:
            raise ValueError(f"Remote '{remote_name}' not configured")

        if not remote_url.startswith(("http://", "https://")):
            src_path = Path(remote_url.replace("file://", "")).resolve()
            src_repo = Repository(src_path)

            updated_refs = {}
            for branch, _ in src_repo.list_branches():
                b_file = src_repo.vcx_dir / "refs" / "heads" / branch
                if not b_file.exists():
                    continue
                sha = b_file.read_text().strip()

                # Transfer missing objects
                reachable = src_repo._collect_reachable_shas([sha])
                missing = [s for s in reachable if not repo.store.has_object(s)]
                if missing:
                    to_pack = [
                        (s, *src_repo.store.read_object(s))
                        for s in missing
                    ]
                    writer = PackWriter(repo.store.pack_dir)
                    writer.write_pack(to_pack)
                    repo.store._pack_readers = None

                # Update remote-tracking ref
                rem_ref = repo.vcx_dir / "refs" / "remotes" / remote_name / branch
                rem_ref.parent.mkdir(parents=True, exist_ok=True)
                rem_ref.write_text(f"{sha}\n")
                updated_refs[branch] = sha

            return updated_refs

        # HTTP Fetch
        refs_url = remote_url.rstrip("/") + "/info/refs"
        with urllib.request.urlopen(refs_url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        remote_refs = data.get("refs", {})
        wanted_shas = [sha for sha in remote_refs.values() if not repo.store.has_object(sha)]

        if wanted_shas:
            upload_url = remote_url.rstrip("/") + "/vcx-upload-pack"
            req_body = json.dumps({"want": wanted_shas, "have": []}).encode("utf-8")
            pack_req = urllib.request.Request(
                upload_url, data=req_body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(pack_req, timeout=30) as resp:
                pack_data = resp.read()

            import hashlib
            pack_hash = hashlib.sha256(pack_data).hexdigest()
            dest_pack = repo.store.pack_dir / f"pack-{pack_hash[:16]}.pack"
            dest_pack.write_bytes(pack_data)
            repo.store._rebuild_pack_index(dest_pack)
            repo.store._pack_readers = None

        updated_refs = {}
        for branch, sha in remote_refs.items():
            rem_ref = repo.vcx_dir / "refs" / "remotes" / remote_name / branch
            rem_ref.parent.mkdir(parents=True, exist_ok=True)
            rem_ref.write_text(f"{sha}\n")
            updated_refs[branch] = sha

        return updated_refs

    @classmethod
    def push(
        cls,
        repo: Repository,
        remote_name: str = "origin",
        branch: Optional[str] = None,
        force: bool = False,
    ) -> str:
        """Push local branch commits to the remote repository."""
        remote_url = repo.remotes.get(remote_name)
        if not remote_url:
            raise ValueError(f"Remote '{remote_name}' not configured")

        active_branch = branch or (repo.head_ref.replace("refs/heads/", "") if repo.head_ref else "main")
        local_head_sha = repo.head_commit_sha
        if not local_head_sha:
            raise ValueError("No local commits to push")

        # 1. Local Filesystem Push
        if not remote_url.startswith(("http://", "https://")):
            remote_path = Path(remote_url.replace("file://", "")).resolve()
            dest_repo = Repository(remote_path)

            dest_branch_file = dest_repo.vcx_dir / "refs" / "heads" / active_branch
            remote_old_sha = dest_branch_file.read_text().strip() if dest_branch_file.exists() else None

            # Fast-forward check unless force
            if remote_old_sha and not force:
                ancestor = repo._find_merge_base(local_head_sha, remote_old_sha)
                if ancestor != remote_old_sha:
                    raise ValueError(
                        f"Non-fast-forward push rejected. Run 'vcx fetch {remote_name}' and merge first."
                    )

            # Transfer missing objects
            local_reachable = repo._collect_reachable_shas([local_head_sha])
            missing = [s for s in local_reachable if not dest_repo.store.has_object(s)]

            if missing:
                to_pack = [(s, *repo.store.read_object(s)) for s in missing]
                writer = PackWriter(dest_repo.store.pack_dir)
                writer.write_pack(to_pack)
                dest_repo.store._pack_readers = None

            # Update remote branch ref
            dest_branch_file.parent.mkdir(parents=True, exist_ok=True)
            dest_branch_file.write_text(f"{local_head_sha}\n")
            return f"Successfully pushed {active_branch} -> {local_head_sha[:8]}"

        # 2. HTTP Push via Resumable Transfer Protocol
        return cls.push_resumable(
            repo=repo,
            remote_name=remote_name,
            branch=active_branch,
            force=force,
        )

    @classmethod
    def push_resumable(
        cls,
        repo: Repository,
        remote_name: str = "origin",
        branch: Optional[str] = None,
        force: bool = False,
        chunk_size: int = 512 * 1024,
        max_retries: int = 5,
        simulate_interrupt_after_bytes: Optional[int] = None,
    ) -> str:
        """Push local commits to remote with automatic resume upon network interruption."""
        remote_url = repo.remotes.get(remote_name)
        if not remote_url:
            raise ValueError(f"Remote '{remote_name}' not configured")

        active_branch = branch or (repo.head_ref.replace("refs/heads/", "") if repo.head_ref else "main")
        local_head_sha = repo.head_commit_sha
        if not local_head_sha:
            raise ValueError("No local commits to push")

        # Determine missing objects and package packfile
        local_reachable = repo._collect_reachable_shas([local_head_sha])
        to_pack = [(s, *repo.store.read_object(s)) for s in local_reachable]

        tmp_writer = PackWriter(repo.store.pack_dir)
        pack_path, idx_path, p_hash = tmp_writer.write_pack(to_pack)
        pack_bytes = pack_path.read_bytes()

        # Clean up local temporary packfiles
        pack_path.unlink()
        idx_path.unlink()

        total_size = len(pack_bytes)
        pack_hash = hashlib.sha256(pack_bytes).hexdigest()

        # Initialize resumable session
        init_url = remote_url.rstrip("/") + "/vcx-upload-session/init"
        init_payload = json.dumps({
            "branch": active_branch,
            "commit": local_head_sha,
            "total_size": total_size,
            "pack_hash": pack_hash,
            "force": force,
        }).encode("utf-8")

        req_init = urllib.request.Request(
            init_url,
            data=init_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req_init, timeout=20) as resp:
            init_res = json.loads(resp.read().decode("utf-8"))

        session_id = init_res["session_id"]
        status_url = f"{remote_url.rstrip('/')}/vcx-upload-session/status?session_id={session_id}"
        chunk_url = f"{remote_url.rstrip('/')}/vcx-upload-session/chunk?session_id={session_id}"

        offset = 0
        has_simulated_interrupt = False

        while offset < total_size:
            end = min(offset + chunk_size, total_size)
            chunk = pack_bytes[offset:end]

            # Allow simulating network interruption for test verification
            if (
                simulate_interrupt_after_bytes is not None
                and offset >= simulate_interrupt_after_bytes
                and not has_simulated_interrupt
            ):
                has_simulated_interrupt = True
                # Query remote server status to simulate reconnect and resume
                req_stat = urllib.request.Request(status_url)
                with urllib.request.urlopen(req_stat, timeout=10) as s_resp:
                    stat_data = json.loads(s_resp.read().decode("utf-8"))
                    offset = stat_data.get("received_bytes", offset)
                continue

            headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {offset}-{end - 1}/{total_size}",
                "X-VCX-Session-ID": session_id,
            }

            retries = 0
            while True:
                try:
                    req_chunk = urllib.request.Request(chunk_url, data=chunk, headers=headers)
                    with urllib.request.urlopen(req_chunk, timeout=30) as resp:
                        res_data = json.loads(resp.read().decode("utf-8"))
                        if resp.status == 201 or res_data.get("status") == "completed":
                            return res_data.get("message", f"Successfully pushed {active_branch}")
                        offset = res_data.get("received_bytes", end)
                        break
                except urllib.error.HTTPError as e:
                    if e.code == 409:
                        # Offset mismatch: server reports current received bytes
                        err_data = json.loads(e.read().decode("utf-8"))
                        offset = err_data.get("expected_offset", offset)
                        break
                    retries += 1
                    if retries > max_retries:
                        raise
                    time.sleep(0.05 * retries)
                except Exception:
                    retries += 1
                    if retries > max_retries:
                        raise
                    # Query remote server status to recover current progress
                    try:
                        req_stat = urllib.request.Request(status_url)
                        with urllib.request.urlopen(req_stat, timeout=10) as s_resp:
                            stat_data = json.loads(s_resp.read().decode("utf-8"))
                            offset = stat_data.get("received_bytes", offset)
                    except Exception:
                        pass
                    time.sleep(0.05 * retries)

        return f"Successfully pushed {active_branch} -> {local_head_sha[:8]}"
