"""Configuration management for WinBridge."""

import json
import os
from pathlib import Path


class Config:
    """Manages application configuration."""

    # Sub-directory names that may hold pre-downloaded winetricks payloads.
    # The source tree and the .deb use "winetricks"; trees predating that
    # rename (and the legacy ~/winbridge/components) keep them in
    # "winetricks-cache". Only accepting the new name makes every preset
    # invisible in the old layout, so components silently download
    # everything again — and the large ones (win7sp1, dotnet48) fail on a
    # slow network even though the files are already on disk.
    PRESET_DIR_NAMES = ("winetricks", "winetricks-cache")

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "winbridge"
        self.data_dir = Path.home() / ".local" / "share" / "winbridge"
        self.bottles_dir = self.data_dir / "bottles"
        self.cache_dir = self.data_dir / "cache"
        self.components_dir = self._resolve_components_dir()
        self.config_file = self.config_dir / "config.json"
        self._ensure_dirs()
        self._settings = self._load()

    def _resolve_components_dir(self) -> Path:
        """Pick the component directory that actually holds presets.

        The project-integrated copy (shipped with the deb/flatpak, read-only,
        "开箱即用") wins, then a system-wide preset location, then the legacy
        ~/winbridge/components. A directory without any preset sub-directory
        must not shadow one that has them: an empty components/ would push
        every font/MSI download back onto the network.
        """
        root = Path(__file__).resolve().parent.parent.parent
        candidates = [root / "components",
                      Path("/usr/share/winbridge/components"),
                      Path.home() / "winbridge" / "components"]
        override = os.environ.get("WINBRIDGE_COMPONENTS_DIR", "").strip()
        if override:
            candidates.insert(0, Path(override).expanduser())
        return self.pick_components_dir(candidates, self.data_dir / "components")

    @classmethod
    def pick_components_dir(cls, candidates, fallback: Path) -> Path:
        """First candidate with presets, else first existing, else fallback."""
        for candidate in candidates:
            if any((candidate / name).is_dir()
                   for name in cls.PRESET_DIR_NAMES):
                return candidate
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        # Nothing on disk yet: presets will be downloaded into the writable
        # data dir, which is also where the deb can create it.
        return fallback

    @property
    def presets_dir(self) -> Path:
        """Directory holding pre-downloaded winetricks payloads.

        Only the path is returned; it may not exist. Use ``preset_dirs`` when
        looking for files, so a legacy ``winetricks-cache`` is found too.
        """
        for name in self.PRESET_DIR_NAMES:
            candidate = self.components_dir / name
            if candidate.is_dir():
                return candidate
        return self.components_dir / self.PRESET_DIR_NAMES[0]

    def _ensure_dirs(self):
        """Create necessary directories."""
        for d in [self.config_dir, self.data_dir, self.bottles_dir,
                  self.cache_dir]:
            d.mkdir(parents=True, exist_ok=True)
        try:
            self.components_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # A read-only system preset location is fine: presets are only
            # read from there, downloads go to cache_dir.
            pass

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