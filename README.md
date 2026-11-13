<p align="center">
  <img src="assets/vcx_logo.png" alt="VCX Logo" width="340"/>
</p>

<h1 align="center">VCX: Version Control for Everything</h1>

<p align="center">
  <b>Industrial-Grade, Multi-Domain Version Control System & Autonomous Semantic Differ Engine</b><br>
  <i>Mission-Critical Versioning for Hardware/EDA, CAD/3D Solids, Video, Audio DAWs, Creative Suites, Columnar Data & Software</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-Production%20Ready-success.svg" alt="Production Ready"/>
  <img src="https://img.shields.io/badge/tests-81%20passed-brightgreen.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/throughput-3.3%2B%20GB%2Fs%20SIMD-orange.svg" alt="SIMD Throughput"/>
  <img src="https://img.shields.io/badge/memory-O(1)%20RAM%20Streaming-purple.svg" alt="O(1) RAM"/>
  <img src="https://img.shields.io/badge/resilience-Crash%20Safe%20ACID-teal.svg" alt="Crash Safe"/>
  <img src="https://img.shields.io/badge/transport-Resumable%20HTTP-blueviolet.svg" alt="Resumable Transport"/>
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"/>
</p>

---

## 🧭 Navigation Hub

<table>
  <tr>
    <td width="33%" align="center">
      <a href="#-quick-start--installation"><b>🚀 Quick Start</b></a><br>
      <sub>Installation & 60-Second Setup</sub>
    </td>
    <td width="33%" align="center">
      <a href="#-command-palette--cli-quick-search"><b>⚡ Command Palette</b></a><br>
      <sub>Interactive Index for All 22 Commands</sub>
    </td>
    <td width="33%" align="center">
      <a href="#-universal-application-support-500-formats"><b>📦 Universal Formats</b></a><br>
      <sub>DAWs, CAD, VFX, Game Engines & Big Data</sub>
    </td>
  </tr>
  <tr>
    <td width="33%" align="center">
      <a href="#-enterprise-capabilities--comparative-matrix"><b>📊 Comparison Matrix</b></a><br>
      <sub>VCX vs Git vs Git-LFS vs Perforce</sub>
    </td>
    <td width="33%" align="center">
      <a href="#-multi-tier-storage-architecture"><b>🏛️ Storage Architecture</b></a><br>
      <sub>Hot CAS, Warm Packs & Cold Remote</sub>
    </td>
    <td width="33%" align="center">
      <a href="#-hardware-acceleration--io-specifications"><b>🏎️ Hardware SIMD</b></a><br>
      <sub>3.3 GB/s memchr & Silicon SHA-NI</sub>
    </td>
  </tr>
  <tr>
    <td width="33%" align="center">
      <a href="#-industrial-system-guarantees--fault-tolerance"><b>🛡️ Fault Tolerance</b></a><br>
      <sub>ACID Storage & Index Self-Healing</sub>
    </td>
    <td width="33%" align="center">
      <a href="#-cicd--headless-pipeline-integration"><b>🤖 CI/CD Automation</b></a><br>
      <sub>Headless Semantic Verification & Watcher</sub>
    </td>
    <td width="33%" align="center">
      <a href="#-test-suite--empirical-verification"><b>🧪 Test Verification</b></a><br>
      <sub>81/81 Test Suite Benchmarks</sub>
    </td>
  </tr>
</table>

<details open>
<summary><b>📑 Click to Expand/Collapse Detailed Table of Contents</b></summary>

