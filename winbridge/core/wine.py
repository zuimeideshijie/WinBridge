"""Wine integration utilities."""

import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional


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
                    capture_output=True, text=True, timeout=10
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

        return subprocess.Popen(
            cmd, env=environment, cwd=workdir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True
        ) if not wait else subprocess.run(
            cmd, env=environment, cwd=workdir,
            capture_output=True, text=True, timeout=300
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
            capture_output=True, text=True, timeout=timeout
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
        """Kill Wine processes."""
        cmd = [self.wineserver_path, "-k"]
        if bottle_path:
            env = os.environ.copy()
            env["WINEPREFIX"] = bottle_path
            subprocess.run(cmd, env=env, capture_output=True, timeout=10)
        else:
            subprocess.run(cmd, capture_output=True, timeout=10)

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
                timeout=120
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
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
                capture_output=True, text=True, timeout=10
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