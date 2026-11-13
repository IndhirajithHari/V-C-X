"""Lightweight HTTP Server for VCX Repositories (vcx serve).

Supports clone, fetch, push, and Resumable Chunked Uploads for large assets.
"""

from __future__ import annotations
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import shutil
import struct
import threading
from typing import Optional
from urllib.parse import parse_qs, urlparse
import uuid

from vcx.core.pack import PackWriter
from vcx.core.repository import Repository


class VcxRequestHandler(BaseHTTPRequestHandler):
    repo: Repository

    def log_message(self, format: str, *args) -> None:
        # Suppress automatic noisy HTTP access logs to stderr
        pass

    def _send_json(self, status_code: int, data: dict) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/info/refs":
            refs = {}
            for branch, is_active in self.repo.list_branches():
                b_file = self.repo.vcx_dir / "refs" / "heads" / branch
                if b_file.exists():
                    refs[branch] = b_file.read_text().strip()

            active = self.repo.head_ref.replace("refs/heads/", "") if self.repo.head_ref else "main"
            data = {
                "HEAD": self.repo.head_commit_sha,
                "active_branch": active,
                "refs": refs,
            }
            self._send_json(200, data)

        elif path == "/vcx-upload-session/status":
            session_id = query.get("session_id", [None])[0]
            if not session_id:
                self._send_json(400, {"error": "Missing session_id parameter"})
                return

            session_dir = self.repo.vcx_dir / "sessions" / session_id
            meta_file = session_dir / "meta.json"
            part_file = session_dir / "data.part"

            if not session_dir.exists() or not meta_file.exists():
                self._send_json(404, {"error": "Upload session not found or expired"})
                return

            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                received_bytes = part_file.stat().st_size if part_file.exists() else 0
                self._send_json(200, {
                    "session_id": session_id,
                    "received_bytes": received_bytes,
                    "total_size": meta.get("total_size", 0),
                    "status": "active" if received_bytes < meta.get("total_size", 0) else "completed"
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        self._handle_post_or_patch()

    def do_PATCH(self) -> None:
        self._handle_post_or_patch()

    def _handle_post_or_patch(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        content_len = int(self.headers.get("Content-Length", 0))

        if path == "/vcx-upload-pack":
            body = self.rfile.read(content_len).decode("utf-8")
            data = json.loads(body)
            want_shas = data.get("want", [])
            have_shas = set(data.get("have", []))

            # Collect reachable objects for wanted SHAs excluding have SHAs
            reachable = self.repo._collect_reachable_shas(want_shas)
            to_send = [s for s in reachable if s not in have_shas]

            objects = []
            for sha in to_send:
                obj_type, raw = self.repo.store.read_object(sha)
                objects.append((sha, obj_type, raw))

            if not objects:
                self.send_response(204)
                self.end_headers()
                return

            # Package into temp packfile
            writer = PackWriter(self.repo.store.pack_dir)
            pack_path, idx_path, p_hash = writer.write_pack(objects)
            pack_data = pack_path.read_bytes()

            # Clean up temp pack on server
            pack_path.unlink()
            idx_path.unlink()

            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(pack_data)))
            self.end_headers()
            self.wfile.write(pack_data)

        elif path == "/vcx-receive-pack":
            pack_data = self.rfile.read(content_len)
            branch = self.headers.get("X-VCX-Branch", "main")
            target_commit = self.headers.get("X-VCX-Commit")

            p_hash = hashlib.sha256(pack_data).hexdigest()
            dest_pack = self.repo.store.pack_dir / f"pack-{p_hash[:16]}.pack"
            dest_pack.write_bytes(pack_data)
            self.repo.store._rebuild_pack_index(dest_pack)
            self.repo.store._pack_readers = None

            if target_commit:
                b_file = self.repo.vcx_dir / "refs" / "heads" / branch
                b_file.parent.mkdir(parents=True, exist_ok=True)
                b_file.write_text(f"{target_commit}\n")

            msg = f"Successfully received push for {branch} -> {target_commit[:8] if target_commit else 'HEAD'}".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

        elif path == "/vcx-upload-session/init":
            raw_body = self.rfile.read(content_len).decode("utf-8")
            data = json.loads(raw_body)
            branch = data.get("branch", "main")
            target_commit = data.get("commit")
            total_size = int(data.get("total_size", 0))
            pack_hash = data.get("pack_hash", "")
            force = bool(data.get("force", False))

            session_id = uuid.uuid4().hex
            session_dir = self.repo.vcx_dir / "sessions" / session_id
            session_dir.mkdir(parents=True, exist_ok=True)

            meta = {
                "session_id": session_id,
                "branch": branch,
                "commit": target_commit,
                "total_size": total_size,
                "pack_hash": pack_hash,
                "force": force,
            }
            (session_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            (session_dir / "data.part").touch()

            self._send_json(200, {
                "session_id": session_id,
                "received_bytes": 0,
                "total_size": total_size,
                "status": "initialized",
            })

        elif path == "/vcx-upload-session/chunk":
            session_id = query.get("session_id", [self.headers.get("X-VCX-Session-ID")])[0]
            if not session_id:
                self._send_json(400, {"error": "Missing session_id"})
                return

            session_dir = self.repo.vcx_dir / "sessions" / session_id
            meta_file = session_dir / "meta.json"
            part_file = session_dir / "data.part"

            if not session_dir.exists() or not meta_file.exists():
                self._send_json(404, {"error": "Invalid or expired session"})
                return

            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            current_size = part_file.stat().st_size if part_file.exists() else 0

            # Parse Content-Range header: bytes START-END/TOTAL
            content_range = self.headers.get("Content-Range", "")
            if content_range.startswith("bytes "):
                try:
                    range_part = content_range[6:].split("/")[0]
                    start_str, end_str = range_part.split("-")
                    range_start = int(start_str)
                    if range_start != current_size:
                        # Offset mismatch: notify client to realign
                        self._send_json(409, {
                            "error": "Offset mismatch",
                            "expected_offset": current_size,
                            "received_bytes": current_size,
                        })
                        return
                except Exception:
                    pass

            chunk_bytes = self.rfile.read(content_len)
            with open(part_file, "ab") as f:
                f.write(chunk_bytes)

            new_size = part_file.stat().st_size
            total_size = meta.get("total_size", 0)

            if new_size >= total_size and total_size > 0:
                # Upload completed: verify integrity and finalize
                part_bytes = part_file.read_bytes()
                computed_hash = hashlib.sha256(part_bytes).hexdigest()
                expected_hash = meta.get("pack_hash")

                if expected_hash and computed_hash != expected_hash:
                    self._send_json(400, {
                        "error": "Checksum verification failed",
                        "computed": computed_hash,
                        "expected": expected_hash,
                    })
                    return

                dest_pack = self.repo.store.pack_dir / f"pack-{computed_hash[:16]}.pack"
                shutil.move(str(part_file), str(dest_pack))
                self.repo.store._rebuild_pack_index(dest_pack)
                self.repo.store._pack_readers = None

                branch = meta.get("branch", "main")
                target_commit = meta.get("commit")
                if target_commit:
                    b_file = self.repo.vcx_dir / "refs" / "heads" / branch
                    b_file.parent.mkdir(parents=True, exist_ok=True)
                    b_file.write_text(f"{target_commit}\n")

                shutil.rmtree(session_dir, ignore_errors=True)

                self._send_json(201, {
                    "status": "completed",
                    "message": f"Successfully received push (resumable session finalized) for {branch} -> {target_commit[:8] if target_commit else 'HEAD'}",
                    "commit": target_commit,
                })
            else:
                self._send_json(200, {
                    "status": "chunk_accepted",
                    "received_bytes": new_size,
                    "total_size": total_size,
                })

        else:
            self.send_response(404)
            self.end_headers()


class VcxServer:
    def __init__(self, repo: Repository, host: str = "127.0.0.1", port: int = 8080):
        self.repo = repo
        self.host = host
        self.port = port
        self.httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, background: bool = False) -> None:
        class BoundHandler(VcxRequestHandler):
            pass

        BoundHandler.repo = self.repo
        self.httpd = HTTPServer((self.host, self.port), BoundHandler)

        if background:
            self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self._thread.start()
        else:
            print(f"VCX Server listening on http://{self.host}:{self.port}/")
            self.httpd.serve_forever()

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