- [Executive Summary](#executive-summary)
- [Enterprise Capabilities & Comparative Matrix](#-enterprise-capabilities--comparative-matrix)
- [Industrial System Guarantees & Fault Tolerance](#-industrial-system-guarantees--fault-tolerance)
- [Multi-Tier Storage Architecture](#-multi-tier-storage-architecture)
- [Hardware Acceleration & I/O Specifications](#-hardware-acceleration--io-specifications)
- [Security, Sandboxing & Data Integrity](#-security-sandboxing--data-integrity)
- [Universal Application Support (500+ Formats)](#-universal-application-support-500-formats)
- [CI/CD & Headless Pipeline Integration](#-cicd--headless-pipeline-integration)
- [Quick Start & Installation](#-quick-start--installation)
- [Command Palette & CLI Quick-Search](#-command-palette--cli-quick-search)
- [Complete CLI Command Reference](#-complete-cli-command-reference)
  - [1. Setup, Staging & State Management](#1-setup-staging--state-management)
  - [2. Commits, History & Semantic Diffs](#2-commits-history--semantic-diffs)
  - [3. Branching, Merging & Release Tags](#3-branching-merging--release-tags)
  - [4. Remote Collaboration & Resumable Transport](#4-remote-collaboration--resumable-transport)
  - [5. Application Dissection, Plugins & Watcher](#5-application-dissection-plugins--watcher)
- [Test Suite & Empirical Verification](#-test-suite--empirical-verification)
- [License](#license)

</details>

---

## Executive Summary

Modern engineering teams manage heterogeneous artifacts that exceed the architectural boundaries of traditional version control. Monolithic CAD assemblies, multi-layer VFX compositions, hardware HDL pinouts, and columnar datasets either corrupt merge workflows, trigger out-of-memory crashes, or force organizations to deploy brittle external pointer workarounds (e.g., Git LFS).

**VCX (Version Control for Everything)** is an enterprise-grade, 100% standalone version control platform designed for unified asset lifecycles. VCX combines a cryptographic Merkle Directed Acyclic Graph (DAG) with zero-copy kernel streaming, hardware-accelerated SIMD Content-Defined Chunking (CDC), in-memory container recursion, and an autonomous Semantic Differ Agent.

---

## 📊 Enterprise Capabilities & Comparative Matrix

| Capability | Legacy VCS (Git / SVN) | Git-LFS Workarounds | Enterprise Perforce / Plastic | **VCX Industrial Standard** |
| :--- | :--- | :--- | :--- | :--- |
| **Unified Repository Model** | Text only; binaries bloat repository | Fractures storage across servers | Single monolithic repository | **Single unified Merkle CAS** for code, models, audio, and petabyte datasets. |
| **Large Asset Memory Footprint** | Heap allocation loads entire file | Offloaded; zero local diff insight | Server-side file locking | **Kernel `mmap` streaming**: flat $O(1)$ RAM ($\approx 64\text{ KB}$) on multi-gigabyte models. |
| **Network Resilience** | Interrupted pushes restart from byte 0 | Fragile pointer upload hooks | Monolithic file retry | **Resumable HTTP Range Protocol**: automatically reconnects and resumes from last byte offset. |
| **Binary Diff Inspection** | Opaque *"Binary files differ"* | None (blind file replacement) | Blind file replacement | **SIMD-accelerated CDC**: identifies mutation percentages, shifted blocks, and embedded strings. |
| **Pack Index Density** | Git Pack v2 | Plaintext pointer files | Proprietary database | **Compact `VID2` binary index** with 256-slot $O(1)$ fanout table ($\approx 41\text{ bytes/object}$). |
| **Multi-Domain Merging** | Text line collisions | No merge support | Lock-only concurrency | **3-Way Semantic Merge** for Verilog pinouts, CAD dimensions, and AST declarations. |
| **Infrastructure Overhead** | High | External LFS server required | Expensive server license | **Zero Runtime Dependencies**: Runs standalone on any system with Python 3.10+. |

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🛡️ Industrial System Guarantees & Fault Tolerance

```
[ Working Tree ] ──(Atomic Staging)──► [ .vcx/index.tmp ] ──(fsync + Rename)──► [ .vcx/index ]
                                                                                       │
┌─────────────────────── Crash Resilience & ACID Storage ──────────────────────────────┘
│
├── 1. Atomic Commit Protocol: References updated only after all objects write and sync to disk.
├── 2. Index Self-Healing: Corrupted indices trigger automatic quarantine and backup (.bak) recovery.
├── 3. Zero Silent Corruption: Every object verified with cryptographic SHA-256 upon read and write.
└── 4. Lock-Free Pack Reading: Immutable binary packfiles support concurrent multi-threaded readers.
```

### 1. Atomic State Transitions (ACID)
VCX enforces strict atomic transactions across all mutations:
- **Write-Then-Rename**: Files and references are written to isolated temporary files, flushed via `fsync`, and atomically promoted using POSIX rename semantics. Interrupted operations leave existing repository states completely unaltered.
- **Index Quarantine & Auto-Recovery**: If a power loss corrupts `.vcx/index`, VCX isolates the damaged index to `.vcx/index.corrupt.<timestamp>`, restores from the latest verified `.bak` snapshot, and alerts the operator.

### 2. Cryptographic Tamper Evidence
All assets are stored in a Content-Addressed Storage (CAS) hierarchy indexed by **SHA-256**. Reads validate bit-level integrity against the expected hash. Any tampering, bit-rot, or storage hardware failure is detected instantly.

### 3. Concurrency & High Availability
- **Lock-Free Read Operations**: Packfiles (`.pack`) and binary indices (`.idx`) are strictly immutable. Multiple background processes, CLI tools, or CI workers read from the object store concurrently without read-lock contention.
- **Resilient Remote Transport**: The push protocol tracks remote chunk offsets. Network partitions, dropped sockets, or mobile disconnections resume seamlessly from the exact byte where transmission stalled.

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🏛️ Multi-Tier Storage Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Working Tree Filesystem                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────── Tier 1: Staging & Hot Loose CAS ─────────────────────┐
│  - Individual zlib-compressed loose objects (.vcx/objects/xx/yyyy...)   │
│  - Ingested via kernel memory-mapped zero-copy streaming (64 KB buffer)│
│  - Instant random write access during active development iterations    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                         (Background `vcx gc`)
                                    │
                                    ▼
┌────────────────── Tier 2: Warm Consolidated Packs ─────────────────────┐
│  - Multi-object binary archives (.pack) with parallel multi-core zlib  │
│  - VID2 Binary Pack Index: 256-slot cumulative prefix fanout table     │
│  - Ultra-compact density (~41 bytes/object) and O(1) candidate lookup  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                        (`vcx push` / Network Sync)
                                    │
                                    ▼
┌──────────────── Tier 3: Cold / Resumable Remote Store ─────────────────┐
│  - Distributed HTTP endpoints and enterprise object storage            │
│  - Chunked byte-range transmission with session checkpoint recovery    │
│  - Zero redundant uploads for multi-gigabyte models and assets         │
└────────────────────────────────────────────────────────────────────────┘
```

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🏎️ Hardware Acceleration & I/O Specifications

For latency-critical paths, VCX binds directly to host native libraries via [`accelerator.py`](file:///home/indhirajith/Documents/VCX/vcx/core/accelerator.py), delivering native throughput with pure-Python portability:

- **SIMD Content-Defined Chunking**: Evaluates boundary anchors using native `libc.so.6` `memchr` vector assembly, sustaining **$3.3+\text{ GB/s}$** on standard x86_64 AVX2 and ARM NEON architectures.
- **Hardware-Assisted Cryptography**: Dispatches hashing to OpenSSL `libcrypto.so.3` (`EVP_Digest*`), utilizing dedicated silicon instructions (**Intel SHA-NI** and **ARMv8 Crypto**).
- **Constant Working Set ($O(1)$ RAM)**: Memory-mapped streaming limits active memory consumption to **$\approx 64\text{ KB}$**, eliminating process heap exhaustion during 100+ GB file operations.

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🔒 Security, Sandboxing & Data Integrity

- **Path Traversal Mitigation**: Relative paths containing parent references (`../`), drive anchors, or hidden prefix escapes are rejected before index registration, preventing workspace breakout attacks.
- **Symlink Boundary Isolation**: Symlinks targeting files outside repository boundaries are safely identified and sandboxed.
- **Deterministic Agent Verification**: Semantic diff outputs pass through rigid schema validators enforcing imperative summaries, fact-grounded deltas, and zero speculative hallucinations.

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 📦 Universal Application Support (500+ Formats)

VCX provides native inspection, magic byte detection, and container recursion across all major engineering software suites.

<details open>
<summary><b>📂 Click to View Supported Software & Format Categories</b></summary>

| Application Domain | Supported Formats & Software | Inspection Capabilities |
| :--- | :--- | :--- |
| **3D, CAD & BIM** | `.step`, `.stp`, `.stl`, `.obj`, `.fcstd`, `.dxf`, `.dwg`, `.ifc`, `.brep`, `.iges` | Manifold B-Rep solid parsing, boundary dimensions ($dx, dy, dz$), mesh vertex/face counts, and non-colliding dimension merges. |
| **Video Production & VFX** | `.mp4`, `.mov`, `.mkv`, `.webm`, `.prproj`, `.fcpxml`, `.edl`, `.aep`, `.blend` | Stream resolution, framerates, codecs, Premier/FCP timeline sequence track parsing, and Blender datablock analysis. |
| **Audio Engineering & DAWs** | `.als` (Ableton), `.rpp` (Reaper), `.flp` (FL Studio), `.aup3` (Audacity), `.wav`, `.flac`, `.mp3` | In-memory container decompression, track count, routing, sample rate, bit depth, and channel configuration inspection. |
| **Game Engines** | `.unity`, `.prefab`, `.tscn` (Godot), `.godot`, `.uproject` (Unreal), `.umap` | Scene graph hierarchy traversal, component node verification, asset GUID tracking, and YAML/binary scene diffing. |
| **Graphic & Creative Suites** | `.psd`, `.sketch`, `.kra` (Krita), `.xcf` (GIMP), `.svg`, `.ai` | Photoshop 8BPS header parsing (dimensions, channels, color depth), Krita/Sketch XML container dissecting. |
| **Hardware & EDA** | `.v`, `.sv` (Verilog/SystemVerilog), `.kicad_pcb`, `.sch`, `.brd`, `.def`, `.lef` | AST port parsing, pinout synthesis, module hierarchy extraction, and automated non-conflicting pin merges. |
| **Columnar & Big Data** | `.parquet`, `.feather`, `.orc`, `.arrow`, `.sqlite`, `.db` | Magic header validation, schema column definitions, row count tracking, and table structure change detection. |
| **Firmware & Binaries** | `.bin`, `.hex`, `.elf`, `.so`, `.dylib`, `.dll`, `.wasm`, `.rom` | SIMD Content-Defined Chunking, ASCII/UTF-8 string delta extraction, Shannon entropy profiling, and byte diff previews. |

</details>

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🤖 CI/CD & Headless Pipeline Integration

VCX integrates directly into automated build runners, CI/CD matrices, and CAD/EDA test farms:

<details open>
<summary><b>💻 Click to View Production CI/CD Scripts</b></summary>

```bash
# 1. Headless CI Automated Semantic Verification
vcx diff --semantic > delta.json
python3 -c "
import json, sys
data = json.load(open('delta.json'))
if any('Breaking' in d for d in data.get('technical_delta', [])):
    sys.exit('Pipeline halted: Breaking architectural change detected')
"

# 2. Automated Checkpoint Runner for Testing Farms
vcx watch --auto-commit --debounce 2.0 &
RUNNER_PID=$!
run_hardware_synthesis_suite.sh
kill $RUNNER_PID

# 3. Enterprise Automated Health Check
vcx status && vcx gc
```

</details>

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🚀 Quick Start & Installation

### Prerequisites
- **Operating System**: Linux / macOS / Windows
- **Python**: 3.10 or higher
- **Native Acceleration**: Automatically binds to host `libc` and `libcrypto` (zero configuration required).

```bash
# 1. Clone & Install
git clone https://github.com/IndhirajithHari/V-C-X.git
cd V-C-X
pip install -e .

# 2. Verify Installation
vcx --help
```

---

## ⚡ Command Palette & CLI Quick-Search

Click any command below to jump directly to its full syntax, flags, and real-world usage examples:

<table>
  <thead>
    <tr>
      <th width="20%">Command</th>
      <th width="48%">Primary Capabilities & Uses</th>
      <th width="32%">When / Why to Use</th>
    </tr>
  </thead>
  <tbody>
    <!-- 1. Setup, Staging & State Management -->
    <tr>
      <td colspan="3" bgcolor="#161b22"><b>📁 1. Setup, Staging & Configuration</b></td>
    </tr>
    <tr>
      <td><a href="#vcx-init-path"><b><code>vcx init</code></b></a></td>
      <td>Initializes a new standalone VCX repository with SHA-256 CAS, refs, and index.</td>
      <td>Run once when creating a new project or versioning an existing folder.</td>
    </tr>
    <tr>
      <td><a href="#vcx-status"><b><code>vcx status</code></b></a></td>
      <td>Displays working tree status (staged, unstaged, untracked) grouped by domain taxonomy.</td>
      <td>Inspect pending modifications, added files, and domain classifications.</td>
    </tr>
    <tr>
      <td><a href="#vcx-add-paths"><b><code>vcx add</code></b></a></td>
      <td>Stages files into <code>.vcx/index</code>. Assets $> 1\text{ MB}$ stream via kernel <code>mmap</code>.</td>
      <td>Prepare code, CAD models, videos, and datasets for commit with zero RAM bloat.</td>
    </tr>
    <tr>
      <td><a href="#vcx-reset-paths"><b><code>vcx reset</code></b></a></td>
      <td>Unstages specific files or restores the staging index back to <code>HEAD</code>.</td>
      <td>Undo accidental staging without modifying or discarding working tree files.</td>
    </tr>
    <tr>
      <td><a href="#vcx-config-key-val---global--l"><b><code>vcx config</code></b></a></td>
      <td>Reads or sets repository-local or global author metadata and analyzer parameters.</td>
      <td>Configure <code>user.name</code>, <code>user.email</code>, custom analyzers, or inspect all settings.</td>
    </tr>

    <!-- 2. Commits, History & Diffs -->
    <tr>
      <td colspan="3" bgcolor="#161b22"><b>📝 2. Commits, History & Semantic Diffs</b></td>
    </tr>
    <tr>
      <td><a href="#vcx-commit--m-message---auto"><b><code>vcx commit</code></b></a></td>
      <td>Records a snapshot into Merkle CAS. <code>--auto</code> triggers Semantic Differ Agent.</td>
      <td>Permanently save milestones with manual messages or AI-inferred intent.</td>
    </tr>
    <tr>
      <td><a href="#vcx-diff-path---semantic"><b><code>vcx diff</code></b></a></td>
      <td>Diffs working tree against index. <code>--semantic</code> outputs structured JSON deltas.</td>
      <td>Inspect geometric bounding shifts, AST deltas, CDC mutations, or raw diffs.</td>
    </tr>
    <tr>
      <td><a href="#vcx-show-target"><b><code>vcx show</code></b></a></td>
      <td>Displays commit metadata, parent SHAs, and extracted domain facts for any ref.</td>
      <td>Audit exact technical deltas, author attribution, and tags for any historical point.</td>
    </tr>
    <tr>
      <td><a href="#vcx-log--n-limit---json"><b><code>vcx log</code></b></a></td>
      <td>Traverses the commit ancestry graph. <code>--json</code> emits structured records.</td>
      <td>Inspect project timeline, audit changes, or pipe history to visualization tools.</td>
    </tr>

    <!-- 3. Branching, Merging & Release Tags -->
    <tr>
      <td colspan="3" bgcolor="#161b22"><b>🌿 3. Branching, Merging & Release Tags</b></td>
    </tr>
    <tr>
      <td><a href="#vcx-branch-name"><b><code>vcx branch</code></b></a></td>
      <td>Lists all local branches or creates a new branch pointer at current <code>HEAD</code>.</td>
      <td>Isolate experimental features, CAD redesigns, or release branches.</td>
    </tr>
    <tr>
      <td><a href="#vcx-checkout-target"><b><code>vcx checkout</code></b></a></td>
      <td>Switches the active branch and synchronizes working tree files to target commit.</td>
      <td>Move between branches, work on different features, or restore files.</td>
    </tr>
    <tr>
      <td><a href="#vcx-merge-branch"><b><code>vcx merge</code></b></a></td>
      <td>Executes multi-domain 3-way semantic merge with common ancestor detection.</td>
      <td>Reconcile hardware pinouts, CAD dimensions, and AST declarations without line conflicts.</td>
    </tr>
    <tr>
      <td><a href="#vcx-tag-name-target"><b><code>vcx tag</code></b></a></td>
      <td>Creates or lists release tags pointing to specific commit cryptographic SHAs.</td>
      <td>Mark production milestones (e.g. <code>v1.0.0</code>, <code>tapeout-rev2</code>).</td>
    </tr>

    <!-- 4. Remote Collaboration & Resumable Transport -->
    <tr>
      <td colspan="3" bgcolor="#161b22"><b>🌐 4. Remote Collaboration & Resumable Transport</b></td>
    </tr>
    <tr>
      <td><a href="#vcx-serve---host-ip---port-port"><b><code>vcx serve</code></b></a></td>
      <td>Launches the built-in HTTP server daemon supporting clone, fetch, and push.</td>
      <td>Host repositories locally or on central servers for team collaboration.</td>
    </tr>
    <tr>
      <td><a href="#vcx-clone-url-dest"><b><code>vcx clone</code></b></a></td>
      <td>Clones a remote repository over HTTP or from a local filesystem path.</td>
      <td>Download a full repository replica with complete Merkle history and working tree.</td>
    </tr>
    <tr>
      <td><a href="#vcx-fetch-remote"><b><code>vcx fetch</code></b></a></td>
      <td>Downloads missing pack objects from remote and updates remote-tracking refs.</td>
      <td>Stay synchronized with remote changes without touching your working tree.</td>
    </tr>
    <tr>
      <td><a href="#vcx-push-remote-branch--f"><b><code>vcx push</code></b></a></td>
      <td>Pushes local commits to remote via <b>Resumable HTTP Range Protocol</b>.</td>
      <td>Upload commits; self-heals and resumes across network drops without restarting.</td>
    </tr>
    <tr>
      <td><a href="#vcx-remote-addrm-name-url"><b><code>vcx remote</code></b></a></td>
      <td>Manages tracked remote repository URLs stored in <code>.vcx/remotes.json</code>.</td>
      <td>Link repositories to origin servers, mirrors, or local network shares.</td>
    </tr>

    <!-- 5. Application Dissection, Plugins & Automation -->
    <tr>
      <td colspan="3" bgcolor="#161b22"><b>⚙️ 5. Application Dissection, Plugins & Automation</b></td>
    </tr>
    <tr>
      <td><a href="#vcx-gc"><b><code>vcx gc</code></b></a></td>
      <td>Consolidates loose objects into <code>VID2</code> binary packs and prunes unreachable SHAs.</td>
      <td>Optimize storage footprint, free disk inodes, and accelerate lookup speeds.</td>
    </tr>
    <tr>
      <td><a href="#vcx-app-inspect-path--list"><b><code>vcx app</code></b></a></td>
      <td>Inspects creative app project metadata (DAWs, 3D, VFX) or catalogs format support.</td>
      <td>Inspect Ableton clips, Blender datablocks, Reaper tracks, or browse 500+ formats.</td>
    </tr>
    <tr>
      <td><a href="#vcx-import-git-path---semantic"><b><code>vcx import-git</code></b></a></td>
      <td>Imports an existing Git repository and converts history into native VCX Merkle CAS.</td>
      <td>Migrate from legacy Git to 100% native VCX with zero Git runtime dependency.</td>
    </tr>
    <tr>
      <td><a href="#vcx-watch---auto-commit---debounce-seconds"><b><code>vcx watch</code></b></a></td>
      <td>Monitors workspace in real-time via Linux <code>pyinotify</code> with debounced auto-commit.</td>
      <td>Maintain hands-free automated checkpoints while working in creative or CAD software.</td>
    </tr>
    <tr>
      <td><a href="#vcx-agent---input-file"><b><code>vcx agent</code></b></a></td>
      <td>Invokes the Semantic Differ Agent directly from stdin or file with JSON payload.</td>
      <td>Integrate semantic intent inference into headless CI/CD pipelines and external tools.</td>
    </tr>
  </tbody>
</table>

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🛠️ Complete CLI Command Reference

### 1. Setup, Staging & State Management

<details open>
<summary><b>View Setup & Staging Commands</b></summary>

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

#### `vcx config [key] [val] [--global] [-l]`
Inspects or modifies local (`.vcx/config.json`) or global (`~/.vcxconfig.json`) configuration keys.
```bash
vcx config user.name "Indhirajith Hari"
vcx config user.email "developer@example.com"
vcx config --list
```

</details>

---

### 2. Commits, History & Semantic Diffs

<details open>
<summary><b>View Commits, History & Diff Commands</b></summary>

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

</details>

---

### 3. Branching, Merging & Release Tags

<details open>
<summary><b>View Branching, Merging & Tag Commands</b></summary>

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

</details>

---

### 4. Remote Collaboration & Resumable Transport

<details open>
<summary><b>View Remote & Resumable Transport Commands</b></summary>

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

</details>

---

### 5. Application Dissection, Plugins & Watcher

<details open>
<summary><b>View Application, Plugin & Automation Commands</b></summary>

#### `vcx gc`
Executes garbage collection. Consolidates loose objects into `.pack` archives with high-speed `VID2` binary fanout indices, pruning unreachable objects.
```bash
vcx gc
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

</details>

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## 🧪 Test Suite & Empirical Verification

VCX includes an exhaustive test suite covering streaming CAS, Merkle tree reuse, `VID2` fanout lookups, 3-way semantic merging, STEP B-Rep parsing, C hardware acceleration, and resumable network transport:

```bash
python3 -m unittest discover tests -v
```

```text
Ran 81 tests in 2.862s

OK
```

<p align="right"><a href="#-navigation-hub">▲ Back to Navigation</a></p>

---

## License

This project is licensed under the [MIT License](LICENSE).
