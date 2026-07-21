"""Configuration management for WinBridge."""

import json
import os
from pathlib import Path


class Config:
    """Manages application configuration."""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "winbridge"
        self.data_dir = Path.home() / ".local" / "share" / "winbridge"
        self.bottles_dir = self.data_dir / "bottles"
        self.cache_dir = self.data_dir / "cache"
        self.components_dir = self.data_dir / "components"
        self.config_file = self.config_dir / "config.json"
        self._ensure_dirs()
        self._settings = self._load()

    def _ensure_dirs(self):
        """Create necessary directories."""
        for d in [self.config_dir, self.data_dir, self.bottles_dir,
                  self.cache_dir, self.components_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        """Load configuration from file."""
        default = {
            "wine_path": self._find_wine(),
            "wine_arch": "win64",
            "windows_version": "win10",
            "theme": "system",
            "language": "zh_CN",
            "download_base_url": "https://gitcode.com/api/v1/repos",
            "download_repo": "winbridge/components",
            "first_run": True,
        }
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                default.update(data)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def _find_wine(self) -> str:
        """Find the system wine binary."""
        # First check if the project has a built binary
        project_wine = Path.home() / "winbridge" / "wine" / "wine"
        if project_wine.exists():
            return str(project_wine)
        # Check system PATH
        for path in os.environ.get("PATH", "").split(":"):
            candidate = Path(path) / "wine"
            if candidate.exists():
                return str(candidate)
        # Default fallback
        return "/usr/bin/wine"

    def save(self):
        """Save configuration to file."""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default=None):
        return self._settings.get(key, default)

    def set(self, key: str, value):
        self._settings[key] = value
        self.save()

    @property
    def wine_path(self) -> str:
        return self.get("wine_path", self._find_wine())

    @property
    def wine_arch(self) -> str:
        return self.get("wine_arch", "win64")

    @property
    def download_base_url(self) -> str:
        return self.get("download_base_url",
                        "https://gitcode.com/api/v1/repos")

    @property
    def download_repo(self) -> str:
        return self.get("download_repo", "winbridge/components")

    @property
    def is_first_run(self) -> bool:
        return self.get("first_run", True)

    def mark_first_run_done(self):
        self.set("first_run", False)