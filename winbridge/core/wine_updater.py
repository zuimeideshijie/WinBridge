"""Wine updater — check for new Wine versions and clone from GitCode."""

import os
import re
import subprocess
import threading
from pathlib import Path
from PyQt5.QtCore import QObject, pyqtSignal


class WineUpdater(QObject):
    """Check Wine version and update from GitCode."""

    progress = pyqtSignal(str, int)  # message, percent
    version_checked = pyqtSignal(str, str)  # local_version, remote_version
    update_finished = pyqtSignal(bool, str)  # success, message

    GITCODE_REPO = "https://gitcode.com/mirrors/wine-mirror/wine.git"
    GITCODE_API = "https://gitcode.com/api/v1/repos/mirrors/wine-mirror/wine/tags"

    def __init__(self, wine_dir: str = None, parent=None):
        super().__init__(parent)
        self.wine_dir = wine_dir or str(Path.home() / "winbridge" / "wine")
        self._cancel = False

    def get_local_version(self) -> str:
        """Get the locally installed Wine version."""
        # Try wine --version first
        wine_bin = Path(self.wine_dir) / "wine"
        if wine_bin.exists():
            try:
                result = subprocess.run(
                    [str(wine_bin), "--version"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                pass

        # Fallback: try system wine
        try:
            result = subprocess.run(
                ["wine", "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass

        return "unknown"

    def get_local_git_tag(self) -> str:
        """Get the latest git tag in the local Wine repository."""
        try:
            result = subprocess.run(
                ["git", "-C", self.wine_dir, "describe", "--tags", "--abbrev=0"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return ""

    def check_remote_version(self) -> str:
        """Check the latest Wine version available on GitCode."""
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                self.GITCODE_API,
                headers={"User-Agent": "WinBridge/1.2.2"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if isinstance(data, list) and len(data) > 0:
                    # Return the latest tag name
                    return data[0].get("name", "")
        except Exception:
            pass
        return ""

    def check_version(self):
        """Check local and remote Wine versions in a background thread."""
        def _run():
            local = self.get_local_git_tag()
            if not local:
                local = self.get_local_version()
            remote = self.check_remote_version()
            self.version_checked.emit(local, remote)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def needs_update(self, local: str, remote: str) -> bool:
        """Check if an update is needed."""
        if not local or not remote:
            return False
        if local == remote:
            return False
        return True

    def clone_wine(self, target_dir: str = None):
        """Clone the Wine source from GitCode with progress."""
        if target_dir is None:
            target_dir = self.wine_dir

        def _clone():
            self.progress.emit("正在连接 GitCode...", 0)
            try:
                # Remove existing directory if it's empty or invalid
                target = Path(target_dir)
                if target.exists() and not any(target.iterdir()):
                    target.rmdir()

                if target.exists():
                    self.update_finished.emit(False, "目标目录已存在，请先删除。")
                    return

                # Do a shallow clone for speed
                cmd = [
                    "git", "clone",
                    "--depth", "1",
                    "--progress",
                    self.GITCODE_REPO,
                    target_dir,
                ]

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

                # Parse progress from stderr
                pattern = re.compile(r"Receiving objects:\s*(\d+)%")
                for line in process.stderr:
                    if self._cancel:
                        process.terminate()
                        self.update_finished.emit(False, "更新已取消。")
                        return
                    m = pattern.search(line)
                    if m:
                        pct = int(m.group(1))
                        self.progress.emit(f"正在下载 Wine 源码... {pct}%", pct)
                    elif "Resolving deltas" in line:
                        self.progress.emit("正在解析差异...", 90)
                    elif "Checking out files" in line:
                        self.progress.emit("正在检出文件...", 95)

                process.wait()
                if process.returncode == 0:
                    self.progress.emit("Wine 源码下载完成", 100)
                    self.update_finished.emit(True, "Wine 源码更新完成！")
                else:
                    self.update_finished.emit(False, "下载失败，请检查网络连接。")

            except FileNotFoundError:
                self.update_finished.emit(False, "未找到 git 命令，请先安装 Git。")
            except Exception as e:
                self.update_finished.emit(False, f"更新失败: {str(e)}")

        t = threading.Thread(target=_clone, daemon=True)
        t.start()

    def cancel(self):
        """Cancel the ongoing clone operation."""
        self._cancel = True