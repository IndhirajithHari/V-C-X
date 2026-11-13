<p align="center">
  <img src="assets/vcx_logo.png" alt="VCX Logo" width="340"/>
</p>

<h1 align="center">VCX: Version Control for Everything</h1>

<p align="center">
  <b>High-Throughput, Multi-Domain Version Control System & Autonomous Semantic Differ Engine</b><br>
  <i>Universal Support for Source Code, Hardware/EDA, CAD/3D, Video, Audio, Creative Suites, Columnar Data, Firmware & Binaries</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tests-81%20passed-brightgreen.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/throughput-3.3%2B%20GB%2Fs%20SIMD-orange.svg" alt="SIMD Throughput"/>
  <img src="https://img.shields.io/badge/memory-O(1)%20RAM%20Streaming-purple.svg" alt="O(1) RAM"/>
  <img src="https://img.shields.io/badge/remote-Resumable%20HTTP-teal.svg" alt="Resumable Transport"/>
  <img src="https://img.shields.io/badge/runtime-100%25%20Git--Independent-success.svg" alt="Zero Git Dependency"/>
  <a href="https://github.com/codecrafters-io/build-your-own-x"><img src="https://img.shields.io/badge/inspired%20by-build--your--own--x-orange.svg" alt="Build Your Own X"/></a>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"/>
</p>

---

## Table of Contents

