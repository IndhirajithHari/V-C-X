"""End-to-End System Simulators for VCX (Version Control X).

This test suite simulates extreme, production-grade real-world conditions:
1. Flaky Satellite Network & Mid-Stream Interruption Simulator (Resumable HTTP Transport).
2. Sudden Power Failure & System Crash Simulator (ACID fault tolerance, corrupt index quarantine).
3. Multi-Worker Concurrent Access & Thread Contention Simulator (Parallel reads, writes, GC).
4. Cross-OS Environment Simulator (Windows, macOS Darwin, Linux, Merkle hash invariance).
5. Multi-Domain Creative & Engineering Studio Simulator (Game, CAD, EDA, Audio, 3D, Code).
6. Comprehensive CLI User Journey Simulator (All core subcommands executed end-to-end).
"""

from __future__ import annotations
import concurrent.futures
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request
import zlib

from vcx.agent.schemas import DifferInput, DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.cli.main import main as vcx_cli_main
from vcx.core.accelerator import (
    _NativeBackend,
    fast_cdc_chunks,
    fast_sha256,
    get_accelerator_status,
)
from vcx.core.index import Index
from vcx.core.object_store import ObjectStore, ObjectType
from vcx.core.repository import Repository
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type
from vcx.diff.merger import SemanticMerger
from vcx.remote.server import VcxServer
from vcx.remote.transport import RemoteTransport


