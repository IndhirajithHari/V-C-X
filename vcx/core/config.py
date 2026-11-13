"""Native Configuration Manager for VCX (.vcx/config.json and ~/.vcxconfig.json)."""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """Manages repository-local and user-global VCX configurations."""

    GLOBAL_CONFIG_PATH = Path.home() / ".vcxconfig.json"

    def __init__(self, repo_dir: Optional[Path | str] = None):
        self.repo_dir = Path(repo_dir).resolve() if repo_dir else None
        self.local_config_path = self.repo_dir / ".vcx" / "config.json" if self.repo_dir else None

    def _read_json(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value (local overrides global)."""
        if self.local_config_path and self.local_config_path.exists():
            local_data = self._read_json(self.local_config_path)
            if key in local_data:
                return local_data[key]

        global_data = self._read_json(self.GLOBAL_CONFIG_PATH)
        return global_data.get(key, default)

    def set(self, key: str, value: Any, global_scope: bool = False) -> None:
        """Set config value in local or global config."""
        target_path = self.GLOBAL_CONFIG_PATH if (global_scope or not self.local_config_path) else self.local_config_path
        data = self._read_json(target_path)
        data[key] = value
        self._write_json(target_path, data)

    def list_all(self) -> Dict[str, Any]:
        """List all combined configurations."""
        combined = self._read_json(self.GLOBAL_CONFIG_PATH)
        if self.local_config_path and self.local_config_path.exists():
            combined.update(self._read_json(self.local_config_path))
        return combined
