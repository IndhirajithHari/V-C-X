"""Command Line Interface for VCX."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
from typing import List, Optional

from vcx.agent.schemas import DifferInput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.core.repository import Repository
from vcx.diff.delta_engine import DeltaEngine
from vcx.diff.detector import detect_file_type
from vcx.engine import VCXEngine
from vcx.watcher.watcher import WorkspaceWatcher

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    _HAS_RICH = True
except ImportError:
    Console = None
    _HAS_RICH = False

_console = Console() if _HAS_RICH else None


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path or ".").resolve()
    repo = Repository.init(target)
    print(f"Initialized empty VCX repository in {repo.vcx_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    st = repo.status()
    print(f"On branch {st['branch']}\n")

    if st["staged"]:
        print("Changes to be committed (staged):")
        for item in st["staged"]:
            print(f"  \033[32m{item['type']:<10} {item['path']} [{item['file_type']}]\033[0m")
        print()

    if st["unstaged"]:
        print("Changes not staged for commit:")
        for item in st["unstaged"]:
            print(f"  \033[31m{item['type']:<10} {item['path']} [{item['file_type']}]\033[0m")
        print()

    if st["untracked"]:
        print("Untracked files:")
        for item in st["untracked"]:
            print(f"  \033[33m?          {item['path']} [{item['file_type']}]\033[0m")
        print()

    if not st["staged"] and not st["unstaged"] and not st["untracked"]:
        print("nothing to commit, working tree clean")

    return 0


def cmd_add(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    staged = repo.add(args.paths)
    if not staged:
        print("No files were staged.")
    else:
        for p in staged:
            print(f"Staged {p}")
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    try:
        commit_sha, commit = repo.commit(message=args.message, auto=args.auto)
        short_sha = commit_sha[:8]
        print(f"[{short_sha}] {commit.message}")
        if commit.semantic_delta:
            deltas = commit.semantic_delta.get("technical_delta", [])
            for d in deltas:
                print(f"  * {d}")
            tags = commit.semantic_delta.get("tags", [])
            if tags:
                print(f"  Tags: {', '.join(tags)}")
        return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_diff(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    st = repo.status()
    all_changes = st["staged"] + st["unstaged"]
    if not all_changes:
        print("No changes found.")
        return 0

    engine = DeltaEngine()
    agent = SemanticDifferAgent()

    target_filter = None
    if args.path:
        try:
            target_filter = repo._sanitize_path(args.path)
        except ValueError as e:
            print(f"fatal: {e}", file=sys.stderr)
            return 1

    for item in all_changes:
        rel_path = item["path"]
        if target_filter and target_filter != rel_path:
            continue

        head_entries = repo.get_head_tree_entries()
        old_sha = head_entries[rel_path].sha if rel_path in head_entries else None
        old_bytes = repo.store.read_blob(old_sha) if old_sha else None

        full_path = repo.root / rel_path
        new_bytes = full_path.read_bytes() if full_path.exists() else None

        payload = engine.analyze_change(rel_path, old_bytes, new_bytes)

        if args.semantic:
            output = agent.analyze(payload.to_dict())
            print(output.to_json())
        else:
            print(f"--- diff for {rel_path} [{payload.file_type}] ---")
            if payload.raw_diff:
                print(payload.raw_diff)
            elif payload.vision_summary:
                print(f"Vision Summary: {payload.vision_summary}")
            print()

    return 0


def cmd_log(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    commits = repo.log(limit=args.limit)
    if not commits:
        print("No commits yet.")
        return 0

    if args.json:
        out = [
            {"sha": sha, "commit": commit.to_dict()}
            for sha, commit in commits
        ]
        print(json.dumps(out, indent=2))
        return 0

    for sha, commit in commits:
        t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(commit.timestamp))
        print(f"\033[33mcommit {sha}\033[0m")
        print(f"Author: {commit.author}")
        print(f"Date:   {t_str}\n")
        print(f"    {commit.message}\n")
        if commit.semantic_delta:
            for item in commit.semantic_delta.get("technical_delta", []):
                print(f"    - {item}")
            if commit.semantic_delta.get("inferred_intent"):
                print(f"\n    Intent: {commit.semantic_delta['inferred_intent']}")
            if commit.semantic_delta.get("tags"):
                print(f"    Tags:   [{', '.join(commit.semantic_delta['tags'])}]")
            print()
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    def handle_change(payload, output):
        print(f"\n\033[36m[VCX Watcher Detected Change]\033[0m {payload.file_name} ({payload.file_type})")
        print(output.to_json())

    watcher = WorkspaceWatcher(
        repo=repo,
        debounce_seconds=args.debounce,
        auto_commit=args.auto_commit,
        on_change_callback=handle_change,
    )

    print(f"Starting VCX Watcher on {repo.root} (auto_commit={args.auto_commit}, debounce={args.debounce}s)...")
    print("Press Ctrl+C to stop.")
    watcher.start()
    try:
        while True:
            time.sleep(1)
            if not watcher._thread or not watcher._thread.is_alive():
                print("fatal: background watcher process terminated unexpectedly", file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        print("\nStopping VCX Watcher...")
        watcher.stop()
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    """Run the Semantic Differ Agent directly from stdin or file."""
    if args.input:
        text = Path(args.input).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"fatal: invalid JSON input: {e}", file=sys.stderr)
        return 1

    agent = SemanticDifferAgent()
    output = agent.analyze(data)

    # Output ONLY valid JSON matching exact schema, without markdown formatting or conversational text
    print(output.to_json())
    return 0


def cmd_branch(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    if args.name:
        try:
            repo.create_branch(args.name)
            print(f"Created branch '{args.name}'")
            return 0
        except ValueError as e:
            print(f"fatal: {e}", file=sys.stderr)
            return 1

    branches = repo.list_branches()
    for name, is_current in branches:
        prefix = "* " if is_current else "  "
        color = "\033[32m" if is_current else ""
        reset = "\033[0m" if is_current else ""
        print(f"{prefix}{color}{name}{reset}")
    return 0


def cmd_checkout(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    try:
        repo.checkout(args.target)
        print(f"Switched to branch/commit '{args.target}'")
        return 0
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1


def cmd_merge(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    try:
        result = repo.merge(args.branch)
        if result.success:
            print(f"Merge successful: integrated '{args.branch}' into {repo.head_ref or 'HEAD'}")
            if result.semantic_resolutions:
                print("Semantic resolutions applied:")
                for r in result.semantic_resolutions:
                    print(f"  * {r}")
            return 0
        else:
            print(f"\033[31mAutomatic merge failed with conflicts:\033[0m", file=sys.stderr)
            for c in result.conflicts:
                print(f"  [{c.domain}] {c.path}: {c.description}", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1


def cmd_gc(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    stats = repo.gc()
    print("VCX Garbage Collection Complete:")
    print(f"  * Packed objects:   {stats['packed_objects']}")
    print(f"  * Pruned objects:   {stats['pruned_objects']}")
    if stats.get("packfile"):
        print(f"  * Generated pack:   {stats['packfile']}")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    pack_path, idx_path = repo.pack()
    if pack_path:
        print(f"Packed repository objects into {pack_path.name}")
    else:
        print("All reachable repository objects are already packed.")
    return 0


def cmd_remote(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    if args.action == "add":
        if not args.name or not args.url:
            print("error: 'remote add' requires name and url", file=sys.stderr)
            return 1
        repo.remotes.add(args.name, args.url)
        print(f"Added remote '{args.name}' -> {args.url}")
        return 0
    elif args.action == "rm":
        if not args.name:
            print("error: 'remote rm' requires name", file=sys.stderr)
            return 1
        repo.remotes.remove(args.name)
        print(f"Removed remote '{args.name}'")
        return 0

    remotes = repo.remotes.list_all()
    if not remotes:
        print("No remotes configured.")
    else:
        for name, url in remotes.items():
            print(f"{name}\t{url}")
    return 0


def cmd_clone(args: argparse.Namespace) -> int:
    from vcx.remote.transport import RemoteTransport
    dest = args.dest or Path(args.url.rstrip("/").split("/")[-1])
    try:
        print(f"Cloning from '{args.url}' into '{dest}'...")
        repo = RemoteTransport.clone(args.url, dest)
        print(f"Clone complete. Head at {repo.head_commit_sha[:8] if repo.head_commit_sha else 'empty'}")
        return 0
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1


def cmd_fetch(args: argparse.Namespace) -> int:
    from vcx.remote.transport import RemoteTransport
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    try:
        print(f"Fetching from remote '{args.remote}'...")
        refs = RemoteTransport.fetch(repo, remote_name=args.remote)
        if not refs:
            print("Already up to date.")
        else:
            for branch, sha in refs.items():
                print(f"  * [{args.remote}/{branch}] -> {sha[:8]}")
        return 0
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1


def cmd_push(args: argparse.Namespace) -> int:
    from vcx.remote.transport import RemoteTransport
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    try:
        print(f"Pushing to '{args.remote}'...")
        msg = RemoteTransport.push(repo, remote_name=args.remote, branch=args.branch, force=args.force)
        print(msg)
        return 0
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1


def cmd_serve(args: argparse.Namespace) -> int:
    from vcx.remote.server import VcxServer
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    server = VcxServer(repo, host=args.host, port=args.port)
    try:
        server.start(background=False)
    except KeyboardInterrupt:
        print("\nStopping VCX Server...")
        server.stop()
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    from vcx.core.config import ConfigManager
    try:
        repo = Repository.find()
        cfg = repo.config
    except Exception:
        cfg = ConfigManager()

    if args.list:
        all_cfg = cfg.list_all()
        for k, v in sorted(all_cfg.items()):
            print(f"{k} = {v}")
        return 0

    if not args.key:
        print("error: config requires key (or --list)", file=sys.stderr)
        return 1

    if args.value is None:
        val = cfg.get(args.key)
        if val is not None:
            print(val)
        return 0

    cfg.set(args.key, args.value, global_scope=args.global_scope)
    print(f"Set {'global ' if args.global_scope else ''}{args.key} = {args.value}")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    uncommitted = repo.reset(args.paths)
    if uncommitted:
        for p in uncommitted:
            print(f"Unstaged changes for {p}")
    else:
        print("Staging index reset to HEAD")
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    if not args.name:
        tags = repo.list_tags()
        for t in tags:
            print(t)
        return 0

    try:
        target_sha = repo.resolve_ref(args.target) if args.target else None
        sha = repo.create_tag(args.name, target_sha=target_sha)
        print(f"Created tag '{args.name}' at {sha[:8]}")
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_show(args: argparse.Namespace) -> int:
    try:
        repo = Repository.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    target = args.target or "HEAD"
    sha = repo.resolve_ref(target)
    if not sha or not repo.store.has_object(sha):
        print(f"fatal: bad object {target}", file=sys.stderr)
        return 1

    try:
        import datetime
        commit = repo.store.read_commit(sha)
        print(f"\033[33mcommit {sha}\033[0m")
        print(f"Author: {commit.author}")
        dt = datetime.datetime.fromtimestamp(commit.timestamp)
        print(f"Date:   {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        if commit.parent_shas:
            print(f"Parents: {' '.join(p[:8] for p in commit.parent_shas)}")
        print(f"\n    {commit.message}\n")

        if commit.semantic_delta:
            print("\033[36m--- Semantic Delta ---\033[0m")
            for d in commit.semantic_delta.get("technical_delta", []):
                print(f"  * {d}")
            tags = commit.semantic_delta.get("tags", [])
            if tags:
                print(f"  Tags: {', '.join(tags)}")
        return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_import_git(args: argparse.Namespace) -> int:
    from vcx.bridge.git_importer import GitImporter
    target_path = Path(args.path or ".").resolve()
    try:
        print(f"Importing Git repository from {target_path} into native VCX...")
        importer = GitImporter(target_path)
        repo = importer.import_to_vcx(semantic_enrichment=args.semantic)
        print(f"Successfully converted Git repository into native VCX at {repo.vcx_dir}")
        print(f"Head at {repo.head_commit_sha[:8] if repo.head_commit_sha else 'empty'}")
        print("VCX is now operating 100% standalone and native!")
        return 0
    except Exception as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1


def cmd_app(args: argparse.Namespace) -> int:
    action = args.action
    if action == "inspect":
        if not args.target:
            print("usage: vcx app inspect <file>", file=sys.stderr)
            return 1
        path = Path(args.target)
        if not path.is_file():
            print(f"error: file not found '{args.target}'", file=sys.stderr)
            return 1
        content = path.read_bytes()
        f_type = detect_file_type(path, content)
        engine = DeltaEngine()
        payload = engine.analyze_change(path.name, None, content, forced_file_type=f_type)
        agent = SemanticDifferAgent()
        out = agent.analyze(payload.to_dict())

        print(f"\033[1;36m=== VCX Universal Application Inspector ===\033[0m")
        print(f"File Target:       {path.name}")
        print(f"Detected Type:     \033[32m{f_type}\033[0m")
        print(f"File Size:         {len(content):,} bytes")
        if payload.domain_facts:
            print(f"\n\033[1mExtracted Application Facts:\033[0m")
            for k, v in payload.domain_facts.items():
                print(f"  * {k}: {v}")
        print(f"\n\033[1mSemantic Differ Output:\033[0m")
        print(f"  Action Summary:  \033[33m{out.action_summary}\033[0m")
        print(f"  Inferred Intent: {out.inferred_intent}")
        print(f"  Tags:            {', '.join(out.tags)}")
        if out.technical_delta:
            print(f"  Technical Delta:")
            for d in out.technical_delta:
                print(f"    * {d}")
        return 0

    elif action == "list":
        engine = DeltaEngine()
        plugins = engine.plugin_manager.list_all_plugins()

        print("\033[1;36m=== VCX Universal Application Ecosystem ===\033[0m")
        print("VCX operates with all applications and software in the world via:")
        print("  1. Native Domain Analyzers (Code, Media, Creative Suites, CAD, EDA)")
        print("  2. Container & Scene Graph Unpackers (DAWs, Game Engines, Design, Office)")
        print("  3. Universal Binary CDC Dissector (Content-Defined Chunking, Strings, Entropy)")
        print("  4. Dynamic Plugins (.vcx/plugins/, .vcx/config.json, Python hooks)\n")

        categories = [
            ("Video & Motion", "Premiere (.prproj), Final Cut (.fcpxml), DaVinci (.drp/.edl), MP4, MOV, ProRes"),
            ("Audio & DAWs", "Ableton Live (.als), Reaper (.rpp), FL Studio (.flp), Logic Pro, WAV, FLAC"),
            ("Game Engines", "Unity (.unity/.prefab), Godot (.tscn/.tres), Unreal Engine (.uproject/.uasset)"),
            ("Graphic & UI/UX", "Photoshop (.psd/.psb), Blender (.blend), Sketch (.sketch), Krita (.kra), GIMP (.xcf), Figma"),
            ("CAD & Engineering", "AutoCAD (.dwg/.dxf), FreeCAD (.fcstd), SolidWorks, KiCad (.kicad_pcb), Eagle (.brd)"),
            ("Data & Scientific", "Apache Parquet (.parquet), HDF5 (.h5), SQLite (.db), NetCDF (.nc), CSV"),
            ("Documents & Office", "Office Word (.docx), Excel (.xlsx), PowerPoint (.pptx), PDF, Pages, Keynote"),
            ("Systems & Binaries", "ELF, Mach-O, Windows PE/COFF, WebAssembly (.wasm), Java Class, 7-Zip, RAR"),
            ("Source & Hardware", "Rust, Python, C/C++, TypeScript, Go, SystemVerilog, Verilog, JSON Floorplans"),
        ]
        for cat, details in categories:
            print(f"  \033[1;32m{cat:<20}\033[0m {details}")

        if plugins:
            print(f"\n\033[1mActive Custom Plugins ({len(plugins)}):\033[0m")
            for p in plugins:
                print(f"  * [{p['type']}] {p.get('name')} -> {p.get('target') or p.get('path') or p.get('patterns')}")
        else:
            print("\nActive Custom Plugins: None (drop scripts in .vcx/plugins/ or configure in .vcx/config.json)")
        return 0

    else:
        print("usage: vcx app [inspect <file> | list]", file=sys.stderr)
        return 1


def cmd_stats(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    stats = engine.get_repository_stats()

    def format_size(bytes_val: int) -> str:
        val = float(bytes_val)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if val < 1024.0 or unit == "TB":
                return f"{val:,.1f} {unit}" if unit != "B" else f"{bytes_val:,} B"
            val /= 1024.0
        return f"{val:.1f} PB"

    uncompressed_str = format_size(stats["uncompressed_size"])
    compressed_str = format_size(stats["compressed_size"])
    db_size_str = format_size(stats["database_size"])

    if _console and sys.stdout.isatty():
        table = Table(title="VCX v2.0 Repository Statistics & Analytics", title_justify="left", border_style="cyan")
        table.add_column("Category", style="bold cyan", width=24)
        table.add_column("Metric", style="bold white", width=28)
        table.add_column("Value / Details", style="bold green")

        table.add_row("Deduplication", "Tracked Files", f"{stats['total_files']:,}")
        table.add_row("Deduplication", "Total CDC Chunks", f"{stats['total_chunks']:,}")
        table.add_row("Deduplication", "Unique Chunks", f"{stats['unique_chunks']:,}")
        table.add_row("Deduplication", "Deduplication Ratio", f"[bold yellow]{stats['deduplication_ratio']:.2f}x[/bold yellow]")

        table.add_row("Storage & Compression", "Uncompressed Size", uncompressed_str)
        table.add_row("Storage & Compression", "Zstandard Compressed Size", compressed_str)
        table.add_row("Storage & Compression", "Compression Ratio", f"{stats['compression_ratio']:.2f}x")
        table.add_row("Storage & Compression", "Space Savings", f"[bold yellow]{stats['space_savings_pct']:.1f}%[/bold yellow]")

        health_style = "bold green" if stats["database_health"] in ("ok", "healthy") else "bold red"
        table.add_row("Database & Health", "SQLite Index Size", db_size_str)
        table.add_row("Database & Health", "Database Health", f"[{health_style}]{stats['database_health'].upper()}[/{health_style}]")

        summary_panel = Panel.fit(
            f"[bold]Deduplication Efficiency:[/bold] [yellow]{stats['deduplication_ratio']:.2f}x[/yellow] "
            f"([green]{max(stats['total_chunks'] - stats['unique_chunks'], 0):,}[/green] redundant chunks eliminated)\n"
            f"[bold]Compression Savings:[/bold]      [yellow]{stats['space_savings_pct']:.1f}%[/yellow] space saved via Zstandard\n"
            f"[bold]Index Integrity:[/bold]          [{health_style}]{stats['database_health'].upper()}[/{health_style}] (ACID SQLite WAL Mode)",
            title="Repository Health Summary",
            border_style="green" if stats["database_health"] in ("ok", "healthy") else "red",
        )

        _console.print(table)
        _console.print()
        _console.print(summary_panel)
    else:
        print("=== VCX v2.0 Repository Statistics ===")
        print(f"Tracked Files:             {stats['total_files']:,}")
        print(f"Total CDC Chunks:          {stats['total_chunks']:,}")
        print(f"Unique Chunks:             {stats['unique_chunks']:,}")
        print(f"Deduplication Ratio:       {stats['deduplication_ratio']:.2f}x")
        print(f"Uncompressed Size:         {uncompressed_str}")
        print(f"Zstd Compressed Size:      {compressed_str}")
        print(f"Space Savings:             {stats['space_savings_pct']:.1f}% (Ratio: {stats['compression_ratio']:.2f}x)")
        print(f"Database Size:             {db_size_str}")
        print(f"Database Health:           {stats['database_health'].upper()}")

    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1

    if _console and sys.stdout.isatty():
        _console.print("Verifying repository integrity (manifests, CDC chunk checksums, index)...", style="dim")
    else:
        print("Verifying repository integrity (manifests, CDC chunk checksums, index)...")
    result = engine.verify_repository_integrity()

    if result["valid"]:
        if _console and sys.stdout.isatty():
            _console.print(
                Panel.fit(
                    f"[bold green]Repository integrity verified: 100% OK[/bold green]\n"
                    f"[dim]Files verified:[/dim]  {result['files_checked']:,}\n"
                    f"[dim]Chunks verified:[/dim] {result['chunks_checked']:,}\n"
                    f"[dim]Database health:[/dim] {'OK' if result['database_ok'] else 'ERROR'}",
                    title="VCX Integrity Check (fsck)",
                    border_style="green",
                )
            )
        else:
            print(f"Repository integrity verified: OK ({result['files_checked']} files, {result['chunks_checked']} chunks verified)")
        return 0
    else:
        if _console and sys.stdout.isatty():
            table = Table(title="Corrupted or Missing Objects Detected", border_style="red")
            table.add_column("Type", style="bold red", width=18)
            table.add_column("Details", style="white")

            for h in result["missing_manifests"]:
                table.add_row("Missing Manifest", h)
            for h in result["corrupted_manifests"]:
                table.add_row("Corrupt Manifest", h)
            for h in result["missing_chunks"]:
                table.add_row("Missing Chunk", h)
            for h in result["corrupted_chunks"]:
                table.add_row("Corrupt Chunk", h)
            for err in result["errors"]:
                table.add_row("Integrity Error", err)

            _console.print(
                Panel.fit(
                    f"[bold red]Integrity check failed: corruptions detected![/bold red]\n"
                    f"[dim]Missing chunks:[/dim]   {len(result['missing_chunks'])}\n"
                    f"[dim]Corrupted chunks:[/dim] {len(result['corrupted_chunks'])}\n"
                    f"[dim]Database ok:[/dim]      {result['database_ok']}",
                    title="VCX Integrity Failure",
                    border_style="red",
                )
            )
            _console.print(table)
        else:
            print("ERROR: Repository integrity check failed!", file=sys.stderr)
            for err in result["errors"]:
                print(f"  * {err}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vcx",
        description="VCX: Version Control for Everything - Multi-Domain VCS & Semantic Differ Agent",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize a new VCX repository")
    p_init.add_argument("path", nargs="?", default=".", help="Directory to initialize")
    p_init.set_defaults(func=cmd_init)

    # status
    p_status = subparsers.add_parser("status", help="Show working tree status")
    p_status.set_defaults(func=cmd_status)

    # add
    p_add = subparsers.add_parser("add", help="Add file contents to the staging index")
    p_add.add_argument("paths", nargs="+", help="Files or directories to add")
    p_add.set_defaults(func=cmd_add)

    # commit
    p_commit = subparsers.add_parser("commit", help="Record changes to repository")
    p_commit.add_argument("-m", "--message", help="Commit message")
    p_commit.add_argument("--auto", action="store_true", help="Generate message using Semantic Differ Agent")
    p_commit.set_defaults(func=cmd_commit)

    # diff
    p_diff = subparsers.add_parser("diff", help="Show changes between commits or working tree")
    p_diff.add_argument("path", nargs="?", help="Specific file path")
    p_diff.add_argument("--semantic", action="store_true", help="Output semantic delta JSON")
    p_diff.set_defaults(func=cmd_diff)

    # log
    p_log = subparsers.add_parser("log", help="Show commit history")
    p_log.add_argument("-n", "--limit", type=int, default=10, help="Max commits to display")
    p_log.add_argument("--json", action="store_true", help="Output log as JSON")
    p_log.set_defaults(func=cmd_log)

    # branch
    p_branch = subparsers.add_parser("branch", help="List or create branches")
    p_branch.add_argument("name", nargs="?", help="New branch name")
    p_branch.set_defaults(func=cmd_branch)

    # checkout
    p_checkout = subparsers.add_parser("checkout", help="Switch branches or restore working tree")
    p_checkout.add_argument("target", help="Branch name or commit SHA")
    p_checkout.set_defaults(func=cmd_checkout)

    # merge
    p_merge = subparsers.add_parser("merge", help="Join two development histories with semantic resolution")
    p_merge.add_argument("branch", help="Branch name to merge into current branch")
    p_merge.set_defaults(func=cmd_merge)

    # gc
    p_gc = subparsers.add_parser("gc", help="Pack repository objects and clean unreachable files")
    p_gc.set_defaults(func=cmd_gc)

    # pack
    p_pack = subparsers.add_parser("pack", help="Consolidate loose objects into VID2 binary packfile")
    p_pack.set_defaults(func=cmd_pack)

    # watch
    p_watch = subparsers.add_parser("watch", help="Watch workspace and generate semantic commit messages")
    p_watch.add_argument("--auto-commit", action="store_true", help="Automatically commit on detected changes")
    p_watch.add_argument("--debounce", type=float, default=0.8, help="Debounce delay in seconds")
    p_watch.set_defaults(func=cmd_watch)

    # agent
    p_agent = subparsers.add_parser("agent", help="Directly invoke Semantic Differ Agent with JSON payload")
    p_agent.add_argument("--input", "-i", help="Path to input JSON payload (reads from stdin if omitted)")
    p_agent.set_defaults(func=cmd_agent)

    # remote
    p_remote = subparsers.add_parser("remote", help="Manage set of tracked repositories")
    p_remote.add_argument("action", nargs="?", choices=["add", "rm"], help="Action to perform (add/rm)")
    p_remote.add_argument("name", nargs="?", help="Remote repository name")
    p_remote.add_argument("url", nargs="?", help="Remote repository URL or path")
    p_remote.set_defaults(func=cmd_remote)

    # clone
    p_clone = subparsers.add_parser("clone", help="Clone a repository into a new directory")
    p_clone.add_argument("url", help="Repository URL or path to clone from")
    p_clone.add_argument("dest", nargs="?", help="Optional destination directory")
    p_clone.set_defaults(func=cmd_clone)

    # fetch
    p_fetch = subparsers.add_parser("fetch", help="Download objects and refs from another repository")
    p_fetch.add_argument("remote", nargs="?", default="origin", help="Remote repository name")
    p_fetch.set_defaults(func=cmd_fetch)

    # push
    p_push = subparsers.add_parser("push", help="Update remote refs along with associated objects")
    p_push.add_argument("remote", nargs="?", default="origin", help="Remote repository name")
    p_push.add_argument("branch", nargs="?", default=None, help="Branch name to push")
    p_push.add_argument("-f", "--force", action="store_true", help="Force push")
    p_push.set_defaults(func=cmd_push)

    # serve
    p_serve = subparsers.add_parser("serve", help="Run HTTP server for smart remote transport")
    p_serve.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    p_serve.add_argument("--port", type=int, default=8000, help="Port to bind")
    p_serve.set_defaults(func=cmd_serve)

    # config
    p_config = subparsers.add_parser("config", help="Get and set repository or global options")
    p_config.add_argument("key", nargs="?", help="Configuration key (e.g. user.name)")
    p_config.add_argument("value", nargs="?", help="Configuration value")
    p_config.add_argument("--global", dest="global_scope", action="store_true", help="Set user-global configuration")
    p_config.add_argument("-l", "--list", action="store_true", help="List all configurations")
    p_config.set_defaults(func=cmd_config)

    # reset
    p_reset = subparsers.add_parser("reset", help="Reset current HEAD to specified state or unstage files")
    p_reset.add_argument("paths", nargs="*", help="File paths to unstage")
    p_reset.set_defaults(func=cmd_reset)

    # tag
    p_tag = subparsers.add_parser("tag", help="Create, list, or verify tags")
    p_tag.add_argument("name", nargs="?", help="Tag name")
    p_tag.add_argument("target", nargs="?", help="Target commit SHA or branch (defaults to HEAD)")
    p_tag.set_defaults(func=cmd_tag)

    # show
    p_show = subparsers.add_parser("show", help="Show various types of objects (commits, deltas)")
    p_show.add_argument("target", nargs="?", default="HEAD", help="Commit SHA, branch, or tag")
    p_show.set_defaults(func=cmd_show)

    # import-git
    p_import = subparsers.add_parser("import-git", help="Import a Git repository and convert history into native VCX")
    p_import.add_argument("path", nargs="?", default=".", help="Path to Git repository directory")
    p_import.add_argument("--semantic", action="store_true", help="Enrich historical commits with VCX Semantic Differ Agent")
    p_import.set_defaults(func=cmd_import_git)

    # app
    p_app = subparsers.add_parser("app", help="Universal application inspection and ecosystem catalog")
    p_app.add_argument("action", choices=["inspect", "list"], help="Action: 'inspect' a file or 'list' supported software")
    p_app.add_argument("target", nargs="?", help="File path to inspect")
    p_app.set_defaults(func=cmd_app)

    # stats
    p_stats = subparsers.add_parser("stats", help="Display repository deduplication, compression, and index analytics")
    p_stats.set_defaults(func=cmd_stats)

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify integrity of manifests, chunks, and index database")
    p_verify.set_defaults(func=cmd_verify)

    # fsck
    p_fsck = subparsers.add_parser("fsck", help="Verify repository integrity (alias for verify)")
    p_fsck.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
