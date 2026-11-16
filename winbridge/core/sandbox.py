"""Run Wine inside a flatpak sandbox with its own graphics stack.

A bottle can be marked `"sandbox": "flatpak"` in bottle.json. Its Wine
processes then run through a small flatpak app that only provides the
runtime's libraries (Mesa/glvnd/Vulkan), while the prefix, the Wine binary
and every program still live on the host at their usual paths.

The point is driver isolation: when the host graphics stack breaks an old
D3D game, the sandbox's newer Mesa makes it work without touching the
system packages.
"""

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

APP_ID = "io.github.zuimeideshijie.WinBridgeRuntime"
# Extensions that carry the sandbox's Mesa. They are deployed by flatpak
# next to the runtime, and their `files/lib` is what Wine needs to see.
GL_EXTENSIONS = ("org.freedesktop.Platform.GL.default",
                 "org.freedesktop.Platform.GL32.default")


def _flatpak() -> Optional[str]:
    return shutil.which("flatpak")


def _run(argv: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout)
    except Exception:
        return subprocess.CompletedProcess(argv, 1, "", "")


_APPS_CACHE: Dict[str, Optional[bool]] = {}


def app_installed(app_id: str = APP_ID) -> bool:
    """Is the sandbox runtime app installed (user or system)?"""
    if app_id in _APPS_CACHE:
        return bool(_APPS_CACHE[app_id])
    flatpak = _flatpak()
    if not flatpak:
        _APPS_CACHE[app_id] = False
        return False
    # `flatpak info` aborts with an assertion for apps installed from a local
    # (non-summary) repo, so ask the app list instead.
    result = _run([flatpak, "list", "--app", "--columns=application"])
    ok = app_id in result.stdout.split()
    _APPS_CACHE[app_id] = ok
    return ok


def forget_app_cache():
    _APPS_CACHE.clear()


def _deploy_roots() -> List[Path]:
    """Directories flatpak deploys runtimes into (system first)."""
    roots = [Path("/var/lib/flatpak"), Path.home() / ".local" / "share" / "flatpak"]
    return [r for r in roots if r.is_dir()]


def extension_files(extension_id: str) -> List[Path]:
    """`files` directory of every deployed extension matching `extension_id`."""
    found: List[Path] = []
    for root in _deploy_roots():
        base = root / "runtime" / extension_id
        if not base.is_dir():
            continue
        for arch_dir in sorted(base.iterdir()):
            if not arch_dir.is_dir():
                continue
            for branch in sorted(arch_dir.iterdir()):
                files = branch / "active" / "files"
                if files.is_dir():
                    found.append(files)
    return found


def wine_root(wine_path: str) -> Optional[Path]:
    """Directory holding a self-contained Wine (bin/ + lib/).

    The sandbox mounts this read-only, so it must not be a system directory:
    bind-mounting `/usr` into a flatpak sandbox would replace the runtime's
    own libc. Wine installed by the distro at /usr/bin/wine resolves through
    its symlink and usually lands in /opt, which is fine.
    """
    real = Path(os.path.realpath(wine_path))
    if real.parent.name == "bin":
        root = real.parent.parent
    else:
        root = real.parent
    if not (root / "lib").is_dir():
        # Not a self-contained install (distro wine: /usr/bin/wine + /usr/lib)
        return None
    if str(root) in ("/usr", "/", "/usr/local") or str(root).startswith("/usr/"):
        return None
    return root


def _wineserver_dir() -> Path:
    """Directory Wine keeps its per-prefix server sockets in.

    Wine names that directory after the uid only (`/tmp/.wine-<uid>`) and
    looks for the existing server there. Every flatpak sandbox gets a private
    /tmp, so without mounting this one directory a second sandbox starts a
    *second* wineserver for the same prefix. That is what hung wine's own
    taskmgr: it ran in a fresh sandbox while another wineserver held the
    prefix. The mount has to exist before flatpak starts, hence the mkdir.
    """
    path = Path("/tmp") / f".wine-{os.getuid()}"
    try:
        path.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        pass
    return path


def _graphics_env() -> Dict[str, str]:
    """Environment that points Mesa at the sandbox's own drivers."""
    dri_dirs: List[str] = []
    lib_dirs: List[str] = []
    icds: List[str] = []
    for ext in GL_EXTENSIONS:
        for files in extension_files(ext):
            lib = files / "lib"
            if (lib / "dri").is_dir():
                dri_dirs.append(str(lib / "dri"))
            if lib.is_dir():
                lib_dirs.append(str(lib))
            icd_dir = lib / "vulkan" / "icd.d"
            if icd_dir.is_dir():
                icds.extend(str(p) for p in sorted(icd_dir.glob("*.json")))
    env: Dict[str, str] = {}
    if dri_dirs:
        env["LIBGL_DRIVERS_PATH"] = ":".join(dri_dirs)
    if lib_dirs:
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs)
    if icds:
        env["VK_DRIVER_FILES"] = ":".join(icds)
        env["VK_ICD_FILENAMES"] = env["VK_DRIVER_FILES"]
    return env


