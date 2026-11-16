"""One-click installation of portable Wine runners.

WinBridge can use any self-contained Wine tree (``bin/wine`` + ``lib/``):
Kron4ek's upstream Wine builds, Wine-GE and Proton-GE. They are downloaded
as release archives from GitHub — through the same mirrors the component
installer uses — extracted under ``~/.local/share/winbridge/runners`` and
then selectable per bottle.

The archives are big, so the download goes through the component
installer's segmented/mirrored fetcher instead of a private implementation.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import Config
from .download import (GITHUB_MIRRORS, ComponentManager, InstallCancelled,
                       check_cancel)

# `relative` is the wine binary inside the archive (after its top-level
# directory). Proton keeps everything under files/, Wine builds do not.
WINE_BUILDS: Dict[str, dict] = {
    "wine11": {
        "label": "Wine 11",
        "description": "Kron4ek 构建的上游 Wine 11（自包含，约 96MB）",
        "repo": "Kron4ek/Wine-Builds",
        "asset": r"^wine-11\.\d+-amd64\.tar\.xz$",
        "relative": "bin/wine",
        "pinned_version": "11.22",
        "pinned_url": ("https://github.com/Kron4ek/Wine-Builds/releases/"
                       "download/11.22/wine-11.22-amd64.tar.xz"),
    },
    "soda": {
        "label": "Soda 11",
        "description": "Bottles 的 Soda 11（Valve Wine + Staging + Proton 补丁，约 166MB）",
        "repo": "bottlesdevs/wine",
        # Stable builds are named soda-11.0-N-x86_64.tar.xz; experimental
        # builds insert "-experimental" before the architecture and are not
        # what this entry installs.
        "asset": r"^soda-11\.0-\d+-x86_64\.tar\.xz$",
        "relative": "bin/wine",
        "per_page": 100,
        "pinned_version": "soda-11.0-10",
        "pinned_url": ("https://github.com/bottlesdevs/wine/releases/"
                       "download/soda-11.0-10/soda-11.0-10-x86_64.tar.xz"),
    },
    "proton11": {
        "label": "Proton 11",
        "description": "GE-Proton 11（Valve Proton 补丁集，约 540MB）",
        "repo": "GloriousEggroll/proton-ge-custom",
        "asset": r"^GE-Proton11-\d+-x86_64\.tar\.gz$",
        "relative": "files/bin/wine",
        "pinned_version": "GE-Proton11-12",
        "pinned_url": ("https://github.com/GloriousEggroll/proton-ge-custom/"
                       "releases/download/GE-Proton11-12/"
                       "GE-Proton11-12-x86_64.tar.gz"),
    },
    "winege": {
        "label": "Wine-GE",
        "description": "wine-ge-custom（GE-Proton8-26，约 223MB，已停止更新）",
        "repo": "GloriousEggroll/wine-ge-custom",
        "asset": r"^wine-lutris-GE-Proton8-26-x86_64\.tar\.xz$",
        "relative": "bin/wine",
        "pinned_version": "GE-Proton8-26",
        "pinned_url": ("https://github.com/GloriousEggroll/wine-ge-custom/"
                       "releases/download/GE-Proton8-26/"
                       "wine-lutris-GE-Proton8-26-x86_64.tar.xz"),
    },
}


def available_builds() -> List[dict]:
    """Build descriptors for the UI (copy so callers cannot mutate them)."""
    return [{"id": key, **value} for key, value in WINE_BUILDS.items()]


def _api_urls(repo: str, per_page: int = 30) -> List[str]:
    """Mirror first, direct GitHub last — same policy as components."""
    base = f"https://api.github.com/repos/{repo}/releases?per_page={per_page}"
    return [f"{mirror}{base}" for mirror in GITHUB_MIRRORS] + [base]


def _fetch_releases(repo: str, timeout: int = 8,
                    per_page: int = 30) -> list:
    for url in _api_urls(repo, per_page):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "WinBridge/1.3.4"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
            if isinstance(data, list):
                return data
        except Exception:
            continue
    return []


def resolve_asset(build_id: str, timeout: int = 8) -> dict:
    """Newest matching asset for a build.

    Returns ``{version, name, url, size}``. Falls back to the pinned release
    when GitHub (or every mirror) is unreachable, so installing still works
    offline from a cached archive.
    """
    build = WINE_BUILDS[build_id]
    pattern = re.compile(build["asset"])
    for release in _fetch_releases(build["repo"], timeout=timeout,
                                   per_page=build.get("per_page", 30)):
        tag = release.get("tag_name") or ""
        for asset in release.get("assets") or []:
            name = asset.get("name") or ""
            if not pattern.match(name):
                continue
            # An archived release list may include LoL-only builds; the
            # pattern already pins the series we asked for.
            return {
                "version": tag or build["pinned_version"],
                "name": name,
                "url": asset.get("browser_download_url") or build["pinned_url"],
                "size": int(asset.get("size") or 0),
            }
    return {
        "version": build["pinned_version"],
        "name": build["pinned_url"].rsplit("/", 1)[-1],
        "url": build["pinned_url"],
        "size": 0,
    }


def _safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "runner"


def _tree_size(path: Path) -> int:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(root) / name).lstat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _linked_commands(root: Path) -> List[str]:
    """Symlinks in the usual bin dirs that point inside ``root``."""
    links = []
    for directory in (Path("/usr/bin"), Path("/usr/local/bin"),
                      Path.home() / ".local" / "bin"):
        if not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_symlink():
                continue
            try:
                target = Path(os.path.realpath(entry))
            except OSError:
                continue
            if target == root or root in target.parents:
                links.append(str(entry))
    return links


class WineRuntimeManager:
    """Installs and lists portable Wine runners."""

    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.runners_dir = self.config.data_dir / "runners"

    @property
    def component_manager(self) -> ComponentManager:
        if getattr(self, "_cm", None) is None:
            self._cm = ComponentManager(self.config)
        return self._cm

    def installed(self) -> List[dict]:
        """Runners on disk, newest installation first.

        Returns ``{id, label, version, wine_path, path}`` dictionaries. A
        directory without ``runner.json`` is still accepted when it has a
        usable ``bin/wine`` — users may drop a Wine tree in by hand.
        """
        found = []
        if not self.runners_dir.is_dir():
            return found
        entries = [entry for entry in self.runners_dir.iterdir()
                   if entry.is_dir()]
        entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        for entry in entries:
            meta_file = entry / "runner.json"
            meta = {}
            if meta_file.is_file():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}
            wine_path = Path(meta.get("wine_path") or "")
            if not wine_path.is_file():
                wine_path = self._guess_wine(entry)
            if not wine_path or not wine_path.is_file():
                continue
            build = WINE_BUILDS.get(meta.get("id") or "", {})
            found.append({
                "id": meta.get("id") or entry.name,
                "label": meta.get("label") or build.get("label") or entry.name,
                "version": meta.get("version") or "",
                "wine_path": str(wine_path),
                "path": str(entry),
                "archive": meta.get("archive") or "",
            })
        return found

    @staticmethod
    def _guess_wine(root: Path) -> Optional[Path]:
        for relative in ("bin/wine", "files/bin/wine"):
            candidate = root / relative
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def version_key(version: str) -> tuple:
        """Numeric part of a runner version, for ordering.

        ``soda-11.0-10`` → (11, 0, 10); ``GE-Proton11-12`` → (11, 12);
        ``wine-11.22`` → (11, 22). Prefixes are ignored.
        """
        return tuple(int(part) for part in re.findall(r"\d+", version or ""))

    def check_updates(self, timeout: int = 6) -> list:
        """Installed runners whose upstream release is newer.

        Only checks runners that were installed by WinBridge (their
        ``runner.json`` carries the build id); hand-dropped trees have no
        upstream to compare against. Intended for a background thread — each
        runner needs one GitHub API query.
        """
        updates = []
        for runner in self.installed():
            if runner["id"] not in WINE_BUILDS or not runner.get("version"):
                continue
            latest = resolve_asset(runner["id"], timeout=timeout)
            if (self.version_key(latest["version"])
                    > self.version_key(runner["version"])):
                updates.append({
                    **runner,
                    "latest_version": latest["version"],
                    "asset": latest,
                })
        return updates

    def system_wine(self) -> dict:
        """Describe the Wine binary WinBridge falls back to."""
        path = Path(self.config.wine_path or "")
        exists = path.exists() or path.is_symlink()
        return {
            "path": str(path),
            "exists": exists,
            "version": self.probe_version(str(path)) if exists else "",
            "target": os.path.realpath(path) if exists else str(path),
        }

    def delete_runner(self, runner: dict) -> tuple:
        """Delete one WinBridge-managed runner directory.

        Refuses anything outside ``runners_dir`` so a tampered ``runner.json``
        cannot point the deletion at an arbitrary directory.
        """
        root = Path(runner.get("path") or "").resolve()
        runners_dir = self.runners_dir.resolve()
        if root.parent != runners_dir:
            return False, "拒绝删除非 WinBridge 管理的目录"
        if not root.is_dir():
            return False, "该 Wine 版本目录已经不存在"
        try:
            shutil.rmtree(root)
        except OSError as error:
            return False, str(error)
        archive = runner.get("archive") or ""
        if archive:
            cached = (self.config.cache_dir / "runners" / Path(archive).name)
            try:
                cached.unlink(missing_ok=True)
            except OSError:
                pass
        return True, f"已删除 {root.name}"

    def _dpkg_packages(self, path: Path) -> List[str]:
        try:
            result = subprocess.run(
                ["dpkg", "-S", str(path)], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0 or not result.stdout.strip():
            return []
        packages = set()
        for line in result.stdout.splitlines():
            prefix = line.rsplit(": ", 1)[0]
            for package in prefix.split(","):
                package = package.strip()
                if package and "wine" in package.lower():
                    packages.add(package)
        return sorted(packages)

    def system_wine_removal_plan(self) -> dict:
        """What deleting the system Wine would do, without doing it."""
        info = self.system_wine()
        path = Path(info["path"])
        target = Path(info["target"])
        root = target.parent.parent if target.parent.name == "bin" else None
        plan = {
            **info,
            "root": str(root) if root else "",
            "links": [],
            "size": 0,
            "packages": [],
            "command": [],
            "removable": False,
            "reason": "",
        }
        if not info["exists"]:
            plan["reason"] = "系统 Wine 未安装"
            return plan

        # Package-managed (apt/rpm/pacman) Wine is removed through the
        # package manager, never by deleting files behind dpkg's back.
        packages = self._dpkg_packages(path)
        if root is not None:
            packages = sorted(set(packages) | set(self._dpkg_packages(root)))
        if packages:
            plan["packages"] = packages
            if shutil.which("apt-get"):
                plan["command"] = ["pkexec", "apt-get", "remove", "-y"] + packages
                plan["removable"] = True
            else:
                plan["reason"] = ("系统 Wine 由包管理器安装，请用系统包管理器卸载："
                                  + ", ".join(packages))
            return plan

        unsafe = {Path("/"), Path("/usr"), Path("/usr/local"), Path("/opt"),
                  Path("/home"), Path.home()}
        system_prefixes = (Path("/usr"), Path("/etc"), Path("/var"),
                           Path("/boot"))
        if (root is None or root in unsafe or len(root.parts) < 3
                or any(root == prefix or prefix in root.parents
                       for prefix in system_prefixes)):
            plan["reason"] = "无法确定安全的 Wine 运行时目录，请手动删除"
            return plan
        if not ((root / "bin" / "wine").is_file()
                or (root / "bin" / "wine64").is_file()):
            plan["reason"] = "该路径不是完整的 Wine 运行时"
            return plan
        if not shutil.which("pkexec"):
            plan["reason"] = "未找到 pkexec（polkit），无法请求管理员权限"
            return plan

        links = _linked_commands(root)
        plan.update({
            "links": links,
            "size": _tree_size(root),
            "removable": True,
            "command": (["pkexec", "rm", "-rf"] + links + [str(root)]),
        })
        return plan

    def remove_system_wine(self) -> tuple:
        """Delete the system Wine, using apt for package-managed installs."""
        plan = self.system_wine_removal_plan()
        if not plan["removable"]:
            return False, plan["reason"] or "无法删除系统 Wine"
        try:
            result = subprocess.run(
                plan["command"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600)
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            return False, str(error)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            return False, detail[-400:] or "删除命令执行失败"
        return True, "系统 Wine 已删除"

    def install(self, build_id: str,
                progress_callback: Callable = None,
                cancel_event=None) -> tuple:
        """Download + extract one runner. Returns ``(ok, message)``."""
        if build_id not in WINE_BUILDS:
            return False, f"未知的 Wine 版本: {build_id}"
        build = WINE_BUILDS[build_id]

        def report(percent: int, message: str):
            if progress_callback:
                progress_callback(max(0, min(100, percent)), message)

        report(1, f"正在查询 {build['label']} 最新版本...")
        asset = resolve_asset(build_id)
        check_cancel(cancel_event)

        self.runners_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = self.config.cache_dir / "runners"
        cache_dir.mkdir(parents=True, exist_ok=True)
        archive = cache_dir / asset["name"]

        if archive.exists():
            valid, _ = ComponentManager._verify_file(str(archive))
            if not valid:
                archive.unlink(missing_ok=True)

        if not archive.exists():
            report(3, f"正在下载 {build['label']} {asset['version']}...")
            ok, error = self.component_manager._download_file(
                asset["url"], str(archive),
                lambda value, total, message: report(
                    5 + int(value * 0.75), message),
                label=f"{build['label']} {asset['version']}",
                cancel_event=cancel_event)
            if not ok:
                # keep going: a previous run may have left another archive
                return False, error

        check_cancel(cancel_event)
        report(82, f"正在解压 {build['label']}...")
        temp_root = Path(tempfile.mkdtemp(
            prefix=f"winbridge-wine-{build_id}-", dir=str(self.runners_dir)))
        extract_dir = temp_root / "extract"
        extract_dir.mkdir()
        try:
            ok, error = ComponentManager._extract_archive(
                str(archive), str(extract_dir))
            if not ok:
                return False, error

            source_root, wine_relative = self._find_wine_root(
                extract_dir, build["relative"])
            if source_root is None:
                return False, "压缩包里没有找到 Wine 可执行文件（bin/wine）"

            version_slug = _safe_slug(asset["version"])
            if not version_slug.lower().startswith(build_id.lower() + "-"):
                version_slug = f"{build_id}-{version_slug}"
            slug = version_slug
            dest = self.runners_dir / slug
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            self._move_tree(source_root, dest, flatten=source_root == extract_dir)

            wine_path = dest / wine_relative
            if not wine_path.is_file():
                return False, f"Wine 可执行文件缺失: {wine_path}"
            try:
                wine_path.chmod(wine_path.stat().st_mode | 0o755)
            except OSError:
                pass

            meta = {
                "id": build_id,
                "label": build["label"],
                "version": asset["version"],
                "wine_path": str(wine_path),
                "archive": asset["name"],
            }
            (dest / "runner.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            report(100, f"{build['label']} {asset['version']} 安装完成")
            return True, str(wine_path)
        except InstallCancelled:
            raise
        except Exception as error:  # noqa: BLE001 - report to the dialog
            return False, str(error)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @staticmethod
    def _find_wine_root(extract_dir: Path, relative: str) -> tuple:
        """Locate the tree to move and the wine path relative to it."""
        candidate = extract_dir / relative
        if candidate.is_file():
            return extract_dir, relative
        for child in extract_dir.iterdir():
            if not child.is_dir():
                continue
            candidate = child / relative
            if candidate.is_file():
                return child, relative
        return None, ""

    @staticmethod
    def _move_tree(source: Path, dest: Path, flatten: bool = False):
        if flatten:
            dest.mkdir(parents=True, exist_ok=True)
            for child in source.iterdir():
                shutil.move(str(child), str(dest / child.name))
        else:
            shutil.move(str(source), str(dest))

    @staticmethod
    def probe_version(wine_path: str) -> str:
        """``wine --version`` for a runner (used by tests/manual checks)."""
        environment = os.environ.copy()
        root = Path(wine_path).resolve().parent.parent
        lib_dirs = [str(path) for path in (root / "lib", root / "lib64")
                    if path.is_dir()]
        if lib_dirs and not str(root).startswith("/usr"):
            existing = environment.get("LD_LIBRARY_PATH", "")
            environment["LD_LIBRARY_PATH"] = ":".join(
                lib_dirs + ([existing] if existing else []))
        try:
            result = subprocess.run(
                [wine_path, "--version"], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20,
                env=environment)
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"