"""Bottle (Wine prefix) management."""

import json
import re
import shlex
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

from . import registry
from .config import Config
from .sandbox import forget_prefix_cache
from .wine import Wine

# HKCU keys behind the two window switches. Values use single backslashes,
# the form Wine's own `reg` command expects.
X11_DRIVER_KEY = r"Software\Wine\X11 Driver"
DESKTOPS_KEY = r"Software\Wine\Explorer\Desktops"
# Wine's switch for the virtual desktop: names which entry under Desktops is
# active. Without it the size alone does nothing, and leaving it behind keeps
# a screen-sized desktop alive after the size was deleted.
EXPLORER_KEY = r"Software\Wine\Explorer"

# Environment type → display label (shared by every view showing a bottle)
ENVIRONMENT_LABELS = {
    "gaming": "游戏",
    "office": "办公",
    "custom": "自定义",
}

# Windows versions as Wine's `winecfg -v` understands them.
WINDOWS_VERSIONS = (
    "win11", "win10", "win81", "win8", "win7", "vista",
    "win2003", "winxp", "win2k", "winme", "win98", "win95",
)

# Only the versions whose Wine key is not the user-facing name. Everything
# else (win10, win7, winxp…) is shown as-is.
WINDOWS_VERSION_LABELS = {
    "win81": "win8.1",
    "win2k": "win2000",
}


