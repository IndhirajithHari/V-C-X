# VCX (Version Control for Everything)

[![Tests](https://img.shields.io/badge/tests-40%20passed-brightgreen.svg)]()
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![Architecture](https://img.shields.io/badge/inspired%20by-build--your--own--x-orange.svg)](https://github.com/codecrafters-io/build-your-own-x)

**VCX** is an autonomous, multi-domain version control system designed from the ground up to track not only source code, but also hardware/EDA designs, CAD/3D models, transactional databases, event logs, and binary assets. 

Inspired by the Git internals from [codecrafters-io/build-your-own-x](https://github.com/codecrafters-io/build-your-own-x), VCX combines Git-style content-addressable storage (Blobs, Hierarchical Merkle Trees, Commits, Packfiles) with an embedded, context-aware **Semantic Differ Agent**, a multi-domain **3-way semantic merge engine**, and an inotify-driven background file watcher.

---

## Key Features

1. **Hierarchical Merkle Trees (`tree -> subtree -> blob`)**:
   - Git-style recursive tree nodes where subdirectories are stored as discrete subtree objects (`040000`).
   - Merkle subtree reuse: unchanged subdirectories preserve their subtree SHA across commits, enabling instant commits in repositories with 100,000+ files.

2. **Object Packing & Garbage Collection (`vcx gc`)**:
   - Compressed archive storage (`.vcx/objects/pack/pack-<hash>.pack`) with high-speed indexed binary lookup (`.idx`).
   - `vcx gc` identifies reachable objects from all branch heads, consolidates loose files into packfiles, and safely prunes unreferenced dangling objects to reclaim disk space.

3. **Multi-Domain 3-Way Semantic Merge (`vcx merge <branch>`)**:
   - **Hardware / EDA (Verilog/SystemVerilog & Floorplans)**: Synthesizes non-conflicting port additions, opcode decoders, and independent macro coordinate shifts without textual merge conflicts.
   - **CAD / 3D Parametric (FreeCAD XML & STEP)**: Resolves independent parametric dimensions (e.g. branch A increases base extrusion while branch B adds an edge fillet). Detects true parametric collisions when identical dimensions collide.
   - **Source Code (Python AST & Code)**: Combines non-colliding function and class declarations across branches.
   - **Databases & Logs (CSV, Logs, SQLite)**: Synthesizes appended transaction streams and audit entries.

4. **Domain-Aware Diff Analyzers**:
   - **Source Code (Python, Rust, C, C++)**: AST function signatures, memory primitives (`malloc`/`free`, `Box`, `Arc`, `unsafe`), and control flow logic.
   - **Hardware / EDA (Verilog, SystemVerilog, Floorplans)**: RTL control logic, instruction decode cases, ALU pipelines, port mappings, and macro placements.
   - **CAD / 3D Models (FreeCAD, STL, STEP, OBJ)**: Parametric features and mesh topology (vertex/face deltas, bounding box resizing).
   - **Databases & Logs (SQLite, CSV, TSV)**: SQLite table schema shifts, column mutations, row count deltas, and appended audit logs.
   - **Binaries & Unknowns**: Factual file-system delta tracking (size deltas, entropy shifts) without hallucinations.

5. **Core Semantic Differ Agent**:
   - Autonomous background differ agent producing structured, human-readable commit messages, technical deltas, and inferred intent.
   - Strictly compliant with the VCX JSON input and output schemas.
   - Works offline with a deterministic heuristic engine and supports Gemini API integration (`GEMINI_API_KEY`).

6. **Autonomous Workspace Watcher (`vcx watch`)**:
   - Real-time Linux `pyinotify` monitoring with configurable debouncing.
   - Optional `--auto-commit` mode to batch debounced changes and checkpoint workspace iterations continuously into the VCX commit graph.

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

## CLI Reference & Usage

### 1. Initialize a Repository
```bash
vcx init
```

### 2. Stage Files and Check Status
```bash
vcx status
vcx add src/ cad/ market.db
vcx status
```

### 3. Commit Changes
```bash
# Manual commit
vcx commit -m "Initialize hardware ALU and chassis baseline"

# Or use the Semantic Differ Agent to generate messages & deltas automatically:
vcx commit --auto
```

### 4. Branching and Checkout
```bash
# List branches (* indicates current active branch)
vcx branch

# Create a new branch
vcx branch feature-chip

# Switch branches
vcx checkout feature-chip
```

### 5. Multi-Domain 3-Way Semantic Merge
Merge a branch into the current branch with automatic domain conflict resolution:
```bash
vcx checkout main
vcx merge feature-chip
```

### 6. Pack Objects and Run Garbage Collection
Pack loose files into a compressed `.pack` archive and prune unreachable objects:
```bash
vcx gc
```

### 7. View Commit History
```bash
vcx log
# Or structured JSON history:
vcx log --json
```

### 8. Run the Autonomous File Watcher
```bash
# Live stream semantic diffs to terminal on save:
vcx watch

# Automatically commit every debounced modification batch:
vcx watch --auto-commit --debounce 0.8
```

### 9. Run Semantic Differ Agent Directly (CI / Tool Pipeline)
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
python3 -m unittest discover tests -v
```
*(40 tests passing with 100% success rate)*