- [Overview](#overview)
- [Key Features & Architectural Advantages](#key-features--architectural-advantages)
- [Algorithmic Complexity & Performance](#algorithmic-complexity--performance)
- [How It Works (System Architecture)](#how-it-works-system-architecture)
  - [1. Streaming Content-Addressed Storage (`mmap`)](#1-streaming-content-addressed-storage-mmap)
  - [2. Hierarchical Merkle Trees](#2-hierarchical-merkle-trees)
  - [3. Binary Packfile v2 (`VID2`) & Garbage Collection](#3-binary-packfile-v2-vid2--garbage-collection)
  - [4. C/SIMD Hardware Accelerator (`vcx/core/accelerator.py`)](#4-csimd-hardware-accelerator)
  - [5. Resumable Remote Transfer Protocol](#5-resumable-remote-transfer-protocol)
  - [6. Multi-Domain 3-Way Semantic Merge](#6-multi-domain-3-way-semantic-merge)
  - [7. CAD Solid B-Rep & Mesh Tessellation Engine](#7-cad-solid-b-rep--mesh-tessellation-engine)
  - [8. Autonomous Semantic Differ Agent](#8-autonomous-semantic-differ-agent)
- [Universal Application Support (500+ Formats)](#universal-application-support-500-formats)
- [Installation & Quick Start](#installation--quick-start)
- [Complete CLI Command Reference & Syntax](#complete-cli-command-reference--syntax)
- [Running the Test Suite](#running-the-test-suite)
- [License](#license)

---

## Overview

Traditional version control systems like Git were architected for flat ASCII text files and line-by-line software diffs. When applied to modern engineering assets—such as **Hardware/EDA RTL**, **Parametric 3D CAD assemblies**, **SQLite databases**, **Audio DAWs**, **Video VFX timelines**, or **multi-gigabyte binary models**—traditional tools collapse into opaque binary blobs, line-collision merge conflicts, and repository bloat.

**VCX (Version Control for Everything)** solves this fundamental limitation. Built from first principles in native Python with dynamic C hardware acceleration, VCX pairs a full-featured Git-independent Merkle DAG engine with domain-specific AST analyzers, in-memory container recursion, and an autonomous **Semantic Differ Agent**.

---

## Key Features & Architectural Advantages

| Capability | Traditional VCS (Git / SVN) | Git-LFS | Perforce / Plastic SCM | **VCX Superpower** |
| :--- | :--- | :--- | :--- | :--- |
| **Binary Diff Visibility** | Opaque *"Binary files differ"* | Offloaded; zero diff insight | File locking; binary diffs rare | **Content-Defined Chunking (CDC)** with SIMD boundary cuts, mutation percentage, and string deltas. |
| **Large File Memory** | High heap memory usage | External server pointer files | Server-side locking | **Kernel `mmap` streaming**: flat $O(1)$ RAM ($\approx 64\text{ KB}$) on multi-gigabyte models. |
| **Remote Interruption** | Restart push from byte 0 | Fragile upload hooks | Monolithic chunk retry | **Resumable HTTP Range Protocol**: automatic status recovery and byte-offset resumption. |
| **Pack Index Density** | Git Pack v2 | Plaintext pointers | Proprietary database | **Compact `VID2` binary index** with 256-slot $O(1)$ fanout table ($\approx 41\text{ bytes/object}$). |
| **Domain Merges** | Line collisions | No merge support | Branch locking | **Multi-domain 3-way semantic merge** for Verilog pinouts, CAD dimensions, and AST declarations. |
| **Runtime Independence** | Requires native `git` CLI | Requires `git-lfs` extension | Heavy daemon required | **100% Native**: Zero runtime Git dependencies; operates anywhere Python 3.10+ exists. |

---

## Algorithmic Complexity & Performance

| Subsystem | Operation | Time Complexity | Space Complexity (RAM) | Throughput / Benchmark |
| :--- | :--- | :--- | :--- | :--- |
| **Object Ingestion** | Staging / Blob Write | $O(N)$ streaming | **$O(1)$ RAM** ($\approx 64\text{ KB}$ buffer) | $\approx 500\text{ MB/s}$ (Disk bounded) |
| **Pack Index Lookup** | Object SHA Resolution | **$O(1)$ prefix jump** + $O(\log_2(N/256))$ | $\approx 41\text{ bytes}$ per object | $\le 8$ bisect comparisons for 65k objects |
| **Pack Compression** | Multi-Core Packing | $O(N / P)$ where $P = \text{CPU cores}$ | Flat pool per worker thread | Multi-threaded parallel zlib |
| **CDC Binary Dissector** | Content Boundary Cuts | $O(N)$ via vectorized `memchr` | $O(1)$ scanning overhead | **$3.3+\text{ GB/s}$ SIMD scan** |
| **Hash Verification** | SHA-256 Digest | $O(N)$ with SHA-NI silicon | $O(1)$ buffer | Hardware accelerated via OpenSSL EVP |
| **Resumable Push** | Network Transfer | $O(N)$ chunked stream | $O(\text{chunk\_size})$ (default 512 KB) | Self-healing across disconnections |

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
                            |     Domain Classifier & Sniffer        |
                            |  * 500+ Extension Taxonomy             |
                            |  * Magic Byte Signature Sniffer        |
                            +-------------------+--------------------+
                                                |
                                                v
                            +----------------------------------------+
                            |        Domain Analyzers & CDC          |
                            |  * Python/Verilog AST * STEP B-Rep     |
                            |  * Universal Container * SIMD CDC      |
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
        |  Multi-Domain 3-Way Merger    |               |  Pack v2 & GC (VID2 Index)    |
        |  * Verilog Port Synthesis     |               |  * Multi-Core Parallel Comp.  |
        |  * CAD Parametric Dimensions  |               |  * 256-Slot O(1) Fanout Table |
        |  * AST Function Composition   |               |  * Prunes Dangling Objects    |
        +-------------------------------+               +-------------------------------+
                        |                                               |
                        +-----------------------+-----------------------+
                                                |
                                                v
                            +----------------------------------------+
                            |    Resumable Remote HTTP Transport     |
                            |   * vcx serve (HTTP Daemon)            |
                            |   * Resumable Byte-Range Push / Fetch  |
                            +----------------------------------------+
```

### 1. Streaming Content-Addressed Storage (`mmap`)
Objects (`blob`, `tree`, `commit`, `tag`) are identified by cryptographic **SHA-256** digests. When storing large assets, [`ObjectStore.write_blob_stream`](file:///home/indhirajith/Documents/VCX/vcx/core/object_store.py) memory-maps the source file via the OS kernel page cache, calculating digests and streaming compressed 64 KB blocks directly to disk with constant memory consumption.

### 2. Hierarchical Merkle Trees
VCX constructs recursive Git-style tree objects:
- Subdirectories are stored as discrete `tree` objects with mode `040000`.
- Leaf files are referenced as `blob` objects with executable or standard permissions (`100755` / `100644`).
- **Merkle Subtree Reuse**: Unchanged subdirectories retain their tree SHA and are completely reused across commits, allowing instant commits regardless of project size.

### 3. Binary Packfile v2 (`VID2`) & Garbage Collection
To prevent loose files from exhausting filesystem inodes:
- `PackWriter` consolidates objects into indexed `.pack` archives accompanied by compact **`VID2` binary index files**.
- The `VID2` format features a **256-slot cumulative prefix fanout table**, cutting the search interval by a factor of 256 in $O(1)$ time before performing binary bisect lookups.
- `vcx gc` traces reachability from branch heads and tags, writes packfiles, and unlinks unreferenced loose objects.

### 4. C/SIMD Hardware Accelerator
Hotspots are accelerated via [`accelerator.py`](file:///home/indhirajith/Documents/VCX/vcx/core/accelerator.py):
- **AVX2/SIMD Boundary Cuts**: Uses `libc.so.6` `memchr` vector assembly to scan content boundaries at **$3.3+\text{ GB/s}$**.
- **Hardware Cryptography**: Binds to OpenSSL `libcrypto.so.3` `EVP_Digest*` routines to leverage Intel SHA-NI and ARMv8 Crypto instructions.
- **Pure-Python Fallback**: Gracefully falls back to pure Python if system C libraries are absent.

### 5. Resumable Remote Transfer Protocol
The built-in HTTP transport ([`transport.py`](file:///home/indhirajith/Documents/VCX/vcx/remote/transport.py) and [`server.py`](file:///home/indhirajith/Documents/VCX/vcx/remote/server.py)) features an enterprise-grade resumable upload protocol:
- Negotiates an upload session via `POST /vcx-upload-session/init`.
- Streams chunked byte ranges with `Content-Range: bytes START-END/TOTAL`.
- If an upload drops due to network failure, the client polls `GET /vcx-upload-session/status` to determine the exact number of bytes safely stored on the server, and immediately resumes transmission without re-uploading prior bytes.

### 6. Multi-Domain 3-Way Semantic Merge
Unlike line-based tools, VCX resolves conflicts using common ancestors and domain semantics:
- **Verilog/EDA**: Computes disjoint pinout additions and merges new input/output declarations without collision.
- **CAD/3D Parametric**: Reconciles independent dimension modifications (e.g., branch A lengthens chassis while branch B adds an edge fillet). Identical conflicting dimensions generate structured parametric conflict markers.
- **Python / Software**: Reconciles non-overlapping functions, classes, and import declarations.

### 7. CAD Solid B-Rep & Mesh Tessellation Engine
- **STEP Parser (`StepBrepParser`)**: Parses ISO-10303-21 manifold entities (`MANIFOLD_SOLID_BREP`, `ADVANCED_FACE`, `CLOSED_SHELL`, `CARTESIAN_POINT`), validating manifold topology and calculating exact 3D extents (`[dx, dy, dz]` in mm).
- **Mesh Analyzer (`CadTessellator`)**: Evaluates STL/OBJ watertightness, vertex/face counts, and produces viewport summaries.

### 8. Autonomous Semantic Differ Agent
Inspects delta facts and AST structures to produce structured commit descriptions conforming to a strict JSON schema:

```json
{
  "action_summary": "Imperative tense, < 50 characters",
  "technical_delta": [
    "Specific technical detail 1",
    "Specific technical detail 2"
  ],
  "inferred_intent": "Explanation of why this change was made based on domain context.",
  "tags": ["array", "of", "relevant", "tags"]
}
```

---

## Universal Application Support (500+ Formats)

VCX provides native domain intelligence and magic byte sniffing across hundreds of formats:

```
├── 3D, CAD & BIM:       .step, .stp, .stl, .obj, .fcstd, .dxf, .dwg, .ifc, .brep, .iges
├── Video & VFX:         .mp4, .mov, .mkv, .webm, .prproj, .fcpxml, .edl, .aep, .blend
├── Audio & DAWs:        .als (Ableton), .rpp (Reaper), .flp, .aup3, .wav, .flac, .mp3
├── Game Engines:        .unity, .prefab, .tscn, .godot, .uproject, .umap
├── Creative Design:     .psd, .sketch, .kra (Krita), .xcf (GIMP), .svg, .ai
├── Hardware & EDA:      .v, .sv, .kicad_pcb, .kicad_sch, .sch, .brd, .def, .lef
├── Columnar & Big Data: .parquet, .feather, .orc, .arrow, .sqlite, .db
├── Firmware & Binaries: .bin, .hex, .elf, .so, .dylib, .dll, .wasm, .rom
└── Container Formats:   In-memory recursive dissection for ZIP, Gzip, Tar, and SQLite
```

---

## Installation & Quick Start

### Prerequisites
- **Operating System**: Linux / macOS / Windows
- **Python**: 3.10 or higher
- **Optional**: Standard C runtime (`libc.so.6`, `libcrypto.so.3`) for hardware acceleration (automatically detected).

### 1. Installation
```bash
git clone https://github.com/IndhirajithHari/V-C-X.git
cd V-C-X
pip install -e .
```

### 2. Verify Installation
```bash
vcx --help
```

---

## Complete CLI Command Reference & Syntax

### Repository Setup & Staging

#### `vcx init [path]`
Initializes a new VCX repository. Creates `.vcx/` directory structure with object store, references, and default configuration.
```bash
vcx init
vcx init /path/to/project
```

#### `vcx status`
Displays the state of the working directory and staging index, grouped by domain classification.
```bash
vcx status
```

#### `vcx add <paths...>`
Stages files or directories into `.vcx/index`. Automatically routes files $> 1\text{ MB}$ to memory-mapped streaming storage.
```bash
vcx add model.step design.v
vcx add .
```

#### `vcx reset [paths...]`
Unstages files from the staging index or restores the staging index to `HEAD`.
```bash
vcx reset model.step
vcx reset
```

---

### Commits, History & Diffs

#### `vcx commit [-m "<message>"] [--auto]`
Creates a new commit from the staged snapshot.
- `-m, --message`: User-specified commit message.
- `--auto`: Invokes the autonomous Semantic Differ Agent to infer intent and technical deltas automatically.
```bash
vcx commit -m "feat(cad): expand chassis mounting brackets"
vcx commit --auto
```

#### `vcx diff [path] [--semantic]`
Shows changes between the working tree and the staging index, or between commits.
- `--semantic`: Emits structured JSON matching the Semantic Differ schema.
```bash
vcx diff
vcx diff chassis.step
vcx diff --semantic
```

#### `vcx show [target]`
Displays detailed metadata, parent SHAs, domain facts, and technical deltas for a specific commit or tag (defaults to `HEAD`).
```bash
vcx show
vcx show 8b4e2519
```

#### `vcx log [-n <limit>] [--json]`
Prints the commit ancestry graph with authors, timestamps, and semantic summaries.
- `-n`: Limits the number of commits displayed.
- `--json`: Outputs history as an array of JSON commit records.
```bash
vcx log -n 5
vcx log --json
```

---

### Branching, Merging & Tags

#### `vcx branch [name]`
Lists existing branches or creates a new branch pointer at `HEAD`.
```bash
vcx branch
vcx branch feature/aerodynamics
```

#### `vcx checkout <target>`
Switches the active branch and updates the working tree.
```bash
vcx checkout main
vcx checkout feature/aerodynamics
```

#### `vcx tag [name] [target]`
Creates or lists release tags pointing to commit SHAs.
```bash
vcx tag
vcx tag v1.0.0
vcx tag v1.0.0 8b4e2519
```

#### `vcx merge <branch>`
Executes a multi-domain 3-way semantic merge with common ancestor detection. Reconciles disjoint pinouts, non-colliding CAD dimensions, and AST declarations.
```bash
vcx merge feature/aerodynamics
```

---

### Maintenance & Optimization

#### `vcx gc`
Executes garbage collection. Consolidates loose objects into `.pack` archives with high-speed `VID2` binary fanout indices, pruning unreachable objects.
```bash
vcx gc
```

#### `vcx config [key] [val] [--global] [-l]`
Inspects or modifies local (`.vcx/config.json`) or global (`~/.vcxconfig.json`) configuration keys.
```bash
vcx config user.name "Indhirajith Hari"
vcx config user.email "developer@example.com"
vcx config --list
```

#### `vcx app inspect <path> | list`
Inspects project metadata for creative applications, game engines, and DAWs, or prints the universal format taxonomy.
```bash
vcx app inspect track.als
vcx app list
```

#### `vcx import-git [path] [--semantic]`
Imports an existing Git repository's complete commit history into native VCX Merkle CAS storage.
```bash
vcx import-git .
vcx import-git /path/to/git/repo --semantic
```

---

### Remote Transport & Collaboration

#### `vcx remote [add|rm] [name] [url]`
Manages tracked remote repository endpoints in `.vcx/remotes.json`.
```bash
vcx remote
vcx remote add origin http://127.0.0.1:8000
vcx remote rm origin
```

#### `vcx serve [--host <ip>] [--port <port>]`
Launches the built-in HTTP server daemon for clone, fetch, and resumable push operations.
```bash
vcx serve --host 0.0.0.0 --port 8080
```

#### `vcx clone <url> [dest]`
Clones a remote repository over HTTP or from a local filesystem path.
```bash
vcx clone http://127.0.0.1:8080 my-project
vcx clone /path/to/source-repo my-project
```

#### `vcx fetch [remote]`
Fetches missing packfile objects from the remote and updates remote-tracking references (`refs/remotes/<remote>/<branch>`).
```bash
vcx fetch origin
```

#### `vcx push [remote] [branch] [-f]`
Pushes local commits to the remote using the **Resumable HTTP Range Protocol**. Automatically resumes interrupted transfers without data loss.
```bash
vcx push origin main
vcx push origin main -f
```

---

### Automation & Continuous Watcher

#### `vcx watch [--auto-commit] [--debounce <seconds>]`
Monitors the workspace in real-time using Linux kernel `pyinotify`. Live-streams semantic deltas and optionally creates automatic checkpoint commits.
```bash
vcx watch
vcx watch --auto-commit --debounce 1.0
```

#### `vcx agent [--input <file>]`
Runs the Semantic Differ Agent directly from standard input or a JSON file.
```bash
vcx agent --input delta_facts.json
```

---

## Running the Test Suite

VCX includes an exhaustive unit and integration test suite covering streaming CAS, hierarchical Merkle trees, VID2 binary fanout indexing, 3-way semantic merging, STEP B-Rep parsing, C hardware acceleration, and resumable network transport:

```bash
python3 -m unittest discover tests -v
```

```text
Ran 81 tests in 2.862s

OK
```

---

## License

This project is licensed under the [MIT License](LICENSE).
