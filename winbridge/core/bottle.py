"""Bottle (Wine prefix) management."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from .config import Config
from .wine import Wine

# Environment type → display label (shared by every view showing a bottle)
ENVIRONMENT_LABELS = {
    "gaming": "游戏",
    "office": "办公",
    "custom": "自定义",
}


def environment_key(value: str) -> str:
    """Normalise a stored environment value to one of the known keys.

    Older bottles store the localised combo text (e.g.
    "游戏/多媒体 (gaming)") instead of the bare key, so match by substring.
    """
    raw = (value or "").lower()
    for key in ENVIRONMENT_LABELS:
        if key in raw:
            return key
    return "custom"


def environment_label(value: str) -> str:
    """Display label for a stored environment value."""
    return ENVIRONMENT_LABELS[environment_key(value)]


class Bottle:
    """Represents a single Wine prefix / bottle."""

    def __init__(self, path: str, name: str = None, config: Config = None):
        self.path = Path(path)
        self.config = config or Config()
        self.meta_file = self.path / "bottle.json"
        # Temporarily create Wine with default path; _load_meta() needs self.wine
        self.wine = Wine(self.config.wine_path)
        self._meta = self._load_meta()
        if name:
            self._meta["name"] = name
            self._save_meta()
        # Now update Wine to use the bottle-specific path if set in meta
        wp = self._meta.get("wine_path", "")
        if wp:
            self.wine = Wine(wp)

    def _load_meta(self) -> Dict:
        """Load bottle metadata."""
        default = {
            "name": self.path.name,
            "created": datetime.now().isoformat(),
            "modified": datetime.now().isoformat(),
            "arch": self.config.wine_arch,
            "windows_version": "win10",
            "description": "",
            "environment": "gaming",  # gaming, office, custom
            "version": self.wine.version,
            "wine_path": "",
            "installed_components": [],
            "dll_overrides": {},
        }
        if self.meta_file.exists():
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                default.update(data)
            except (json.JSONDecodeError, OSError):
                pass
        return default

    def _save_meta(self):
        """Save bottle metadata."""
        self._meta["modified"] = datetime.now().isoformat()
        self.meta_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(self._meta, f, indent=2, ensure_ascii=False)

    @property
    def name(self) -> str:
        return self._meta.get("name", self.path.name)

    @name.setter
    def name(self, value: str):
        self._meta["name"] = value
        self._save_meta()

    @property
    def wine_path(self) -> str:
        """Get the bottle-specific Wine path, or the global default."""
        wp = self._meta.get("wine_path", "")
        return wp if wp else self.config.wine_path

    @wine_path.setter
    def wine_path(self, value: str):
        self._meta["wine_path"] = value
        self._save_meta()
        # Recreate Wine instance with the new path
        self.wine = Wine(value if value else self.config.wine_path)

    @property
    def created(self) -> str:
        return self._meta.get("created", "")

    @property
    def modified(self) -> str:
        return self._meta.get("modified", "")

    @property
    def arch(self) -> str:
        return self._meta.get("arch", "win64")

    @property
    def windows_version(self) -> str:
        return self._meta.get("windows_version", "win10")

    @windows_version.setter
    def windows_version(self, value: str):
        self._meta["windows_version"] = value
        self._save_meta()
        self.wine.set_win_version(str(self.path), value)

    @property
    def description(self) -> str:
        return self._meta.get("description", "")

    @description.setter
    def description(self, value: str):
        self._meta["description"] = value
        self._save_meta()

    @property
    def environment(self) -> str:
        return self._meta.get("environment", "gaming")

    @environment.setter
    def environment(self, value: str):
        self._meta["environment"] = value
        self._save_meta()

    @property
    def installed_components(self) -> List[str]:
        return self._meta.get("installed_components", [])

    @property
    def shortcuts(self) -> List[Dict]:
        """Remembered applications: name / target / source / icon.

        Kept in metadata rather than re-scanned every time so a program
        stays in the list after its Windows desktop shortcut is deleted.
        """
        return list(self._meta.get("shortcuts", []))

    @shortcuts.setter
    def shortcuts(self, value: List[Dict]):
        self._meta["shortcuts"] = list(value)
        self._save_meta()

    def forget_shortcut(self, target: str) -> bool:
        """Drop one shortcut from the bottle's list (program files untouched)."""
        items = [s for s in self.shortcuts if s.get("target") != target]
        if len(items) == len(self.shortcuts):
            return False
        self.shortcuts = items
        return True

    def rename_shortcut(self, target: str, new_name: str) -> bool:
        """Rename a shortcut's display name (the program file is untouched)."""
        items = self.shortcuts
        for item in items:
            if item.get("target") == target:
                item["name"] = new_name
                self.shortcuts = items
                return True
        return False

    @property
    def dll_overrides(self) -> Dict[str, str]:
        return self._meta.get("dll_overrides", {})

    @property
    def exists(self) -> bool:
        return self.path.exists() and (self.path / "user.reg").exists()

    @property
    def drive_c_size(self) -> str:
        """Get size of drive_c directory."""
        drive_c = self.path / "drive_c"
        if drive_c.exists():
            total = sum(f.stat().st_size for f in drive_c.rglob("*")
                        if f.is_file())
            for unit in ["B", "KB", "MB", "GB"]:
                if total < 1024:
                    return f"{total:.1f} {unit}"
                total /= 1024
            return f"{total:.1f} TB"
        return "0 B"

    def get_config(self) -> Dict:
        """Get full bottle configuration."""
        return {
            "name": self.name,
            "arch": self.arch,
            "windows_version": self.windows_version,
            "environment": self.environment,
            "description": self.description,
            "created": self.created,
            "modified": self.modified,
            "wine_version": self._meta.get("version", "unknown"),
            "wine_path": self.wine_path,
            "path": str(self.path),
            "size": self.drive_c_size,
            "installed_components": self.installed_components,
            "dll_overrides": self.dll_overrides,
        }

    def add_component(self, name: str):
        """Mark a component as installed."""
        if name not in self._meta["installed_components"]:
            self._meta["installed_components"].append(name)
            self._save_meta()

    def remove_component(self, name: str):
        """Mark a component as uninstalled."""
        if name in self._meta["installed_components"]:
            self._meta["installed_components"].remove(name)
            self._save_meta()

    def set_dll_override(self, dll: str, mode: str):
        """Set a DLL override (native, builtin, native,builtin, etc.)."""
        self._meta["dll_overrides"][dll] = mode
        self._save_meta()

    def remove_dll_override(self, dll: str):
        """Remove a DLL override."""
        self._meta["dll_overrides"].pop(dll, None)
        self._save_meta()

    def set_registry(self, key: str, value_name: str, value_type: str,
                     value_data: str, hive: str = "HKCU"):
        """Set a registry value."""
        reg_path = self.path / f"{hive.lower()}.reg"
        # Use wine reg add
        self.wine.reg(str(self.path), str(reg_path))

    def delete(self):
        """Delete the bottle and all its data.

        Kills the wineserver and *waits* for it to exit (so file handles
        are released), then removes the prefix directory and verifies the
        removal actually succeeded. Without the wait/verify, a residual
        directory containing user.reg would make list_bottles() show the
        deleted bottle again moments later.
        """
        if not self.path.exists():
            return True
        try:
            self.wine.kill(str(self.path))
        except Exception:
            pass
        # Retry removal a few times; a just-killed wineserver may still be
        # flushing files on the first attempt.
        for attempt in range(3):
            try:
                shutil.rmtree(str(self.path))
            except OSError:
                import time
                time.sleep(1)
            if not self.path.exists():
                # Give a SIGKILLed wineserver a moment to die — if it was
                # still alive it cannot flush, but double-check no registry
                # files were recreated in the meantime.
                import time
                time.sleep(1.5)
                if not self.path.exists():
                    return True
        # Removal failed — don't silently leave a zombie bottle behind.
        raise OSError(f"删除容器失败，目录仍存在: {self.path}")

    def run(self, executable: str, args: list = None) -> bool:
        """Run an executable in the bottle."""
        if not self.exists:
            return False
        result = self.wine.run(str(self.path), executable, args, wait=False)
        return True