def windows_version_label(value: str) -> str:
    """Display label for a stored Windows version key."""
    raw = (value or "").strip()
    return WINDOWS_VERSION_LABELS.get(raw, raw)


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
            "sandbox": "host",  # host | flatpak (sandboxed graphics runtime)
            "installed_components": [],
            "dll_overrides": {},
            "component_records": {},
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
    def sandbox(self) -> str:
        """Runtime this bottle runs on: "host" or "flatpak"."""
        return self._meta.get("sandbox", "host") or "host"

    @sandbox.setter
    def sandbox(self, value: str):
        self._meta["sandbox"] = value or "host"
        self._save_meta()
        forget_prefix_cache(str(self.path))

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

    @property
    def hidden_shortcuts(self) -> List[str]:
        """Targets the user removed by hand.

        Discovery rescans the container every time the list is (re)loaded, so
        without this a removed entry would come straight back.
        """
        return list(self._meta.get("hidden_shortcuts", []))

    def hide_shortcut(self, target: str) -> bool:
        """Keep a removed shortcut out of future discovery passes."""
        hidden = self.hidden_shortcuts
        if not target or target in hidden:
            return False
        hidden.append(target)
        self._meta["hidden_shortcuts"] = hidden
        self._save_meta()
        return True

    def unhide_shortcut(self, target: str) -> bool:
        """Allow a previously removed shortcut to be discovered again."""
        hidden = self.hidden_shortcuts
        if target not in hidden:
            return False
        self._meta["hidden_shortcuts"] = [t for t in hidden if t != target]
        self._save_meta()
        return True

    def forget_shortcuts_under(self, root) -> int:
        """Drop every shortcut whose program lives inside `root`.

        Used after deleting an application folder: the app's own entries
        (updater, uninstaller, translator…) all die with it, so leaving them
        behind produces "程序文件不存在" on every double-click.
        Returns how many records were removed.
        """
        try:
            root_path = Path(root).resolve()
        except (OSError, ValueError):
            return 0
        keep, dropped = [], 0
        for entry in self.shortcuts:
            target = entry.get("target") or ""
            try:
                inside = bool(target) and Path(target).resolve().is_relative_to(root_path)
            except (OSError, ValueError):
                inside = False
            if inside:
                dropped += 1
            else:
                keep.append(entry)
        if dropped:
            self.shortcuts = keep
        return dropped

    def add_shortcut(self, name: str, target: str, source: str = "exe",
                     icon: str = "") -> bool:
        """Register a program in the shortcut list.

        Returns False when the same target is already listed, so clicking
        "添加程序" twice on one exe does not create duplicates.
        """
        items = self.shortcuts
        if any(item.get("target") == target for item in items):
            return False
        # An explicit add overrides an earlier "delete shortcut".
        self.unhide_shortcut(target)
        items.append({"name": name, "target": target,
                      "source": source, "icon": icon})
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

    def shortcut_args(self, target: str) -> List[str]:
        """Launch arguments remembered for one shortcut (empty when unset)."""
        for item in self.shortcuts:
            if item.get("target") == target:
                return [str(arg) for arg in (item.get("args") or [])]
        return []

    def set_shortcut_args(self, target: str, args: List[str]) -> bool:
        """Persist launch arguments for one shortcut.

        Stored as a list so quoting survives a save/load round trip; an empty
        list drops the key entirely, keeping bottle.json tidy.
        """
        items = self.shortcuts
        for item in items:
            if item.get("target") == target:
                cleaned = [str(arg) for arg in (args or []) if str(arg)]
                if cleaned:
                    item["args"] = cleaned
                else:
                    item.pop("args", None)
                self.shortcuts = items
                return True
        return False

    def launch_shortcut(self, target: str) -> bool:
        """Run a shortcut with the arguments it remembers."""
        return self.run(target, self.shortcut_args(target) or None)

    # ------------------------------------------------------------------
    # window options (winecfg's "Decorated" / "virtual desktop")
    # ------------------------------------------------------------------
    def _hkcu_value(self, key: str, name: str) -> str:
        """Read one HKCU value straight out of user.reg.

        Avoids spawning Wine just to paint a checkbox. The flip side is that a
        value written a moment ago may still only live in the running
        wineserver's memory, so callers should trust their own last write.
        """
        reg_file = self.path / "user.reg"
        if not reg_file.exists():
            return ""
        try:
            text = reg_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        tree_path = "HKCU" + registry.SEP + key.replace("\\", registry.SEP)
        for entry in registry.parse_values(text, tree_path):
            if entry.get("name") == name:
                return entry.get("data", "")
        return ""

    def _run_reg(self, command: str) -> tuple:
        """Run one ``reg`` command inside this bottle."""
        try:
            result = self.wine.run_cmd(str(self.path), command, timeout=60,
                                       env={"WINEDEBUG": "-all"})
        except Exception as error:  # noqa: BLE001 - shown to the user
            return False, str(error)
        if result.returncode == 0:
            return True, ""
        lines = [line.strip() for line in
                 (result.stderr or result.stdout or "").splitlines()
                 if line.strip()]
        # Wine prints its own chatter ("wineserver: using server-side
        # synchronization.", lsteamclient fixmes); the real complaint is the
        # line reg itself writes.
        message = next((line for line in reversed(lines)
                        if line.lower().startswith("reg:")),
                       lines[-1] if lines else "")
        return False, message[:300] or "wine reg 返回非零"

    @staticmethod
    def _reg_key(key: str) -> str:
        """Full path for Wine's ``reg``: it needs the hive, the .reg files not."""
        return key if key.upper().startswith("HKCU\\") else f"HKCU\\{key}"

    def _set_hkcu_value(self, key: str, name: str, data: str) -> tuple:
        return self._run_reg(
            f"reg add {shlex.quote(self._reg_key(key))} "
            f"/v {shlex.quote(name)} /t REG_SZ /d {shlex.quote(data)} /f")

    def _delete_hkcu_value(self, key: str, name: str) -> tuple:
        ok, error = self._run_reg(
            f"reg delete {shlex.quote(self._reg_key(key))} "
            f"/v {shlex.quote(name)} /f")
        if ok or not self._hkcu_value(key, name):
            # Wine errors out when the value isn't there; already-off is fine.
            return True, ""
        return False, error

    @property
    def window_decorated(self) -> bool:
        """Whether the window manager draws the titlebar (Wine default: yes)."""
        value = (self._hkcu_value(X11_DRIVER_KEY, "Decorated") or "Y").strip()
        return value.upper() != "N"

    def set_window_decorated(self, enabled: bool) -> tuple:
        """Turn WM titlebars on/off for this bottle (`Decorated`)."""
        return self._set_hkcu_value(X11_DRIVER_KEY, "Decorated",
                                    "Y" if enabled else "N")

    @property
    def virtual_desktop_enabled(self) -> bool:
        """Wine's switch for the virtual desktop (`Explorer\\Desktop`).

        This is what winecfg and Bottles toggle; the size under
        ``Desktops\\<name>`` alone does nothing.
        """
        return bool((self._hkcu_value(EXPLORER_KEY, "Desktop") or "").strip())

    @property
    def virtual_desktop(self) -> str:
        """Size of the active virtual desktop ("1920x1080"); "" when off."""
        if not self.virtual_desktop_enabled:
            return ""
        return (self._hkcu_value(DESKTOPS_KEY, "Default") or "").strip()

    def set_virtual_desktop(self, size: str) -> tuple:
        """Enable (``WxH``) or disable the virtual desktop for this bottle.

        Matches winecfg/Bottles: ``Explorer\\Desktop`` names the desktop and
        ``Desktops\\<name>`` holds its size. Writing only the size leaves an
        already-enabled desktop untouched, and clearing only the size keeps a
        screen-sized desktop alive — that is the "关掉了窗口还是很大" case.
        """
        size = (size or "").strip().lower().replace("×", "x")
        if not size:
            ok, error = self._delete_hkcu_value(EXPLORER_KEY, "Desktop")
            if not ok:
                return False, error
            return self._delete_hkcu_value(DESKTOPS_KEY, "Default")
        if not re.fullmatch(r"\d{3,5}x\d{3,5}", size):
            return False, "虚拟桌面尺寸格式应为 宽x高，例如 1920x1080。"
        ok, error = self._set_hkcu_value(DESKTOPS_KEY, "Default", size)
        if not ok:
            return False, error
        return self._set_hkcu_value(EXPLORER_KEY, "Desktop", "Default")

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

    @property
    def component_records(self) -> Dict[str, Dict]:
        """What each component put into the container.

        {"dxvk": {"files": ["system32/d3d11.dll", ...],
                  "overrides": {"d3d11": "native", ...}}}
        Files are relative to drive_c/windows. Components without a record
        (winetricks verbs, MSI installers) cannot be reverted file by file.
        """
        return self._meta.get("component_records", {})

    def get_component_record(self, name: str) -> Dict:
        return self.component_records.get(name, {})

    def set_component_record(self, name: str, files: List[str],
                             overrides: Dict[str, str]):
        """Remember the files/overrides a component installed."""
        self._meta.setdefault("component_records", {})[name] = {
            "files": list(files or []),
            "overrides": dict(overrides or {}),
        }
        self._save_meta()

    def drop_component_record(self, name: str):
        records = self._meta.get("component_records", {})
        if records.pop(name, None) is not None:
            self._save_meta()

    def component_overrides(self, exclude: str = None) -> List[str]:
        """DLL names still needed by components other than `exclude`."""
        names = []
        for component, record in self.component_records.items():
            if component == exclude:
                continue
            names.extend(record.get("overrides", {}))
        return names

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
        """Run an executable in the bottle.

        The working directory is the program's own folder: engines from the
        Win9x/XP era (Virtools, many installers) resolve their data files
        relative to it, so launching from WinBridge's own cwd makes them
        report "failed to initialize player" with every asset missing.
        """
        if not self.exists:
            return False
        workdir = None
        try:
            exe_path = Path(executable)
            if exe_path.is_file():
                workdir = str(exe_path.parent)
        except (OSError, ValueError):
            workdir = None
        result = self.wine.run(str(self.path), executable, args,
                               workdir=workdir, wait=False)
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
                      wine_path: str = "",
                      sandbox: str = "host") -> Optional[Bottle]:
        """Create a new bottle.

        `sandbox="flatpak"` creates the prefix with the flatpak runtime's
        libraries (its own Mesa/Vulkan) instead of the host ones; everything
        else — prefix path, Wine binary, programs — stays on the host.
        """
        bottle_path = self.bottles_dir / name
        if bottle_path.exists():
            return None

        # Use custom Wine path if specified; refuse early when there is no
        # Wine at all (a deb install may have Wine only in Recommends).
        wine = Wine(wine_path) if wine_path else self.wine
        if not wine.is_valid:
            return None

        # Create the Wine prefix
        success = wine.create_prefix(str(bottle_path), arch, sandbox=sandbox)
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
        bottle._meta["sandbox"] = sandbox or "host"
        if wine_path:
            bottle._meta["wine_path"] = wine_path
        bottle._save_meta()

        # Set Windows version
        bottle.windows_version = windows_version

        return bottle

    def create_or_clone(self, name: str, arch: str = "win64",
                        environment: str = "gaming",
                        windows_version: str = "win10",
                        description: str = "", wine_path: str = "",
                        sandbox: str = "host",
                        preinstall: bool = False) -> tuple:
        """Create a bottle, reusing the prepared template when possible.

        Returns (bottle, used_template). Kept separate from the UI so the
        whole "copy template or build a prefix" decision can run in a worker
        thread while a progress dialog is on screen.
        """
        if (preinstall and (sandbox or "host") == "host"
                and self.template_exists(arch, wine_path)):
            bottle, _error = self.bottle_from_template(name, arch, wine_path)
            if bottle is not None:
                bottle.windows_version = windows_version
                if environment:
                    bottle.environment = environment
                if description:
                    bottle.description = description
                bottle.sandbox = sandbox or "host"
                return bottle, True
        bottle = self.create_bottle(name=name, arch=arch,
                                    environment=environment,
                                    windows_version=windows_version,
                                    description=description,
                                    wine_path=wine_path, sandbox=sandbox)
        return bottle, False

    def delete_bottle(self, name: str) -> bool:
        """Delete a bottle by name."""
        bottle = self.get_bottle(name)
        if bottle:
            bottle.delete()
            return True
        return False

    # Items that make a bottle what it is. Same list Bottles copies in
    # backup.py::_DUPLICATE_ITEMS (drive_c + the registry hives), because that
    # is where installed .NET/fonts/components live. `dosdevices` is copied as
    # well so drive letters keep working without a wineboot round trip.
    _DUPLICATE_ITEMS = ("drive_c", "dosdevices", "system.reg", "user.reg",
                        "userdef.reg")

    # Components a new bottle is expected to have (VC++ runtime, Latin and
    # CJK fonts, .NET 4.8). Installing them takes ~12 minutes under Wine, so
    # the result is snapshotted as a template and every later bottle is a
    # copy of it (a few seconds).
    DEFAULT_COMPONENTS = ("vcrun2022", "corefonts", "cjkfonts", "dotnet48")

    def clone_bottle(self, source_name: str, new_name: str) -> tuple:
        """Copy a bottle so a new one starts with everything installed."""
        source = self.bottles_dir / str(source_name)
        if not (source / "user.reg").exists():
            return None, f"找不到容器：{source_name}"
        return self._copy_prefix(source, self.bottles_dir, new_name)

    @property
    def template_dir(self) -> Path:
        return self.config.data_dir / "templates"

    def template_key(self, arch: str, wine_path: str) -> str:
        """Templates are per architecture and per Wine build."""
        wine = Path(wine_path or self.config.wine_path)
        tag = wine.parent.parent.name or wine.parent.name or "wine"
        return f"{arch or 'win64'}-{tag}"

    def template_exists(self, arch: str, wine_path: str) -> bool:
        template = self.template_dir / self.template_key(arch, wine_path)
        return (template / "user.reg").exists()

    def bottle_from_template(self, name: str, arch: str, wine_path: str) -> tuple:
        """Create a bottle by copying the prepared template (fast path)."""
        template = self.template_dir / self.template_key(arch, wine_path)
        if not (template / "user.reg").exists():
            return None, "还没有可用的基础模板。"
        bottle, error = self._copy_prefix(template, self.bottles_dir, name)
        if bottle is None:
            return None, error
        bottle._meta["arch"] = arch or "win64"
        if wine_path:
            bottle._meta["wine_path"] = wine_path
        bottle._save_meta()
        return bottle, ""

    def save_template(self, bottle) -> Optional[str]:
        """Snapshot a fully prepared bottle as the template for its runtime."""
        if (bottle.sandbox or "host") != "host":
            return None
        key = self.template_key(bottle.arch, bottle.wine_path)
        target = self.template_dir / key
        if (target / "user.reg").exists():
            return key
        self.template_dir.mkdir(parents=True, exist_ok=True)
        _, error = self._copy_prefix(Path(bottle.path), self.template_dir, key)
        return key if not error else None

    def install_default_components(self, bottle, progress_callback=None,
                                  cancel_event=None) -> list:
        """Install DEFAULT_COMPONENTS into a bottle; returns [(name, error)]."""
        from .download import ComponentManager

        manager = ComponentManager(self.config)
        failures = []
        for name in self.DEFAULT_COMPONENTS:
            if cancel_event is not None and cancel_event.is_set():
                break
            ok, log, overrides, files = manager.install(
                name, str(bottle.path), progress_callback, cancel_event)
            if not ok:
                failures.append((name, (log or "").strip()[:200]))
                continue
            bottle.add_component(name)
            for dll, mode in (overrides or {}).items():
                bottle.set_dll_override(dll, mode)
            bottle.set_component_record(name, files or [], overrides or {})
        return failures

    def _copy_prefix(self, source: Path, root: Path, new_name: str) -> tuple:
        """Copy one prefix into ``root/new_name`` and fix up its metadata."""
        new_name = (new_name or "").strip()
        if not new_name:
            return None, "容器名称不能为空。"
        if "/" in new_name or new_name in (".", ".."):
            return None, "容器名称不能包含斜杠。"

        target_name = self._unique_name_in(root, new_name)
        target = root / target_name

        needed = 0
        for item in self._DUPLICATE_ITEMS:
            path = source / item
            if path.is_dir():
                needed += sum(f.stat().st_size for f in path.rglob("*")
                              if f.is_file() and not f.is_symlink())
            elif path.is_file():
                needed += path.stat().st_size
        free = shutil.disk_usage(root).free
        if needed and free < needed:
            return None, (f"磁盘空间不足：需要约 {needed // (1024 ** 2)} MB，"
                          f"剩余 {free // (1024 ** 2)} MB。")

        try:
            target.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            return None, str(error)

        try:
            for item in self._DUPLICATE_ITEMS:
                src = source / item
                dst = target / item
                if src.is_dir():
                    shutil.copytree(src, dst, symlinks=True)
                elif src.is_file():
                    shutil.copy2(src, dst)

            meta_file = source / "bottle.json"
            meta = (json.loads(meta_file.read_text("utf-8"))
                    if meta_file.exists() else {})
            meta["name"] = target_name
            meta["created"] = datetime.now().isoformat()
            meta["modified"] = meta["created"]
            # Shortcut targets, icons and component records may hold absolute
            # paths inside the old prefix; point them at the copy.
            meta = self._rewrite_bottle_paths(meta, str(source), str(target))
            (target / "bottle.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except (OSError, ValueError) as error:
            shutil.rmtree(target, ignore_errors=True)
            return None, str(error)

        return Bottle(str(target), config=self.config), ""

    def _unique_name_in(self, root: Path, name: str) -> str:
        """Append __1, __2 … until the name is free (Bottles does the same)."""
        candidate = name
        suffix = 1
        while (root / candidate).exists():
            candidate = f"{name}__{suffix}"
            suffix += 1
        return candidate

    @classmethod
    def _rewrite_bottle_paths(cls, value, old_root: str, new_root: str):
        """Replace old prefix paths inside bottle.json strings, recursively."""
        if isinstance(value, str):
            return value.replace(old_root, new_root)
        if isinstance(value, list):
            return [cls._rewrite_bottle_paths(v, old_root, new_root) for v in value]
        if isinstance(value, dict):
            return {k: cls._rewrite_bottle_paths(v, old_root, new_root)
                    for k, v in value.items()}
        return value

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
        """Duplicate a bottle.

        Kept as the simple entry point (returns the new bottle or None); the
        work happens in :meth:`clone_bottle`, which reports *why* it failed
        and rewrites paths inside the copied metadata.
        """
        bottle, _error = self.clone_bottle(name, new_name)
        return bottle