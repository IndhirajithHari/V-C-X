<p align="center">
  <img src="assets/vcx_logo.png" alt="VCX Logo" width="340"/>
</p>

<h1 align="center">VCX: Version Control for Everything</h1>

<p align="center">
  <b>Autonomous, Multi-Domain Version Control System & Semantic Differ Engine</b><br>
  <i>Universal Support for Source Code, Hardware/EDA, CAD/3D, Video, Audio, Creative Suites, Documents & Databases</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-61%20passed-brightgreen.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/formats-Universal%20Media%20%2B%20Apps-blueviolet.svg" alt="Formats"/>
  <img src="https://img.shields.io/badge/runtime-100%25%20Fully%20Independent-success.svg" alt="Independent"/>
  <img src="https://img.shields.io/badge/storage-SHA--256%20CAS%20%2B%20Merkle-purple.svg" alt="Storage"/>
  <a href="https://github.com/codecrafters-io/build-your-own-x"><img src="https://img.shields.io/badge/inspired%20by-build--your--own--x-orange.svg" alt="Build Your Own X"/></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"/>
</p>

---

## Table of Contents

- [Overview](#overview)
- [Why VCX? (Key Uses & Applications)](#why-vcx-key-uses--applications)
- [How It Works (System Architecture)](#how-it-works-system-architecture)
  - [1. Content-Addressable Storage (CAS)](#1-content-addressable-storage-cas)
  - [2. Hierarchical Merkle Trees](#2-hierarchical-merkle-trees)
  - [3. Binary Packfiles & Garbage Collection (`vcx gc`)](#3-binary-packfiles--garbage-collection-vcx-gc)
  - [4. Multi-Domain 3-Way Semantic Merge (`vcx merge`)](#4-multi-domain-3-way-semantic-merge-vcx-merge)
  - [5. CAD Solid B-Rep & Mesh Tessellation Engine](#5-cad-solid-b-rep--mesh-tessellation-engine)
  - [6. Smart Remote Transport & HTTP Server (`vcx serve`)](#6-smart-remote-transport--http-server-vcx-serve)
  - [7. Core Semantic Differ Agent](#7-core-semantic-differ-agent)
  - [8. Real-Time Workspace Watcher (`vcx watch`)](#8-real-time-workspace-watcher-vcx-watch)
- [Step-by-Step Setup Guide](#step-by-step-setup-guide)
- [Getting Started Walkthrough](#getting-started-walkthrough)
- [CLI Reference](#cli-reference)
- [Running the Test Suite](#running-the-test-suite)
- [License](#license)

---

## Overview

Traditional version control systems like Git were built primarily for flat ASCII text files and line-by-line code changes. When applied to modern engineering stacks—such as **Hardware/EDA RTL**, **Parametric 3D CAD models**, **SQLite databases**, **STEP solid bodies**, or **binary assets**—traditional tools collapse into opaque binary blobs, line-collision merge conflicts, and repository bloat.

**VCX (Version Control for Everything)** solves this fundamental limitation. Inspired by Git internals from [codecrafters-io/build-your-own-x](https://github.com/codecrafters-io/build-your-own-x), VCX pairs an enterprise-grade Git-compatible engine (hierarchical Merkle trees, SHA-256 CAS, binary packfile archiving, atomic staging, smart HTTP remote synchronization) with domain-specific AST analyzers and an autonomous **Semantic Differ Agent**.

---

## Why VCX? (Key Uses & Applications)

| Domain | File Types Tracked | Traditional VCS Limitation | VCX Solution & Superpower |
| :--- | :--- | :--- | :--- |
| **Video Production & Streaming** | MP4, MOV, MKV, WebM, AVI, ProRes (`.mp4`, `.mov`, `.mkv`, `.webm`) | Treated as dumb binary files; no insight into stream changes | **Media Stream Analyzer**: tracks frame resolution (1080p $\to$ 4K), framerate (24 $\to$ 60fps), duration deltas, codecs (HEVC, ProRes, AV1), and audio stream layouts. |
| **Audio Engineering & Stems** | WAV, FLAC, MP3, AAC, OGG, AIFF (`.wav`, `.flac`, `.mp3`) | Large opaque binaries; git LFS blind to audio shifts | **Acoustic Spec Inspection**: tracks sample rates (44.1kHz $\to$ 96kHz), bit depths (16 $\to$ 24-bit), channel layouts (Mono, Stereo, 5.1 Surround), and duration deltas. |
| **Creative Apps & Video Editors** | Premiere Pro (`.prproj`), Final Cut (`.fcpxml`), DaVinci (`.edl`), Audacity (`.aup3`), Filmcraft | Corrupted merges, proprietary app lock-in | **Project Container Dissection**: decompresses Premiere/FCP XML timelines (sequences, video/audio tracks, clips), queries Audacity SQLite sessions, and diffs cuts and stems. |
| **Design & 3D Authoring** | Photoshop (`.psd`, `.psb`), Blender (`.blend`), glTF/GLB (`.gltf`, `.glb`), SVG | Monolithic binary files with zero visibility into art assets | **Canvas & Scene Graph Engine**: parses Photoshop 8BPS headers (dimensions, color modes, channels), Blender versions/blocks, and glTF nodes/meshes/materials. |
| **Hardware & EDA** | Verilog, SystemVerilog (`.v`, `.sv`), JSON Floorplans | Line conflicts when merging pinouts; opaque macro shifts | **Semantic port synthesis**: merges disjoint pinout additions without conflict; detects ALU pipeline modifications and ISA decode logic. |
| **CAD & 3D Engineering** | FreeCAD (`.fcstd`), STEP (`.step`, `.stp`), STL, OBJ | Treated as opaque binary files; git LFS cannot diff geometry | **CAD Solid B-Rep Engine**: parses ISO-10303-21 manifold solids, calculates bounding box extents (`dx, dy, dz` in mm), and merges non-colliding parametric dimensions. |
| **Software Development** | Python, Rust, C, C++, JavaScript, TypeScript, Go | Blind diffs showing moved lines without intent | **AST-aware semantic diffing**: recognizes renamed functions, memory safety primitives (`unsafe`, `Box`, `malloc`), and control flow shifts. |
| **Documents & Office Suites** | PDF, Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`) | Binary collisions; unreadable raw XML diffs | **Document Structure Inspection**: extracts word counts, spreadsheet sheets, slide counts, revision history, and PDF page counts. |
| **Databases & Event Streams** | SQLite (`.db`, `.sqlite`), CSV, TSV, Transaction Logs | Corrupt index merges; binary diff blobs | **Schema & Row-Level Delta Tracking**: diffs table definitions, column types, row counts, and auto-synthesizes appended audit logs. |
| **Autonomous AI Agents** | Automated Agent Pipelines, CI/CD, Robotics | Hallucinatory commit messages and fragile tools | **Deterministic Differ Agent**: operates offline or with Gemini API, strictly adhering to JSON schemas with zero hallucinations. |
| **Universal Applications & DAWs** | Ableton (`.als`), Reaper (`.rpp`), Unity, Godot, Unreal, Sketch, Krita, KiCad | Incompatible proprietary binaries; silent data corruption | **Universal Container & CDC Dissector**: unpacks project containers in memory, performs Content-Defined Chunking (CDC) on proprietary binaries, extracts embedded strings, and exposes custom plugin hooks. |

---

## How It Works (System Architecture)

```
                            +----------------------------------------+
                            |            Working Tree Files          |
                            |  (Python, Verilog, STEP, FreeCAD, DB)  |
                            +-------------------+--------------------+
                                                |
                                                v
                            +----------------------------------------+
                            |        Domain Detector & Analyzers     |
                            |  * Python AST      * STEP B-Rep        |
                            |  * Verilog Ports   * FreeCAD XML       |
                            |  * SQLite Tables   * Binary Entropy    |
                            +-------------------+--------------------+
                                                |
                                                v
                            +----------------------------------------+
                            |          Staging Index (.vcx/index)    |
                            |     Atomic JSON with SHA integrity     |
                            +-------------------+--------------------+
                                                |
                                                v
                            +----------------------------------------+
                            |    Hierarchical Merkle Trees (CAS)     |
                            |       Commit -> Tree -> Subtrees       |
                            |     SHA-256 Content-Addressed Blobs    |
                            +-------------------+--------------------+
                                                |
                        +-----------------------+-----------------------+
                        |                                               |
                        v                                               v
        +-------------------------------+               +-------------------------------+
        |  Multi-Domain 3-Way Merger    |               |   Packfiles & GC (vcx gc)     |
        |  * Verilog Port Synthesis     |               |   * Delta-Compressed .pack    |
        |  * CAD Parametric Dimensions  |               |   * High-Speed Binary .idx    |
        |  * AST Function Composition   |               |   * Prunes Unreachable SHAs   |
        +-------------------------------+               +-------------------------------+
                        |                                               |
                        +-----------------------+-----------------------+
                                                |
                                                v
                            +----------------------------------------+
                            |    Smart Remote Network Transport      |
                            |   * vcx serve (HTTP Server Daemon)     |
                            |   * vcx clone, vcx fetch, vcx push     |
                            +----------------------------------------+
```

### 1. Content-Addressable Storage (CAS)
Every object in VCX (`blob`, `tree`, `commit`, `tag`) is identified by its cryptographic **SHA-256** hash. Objects are compressed using zlib (level 6) and stored under `.vcx/objects/<prefix>/<hash>`. VCX enforces strict checksum verification on read to guarantee zero silent corruption.

### 2. Hierarchical Merkle Trees
Rather than flattening file lists into monolithic arrays, VCX constructs recursive Git-style tree objects:
- Subdirectories are stored as discrete `tree` objects with mode `040000`.
- Leaf files are referenced as `blob` objects with executable or standard permissions (`100755` / `100644`).
- **Merkle Subtree Reuse**: If a subdirectory with 50,000 files experiences no modifications, its tree SHA is unchanged and completely reused in subsequent commits, making commits near-instantaneous.

### 3. Binary Packfiles & Garbage Collection (`vcx gc`)
To prevent millions of loose files from exhausting filesystem inodes:
- `PackWriter` bundles reachable commits, trees, and blobs into indexed binary archives (`VPK1` format with `VIDX` binary lookup tables).
- `vcx gc` traces reachability from all branch heads and tags, writes packfiles, and safely unlinks dangling loose objects.

### 4. Multi-Domain 3-Way Semantic Merge (`vcx merge`)
Traditional merge tools perform line-based diffing. VCX performs **domain-aware 3-way semantic merges** using common ancestors:
- **Verilog/EDA**: Computes disjoint sets of added input/output ports and decoders, automatically reconciling pinouts without merge conflicts.
- **CAD/3D Parametric**: Reconciles independent dimension modifications (e.g., branch A alters chassis length while branch B adds an edge fillet). If identical dimensions collide, VCX generates a structured parametric conflict marker.
- **Python / Software**: Reconciles non-overlapping function declarations and class bodies.

### 5. CAD Solid B-Rep & Mesh Tessellation Engine
- **STEP Parser (`StepBrepParser`)**: Directly parses ISO-10303-21 text entities (`MANIFOLD_SOLID_BREP`, `ADVANCED_FACE`, `CLOSED_SHELL`, `CARTESIAN_POINT`), validating manifold topology and calculating exact 3D extents (`[dx, dy, dz]` in mm).
- **Mesh Analyzer (`CadTessellator`)**: Analyzes STL/OBJ meshes for watertightness, vertex/face deltas, and produces viewport vision summaries for visual inspection.

### 6. Smart Remote Transport & HTTP Server (`vcx serve`)
- Built-in HTTP server (`VcxServer`) providing `/info/refs`, `/vcx-upload-pack`, and `/vcx-receive-pack`.
- `vcx clone`, `vcx fetch`, and `vcx push` work seamlessly across local filesystem directories and network HTTP endpoints.
- Remote tracking refs are maintained under `.vcx/refs/remotes/<remote>/<branch>` with fast-forward verification.

### 7. Core Semantic Differ Agent
The embedded differ agent inspects delta facts, AST changes, and viewport geometries to generate structured, human-readable commit messages matching a strict JSON schema:

```json
{
  "action_summary": "Imperative tense, < 50 characters",
  "technical_delta": [
    "Specific technical detail 1",
    "Specific technical detail 2"
  ],
  "inferred_intent": "Brief explanation of why this change was likely made based on the context.",
  "tags": ["array", "of", "relevant", "tags"]
}
```

### 8. Real-Time Workspace Watcher (`vcx watch`)
Leverages Linux kernel `pyinotify` with non-blocking event loops and debouncing (default 0.8s) to track file modifications in real-time, with optional `--auto-commit` to maintain an automated checkpoint history.

---

## Step-by-Step Setup Guide

### Prerequisites
- **Operating System**: Linux / Unix / macOS
- **Python**: Python 3.10 or higher
- **Core Dependencies**: `pyinotify` (Linux file watcher), `trimesh`, `numpy`, `pyyaml`

### 1. Clone the Repository
```bash
git clone https://github.com/IndhirajithHari/V-C-X.git
cd V-C-X
```

### 2. Install VCX in Editable Mode
```bash
pip install -e .
```

### 3. Verify the Installation
```bash
vcx --help
```

You should see all 16 registered subcommands:
```text
usage: vcx [-h] {init,status,add,commit,diff,log,branch,checkout,merge,gc,watch,agent,remote,clone,fetch,push,serve} ...
```

### 4. Run the Unit Test Suite
Ensure all 49 test cases pass:
```bash
python3 -m unittest discover tests -v
```

---

## Getting Started Walkthrough

### 1. Initialize a Repository
```bash
mkdir my-hardware-project
cd my-hardware-project
vcx init
```
*Creates `.vcx/` with `objects/`, `refs/heads/`, `index`, and `HEAD`.*

### 2. Stage Multi-Domain Files
Create source, hardware, and CAD files:
```bash
# Hardware design
cat << 'EOF' > alu.v
module alu(input [7:0] a, input [7:0] b, output [7:0] out);
  assign out = a + b;
endmodule
EOF

# CAD STEP solid model
cat << 'EOF' > chassis.step
ISO-10303-21;
DATA;
#10 = CARTESIAN_POINT('Origin', (0.0, 0.0, 0.0));
#20 = CARTESIAN_POINT('P1', (100.0, 50.0, 20.0));
#30 = CLOSED_SHELL('Shell', ());
#40 = MANIFOLD_SOLID_BREP('Solid', #30);
ENDSEC;
END-ISO-10303-21;
EOF

vcx add alu.v chassis.step
vcx status
```

### 3. Commit with the Autonomous Semantic Differ
```bash
# Automatically infer intent and technical deltas:
vcx commit --auto
```
*Output:*
```text
[7a2f1b8c] Add 8-bit adder ALU module and chassis STEP solid
  * Defined sequential always @(posedge clk) or combinational logic
  * Created CAD model with 1 solids and extents [100.0 x 50.0 x 20.0] mm
  Tags: eda-hardware, verilog, cad-geometry
```

### 4. Branching and Semantic 3-Way Merge
```bash
# Create and switch to a feature branch
vcx branch feature/alu-sub
vcx checkout feature/alu-sub

# Add subtraction capability
cat << 'EOF' > alu.v
module alu(input [7:0] a, input [7:0] b, input sub, output [7:0] out);
  assign out = sub ? (a - b) : (a + b);
endmodule
EOF

vcx add alu.v
vcx commit -m "Add subtract control signal to ALU"

# Switch back to main and merge
vcx checkout main
vcx merge feature/alu-sub
```

### 5. Pack Objects & Garbage Collection
```bash
vcx gc
```
*Output:*
```text
VCX Garbage Collection Complete:
  * Packed objects:   14
  * Pruned objects:   0
  * Generated pack:   pack-d70de4b04ea835c9.pack
```

### 6. Remote Synchronization & HTTP Server Daemon
```bash
# In server repository:
vcx serve --host 127.0.0.1 --port 8000

# In client repository:
vcx clone http://127.0.0.1:8000 ./cloned-project
cd cloned-project
vcx remote
vcx fetch origin
vcx push origin main
```

### 7. Run the Background Workspace Watcher
```bash
# Continuously monitor workspace and auto-commit changes:
vcx watch --auto-commit --debounce 0.8
```

---

## CLI Reference

| Command | Arguments / Flags | Description |
| :--- | :--- | :--- |
| **`vcx init`** | `[path]` | Initialize a new VCX repository in the target directory (default `.`) |
| **`vcx status`** | — | Show working tree status (staged, unstaged, untracked with domain tags) |
| **`vcx add`** | `<paths...>` | Stage files or directories into `.vcx/index` |
| **`vcx reset`** | `[paths...]` | Unstage specific files or reset the entire staging index to HEAD |
| **`vcx commit`** | `-m "<msg>"`, `--auto` | Commit staged changes. `--auto` generates messages via Semantic Differ |
| **`vcx diff`** | `[path]`, `--semantic` | View working tree or commit deltas. `--semantic` outputs structured JSON |
| **`vcx show`** | `[target]` | Inspect commit metadata, parent SHAs, and technical deltas (default `HEAD`) |
| **`vcx log`** | `-n <limit>`, `--json` | Display commit history. `--json` emits structured commit records |
| **`vcx branch`** | `[name]` | List branches or create a new branch pointer |
| **`vcx checkout`** | `<target>` | Switch active branch or restore working tree files |
| **`vcx tag`** | `[name] [target]` | List release tags or create a new tag pointing to a commit SHA |
| **`vcx merge`** | `<branch>` | Perform multi-domain 3-way semantic merge with two-parent commit |
| **`vcx gc`** | — | Consolidate loose objects into `.pack`/`.idx` files and prune unreferenced SHAs |
| **`vcx config`** | `[key] [val] [--global] [-l]`| Manage local/global configurations (`user.name`, `user.email`) |
| **`vcx remote`** | `[add\|rm] [name] [url]`| Manage tracked remote repositories (`.vcx/remotes.json`) |
| **`vcx clone`** | `<url> [dest]` | Clone repository from a local path or HTTP endpoint |
| **`vcx fetch`** | `[remote]` | Download missing pack objects and update remote tracking refs |
| **`vcx push`** | `[remote] [branch] [-f]` | Push commits to remote with fast-forward verification |
| **`vcx serve`** | `--host <h>`, `--port <p>` | Start lightweight HTTP server daemon for smart network transport |
| **`vcx watch`** | `--auto-commit`, `--debounce <sec>` | Monitor workspace using `pyinotify` and live-stream semantic deltas |
| **`vcx agent`** | `--input <file>` | Invoke Semantic Differ Agent directly with JSON payload |
| **`vcx app`** | `inspect <file> \| list` | Inspect any software's project file or catalog the universal application ecosystem |
| **`vcx import-git`** | `[path] [--semantic]` | Convert an existing Git repository into native VCX Merkle CAS |

---

## Running the Test Suite

VCX includes comprehensive unit and integration tests covering CAS integrity, Merkle tree reuse, packing/GC, 3-way semantic merging, STEP B-Rep parsing, network transport, tags, configs, and the Git importer:

```bash
python3 -m unittest discover tests -v
```

*(61 tests passing with 100% success rate)*

```text
test_binary_analyzer (test_analyzers.TestAnalyzers) ... ok
test_cad_3d_analyzer_parametric (test_analyzers.TestAnalyzers) ... ok
test_database_logs_analyzer_sqlite (test_analyzers.TestAnalyzers) ... ok
test_eda_hardware_analyzer_verilog (test_analyzers.TestAnalyzers) ... ok
test_source_code_analyzer_python (test_analyzers.TestAnalyzers) ... ok
test_corrupt_index_backup_safety (test_audit_fixes.TestAuditFixes) ... ok
test_freecad_fcstd_zip_container_parsing (test_audit_fixes.TestAuditFixes) ... ok
test_null_byte_in_python_source (test_audit_fixes.TestAuditFixes) ... ok
test_object_store_checksum_verification (test_audit_fixes.TestAuditFixes) ... ok
test_path_traversal_rejection (test_audit_fixes.TestAuditFixes) ... ok
test_plaintext_detection (test_audit_fixes.TestAuditFixes) ... ok
test_sqlite_injection_safety (test_audit_fixes.TestAuditFixes) ... ok
test_step_cad_brep_handling (test_audit_fixes.TestAuditFixes) ... ok
test_cad_tessellator_step_analysis (test_cad_engine.TestCadEngine) ... ok
test_cad_tessellator_stl_analysis (test_cad_engine.TestCadEngine) ... ok
test_generate_vision_summary (test_cad_engine.TestCadEngine) ... ok
test_step_brep_empty_and_malformed (test_cad_engine.TestCadEngine) ... ok
test_step_brep_parser_geometry (test_cad_engine.TestCadEngine) ... ok
test_blob_storage (test_core.TestCoreObjectStore) ... ok
test_commit_storage (test_core.TestCoreObjectStore) ... ok
test_tree_storage (test_core.TestCoreObjectStore) ... ok
test_add_and_commit (test_core.TestRepositoryOperations) ... ok
test_init_creates_structure (test_core.TestRepositoryOperations) ... ok
test_corrupt_or_malformed_freecad_xml (test_edge_cases.TestEdgeCases) ... ok
test_corrupt_sqlite_db (test_edge_cases.TestEdgeCases) ... ok
test_empty_file_diff (test_edge_cases.TestEdgeCases) ... ok
test_file_deletion_and_addition (test_edge_cases.TestEdgeCases) ... ok
test_long_action_summary_truncation (test_edge_cases.TestEdgeCases) ... ok
test_untracked_and_ignored_directories (test_edge_cases.TestEdgeCases) ... ok
test_hierarchical_tree_creation_and_flattening (test_hierarchical_trees.TestHierarchicalTrees) ... ok
test_subtree_reuse_across_commits (test_hierarchical_trees.TestHierarchicalTrees) ... ok
test_pack_writer_and_reader (test_pack_and_gc.TestPackAndGC) ... ok
test_repository_gc (test_pack_and_gc.TestPackAndGC) ... ok
test_http_server_clone_and_push (test_remote_transport.TestRemoteTransport) ... ok
test_local_clone_and_fetch (test_remote_transport.TestRemoteTransport) ... ok
test_local_push_and_rejection (test_remote_transport.TestRemoteTransport) ... ok
test_remote_manager_crud (test_remote_transport.TestRemoteTransport) ... ok
test_binary_file_system_analysis (test_semantic_differ.TestSemanticDifferAgent) ... ok
test_cad_3d_extrusion_analysis (test_semantic_differ.TestSemanticDifferAgent) ... ok
test_cad_3d_fillet_analysis (test_semantic_differ.TestSemanticDifferAgent) ... ok
test_database_logs_analysis (test_semantic_differ.TestSemanticDifferAgent) ... ok
test_hardware_eda_analysis (test_semantic_differ.TestSemanticDifferAgent) ... ok
test_schema_validity (test_semantic_differ.TestSemanticDifferAgent) ... ok
test_cad_conflicting_parametric_dimensions (test_semantic_merge.TestSemanticMerge) ... ok
test_cad_freecad_parametric_merge (test_semantic_merge.TestSemanticMerge) ... ok
test_python_ast_function_merge (test_semantic_merge.TestSemanticMerge) ... ok
test_repository_branch_and_merge_workflow (test_semantic_merge.TestSemanticMerge) ... ok
test_verilog_eda_semantic_merge (test_semantic_merge.TestSemanticMerge) ... ok
test_watcher_detects_and_analyzes (test_watcher.TestWorkspaceWatcher) ... ok

test_ableton_live_als_project (test_universal_apps.TestUniversalApps) ... ok
test_apache_parquet_detection (test_universal_apps.TestUniversalApps) ... ok
test_autocad_dxf (test_universal_apps.TestUniversalApps) ... ok
test_custom_plugin_registration (test_universal_apps.TestUniversalApps) ... ok
test_godot_scene (test_universal_apps.TestUniversalApps) ... ok
test_kicad_pcb_eda (test_universal_apps.TestUniversalApps) ... ok
test_krita_painting_file (test_universal_apps.TestUniversalApps) ... ok
test_reaper_rpp_session (test_universal_apps.TestUniversalApps) ... ok
test_sketch_design_file (test_universal_apps.TestUniversalApps) ... ok
test_unity_scene_and_prefab (test_universal_apps.TestUniversalApps) ... ok
test_universal_binary_cdc_and_string_dissection (test_universal_apps.TestUniversalApps) ... ok
test_universal_container_fallback_zip (test_universal_apps.TestUniversalApps) ... ok

test_mmap_streaming_blob_write_and_read (test_performance_optimizations.TestPerformanceOptimizations) ... ok
test_pack_reader_json_backward_compatibility (test_performance_optimizations.TestPerformanceOptimizations) ... ok
test_repository_stages_large_file_via_streaming (test_performance_optimizations.TestPerformanceOptimizations) ... ok
test_vid2_binary_pack_index_and_parallel_compression (test_performance_optimizations.TestPerformanceOptimizations) ... ok

----------------------------------------------------------------------
Ran 78 tests in 2.181s

OK
```

---

## License

This project is open-source and available under the [MIT License](LICENSE).
