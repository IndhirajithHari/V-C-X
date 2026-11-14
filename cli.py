#!/usr/bin/env python3
"""Command Line Interface for VCX v2.0 Production Engine.

Provides an intuitive, high-performance terminal interface powered by Rich
and the VCX v2.0 engine (Content-Defined Chunking, Zstandard compression,
SQLite local indexing, and pluggable semantic diffing).
"""

from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import time
from typing import List, Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    _HAS_RICH = True
except ImportError:
    Console = None
    _HAS_RICH = False

from vcx import __version__
from vcx.engine import VCXEngine

console = Console() if _HAS_RICH else None


def print_msg(msg: str, style: str = "white") -> None:
    if console and sys.stdout.isatty():
        console.print(msg, style=style)
    else:
        print(msg)


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path or ".").resolve()
    engine = VCXEngine.init(target)
    if console and sys.stdout.isatty():
        console.print(
            Panel.fit(
                f"[bold green]Initialized empty VCX v2.0 repository[/bold green]\n"
                f"[dim]Root:[/dim] {engine.repo_dir}\n"
                f"[dim]Metadata:[/dim] {engine.vcx_dir}\n"
                f"[dim]Storage:[/dim] Content-Defined Chunking + Zstandard\n"
                f"[dim]Index:[/dim] SQLite index.db (WAL Mode)",
                title="VCX v2.0 Architecture",
                border_style="green",
            )
        )
    else:
        print(f"Initialized empty VCX v2.0 repository in {engine.vcx_dir}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print_msg(f"fatal: {e}", style="bold red")
        return 1

    st = engine.status()
    branch = st["branch"]

    if console and sys.stdout.isatty():
        console.print(f"[bold cyan]On branch[/bold cyan] [bold yellow]{branch}[/bold yellow]\n")

        if st["staged"]:
            table = Table(title="Changes to be committed (staged)", title_justify="left", border_style="green")
            table.add_column("Status", style="bold green", width=12)
            table.add_column("Path", style="white")
            table.add_column("Size", style="dim", justify="right")
            for item in st["staged"]:
                sz = f"{item.get('size', 0):,} B"
                table.add_row(item["type"].upper(), item["path"], sz)
            console.print(table)
            console.print()

        if st["unstaged"]:
            table = Table(title="Changes not staged for commit", title_justify="left", border_style="red")
            table.add_column("Status", style="bold red", width=12)
            table.add_column("Path", style="white")
            table.add_column("Size", style="dim", justify="right")
            for item in st["unstaged"]:
                sz = f"{item.get('size', 0):,} B"
                table.add_row(item["type"].upper(), item["path"], sz)
            console.print(table)
            console.print()

        if st["untracked"]:
            table = Table(title="Untracked files", title_justify="left", border_style="yellow")
            table.add_column("Status", style="bold yellow", width=12)
            table.add_column("Path", style="white")
            table.add_column("Size", style="dim", justify="right")
            for item in st["untracked"]:
                sz = f"{item.get('size', 0):,} B"
                table.add_row("UNTRACKED", item["path"], sz)
            console.print(table)
            console.print()

        if not st["staged"] and not st["unstaged"] and not st["untracked"]:
            console.print("[green]nothing to commit, working tree clean[/green]")
    else:
        print(f"On branch {branch}\n")
        if st["staged"]:
            print("Changes to be committed (staged):")
            for item in st["staged"]:
                print(f"  {item['type']:<10} {item['path']}")
            print()
        if st["unstaged"]:
            print("Changes not staged for commit:")
            for item in st["unstaged"]:
                print(f"  {item['type']:<10} {item['path']}")
            print()
        if st["untracked"]:
            print("Untracked files:")
            for item in st["untracked"]:
                print(f"  ?          {item['path']}")
            print()
        if not st["staged"] and not st["unstaged"] and not st["untracked"]:
            print("nothing to commit, working tree clean")

    return 0


def cmd_add(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print_msg(f"fatal: {e}", style="bold red")
        return 1

    try:
        staged = engine.add(args.paths)
        if not staged:
            print_msg("No files were staged.", style="dim")
        else:
            for p in staged:
                print_msg(f"Staged {p} (CDC chunked & Zstd indexed)", style="green")
        return 0
    except Exception as e:
        print_msg(f"error: {e}", style="bold red")
        return 1


def cmd_reset(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print_msg(f"fatal: {e}", style="bold red")
        return 1

    unstaged = engine.reset(args.paths)
    for p in unstaged:
        print_msg(f"Unstaged {p}", style="yellow")
    return 0


def cmd_commit(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print_msg(f"fatal: {e}", style="bold red")
        return 1

    try:
        sha, commit = engine.commit(message=args.message, auto=args.auto)
        short_sha = sha[:8]
        msg = commit["message"]
        delta = commit.get("semantic_delta", {})

        if console and sys.stdout.isatty():
            panel_content = f"[bold cyan][{short_sha}][/bold cyan] [bold white]{msg}[/bold white]\n"
            if delta.get("technical_delta"):
                panel_content += "\n[bold yellow]Technical Delta:[/bold yellow]\n"
                for d in delta["technical_delta"]:
                    panel_content += f"  • {d}\n"
            if delta.get("tags"):
                panel_content += f"\n[dim]Tags:[/dim] {', '.join(delta['tags'])}\n"
            console.print(Panel(panel_content.strip(), title="Committed to Merkle DAG", border_style="cyan"))
        else:
            print(f"[{short_sha}] {msg}")
            if delta.get("technical_delta"):
                for d in delta["technical_delta"]:
                    print(f"  * {d}")
                tags = delta.get("tags", [])
                if tags:
                    print(f"  Tags: {', '.join(tags)}")
        return 0
    except ValueError as e:
        print_msg(f"error: {e}", style="bold red")
        return 1


def cmd_diff(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print_msg(f"fatal: {e}", style="bold red")
        return 1

    # Extract diffs for unstaged or staged files
    st = engine.status()
    targets = [item["path"] for item in st["staged"] + st["unstaged"]]
    if args.path:
        targets = [args.path]

    for p in targets:
        curr_p = engine.repo_dir / p
        curr_bytes = curr_p.read_bytes() if curr_p.exists() else b""
        diff_res = engine.semantic.extract(p, base_bytes=None, current_bytes=curr_bytes)
        print(f"--- diff for {p} [{diff_res.file_type}] ---")
        print(diff_res.raw_diff)
        print()

    return 0


def cmd_checkout(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print_msg(f"fatal: {e}", style="bold red")
        return 1

    try:
        reconstructed = engine.checkout(args.target)
        print_msg(f"Checked out '{args.target}' ({reconstructed} files reconstructed via CDC stream)", style="bold green")
        return 0
    except Exception as e:
        print_msg(f"error: {e}", style="bold red")
        return 1


def cmd_log(args: argparse.Namespace) -> int:
    try:
        engine = VCXEngine.find()
    except FileNotFoundError as e:
        print_msg(f"fatal: {e}", style="bold red")
        return 1

    commits = engine.log(limit=args.limit)
    if not commits:
        print_msg("No commits yet on this branch.", style="dim")
        return 0

    for c in commits:
        sha = c.get("sha", "")[:8]
        msg = c.get("message", "")
        author = c.get("author", "Unknown")
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(c.get("timestamp", time.time())))
        delta = c.get("semantic_delta", {})

        if console and sys.stdout.isatty():
            content = f"[bold cyan]commit {c.get('sha', '')}[/bold cyan]\n"
            content += f"[dim]Author:[/dim] {author}\n"
            content += f"[dim]Date:  [/dim] {ts}\n\n"
            content += f"    [bold white]{msg}[/bold white]\n"
            if delta.get("technical_delta"):
                content += "\n"
                for d in delta["technical_delta"]:
                    content += f"    [dim]•[/dim] {d}\n"
            console.print(Panel(content.strip(), border_style="blue"))
        else:
            print(f"commit {c.get('sha', '')}")
            print(f"Author: {author}")
            print(f"Date:   {ts}\n")
            print(f"    {msg}\n")
            if delta.get("technical_delta"):
                for d in delta["technical_delta"]:
                    print(f"    * {d}")
                print()

    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(f"VCX Version Control Engine v{__version__} (CDC + Zstd + SQLite Merkle DAG)")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vcx",
        description="VCX v2.0: Content-Defined Chunking, Zstd Compression, and SQLite Merkle DAG",
    )
    parser.add_argument("-v", "--version", action="version", version=f"vcx {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # init
    p_init = subparsers.add_parser("init", help="Initialize empty repository with v2.0 architecture")
    p_init.add_argument("path", nargs="?", default=".", help="Directory to initialize")
    p_init.set_defaults(func=cmd_init)

    # status
    p_status = subparsers.add_parser("status", help="Show working tree status via instant SQLite index")
    p_status.set_defaults(func=cmd_status)

    # add
    p_add = subparsers.add_parser("add", help="Stage files with Content-Defined Chunking and Zstd")
    p_add.add_argument("paths", nargs="+", help="Files or directories to stage")
    p_add.set_defaults(func=cmd_add)

    # reset
    p_reset = subparsers.add_parser("reset", help="Unstage files")
    p_reset.add_argument("paths", nargs="*", help="Files to unstage")
    p_reset.set_defaults(func=cmd_reset)

    # commit
    p_commit = subparsers.add_parser("commit", help="Record changes to Merkle DAG")
    p_commit.add_argument("-m", "--message", help="Commit message")
    p_commit.add_argument("--auto", action="store_true", help="Use Antigravity AI Semantic Differ for commit message")
    p_commit.set_defaults(func=cmd_commit)

    # diff
    p_diff = subparsers.add_parser("diff", help="Show semantic diff across CAD, EDA, code, and binary")
    p_diff.add_argument("path", nargs="?", help="Specific file to diff")
    p_diff.set_defaults(func=cmd_diff)

    # checkout
    p_checkout = subparsers.add_parser("checkout", help="Reconstruct files streamingly from CDC manifests")
    p_checkout.add_argument("target", help="Branch name, tag, or commit SHA")
    p_checkout.set_defaults(func=cmd_checkout)

    # log
    p_log = subparsers.add_parser("log", help="Display commit DAG history")
    p_log.add_argument("-n", "--limit", type=int, default=10, help="Maximum number of commits to show")
    p_log.set_defaults(func=cmd_log)

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
