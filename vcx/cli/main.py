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
from vcx.watcher.watcher import WorkspaceWatcher


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

    # watch
    p_watch = subparsers.add_parser("watch", help="Watch workspace and generate semantic commit messages")
    p_watch.add_argument("--auto-commit", action="store_true", help="Automatically commit on detected changes")
    p_watch.add_argument("--debounce", type=float, default=0.8, help="Debounce delay in seconds")
    p_watch.set_defaults(func=cmd_watch)

    # agent
    p_agent = subparsers.add_parser("agent", help="Directly invoke Semantic Differ Agent with JSON payload")
    p_agent.add_argument("--input", "-i", help="Path to input JSON payload (reads from stdin if omitted)")
    p_agent.set_defaults(func=cmd_agent)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