class SandboxRuntime:
    """Launches commands inside the WinBridge sandbox flatpak app."""

    def __init__(self, app_id: str = APP_ID):
        self.app_id = app_id

    def available(self) -> bool:
        return app_installed(self.app_id) and bool(_flatpak())

    def _fs_args(self, wine_path: str) -> List[str]:
        args = ["--filesystem=home"]
        # Share the wineserver socket dir, not the whole /tmp: one wineserver
        # per prefix is what keeps a second sandboxed launch from deadlocking
        # on the registry/prefix the first one holds.
        args.append(f"--filesystem={_wineserver_dir()}")
        root = wine_root(wine_path)
        if root is not None:
            args.append(f"--filesystem={root}:ro")
        for ext in GL_EXTENSIONS:
            for files in extension_files(ext):
                args.append(f"--filesystem={files}:ro")
        return args

    def visible_wine(self, wine_path: str) -> str:
        """Path of the Wine binary *inside* the sandbox.

        `/usr/bin/wine` is usually a symlink into `/opt/…`, and the sandbox's
        `/usr` is the runtime, not the host: the symlink does not exist there
        even though its target is mounted. Resolve it.
        """
        real = os.path.realpath(wine_path)
        root = wine_root(wine_path)
        if root is not None:
            try:
                if Path(real).is_relative_to(root):
                    return real
            except (OSError, ValueError):
                pass
        return wine_path

    def command(self, argv: List[str], wine_path: str,
                env: Dict[str, str] = None) -> List[str]:
        """Wrap a single executable + arguments."""
        argv = [self.visible_wine(str(argv[0])), *argv[1:]]
        exports = " ".join(f"{k}={shlex.quote(v)}"
                           for k, v in self._env(wine_path, env).items())
        inner = " ".join(shlex.quote(str(a)) for a in argv)
        script = f"export {exports}; exec {inner}" if exports else f"exec {inner}"
        return ["flatpak", "run", *self._fs_args(wine_path),
                f"--command=bash", self.app_id, "-c", script]

    def shell_command(self, command: str, wine_path: str,
                      env: Dict[str, str] = None) -> List[str]:
        """Wrap a shell command string (run_cmd style)."""
        exports = " ".join(f"{k}={shlex.quote(v)}"
                           for k, v in self._env(wine_path, env).items())
        script = f"export {exports}; {command}" if exports else command
        return ["flatpak", "run", *self._fs_args(wine_path),
                "--command=bash", self.app_id, "-c", script]

    def _env(self, wine_path: str, env: Dict[str, str] = None) -> Dict[str, str]:
        merged = _graphics_env()
        if env:
            merged.update({k: str(v) for k, v in env.items() if v is not None})
        merged.setdefault("WINEDEBUG", "-all")
        return merged

    def kill(self, timeout: int = 10):
        """Terminate every process of this sandbox app."""
        flatpak = _flatpak()
        if not flatpak:
            return
        try:
            subprocess.run([flatpak, "kill", self.app_id],
                           capture_output=True, timeout=timeout)
        except Exception:
            pass


# prefix path -> (mtime, SandboxRuntime or None)
_PREFIX_CACHE: Dict[str, Tuple[float, Optional[SandboxRuntime]]] = {}


def forget_prefix_cache(bottle_path: str):
    """Drop the cached runtime after bottle.json is rewritten."""
    _PREFIX_CACHE.pop(str(bottle_path), None)


def sandbox_for_prefix(bottle_path: str) -> Optional[SandboxRuntime]:
    """Return the runtime configured for a prefix, or None for host mode."""
    meta = Path(bottle_path) / "bottle.json"
    try:
        mtime = meta.stat().st_mtime
    except OSError:
        return None
    cached = _PREFIX_CACHE.get(bottle_path)
    if cached and cached[0] == mtime:
        return cached[1]

    runtime: Optional[SandboxRuntime] = None
    try:
        with open(meta, "r", encoding="utf-8") as f:
            data = json.load(f)
        if (data.get("sandbox") or "host") == "flatpak":
            candidate = SandboxRuntime(data.get("sandbox_app_id") or APP_ID)
            runtime = candidate if candidate.available() else None
    except (OSError, json.JSONDecodeError):
        runtime = None
    _PREFIX_CACHE[bottle_path] = (mtime, runtime)
    return runtime