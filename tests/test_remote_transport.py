"""Unit tests for Smart Remote Transport and HTTP Server in VCX."""

from __future__ import annotations
import json
from pathlib import Path
import shutil
import socket
import tempfile
import time
import unittest

from vcx.core.repository import Repository
from vcx.remote.server import VcxServer
from vcx.remote.transport import RemoteManager, RemoteTransport


class TestRemoteTransport(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vcx_remote_test_")
        self.base_path = Path(self.tmp_dir)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_remote_manager_crud(self):
        repo_dir = self.base_path / "repo_rm"
        repo = Repository.init(repo_dir)

        # Initially empty
        self.assertEqual(repo.remotes.list_all(), {})

        # Add origin
        repo.remotes.add("origin", "https://github.com/example/vcx.git")
        self.assertEqual(repo.remotes.get("origin"), "https://github.com/example/vcx.git")

        # Add upstream
        repo.remotes.add("upstream", "/local/path/repo")
        self.assertEqual(len(repo.remotes.list_all()), 2)

        # Remove
        repo.remotes.remove("origin")
        self.assertIsNone(repo.remotes.get("origin"))
        self.assertEqual(repo.remotes.get("upstream"), "/local/path/repo")

    def test_local_clone_and_fetch(self):
        # Create source repository
        src_dir = self.base_path / "source_repo"
        src_repo = Repository.init(src_dir)

        # Make initial commit
        (src_dir / "design.v").write_text("module top; endmodule\n")
        src_repo.add(["design.v"])
        c1, _ = src_repo.commit("Initial commit on main")

        # Clone into dest_dir
        dest_dir = self.base_path / "dest_repo"
        dest_repo = RemoteTransport.clone(str(src_dir), dest_dir)

        self.assertEqual(dest_repo.head_commit_sha, c1)
        self.assertTrue((dest_dir / "design.v").exists())
        self.assertEqual((dest_dir / "design.v").read_text(), "module top; endmodule\n")

        # Remote tracking ref exists
        self.assertEqual(dest_repo.remotes.get("origin"), str(src_dir.resolve()))

        # Add new commit in source repo on a new branch
        src_repo.create_branch("feature-alu")
        src_repo.checkout("feature-alu")
        (src_dir / "alu.v").write_text("module alu; endmodule\n")
        src_repo.add(["alu.v"])
        c2, _ = src_repo.commit("Add ALU module")

        # Fetch from dest repo
        updated = RemoteTransport.fetch(dest_repo, "origin")
        self.assertIn("feature-alu", updated)
        self.assertEqual(updated["feature-alu"], c2)

        # Dest repo store now has the commit and blob
        self.assertTrue(dest_repo.store.has_object(c2))

    def test_local_push_and_rejection(self):
        # Setup source (acts as bare/remote)
        remote_dir = self.base_path / "remote_repo"
        remote_repo = Repository.init(remote_dir)
        (remote_dir / "init.txt").write_text("v1\n")
        remote_repo.add(["init.txt"])
        c1, _ = remote_repo.commit("Initial commit")

        # Clone to local
        local_dir = self.base_path / "local_repo"
        local_repo = RemoteTransport.clone(str(remote_dir), local_dir)

        # Make a commit locally
        (local_dir / "init.txt").write_text("v2\n")
        local_repo.add(["init.txt"])
        c2, _ = local_repo.commit("Update to v2")

        # Push to remote
        push_msg = RemoteTransport.push(local_repo, "origin", branch="main")
        self.assertIn("Successfully pushed main", push_msg)

        # Remote branch ref updated
        remote_head = (remote_dir / ".vcx" / "refs" / "heads" / "main").read_text().strip()
        self.assertEqual(remote_head, c2)

        # Test non-fast-forward rejection
        # Make conflicting divergent commit in remote
        (remote_dir / "divergent.txt").write_text("divergent\n")
        remote_repo.add(["divergent.txt"])
        c3, _ = remote_repo.commit("Divergent commit in remote")

        # Attempt push from local (which is behind c3)
        (local_dir / "another.txt").write_text("another\n")
        local_repo.add(["another.txt"])
        c4, _ = local_repo.commit("Another local commit")

        with self.assertRaises(ValueError) as ctx:
            RemoteTransport.push(local_repo, "origin", branch="main", force=False)
        self.assertIn("Non-fast-forward push rejected", str(ctx.exception))

        # Push with force=True succeeds
        force_msg = RemoteTransport.push(local_repo, "origin", branch="main", force=True)
        self.assertIn("Successfully pushed", force_msg)
        remote_head_after_force = (remote_dir / ".vcx" / "refs" / "heads" / "main").read_text().strip()
        self.assertEqual(remote_head_after_force, c4)

    def test_http_server_clone_and_push(self):
        # Setup server repo
        server_dir = self.base_path / "http_server_repo"
        server_repo = Repository.init(server_dir)
        (server_dir / "model.step").write_text("ISO-10303-21;\nHEADER;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
        server_repo.add(["model.step"])
        c1, _ = server_repo.commit("Initial CAD STEP commit")

        # Find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        server = VcxServer(server_repo, host="127.0.0.1", port=port)
        server.start(background=True)
        time.sleep(0.15)  # Allow socket to bind

        try:
            http_url = f"http://127.0.0.1:{port}"

            # Clone over HTTP
            client_dir = self.base_path / "http_client_repo"
            client_repo = RemoteTransport.clone(http_url, client_dir)

            self.assertEqual(client_repo.head_commit_sha, c1)
            self.assertTrue((client_dir / "model.step").exists())

            # Make local changes and push over HTTP
            (client_dir / "chassis.v").write_text("module chassis; endmodule\n")
            client_repo.add(["chassis.v"])
            c2, _ = client_repo.commit("Add chassis HDL")

            push_res = RemoteTransport.push(client_repo, "origin", branch="main")
            self.assertIn("Successfully received push", push_res)

            # Server repo ref updated
            srv_head = (server_dir / ".vcx" / "refs" / "heads" / "main").read_text().strip()
            self.assertEqual(srv_head, c2)
            self.assertTrue(server_repo.store.has_object(c2))

        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
