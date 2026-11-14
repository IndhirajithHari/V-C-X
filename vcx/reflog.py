"""Reference Transaction Log for VCX (v2.0).

Maintains an append-only transaction audit log in `.vcx/logs/` tracking
all reference transitions (commits, checkouts, branch creations, merges, resets).
"""

from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
import time
from typing import List, Optional, Union


@dataclass
class ReflogEntry:
    """Represents a single reference transaction entry."""
    old_sha: str
    new_sha: str
    timestamp: float
    action: str
    message: str


def record_reflog(
    vcx_dir: Union[str, Path],
    ref_name: str,
    old_sha: Optional[str],
    new_sha: Optional[str],
    action: str,
    message: str,
    timestamp: Optional[float] = None,
) -> None:
    """Record a ref transition into .vcx/logs/HEAD and the target ref log.

    Args:
        vcx_dir: Path to the .vcx directory.
        ref_name: The ref being updated (e.g., 'HEAD', 'refs/heads/main').
        old_sha: The previous commit SHA (40 chars, or None / 0*40 for initial).
        new_sha: The new commit SHA (40 chars, or None / 0*40 for deletion).
        action: The operation name (commit, checkout, branch, merge, reset).
        message: Descriptive message for the reflog entry.
        timestamp: Optional epoch timestamp (defaults to time.time()).
    """
    v_dir = Path(vcx_dir)
    logs_dir = v_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    ts = timestamp if timestamp is not None else time.time()
    clean_old = (old_sha or "0" * 40).strip()
    clean_new = (new_sha or "0" * 40).strip()
    clean_action = (action or "unknown").strip()
    clean_msg = (message or "").strip().replace("\n", " ")

    line = f"{clean_old} {clean_new} {ts:.6f} {clean_action}: {clean_msg}\n"

    # Always write to logs/HEAD
    head_log = logs_dir / "HEAD"
    head_log.parent.mkdir(parents=True, exist_ok=True)
    with head_log.open("a", encoding="utf-8") as f:
        f.write(line)

    # Write to specific ref log if not HEAD
    if ref_name and ref_name != "HEAD":
        norm_ref = ref_name
        if not norm_ref.startswith("refs/"):
            norm_ref = f"refs/heads/{norm_ref}"
        ref_log_path = logs_dir / norm_ref
        ref_log_path.parent.mkdir(parents=True, exist_ok=True)
        with ref_log_path.open("a", encoding="utf-8") as f:
            f.write(line)


def read_reflog(
    vcx_dir: Union[str, Path],
    ref_name: str = "HEAD",
    limit: int = 50,
) -> List[ReflogEntry]:
    """Read reference transaction log entries in reverse-chronological order.

    Args:
        vcx_dir: Path to the .vcx directory.
        ref_name: Target reference to read ('HEAD', 'refs/heads/main', or branch name).
        limit: Maximum number of entries to return (default 50).

    Returns:
        List of ReflogEntry objects, newest first.
    """
    v_dir = Path(vcx_dir)
    logs_dir = v_dir / "logs"

    target_file = logs_dir / ref_name
    if not target_file.exists() and ref_name != "HEAD" and not ref_name.startswith("refs/"):
        target_file = logs_dir / "refs" / "heads" / ref_name

    if not target_file.exists() or not target_file.is_file():
        return []

    entries: List[ReflogEntry] = []
    try:
        content = target_file.read_text(encoding="utf-8")
    except OSError:
        return []

    lines = content.splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 3)
        if len(parts) < 4:
            continue
        old_sha, new_sha, ts_str, rest = parts
        try:
            ts = float(ts_str)
        except ValueError:
            continue

        if ": " in rest:
            action, msg = rest.split(": ", 1)
        else:
            action, msg = rest, ""

        entries.append(
            ReflogEntry(
                old_sha=old_sha,
                new_sha=new_sha,
                timestamp=ts,
                action=action,
                message=msg,
            )
        )
        if len(entries) >= limit:
            break

    return entries