class BottleManager:
    """Manages all bottles."""

    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.wine = Wine(self.config.wine_path)

    @property
    def bottles_dir(self) -> Path:
        return self.config.bottles_dir

    def list_bottles(self) -> List[Bottle]:
        """List all available bottles."""
        bottles = []
        if not self.bottles_dir.exists():
            return bottles
        for item in sorted(self.bottles_dir.iterdir()):
            if item.is_dir():
                bottle = Bottle(str(item), config=self.config)
                if bottle.exists:
                    bottles.append(bottle)
        return bottles

    def get_bottle(self, name: str) -> Optional[Bottle]:
        """Get a bottle by name."""
        path = self.bottles_dir / name
        if path.exists():
            return Bottle(str(path), config=self.config)
        return None

    def create_bottle(self, name: str, arch: str = "win64",
                      environment: str = "gaming",
                      windows_version: str = "win10",
                      description: str = "",
                      wine_path: str = "") -> Optional[Bottle]:
        """Create a new bottle."""
        bottle_path = self.bottles_dir / name
        if bottle_path.exists():
            return None

        # Use custom Wine path if specified
        wine = Wine(wine_path) if wine_path else self.wine

        # Create the Wine prefix
        success = wine.create_prefix(str(bottle_path), arch)
        if not success:
            return None

        # Inject host CJK + core Latin fonts so Wine apps can render
        # Chinese/Japanese/Korean characters instead of tofu boxes.
        wine.inject_fonts(str(bottle_path))

        # Create bottle metadata
        bottle = Bottle(str(bottle_path), name=name, config=self.config)
        bottle._meta["arch"] = arch
        bottle._meta["environment"] = environment
        bottle._meta["windows_version"] = windows_version
        bottle._meta["description"] = description
        bottle._meta["version"] = wine.version
        if wine_path:
            bottle._meta["wine_path"] = wine_path
        bottle._save_meta()

        # Set Windows version
        bottle.windows_version = windows_version

        return bottle

    def delete_bottle(self, name: str) -> bool:
        """Delete a bottle by name."""
        bottle = self.get_bottle(name)
        if bottle:
            bottle.delete()
            return True
        return False

    def rename_bottle(self, old_name: str, new_name: str) -> bool:
        """Rename a bottle."""
        old_path = self.bottles_dir / old_name
        new_path = self.bottles_dir / new_name
        if not old_path.exists() or new_path.exists():
            return False
        old_path.rename(new_path)
        bottle = Bottle(str(new_path), config=self.config)
        bottle.name = new_name
        return True

    def duplicate_bottle(self, name: str, new_name: str) -> Optional[Bottle]:
        """Duplicate a bottle."""
        src = self.bottles_dir / name
        dst = self.bottles_dir / new_name
        if not src.exists() or dst.exists():
            return None
        shutil.copytree(str(src), str(dst))
        bottle = Bottle(str(dst), name=new_name, config=self.config)
        bottle._meta["created"] = datetime.now().isoformat()
        bottle._save_meta()
        return bottle