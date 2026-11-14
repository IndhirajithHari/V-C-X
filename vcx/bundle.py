"""Single-File Repository Bundle Packaging for VCX (v2.0).

Allows packaging an entire VCX repository or subset of refs into a single portable
`.vcxpack` archive for offline transfer, backup, air-gapped sync, and archiving.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import zipfile


def create_bundle(
    repo_or_engine: Any,
    bundle_path: Union[str, Path],
    refs: Optional[List[str]] = None,
) -> Path:
    """Create a portable .vcxpack archive from a VCX repository.

    Args:
        repo_or_engine: VCXEngine, Repository, or Path to repo directory.
        bundle_path: Output archive file path (e.g., 'backup.vcxpack').
        refs: Optional list of branch or tag names to include. If None, includes all.

    Returns:
        Path to the created bundle file.
    """
    b_path = Path(bundle_path).resolve()
    b_path.parent.mkdir(parents=True, exist_ok=True)

    # Resolve vcx directory
    if hasattr(repo_or_engine, "vcx_dir"):
        vcx_dir = Path(repo_or_engine.vcx_dir)
    elif hasattr(repo_or_engine, "root"):
        vcx_dir = Path(repo_or_engine.root) / ".vcx"
    else:
        raw_p = Path(repo_or_engine)
        vcx_dir = raw_p / ".vcx" if (raw_p / ".vcx").is_dir() else raw_p

    if not vcx_dir.is_dir():
        raise FileNotFoundError(f"Not a valid VCX directory: {vcx_dir}")

    # Read HEAD
    head_content = ""
    head_file = vcx_dir / "HEAD"
    if head_file.exists():
        head_content = head_file.read_text(encoding="utf-8").strip()

    # Collect refs (heads and tags)
    all_refs: Dict[str, str] = {}
    heads_dir = vcx_dir / "refs" / "heads"
    if heads_dir.exists():
        for root, _, files in os.walk(heads_dir):
            for f in files:
                p = Path(root) / f
                rel_name = p.relative_to(heads_dir).as_posix()
                ref_key = f"refs/heads/{rel_name}"
                all_refs[ref_key] = p.read_text(encoding="utf-8").strip()

    tags_dir = vcx_dir / "refs" / "tags"
    if tags_dir.exists():
        for root, _, files in os.walk(tags_dir):
            for f in files:
                p = Path(root) / f
                rel_name = p.relative_to(tags_dir).as_posix()
                ref_key = f"refs/tags/{rel_name}"
                all_refs[ref_key] = p.read_text(encoding="utf-8").strip()

    # Filter refs if requested
    if refs:
        norm_refs_filter = set()
        for r in refs:
            r_str = str(r).strip()
            norm_refs_filter.add(r_str)
            if not r_str.startswith("refs/"):
                norm_refs_filter.add(f"refs/heads/{r_str}")
                norm_refs_filter.add(f"refs/tags/{r_str}")

        bundled_refs = {k: v for k, v in all_refs.items() if k in norm_refs_filter or k.replace("refs/heads/", "") in norm_refs_filter or k.replace("refs/tags/", "") in norm_refs_filter}
    else:
        bundled_refs = dict(all_refs)

    # Collect object files to store
    objects_dir = vcx_dir / "objects"
    objects_to_pack: List[Tuple[Path, str]] = []
    if objects_dir.exists():
        for root, _, files in os.walk(objects_dir):
            for f in files:
                if f.startswith(".tmp"):
                    continue
                full_p = Path(root) / f
                rel_p = full_p.relative_to(objects_dir).as_posix()
                objects_to_pack.append((full_p, f"objects/{rel_p}"))

    # Write ZIP bundle
    with zipfile.ZipFile(b_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "format": "VCXPACK-v1",
            "version": "2.0",
            "created_at": time.time(),
            "head": head_content,
            "refs": bundled_refs,
            "objects_count": len(objects_to_pack),
        }
        zf.writestr("bundle_manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

        for file_path, arcname in objects_to_pack:
            zf.write(file_path, arcname=arcname)

    return b_path


def verify_bundle(bundle_path: Union[str, Path]) -> Tuple[bool, List[str]]:
    """Verify integrity and format validity of a .vcxpack bundle archive.

    Args:
        bundle_path: Path to the .vcxpack bundle file.

    Returns:
        Tuple of (is_valid: bool, errors: List[str]).
    """
    b_path = Path(bundle_path)
    errors: List[str] = []

    if not b_path.exists():
        return False, [f"Bundle file does not exist: {b_path}"]

    if not b_path.is_file():
        return False, [f"Bundle path is not a file: {b_path}"]

    if not zipfile.is_zipfile(b_path):
        return False, [f"File is not a valid ZIP/VCXPACK archive: {b_path}"]

    try:
        with zipfile.ZipFile(b_path, "r") as zf:
            # 1. CRC test of all archive members
            bad_entry = zf.testzip()
            if bad_entry:
                errors.append(f"Corrupted entry detected in archive: {bad_entry}")

            namelist = set(zf.namelist())

            # 2. Check bundle manifest existence
            if "bundle_manifest.json" not in namelist:
                errors.append("Invalid bundle: missing 'bundle_manifest.json'")
                return False, errors

            # 3. Parse and validate manifest contents
            try:
                manifest_bytes = zf.read("bundle_manifest.json")
                manifest_data = json.loads(manifest_bytes.decode("utf-8"))
            except Exception as e:
                errors.append(f"Malformed 'bundle_manifest.json': {e}")
                return False, errors

            if manifest_data.get("format") != "VCXPACK-v1":
                errors.append(
                    f"Unsupported bundle format: expected 'VCXPACK-v1', got '{manifest_data.get('format')}'"
                )

            if not isinstance(manifest_data.get("refs"), dict):
                errors.append("Invalid manifest: 'refs' must be a dictionary")

            # 4. Check objects count consistency
            objects_in_zip = [name for name in namelist if name.startswith("objects/") and not name.endswith("/")]
            expected_count = manifest_data.get("objects_count")
            if expected_count is not None and expected_count != len(objects_in_zip):
                errors.append(
                    f"Objects count mismatch: manifest declares {expected_count}, archive contains {len(objects_in_zip)}"
                )

    except Exception as e:
        errors.append(f"Failed to inspect bundle archive: {e}")

    return len(errors) == 0, errors
