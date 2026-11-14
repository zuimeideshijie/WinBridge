"""Wine integration utilities."""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


# HKLM font table in system.reg. Wine fills it with every host font the first
# time a prefix is created; a bottle that only lists a handful of faces makes
# Chromium-built apps abort before they ever show a window.
_FONT_SECTION = re.compile(
    r"\[Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts\][^\[]*",
    re.DOTALL,
)
# A freshly created prefix lists thousands of host faces; anything this small
# means our own font registration wiped the table.
_MIN_FONT_ENTRIES = 200


# CJK font candidates on the host (in priority order).
# These get symlinked into each bottle's drive_c/windows/Fonts/ so that
# Wine applications can render Chinese/Japanese/Korean characters.
_HOST_CJK_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]

# Core Latin fonts from the host that Wine apps commonly expect.
_HOST_CORE_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuMono.ttf",
]


class Wine:
    """Wine binary wrapper."""

    def __init__(self, wine_path: str = "/usr/bin/wine"):
        self.wine_path = wine_path
        self._version = None

    @property
    def version(self) -> str:
        if self._version is None:
            try:
                result = subprocess.run(
                    [self.wine_path, "--version"],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=10
                )
                self._version = result.stdout.strip() or "unknown"
            except Exception:
                self._version = "unknown"
        return self._version

    @property
    def is_valid(self) -> bool:
        return Path(self.wine_path).exists()

    @property
    def wineserver_path(self) -> str:
        p = Path(self.wine_path)
        ws = p.parent / "wineserver"
        if ws.exists():
            return str(ws)
        return "wineserver"

    def run(self, bottle_path: str, executable: str,
            args: list = None, workdir: str = None,
            env: dict = None, wait: bool = True) -> subprocess.Popen:
        """Run a command in a Wine bottle environment."""
        environment = os.environ.copy()
        environment["WINEPREFIX"] = bottle_path
        environment["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
        if env:
            environment.update(env)

        cmd = [self.wine_path, executable]
        if args:
            cmd.extend(args)

        if wait:
            return subprocess.run(
                cmd, env=environment, cwd=workdir,
                capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=300
            )
        # Nobody reads the pipes of a detached program, so a chatty one (Wine
        # logs every fixme) would block once the 64 KB buffer fills.
        return subprocess.Popen(
            cmd, env=environment, cwd=workdir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    def run_cmd(self, bottle_path: str, wine_cmd: str,
                env: dict = None, timeout: int = 120) -> subprocess.CompletedProcess:
        """Run a Wine command string in a bottle."""
        environment = os.environ.copy()
        environment["WINEPREFIX"] = bottle_path
        if env:
            environment.update(env)

        cmd = f"{shlex.quote(self.wine_path)} {wine_cmd}"
        return subprocess.run(
            cmd, env=environment, shell=True,
            capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=timeout
        )

    def boot(self, bottle_path: str, wait: bool = True) -> subprocess.CompletedProcess:
        """Boot the Wine server for a bottle."""
        return self.run_cmd(bottle_path, "wineboot", timeout=60)

    def reg(self, bottle_path: str, reg_file: str) -> subprocess.CompletedProcess:
        """Import a .reg file into the bottle registry."""
        return self.run_cmd(bottle_path, f"regedit /S {shlex.quote(reg_file)}")

    def set_win_version(self, bottle_path: str, version: str):
        """Set Windows version for a bottle."""
        env = {"WINEDLLOVERRIDES": ""}
        self.run_cmd(bottle_path, f"winecfg -v {version}", env=env)

    def kill(self, bottle_path: str = None):
        """Kill Wine processes and wait for wineserver to fully exit.

        `wineserver -k` only *requests* shutdown — the wineserver and its
        child processes (services.exe, winedevice.exe, …) need time to
        actually exit and release their file handles. Without waiting, a
        subsequent rmtree of the prefix can silently fail, leaving a
        residual directory that list_bottles() will show as a bottle again.

        If the wineserver is still alive after -w times out, SIGKILL it:
        a live wineserver flushes the registry back to disk on exit and
        would recreate system.reg/user.reg — and the directory — right
        after we deleted it.
        """
        env = os.environ.copy()
        if bottle_path:
            env["WINEPREFIX"] = bottle_path
        try:
            subprocess.run([self.wineserver_path, "-k"],
                           env=env, capture_output=True, timeout=10)
            try:
                # -w blocks until the wineserver has fully shut down
                subprocess.run([self.wineserver_path, "-w"],
                               env=env, capture_output=True, timeout=30)
            except subprocess.TimeoutExpired:
                # Still alive — force-kill the wineserver for this prefix
                self._force_kill_wineserver(bottle_path)
        except subprocess.TimeoutExpired:
            self._force_kill_wineserver(bottle_path)
        except Exception:
            pass

    def _force_kill_wineserver(self, bottle_path: str = None):
        """SIGKILL the wineserver(s) for a prefix (fallback after -w timeout).

        A wineserver that is killed with SIGKILL cannot flush the registry,
        so the deleted prefix directory won't be recreated afterwards.
        """
        try:
            import signal
            for pid in self._find_wineserver_pids(bottle_path):
                try:
                    os.kill(pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
        except Exception:
            pass

    def _find_wineserver_pids(self, bottle_path: str = None) -> list:
        """Find wineserver process PIDs (optionally for a specific prefix)."""
        pids = []
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,args"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=10)
            for line in result.stdout.splitlines()[1:]:
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                pid, args = parts[0], parts[1]
                if "wineserver" not in args:
                    continue
                if bottle_path:
                    # Only kill wineservers rooted at this prefix
                    cwd = os.readlink(f"/proc/{pid}/cwd") if os.path.exists(f"/proc/{pid}/cwd") else ""
                    prefix = self._wineserver_prefix(pid)
                    if prefix != bottle_path and cwd != bottle_path:
                        continue
                pids.append(int(pid))
        except Exception:
            pass
        return pids

    def _wineserver_prefix(self, pid: int) -> str:
        """Read WINEPREFIX from a process's environment."""
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                for item in f.read().split(b"\0"):
                    if item.startswith(b"WINEPREFIX="):
                        return item.split(b"=", 1)[1].decode("utf-8", "ignore")
        except OSError:
            pass
        return ""

    def get_prefix_arch(self, bottle_path: str) -> str:
        """Detect bottle architecture."""
        reg_dir = Path(bottle_path)
        if (reg_dir / "user.reg").exists():
            with open(reg_dir / "user.reg", "r", encoding="utf-8",
                      errors="ignore") as f:
                content = f.read()
                if "#arch=win64" in content:
                    return "win64"
                elif "#arch=win32" in content:
                    return "win32"
        return "unknown"

    def get_prefix_windows_version(self, bottle_path: str) -> str:
        """Read Windows version from bottle registry."""
        try:
            result = self.run_cmd(bottle_path,
                                  'reg query "HKLM\\Software\\Microsoft\\Windows\\CurrentVersion" /v ProductName')
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if "ProductName" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            return " ".join(parts[2:])
        except Exception:
            pass
        return "unknown"

    def create_prefix(self, bottle_path: str, arch: str = "win64") -> bool:
        """Create a new Wine prefix (bottle)."""
        environment = os.environ.copy()
        environment["WINEPREFIX"] = bottle_path
        environment["WINEARCH"] = arch
        environment["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"

        try:
            result = subprocess.run(
                [self.wine_path, "wineboot", "-u"],
                env=environment,
                capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                timeout=120
            )
            # Let the wineserver flush system.reg before inject_fonts() edits
            # it — otherwise its in-memory copy overwrites the font table.
            self._stop_prefix(bottle_path)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def _stop_prefix(self, bottle_path: str):
        """Shut the bottle's wineserver down and wait for it to flush."""
        environment = os.environ.copy()
        environment["WINEPREFIX"] = bottle_path
        for args in (["-k"], ["-w"]):
            try:
                subprocess.run([self.wineserver_path] + args, env=environment,
                               capture_output=True, timeout=90)
            except Exception:
                pass

    def _host_font_table(self) -> str:
        """Font table Wine writes for a brand new prefix.

        Existing prefixes never regenerate it, so a bottle whose table was
        overwritten has to borrow the table of a throwaway prefix.
        """
        tmp = tempfile.mkdtemp(prefix="winbridge-fonts-")
        try:
            environment = os.environ.copy()
            environment["WINEPREFIX"] = tmp
            environment["WINEARCH"] = "win64"
            environment["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
            subprocess.run([self.wine_path, "wineboot", "-i"], env=environment,
                           capture_output=True, timeout=180)
            self._stop_prefix(tmp)
            reg = Path(tmp) / "system.reg"
            if not reg.exists():
                return ""
            match = _FONT_SECTION.search(reg.read_text(encoding="utf-8",
                                                       errors="replace"))
            return match.group(0) if match else ""
        except Exception:
            return ""
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def inject_fonts(self, bottle_path: str) -> int:
        """Symlink host CJK + core Latin fonts into the bottle.

        Wine applications often render Chinese/Japanese/Korean characters
        as boxes (tofu) because a fresh prefix only ships a single Latin
        fallback font. Linking the host Noto CJK / WenQuanYi fonts into
        drive_c/windows/Fonts/ makes them visible to Wine.

        After linking, every font in drive_c/windows/Fonts/ is also
        registered into the Wine registry (HKLM\\...\\Fonts). GDI-based
        apps that enumerate fonts through the registry — not the
        filesystem — otherwise render ALL text as boxes, even English.

        Returns the number of fonts successfully linked.
        """
        fonts_dir = Path(bottle_path) / "drive_c" / "windows" / "Fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)

        linked = 0
        for host_font in _HOST_CJK_FONTS + _HOST_CORE_FONTS:
            src = Path(host_font)
            if not src.exists():
                continue
            dst = fonts_dir / src.name
            if dst.exists() or dst.is_symlink():
                linked += 1
                continue
            try:
                os.symlink(str(src), str(dst))
                linked += 1
            except OSError:
                # symlinks may be unsupported on some filesystems; copy instead
                try:
                    shutil.copy2(str(src), str(dst))
                    linked += 1
                except OSError:
                    pass

        # Register every font in the bottle's Fonts directory into the
        # Wine registry so GDI apps can enumerate them. This is the fix
        # for "all text renders as boxes" — wine ships fonts only as
        # files, but apps query the registry for the font table.
        self.register_all_fonts(bottle_path)
        return linked

    def register_all_fonts(self, bottle_path: str) -> int:
        """Register every font file in the bottle's Fonts dir into the
        Wine registry. Returns the number of fonts registered.

        Writes directly to the bottle's system.reg file instead of spawning
        `wine reg add` per font (118 fonts × 1 wineboot = hangs the UI).
        Wine reads this file on next boot; no subprocess needed.
        """
        fonts_dir = Path(bottle_path) / "drive_c" / "windows" / "Fonts"
        if not fonts_dir.exists():
            return 0
        # Collect all font entries first (single pass over the directory)
        entries = []
        for font_file in fonts_dir.iterdir():
            if not font_file.is_file():
                continue
            ext = font_file.suffix.lower()
            if ext not in (".ttf", ".ttc", ".otf"):
                continue
            face_name = font_file.stem
            # system.reg uses double-backslash escaping in paths
            win_path = f"C:\\\\windows\\\\Fonts\\\\{font_file.name}"
            entries.append((face_name, win_path))
        if not entries:
            return 0

        # Write all entries to system.reg in one shot. The Fonts key lives
        # under HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Fonts
        # which wine stores in system.reg (not user.reg) as a [Software\\...] section.
        system_reg = Path(bottle_path) / "system.reg"
        try:
            # Write only while the wineserver is down: it keeps the registry in
            # memory and would flush its own copy over our table on exit.
            self._stop_prefix(bottle_path)

            existing = ""
            if system_reg.exists():
                existing = system_reg.read_text(encoding="utf-8", errors="replace")

            current = _FONT_SECTION.search(existing)
            table = {}
            header = ("[Software\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\\\\Fonts]"
                      " 1785670878\n")
            if current:
                header = current.group(0).splitlines(True)[0]
                for line in current.group(0).splitlines()[1:]:
                    m = re.match(r'^"(.+)"="(.*)"$', line.strip())
                    if m:
                        table[m.group(1)] = m.group(2)

            if len(table) < _MIN_FONT_ENTRIES:
                # The table lost the host fonts Wine registered at creation
                # time; borrow them from a throwaway prefix.
                host_block = self._host_font_table()
                host_lines = host_block.splitlines()[1:] if host_block else []
                if host_lines and not table:
                    header = host_block.splitlines(True)[0] if host_block else header
                for line in host_lines:
                    m = re.match(r'^"(.+)"="(.*)"$', line.strip())
                    if m:
                        table[m.group(1)] = m.group(2)

            for face_name, win_path in entries:
                # reg file format: "Name (TrueType)"="C:\\windows\\Fonts\\file.ttf"
                table[f"{face_name} (TrueType)"] = win_path

            block = header + "".join(f'"{k}"="{v}"\n' for k, v in table.items())
            # Use a function replacement — a plain string replacement would let
            # re.sub collapse the "\\" escapes and corrupt the section.
            merged = (_FONT_SECTION.sub(lambda m: block, existing)
                      if current else existing + "\n" + block)

            system_reg.write_text(merged, encoding="utf-8")
            return len(entries)
        except Exception:
            # Fallback: best-effort per-font via subprocess (slow but safe)
            registered = 0
            for face_name, win_path in entries:
                if self.register_font(bottle_path, face_name, win_path):
                    registered += 1
            return registered

    def register_font(self, bottle_path: str,
                      font_name: str, file_name: str) -> bool:
        """Register a font file in the Wine registry (HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Fonts).

        This makes the linked font visible to GDI-based applications that
        enumerate installed fonts through the registry rather than the
        filesystem.
        """
        env = os.environ.copy()
        env["WINEPREFIX"] = bottle_path
        env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
        try:
            result = subprocess.run(
                [self.wine_path, "reg", "add",
                 "HKLM\\Software\\Microsoft\\Windows NT\\CurrentVersion\\Fonts",
                 "/v", f"{font_name} (TrueType)",
                 "/t", "REG_SZ",
                 "/d", file_name,
                 "/f"],
                env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=30
            )
            return result.returncode == 0
        except Exception:
            return False

    def list_processes(self, bottle_path: str = None) -> list:
        """List running Wine processes.

        Returns a list of dicts with keys: pid, name, cpu, memory, exe_path.
        Only returns user-facing processes, filtering out internal Wine services.
        """
        # Known Wine internal background processes to exclude
        internal_processes = {
            "wineserver", "winedevice", "services.exe", "plugplay.exe",
            "explorer.exe", "rpcss.exe", "svchost.exe", "winecfg.exe",
            "wineboot.exe", "winebrowser.exe", "winemenubuilder.exe",
            "isapibrowser.dll", "start.ch", "desktop",
        }
        try:
            env = os.environ.copy()
            if bottle_path:
                env["WINEPREFIX"] = bottle_path

            result = subprocess.run(
                ["ps", "aux", "--sort=-%cpu"],
                capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=10
            )
            processes = []
            for line in result.stdout.split("\n")[1:]:
                if not line.strip():
                    continue
                parts = line.split(None, 10)
                if len(parts) < 11:
                    continue
                user, pid, cpu, mem, vsz, rss, tty, stat, start, time, cmd = parts
                low = cmd.lower()
                if "wine" in low or "wine64" in low or \
                   ".exe" in low or "wineserver" in low or \
                   "winedevice" in low:
                    name = cmd.split("/")[-1] if "/" in cmd else cmd
                    # Skip Wine internal background processes
                    if name.lower() in internal_processes:
                        continue
                    # Skip processes with C:... paths (Wine internal executables)
                    if name.startswith("C:") or name.startswith("c:"):
                        continue
                    # Skip prefetch processes
                    if name.startswith("prefetch:"):
                        continue
                    processes.append({
                        "pid": pid,
                        "cpu": cpu,
                        "memory": mem,
                        "name": name,
                        "exe_path": cmd,
                        "user": user,
                        "status": stat,
                        "start_time": start,
                    })
            return processes
        except Exception:
            return []

    def kill_process(self, pid: str) -> bool:
        """Kill a process by PID."""
        try:
            subprocess.run(["kill", "-9", str(pid)], capture_output=True, timeout=5)
            return True
        except Exception:
            return False