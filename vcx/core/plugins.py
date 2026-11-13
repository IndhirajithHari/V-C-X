"""Universal Plugin and External Adapter Manager for VCX.

Enables any application or software in the world to integrate custom diff,
decompression, or inspection logic into VCX via:
1. Executable scripts in .vcx/plugins/ or ~/.vcx/plugins/ (e.g., diff-<ext>)
2. Configuration commands in .vcx/config.json ("analyzers": { "*.ext": "cmd {old} {new}" })
3. In-process Python analyzer plugin registration
"""

from __future__ import annotations
import fnmatch
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from vcx.core.config import ConfigManager
from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer

PluginCallable = Callable[[Optional[bytes], Optional[bytes], str], AnalysisResult]

_PYTHON_PLUGINS: Dict[str, Tuple[List[str], List[bytes], PluginCallable]] = {}


def register_plugin(
    name: str,
    patterns: Optional[List[str]] = None,
    magic: Optional[List[bytes]] = None,
) -> Callable[[PluginCallable], PluginCallable]:
    """Decorator to register a Python analyzer plugin dynamically."""
    def decorator(fn: PluginCallable) -> PluginCallable:
        _PYTHON_PLUGINS[name] = (patterns or [], magic or [], fn)
        return fn
    return decorator


class PluginManager:
    """Discovers, routes, and executes external adapters and plugins for any software."""

    def __init__(self, repo_dir: Optional[Path | str] = None):
        self.repo_dir = Path(repo_dir).resolve() if repo_dir else None
        self.config_mgr = ConfigManager(self.repo_dir)

    def find_analyzer_for_file(
        self,
        file_name: str,
        content: Optional[bytes] = None,
    ) -> Optional[Tuple[str, str]]:
        """Return (plugin_type, execution_target) if an external or python plugin matches."""
        name_lower = Path(file_name).name.lower()
        suffix = Path(file_name).suffix.lower()

        # 1. In-process Python plugins
        for p_name, (patterns, magics, _) in _PYTHON_PLUGINS.items():
            for pat in patterns:
                if fnmatch.fnmatch(name_lower, pat.lower()):
                    return ("python", p_name)
            if content and magics:
                for m in magics:
                    if content.startswith(m):
                        return ("python", p_name)

        # 2. Config-driven analyzer commands (.vcx/config.json)
        analyzers_config = self.config_mgr.get("analyzers", {})
        if isinstance(analyzers_config, dict):
            for pat, cmd_str in analyzers_config.items():
                if fnmatch.fnmatch(name_lower, pat.lower()):
                    return ("config_cmd", cmd_str)

        # 3. Executable script plugins in .vcx/plugins/ or ~/.vcx/plugins/
        plugin_dirs = []
        if self.repo_dir:
            plugin_dirs.append(self.repo_dir / ".vcx" / "plugins")
        plugin_dirs.append(Path.home() / ".vcx" / "plugins")

        clean_ext = suffix.lstrip(".")
        candidates = [f"diff-{clean_ext}", f"analyze-{clean_ext}", f"diff-{name_lower}"]
        for pdir in plugin_dirs:
            if pdir.is_dir():
                for cand in candidates:
                    script_path = pdir / cand
                    if script_path.is_file() and os.access(script_path, os.X_OK):
                        return ("script", str(script_path))

        return None

    def execute(
        self,
        plugin_info: Tuple[str, str],
        file_name: str,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
    ) -> Optional[AnalysisResult]:
        """Execute the matched plugin safely."""
        p_type, target = plugin_info

        if p_type == "python":
            if target in _PYTHON_PLUGINS:
                _, _, fn = _PYTHON_PLUGINS[target]
                try:
                    return fn(old_content, new_content, file_name)
                except Exception as err:
                    return AnalysisResult(
                        previous_metadata={},
                        current_metadata={},
                        raw_diff=f"Python plugin '{target}' error: {err}",
                        domain_facts={"plugin_error": str(err)},
                    )

        elif p_type in ("config_cmd", "script"):
            return self._run_subprocess_analyzer(target, p_type, file_name, old_content, new_content)

        return None

    def _run_subprocess_analyzer(
        self,
        command_template: str,
        p_type: str,
        file_name: str,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
    ) -> AnalysisResult:
        with tempfile.TemporaryDirectory(prefix="vcx_plugin_") as tmpdir:
            tmppath = Path(tmpdir)
            old_file = tmppath / "old_blob"
            new_file = tmppath / "new_blob"
            old_file.write_bytes(old_content or b"")
            new_file.write_bytes(new_content or b"")

            if p_type == "script":
                cmd = [command_template, str(old_file), str(new_file), file_name]
            else:
                # Replace tokens in template
                resolved = (
                    command_template.replace("{old}", str(old_file))
                    .replace("{new}", str(new_file))
                    .replace("{file}", file_name)
                )
                cmd = shlex.split(resolved)

            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=15,
                    check=False,
                )
                out = proc.stdout.decode("utf-8", errors="replace").strip()
                err = proc.stderr.decode("utf-8", errors="replace").strip()
                raw_diff = out if out else (err or f"Executed plugin with exit code {proc.returncode}")
                return AnalysisResult(
                    previous_metadata={"size_bytes": len(old_content or b"")},
                    current_metadata={"size_bytes": len(new_content or b"")},
                    raw_diff=raw_diff,
                    domain_facts={
                        "plugin_target": command_template,
                        "plugin_type": p_type,
                        "exit_code": proc.returncode,
                    },
                )
            except Exception as err:
                return AnalysisResult(
                    previous_metadata={},
                    current_metadata={},
                    raw_diff=f"Failed to execute plugin command: {err}",
                    domain_facts={"error": str(err)},
                )

    def list_all_plugins(self) -> List[Dict[str, Any]]:
        """List all active plugins (Python, config commands, and scripts)."""
        results: List[Dict[str, Any]] = []

        # Python plugins
        for p_name, (pats, magics, _) in _PYTHON_PLUGINS.items():
            results.append({
                "type": "Python Plugin",
                "name": p_name,
                "patterns": pats,
                "magic_bytes": [m.hex() for m in magics],
            })

        # Config commands
        analyzers_config = self.config_mgr.get("analyzers", {})
        if isinstance(analyzers_config, dict):
            for pat, cmd in analyzers_config.items():
                results.append({
                    "type": "Config Command",
                    "name": pat,
                    "target": cmd,
                })

        # Scripts
        plugin_dirs = []
        if self.repo_dir:
            plugin_dirs.append(self.repo_dir / ".vcx" / "plugins")
        plugin_dirs.append(Path.home() / ".vcx" / "plugins")

        for pdir in plugin_dirs:
            if pdir.is_dir():
                for script in pdir.iterdir():
                    if script.is_file() and os.access(script, os.X_OK):
                        results.append({
                            "type": "Script Hook",
                            "name": script.name,
                            "path": str(script),
                        })

        return results
