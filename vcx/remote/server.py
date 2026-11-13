"""Lightweight HTTP Server for VCX Repositories (vcx serve)."""

from __future__ import annotations
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import struct
import threading
from typing import Optional

from vcx.core.pack import PackWriter
from vcx.core.repository import Repository


class VcxRequestHandler(BaseHTTPRequestHandler):
    repo: Repository

    def log_message(self, format: str, *args) -> None:
        # Suppress automatic noisy HTTP access logs to stderr
        pass

    def do_GET(self) -> None:
        if self.path == "/info/refs":
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
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))

        if self.path == "/vcx-upload-pack":
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

        elif self.path == "/vcx-receive-pack":
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