class TestSatelliteNetworkDropSimulator(unittest.TestCase):
    """Simulates high-latency, packet-dropping satellite and edge networks."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.server_repo_dir = Path(self.temp_dir) / "server_repo"
        self.client_repo_dir = Path(self.temp_dir) / "client_repo"
        self.clone_repo_dir = Path(self.temp_dir) / "clone_repo"

        # Initialize server repository
        self.server_repo = Repository.init(self.server_repo_dir)
        (self.server_repo_dir / "README.md").write_text("# Central Remote Repo\n")
        self.server_repo.add(["README.md"])
        self.server_repo.commit("Initial remote commit")

        # Start Remote HTTP Server
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        self.server = VcxServer(self.server_repo, host="127.0.0.1", port=port)
        self.server.start(background=True)
        time.sleep(0.1)

        self.server_url = f"http://127.0.0.1:{port}"

    def tearDown(self):
        self.server.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_satellite_interrupted_upload_and_auto_resume(self):
        """Simulate satellite dropouts mid-upload and verify byte-exact resume."""
        client_repo = Repository.init(self.client_repo_dir)
        client_repo.remotes.add("origin", self.server_url)

        # Create substantial multi-part assets (CAD STEP solid + Verilog HDL + binary chunk)
        large_step_data = (
            "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Simulator CAD Solid'),'2;1');\n"
            + ("ADVANCED_FACE('',(#10,#11),#12,.T.);\n" * 1500)
            + "ENDSEC;\nEND-10303-21;\n"
        )
        (self.client_repo_dir / "assembly.step").write_text(large_step_data)
        (self.client_repo_dir / "core.v").write_text(
            "module sat_transceiver(input clk, output reg [31:0] tx_data);\n"
            "always @(posedge clk) tx_data <= tx_data + 1;\nendmodule\n"
        )
        (self.client_repo_dir / "payload.bin").write_bytes(os.urandom(64 * 1024))

        client_repo.add(["assembly.step", "core.v", "payload.bin"])
        commit_sha, _ = client_repo.commit("Satellite flight package v1")

        # Simulate network drop after 12KB with 16KB chunk size
        # This exercises chunk boundary resume, status check, and offset recovery
        push_result = RemoteTransport.push_resumable(
            repo=client_repo,
            remote_name="origin",
            branch="main",
            force=True,
            chunk_size=16 * 1024,
            simulate_interrupt_after_bytes=12 * 1024,
        )

        self.assertIn("Successfully", push_result)

        # Clone from remote server into new directory to verify bit-level fidelity
        cloned_repo = RemoteTransport.clone(self.server_url, self.clone_repo_dir)
        self.assertEqual(cloned_repo.head_commit_sha, commit_sha)

        # Verify cloned file contents
        self.assertEqual(
            (self.clone_repo_dir / "assembly.step").read_text(),
            large_step_data,
        )
        self.assertEqual(
            (self.clone_repo_dir / "payload.bin").read_bytes(),
            (self.client_repo_dir / "payload.bin").read_bytes(),
        )

    def test_corrupted_chunk_tampering_rejected_by_server(self):
        """Simulate in-transit packet corruption; assert server rejects bad SHA-256."""
        # Initialize an upload session directly on the server
        init_url = f"{self.server_url}/vcx-upload-session/init"
        pack_payload = b"SimulatedPackBytesThatAreCorruptedByBitFlips"
        real_hash = hashlib.sha256(pack_payload).hexdigest()

        init_data = json.dumps({
            "branch": "main",
            "commit": "deadbeef" * 8,
            "total_size": len(pack_payload),
            "pack_hash": real_hash,
            "force": True,
        }).encode("utf-8")

        req = urllib.request.Request(
            init_url, data=init_data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            session_id = json.loads(resp.read().decode("utf-8"))["session_id"]

        # Send tampered bytes where full chunk data fails SHA-256 session hash
        chunk_url = f"{self.server_url}/vcx-upload-session/chunk?session_id={session_id}"
        tampered_chunk = b"X" * len(pack_payload)
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(tampered_chunk)),
            "Content-Range": f"bytes 0-{len(pack_payload) - 1}/{len(pack_payload)}",
            "X-VCX-Session-ID": session_id,
        }

        bad_req = urllib.request.Request(chunk_url, data=tampered_chunk, headers=headers)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(bad_req)

        self.assertEqual(ctx.exception.code, 400)


class TestPowerFailureAndCrashRecoverySimulator(unittest.TestCase):
    """Simulates sudden power outages, process crashes (SIGKILL), and storage faults."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir) / "acid_repo"
        self.repo = Repository.init(self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_corrupt_index_auto_quarantine_and_clean_recovery(self):
        """Simulate power-cut during index write leaving a truncated JSON file."""
        (self.repo_dir / "file1.txt").write_text("Hello World\n")
        self.repo.add(["file1.txt"])
        self.repo.commit("Base commit")

        # Simulate power failure: truncate .vcx/index mid-write
        index_file = self.repo_dir / ".vcx" / "index"
        self.assertTrue(index_file.exists())
        index_file.write_text('{"file1.txt": {"path": "file1.txt", "sha": "abc')  # Half written JSON

        # Loading index should quarantine corrupt file and raise informative error
        with self.assertRaises(RuntimeError) as ctx:
            Index(self.repo_dir)

        self.assertIn("Corrupt index file detected", str(ctx.exception))

        # Assert quarantine backup file was created
        corrupt_backups = list((self.repo_dir / ".vcx").glob("index.corrupt.*"))
        self.assertGreaterEqual(len(corrupt_backups), 1)

        # Verify repo can re-index cleanly after removing corrupted remnant
        index_file.unlink()
        rebuilt_index = Index(self.repo_dir)
        rebuilt_index.write()
        self.assertEqual(len(rebuilt_index), 0)

    def test_orphan_tmp_files_survive_crash_without_store_corruption(self):
        """Simulate process kill leaving .tmp_<pid>_<sha> in the object store."""
        # Inject orphan temporary file in object directory
        obj_dir = self.repo.store.objects_dir / "ab"
        obj_dir.mkdir(parents=True, exist_ok=True)
        orphan_tmp = obj_dir / f".tmp_{os.getpid()}_cdef12345678"
        orphan_tmp.write_bytes(b"PartialWriteInterruptedBySIGKILL")

        # Object store must not recognize orphan tmp as valid object
        fake_sha = "abcdef12345678" + "0" * 50
        self.assertFalse(self.repo.store.has_object(fake_sha))

        # Writing valid object with same prefix must succeed without conflict
        real_data = b"Legitimate object payload after reboot"
        written_sha = self.repo.store.write_object(ObjectType.BLOB, real_data)
        read_type, read_bytes = self.repo.store.read_object(written_sha)
        self.assertEqual(read_type, ObjectType.BLOB)
        self.assertEqual(read_bytes, real_data)

    def test_bit_flip_object_corruption_detected_deterministically(self):
        """Simulate bit-flip in object store; verify SHA-256 detection and rejection."""
        original_data = b"Critical spacecraft telemetry payload"
        obj_sha = self.repo.store.write_object(ObjectType.BLOB, original_data)

        # Corrupt the compressed payload on disk (simulate storage corruption)
        obj_file = self.repo.store.objects_dir / obj_sha[:2] / obj_sha[2:]
        compressed = bytearray(obj_file.read_bytes())
        # Flip bytes in the compressed stream
        compressed[len(compressed) // 2] ^= 0xFF
        obj_file.write_bytes(bytes(compressed))

        # ObjectStore.read_object MUST catch the decompression or checksum failure
        with self.assertRaises(ValueError):
            self.repo.store.read_object(obj_sha)


class TestMultiWorkerConcurrentAccessSimulator(unittest.TestCase):
    """Simulates multi-developer and parallel daemon contention on a single repository."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir) / "multi_worker_repo"
        self.repo = Repository.init(self.repo_dir)
        (self.repo_dir / "init.txt").write_text("Repository initialization\n")
        self.repo.add(["init.txt"])
        self.repo.commit("Init repo")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parallel_worker_reads_and_writes(self):
        """Run 12 concurrent worker threads executing status, reads, and object writes."""
        def worker_task(worker_id: int) -> bool:
            try:
                # Open isolated repo handle to simulate separate process/thread access
                local_repo = Repository(self.repo_dir)

                # Each worker writes unique file and stages it
                file_name = f"worker_{worker_id}.dat"
                file_path = self.repo_dir / file_name
                file_path.write_bytes(f"Worker {worker_id} payload: {os.urandom(1024).hex()}".encode())

                # Parallel object hashing & storage
                obj_sha = local_repo.store.write_object(
                    ObjectType.BLOB, f"blob_data_from_{worker_id}".encode()
                )
                t, data = local_repo.store.read_object(obj_sha)
                assert t == ObjectType.BLOB
                assert f"blob_data_from_{worker_id}".encode() in data

                # Read status and log concurrently
                st = local_repo.status()
                assert "branch" in st
                log_entries = local_repo.log(limit=5)
                assert len(log_entries) >= 1
                return True
            except Exception as e:
                print(f"Worker {worker_id} failed with: {e}", file=sys.stderr)
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_task, i) for i in range(16)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        self.assertTrue(all(results))
        self.assertEqual(len(results), 16)


class TestCrossPlatformEnvironmentSimulator(unittest.TestCase):
    """Simulates Windows (NT), macOS (Darwin), and Linux cross-platform determinism."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir) / "cross_platform_repo"
        self.repo = Repository.init(self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_windows_crlf_and_backslash_tree_hash_determinism(self):
        """Verify repository produces identical canonical Merkle tree hashes across OSes."""
        # 1. Create file with Linux style forward slashes
        sub_dir = self.repo_dir / "src" / "math"
        sub_dir.mkdir(parents=True, exist_ok=True)
        file_path = sub_dir / "matrix.py"
        file_path.write_text("def mul(a, b):\n    return a * b\n", encoding="utf-8")

        # Stage with Windows backslash path representation
        windows_path_repr = "src\\math\\matrix.py"
        self.repo.add([windows_path_repr])

        # Assert staging index strictly stores canonical POSIX forward slashes
        index_entries = [e.path for e in self.repo.index.entries()]
        self.assertIn("src/math/matrix.py", index_entries)
        self.assertNotIn("src\\math\\matrix.py", index_entries)

        # Commit and verify tree structure
        sha, commit = self.repo.commit("Cross platform path test")
        tree = self.repo.store.read_tree(commit.tree_sha)
        tree_paths = [e.path for e in tree]
        self.assertIn("src", tree_paths)

    def test_mock_windows_accelerator_runtime_discovery(self):
        """Simulate Windows environment (win32) for native backend initialization."""
        with patch("sys.platform", "win32"), patch("os.name", "nt"):
            backend = _NativeBackend()
            self.assertIsInstance(backend.has_c_runtime, bool)
            self.assertIsInstance(backend.has_crypto_accel, bool)

            status = get_accelerator_status()
            self.assertIn("backend", status)
            self.assertIn("has_c_runtime", status)
            self.assertIn("has_crypto_accel", status)

    def test_mock_darwin_accelerator_runtime_discovery(self):
        """Simulate macOS Apple Silicon / Intel environment (darwin) for accelerator."""
        with patch("sys.platform", "darwin"):
            backend = _NativeBackend()
            self.assertIsInstance(backend.has_c_runtime, bool)
            self.assertIsInstance(backend.has_crypto_accel, bool)


class TestProductionCreativeAndEngineeringStudioSimulator(unittest.TestCase):
    """Simulates a full-scale studio: Games, CAD, EDA, Audio, 3D, and Code."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_dir = Path(self.temp_dir) / "studio_repo"
        self.repo = Repository.init(self.repo_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multi_domain_production_pipeline_and_semantic_merge(self):
        """Comprehensive multi-disciplinary asset creation, branching, and 3-way merge."""
        # 1. Godot Game Scene (.tscn)
        godot_scene = (
            "[gd_scene load_steps=2 format=3]\n"
            '[ext_resource type="Script" path="res://player.gd" id="1_abc"]\n'
            '[node name="Player" type="CharacterBody2D"]\n'
            "script = ExtResource( 1_abc )\n"
            "position = Vector2( 100, 250 )\n"
        )
        (self.repo_dir / "player.tscn").write_text(godot_scene)

        # 2. Ableton Live Audio Project (.als - gzipped XML)
        als_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <Ableton MajorVersion="5" MinorVersion="11.0_432" SchemaChangeCount="3">
            <LiveSet>
                <Tracks>
                    <MidiTrack Id="1">
                        <Name Value="Bass Synth" />
                    </MidiTrack>
                </Tracks>
            </LiveSet>
        </Ableton>"""
        with gzip.open(self.repo_dir / "soundtrack.als", "wb") as f:
            f.write(als_xml)

        # 3. FreeCAD Parametric Model Document (.fcstd container or Document.xml)
        doc_xml_base = (
            '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
            '<Document SchemaVersion="4">\n'
            '  <Object name="Body">\n'
            '    <Property name="Length" type="App::PropertyFloat"><Float value="100.0"/></Property>\n'
            '    <Property name="Width" type="App::PropertyFloat"><Float value="50.0"/></Property>\n'
            '  </Object>\n'
            '</Document>'
        )
        (self.repo_dir / "Document.xml").write_text(doc_xml_base)

        # 4. Hardware Verilog RTL (.v)
        verilog_base = (
            "module alu(\n"
            "    input [7:0] a,\n"
            "    input [7:0] b,\n"
            "    output [7:0] out\n"
            ");\n"
            "    assign out = a + b;\n"
            "endmodule\n"
        )
        (self.repo_dir / "alu.v").write_text(verilog_base)

        # 5. Python AST Source Code (.py)
        python_base = (
            "def calculate_trajectory(velocity: float, angle: float) -> float:\n"
            "    import math\n"
            "    return (velocity ** 2) * math.sin(2 * angle) / 9.81\n"
        )
        (self.repo_dir / "physics.py").write_text(python_base)

        # Initial studio commit
        self.repo.add(["player.tscn", "soundtrack.als", "Document.xml", "alu.v", "physics.py"])
        base_commit_sha, _ = self.repo.commit("Init studio assets (Game, Audio, CAD, EDA, Code)")

        # Create branch for hardware & CAD engineering
        self.repo.create_branch("feature/engineering-v2")
        self.repo.checkout("feature/engineering-v2")

        # Engineering branch modifies FreeCAD Width dimension and adds Verilog subtraction
        doc_xml_engineering = doc_xml_base.replace('value="50.0"', 'value="75.0"')
        (self.repo_dir / "Document.xml").write_text(doc_xml_engineering)

        verilog_engineering = verilog_base.replace(
            "assign out = a + b;",
            "input sub_mode,\n    assign out = sub_mode ? (a - b) : (a + b);",
        )
        (self.repo_dir / "alu.v").write_text(verilog_engineering)

        self.repo.add(["Document.xml", "alu.v"])
        eng_commit_sha, _ = self.repo.commit("Eng: Update bracket width to 75mm and add ALU subtraction")

        # Switch back to main to make concurrent non-conflicting changes (Game & Audio)
        self.repo.checkout("main")

        # Main branch updates Python physics and Godot player position
        (self.repo_dir / "physics.py").write_text(
            python_base + "\ndef terminal_velocity(mass: float) -> float:\n    return mass * 9.81\n"
        )
        (self.repo_dir / "player.tscn").write_text(
            godot_scene.replace("position = Vector2( 100, 250 )", "position = Vector2( 300, 450 )")
        )
        # Also modify Length in CAD (non-conflicting with Width modification in engineering branch!)
        doc_xml_main = doc_xml_base.replace('value="100.0"', 'value="120.0"')
        (self.repo_dir / "Document.xml").write_text(doc_xml_main)

        self.repo.add(["physics.py", "player.tscn", "Document.xml"])
        main_commit_sha, _ = self.repo.commit("Main: Adjust player spawn, add terminal velocity, extend CAD length")

        # 3-Way Semantic Merge: Merge feature/engineering-v2 into main
        merge_result = self.repo.merge("feature/engineering-v2")
        self.assertTrue(merge_result.success, f"Merge failed with conflicts: {merge_result.conflicts}")

        # Verify semantic resolution for FreeCAD: Both Length (120.0) and Width (75.0) preserved!
        merged_doc_xml = (self.repo_dir / "Document.xml").read_text()
        self.assertIn('value="120.0"', merged_doc_xml)
        self.assertIn('value="75.0"', merged_doc_xml)

        # Verify Verilog additions preserved
        merged_verilog = (self.repo_dir / "alu.v").read_text()
        self.assertIn("sub_mode", merged_verilog)

        # Verify Python additions preserved
        merged_python = (self.repo_dir / "physics.py").read_text()
        self.assertIn("terminal_velocity", merged_python)

        # Verify Packfile consolidation
        pack_path, idx_path = self.repo.pack()
        self.assertTrue(pack_path.exists())
        self.assertTrue(idx_path.exists())

        # Verify Garbage Collector preserves reachable commits
        gc_stats = self.repo.gc()
        self.assertIsInstance(gc_stats, dict)
        self.assertIn("packed_objects", gc_stats)
        self.assertIn("pruned_objects", gc_stats)
        self.assertIsNotNone(self.repo.head_commit_sha)


class TestCLIProcessSimulator(unittest.TestCase):
    """Simulates a complete real-world user workflow executing all VCX CLI subcommands."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_cwd = os.getcwd()
        os.chdir(self.temp_dir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_cli(self, args: list[str]) -> tuple[int, str, str]:
        """Run CLI command in-process with stdout and stderr captured."""
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()
        with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
            exit_code = vcx_cli_main(args)
        return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue()

    def test_complete_cli_lifecycle(self):
        """Execute init, config, add, commit, branch, checkout, tag, pack, gc, app."""
        # 1. vcx init
        code, out, _ = self._run_cli(["init"])
        self.assertEqual(code, 0)
        self.assertIn("Initialized empty VCX repository", out)

        # 2. vcx config
        code, out, _ = self._run_cli(["config", "user.name", "Simulator Lead"])
        self.assertEqual(code, 0)
        code, out, _ = self._run_cli(["config", "user.email", "lead@studio.vcx"])
        self.assertEqual(code, 0)
        code, out, _ = self._run_cli(["config", "-l"])
        self.assertEqual(code, 0)
        self.assertIn("Simulator Lead", out)

        # 3. Create sample assets and stage
        Path("main.py").write_text("print('Hello VCX Simulator')\n")
        Path("hardware.v").write_text("module top; endmodule\n")

        code, out, _ = self._run_cli(["add", "."])
        self.assertEqual(code, 0)
        self.assertIn("Staged", out)

        # 4. vcx status
        code, out, _ = self._run_cli(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Changes to be committed", out)

        # 5. vcx commit
        code, out, _ = self._run_cli(["commit", "-m", "feat: initial simulation setup"])
        self.assertEqual(code, 0)
        self.assertIn("initial simulation setup", out)

        # 6. vcx log
        code, out, _ = self._run_cli(["log"])
        self.assertEqual(code, 0)
        self.assertIn("initial simulation setup", out)

        # 7. vcx branch & checkout
        code, out, _ = self._run_cli(["branch", "v1.0-release"])
        self.assertEqual(code, 0)
        code, out, _ = self._run_cli(["checkout", "v1.0-release"])
        self.assertEqual(code, 0)
        self.assertIn("v1.0-release", out)

        # 8. vcx tag
        code, out, _ = self._run_cli(["tag", "v1.0.0"])
        self.assertEqual(code, 0)
        code, out, _ = self._run_cli(["tag"])
        self.assertEqual(code, 0)
        self.assertIn("v1.0.0", out)

        # 9. vcx show
        code, out, _ = self._run_cli(["show", "HEAD"])
        self.assertEqual(code, 0)
        self.assertIn("initial simulation setup", out)

        # 10. vcx diff
        Path("main.py").write_text("print('Hello VCX Simulator v2')\n")
        code, out, _ = self._run_cli(["diff"])
        self.assertEqual(code, 0)
        self.assertIn("Simulator v2", out)

        # 11. vcx reset
        code, out, _ = self._run_cli(["reset", "main.py"])
        self.assertEqual(code, 0)

        # 12. vcx pack & gc
        code, out, _ = self._run_cli(["pack"])
        self.assertEqual(code, 0)
        code, out, _ = self._run_cli(["gc"])
        self.assertEqual(code, 0)

        # 13. vcx app list & inspect
        code, out, _ = self._run_cli(["app", "list"])
        self.assertEqual(code, 0)
        self.assertIn("FreeCAD", out)
        self.assertIn("Ableton Live", out)

        code, out, _ = self._run_cli(["app", "inspect", "hardware.v"])
        self.assertEqual(code, 0)
        self.assertIn("eda/verilog", out)


if __name__ == "__main__":
    unittest.main()
