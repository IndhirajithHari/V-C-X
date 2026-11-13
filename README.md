# VCX (Version Control for Everything)

[![Tests](https://img.shields.io/badge/tests-17%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![Architecture](https://img.shields.io/badge/inspired%20by-build--your--own--x-orange.svg)](https://github.com/codecrafters-io/build-your-own-x)

**VCX** is an autonomous, multi-domain version control system designed from the ground up to track not only source code, but also hardware/EDA designs, CAD/3D models, transactional databases, event logs, and binary assets. 

Inspired by the Git internals from [codecrafters-io/build-your-own-x](https://github.com/codecrafters-io/build-your-own-x), VCX pairs content-addressable storage (Blobs, Trees, Commits) with an embedded, context-aware **Semantic Differ Agent** and an inotify-driven background file watcher.

---

## Key Features

1. **Content-Addressable Object Store (`.vcx/objects`)**:
   - SHA-256 hashed and zlib-compressed storage format.
   - Canonical trees and commits with parent references and rich semantic delta attachments.
   - Staging index (`.vcx/index`) tracking modes, hashes, sizes, mtimes, and detected domain types.

2. **Domain-Aware Diff Analyzers**:
   - **Source Code (Python, Rust, C, C++)**: AST function signatures, class hierarchies, memory primitives (`malloc`/`free`, `Box`, `Arc`, `unsafe`), and control flow logic.
   - **Hardware / EDA (Verilog, SystemVerilog, Floorplans)**: Register transfer level (RTL) logic, instruction decode cases, ALU pipelines, port mappings, and macro placement coordinates.
   - **CAD / 3D Models (FreeCAD, STL, STEP, OBJ)**: Parametric features (extrusions, fillets, chamfers) and mesh topology (vertex/face deltas, bounding box resizing).
   - **Databases & Logs (SQLite, CSV, TSV)**: SQLite table schema shifts, column mutations, row count deltas, and appended audit logs.
   - **Binaries & Unknowns**: Factual file-system delta tracking (size deltas, entropy shifts) without hallucinations.

3. **Core Semantic Differ Agent**:
   - Autonomous background differ agent producing structured, human-readable commit messages, technical deltas, and inferred intent.
   - Fully compliant with the strict VCX JSON input and output schemas.
   - Works offline with a deterministic heuristic engine and supports Gemini API integration (`GEMINI_API_KEY`).

4. **Autonomous Workspace Watcher (`vcx watch`)**:
   - Real-time Linux `pyinotify` monitoring with configurable debouncing.
   - Optional `--auto-commit` mode to checkpoint workspace iterations continuously into the VCX commit graph.

---

## Installation

Install in editable mode:

```bash
git clone https://github.com/your-username/VCX.git
cd VCX
pip install -e .
```

Verify installation:

```bash
vcx --help
```

---

## Quick Start CLI Usage

### 1. Initialize a Repository
```bash
vcx init
```

### 2. Stage Files and Check Status
```bash
vcx status
vcx add alu.v chassis.fcstd market.db
vcx status
```

### 3. Commit Changes with Semantic Commit Messages
Manual commit:
```bash
vcx commit -m "Add initial hardware and mechanical models"
```
Or use the **Semantic Differ Agent** to automatically infer the commit message and technical delta:
```bash
vcx commit --auto
```

### 4. Inspect Semantic Diffs
View domain-aware JSON diff payload:
```bash
vcx diff --semantic
```

### 5. View Commit History
```bash
vcx log
# Or structured JSON history:
vcx log --json
```

### 6. Run the Autonomous File Watcher
```bash
# Watch for workspace changes and stream semantic diffs
vcx watch

# Automatically commit every debounced modification
vcx watch --auto-commit --debounce 0.8
```

### 7. Run Semantic Differ Agent Directly (CLI / CI Integration)
Pipe an input JSON payload directly:
```bash
echo '{
  "file_name": "riscv_alu.v",
  "file_type": "eda/verilog",
  "previous_metadata": {},
  "current_metadata": {},
  "raw_diff": "+ always @(posedge clk) case (opcode)",
  "vision_summary": ""
}' | vcx agent
```
Outputs strictly valid JSON:
```json
{
  "action_summary": "Update RISC-V ALU pipeline logic",
  "technical_delta": [
    "Modified sequential always @(posedge clk) control logic",
    "Updated instruction decode case branch mappings"
  ],
  "inferred_intent": "Improve ALU execution stage throughput and instruction decode timing.",
  "tags": [
    "eda-hardware",
    "risc-v",
    "pipeline"
  ]
}
```

---

## Running the Test Suite

Execute the unit tests:

```bash
python3 -m unittest discover tests
```
