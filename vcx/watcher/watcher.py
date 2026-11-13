"""Autonomous background file watcher for VCX workspace."""

from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, Optional, Set

from vcx.agent.schemas import DifferOutput
from vcx.agent.semantic_differ import SemanticDifferAgent
from vcx.core.repository import Repository
from vcx.diff.delta_engine import DeltaEngine, WatcherPayload


class WorkspaceWatcher:
    def __init__(
        self,
        repo: Repository,
        debounce_seconds: float = 0.8,
        auto_commit: bool = False,
        on_change_callback: Optional[Callable[[WatcherPayload, DifferOutput], None]] = None,
    ):
        self.repo = repo
        self.debounce_seconds = debounce_seconds
        self.auto_commit = auto_commit
        self.callback = on_change_callback
        self.delta_engine = DeltaEngine()
        self.agent = SemanticDifferAgent()

        self._pending_changes: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start watcher in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop background watcher."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _should_ignore(self, path: Path) -> bool:
        parts = path.parts
        for p in parts:
            if p in Repository.IGNORE_DIRS or p.startswith(".tmp_") or p.endswith("~"):
                return True
        return False

    def trigger_change(self, rel_path: str) -> None:
        """Record an observed change event for debouncing."""
        with self._lock:
            self._pending_changes[rel_path] = time.time()

    def _process_debounced_changes(self) -> None:
        now = time.time()
        to_process: Set[str] = set()

        with self._lock:
            for path, timestamp in list(self._pending_changes.items()):
                if now - timestamp >= self.debounce_seconds:
                    to_process.add(path)
                    del self._pending_changes[path]

        for rel_path in to_process:
            self._analyze_and_handle(rel_path)

    def _analyze_and_handle(self, rel_path: str) -> Optional[DifferOutput]:
        full_path = self.repo.root / rel_path
        if not full_path.exists():
            return None

        # Fetch old blob if tracked
        head_entries = self.repo.get_head_tree_entries()
        index_entry = self.repo.index.get(rel_path)

        old_bytes: Optional[bytes] = None
        if index_entry:
            old_bytes = self.repo.store.read_blob(index_entry.sha)
        elif rel_path in head_entries:
            old_bytes = self.repo.store.read_blob(head_entries[rel_path].sha)

        new_bytes = full_path.read_bytes()

        # If content unchanged, skip
        if old_bytes == new_bytes:
            return None

        # 1. Delta engine produces payload matching INPUT SCHEMA
        payload = self.delta_engine.analyze_change(rel_path, old_bytes, new_bytes)

        # 2. Semantic Differ Agent processes payload and produces OUTPUT SCHEMA
        output = self.agent.analyze(payload.to_dict())

        # 3. If auto_commit enabled, commit to VCX repository
        if self.auto_commit:
            self.repo.add([rel_path])
            self.repo.commit(
                message=output.action_summary,
                auto=False,
                author="VCX Autonomous Watcher <watcher@vcx.local>",
            )

        # 4. Trigger callback or display
        if self.callback:
            self.callback(payload, output)

        return output

    def _run_loop(self) -> None:
        """Main watch loop using pyinotify if on Linux, otherwise fallback polling."""
        try:
            import pyinotify

            wm = pyinotify.WatchManager()
            mask = (
                pyinotify.IN_MODIFY
                | pyinotify.IN_CREATE
                | pyinotify.IN_MOVED_TO
            )

            class EventHandler(pyinotify.ProcessEvent):
                def __init__(self, watcher: WorkspaceWatcher):
                    self.watcher = watcher

                def process_default(self, event):
                    p = Path(event.pathname)
                    if not self.watcher._should_ignore(p) and p.is_file():
                        try:
                            rel = str(p.relative_to(self.watcher.repo.root))
                            self.watcher.trigger_change(rel)
                        except ValueError:
                            pass

            handler = EventHandler(self)
            notifier = pyinotify.Notifier(wm, handler, timeout=100)
            wm.add_watch(str(self.repo.root), mask, rec=True, auto_add=True)

            while self._running:
                notifier.process_events()
                if notifier.check_events():
                    notifier.read_events()
                self._process_debounced_changes()
                time.sleep(0.1)

        except Exception:
            # Fallback polling loop
            last_mtimes: Dict[str, float] = {}
            while self._running:
                for root, dirs, files in os.walk(self.repo.root):
                    dirs[:] = [d for d in dirs if d not in Repository.IGNORE_DIRS]
                    for f in files:
                        p = Path(root) / f
                        if self._should_ignore(p):
                            continue
                        rel = str(p.relative_to(self.repo.root))
                        try:
                            mtime = p.stat().st_mtime
                            if rel in last_mtimes and last_mtimes[rel] != mtime:
                                self.trigger_change(rel)
                            last_mtimes[rel] = mtime
                        except OSError:
                            pass

                self._process_debounced_changes()
                time.sleep(0.3)
