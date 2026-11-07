"""Component installer using winetricks for Wine components."""

import os
import re
import select
import shutil
import tarfile
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

from .config import Config


# GitHub 直连在 CN 网络经常超时（release 资产尤其明显），所有 GitHub
# 资源统一走镜像前缀：镜像的用法是 "<镜像前缀><完整原始 URL>"。
# 前两个是首选镜像（实测速度最好），其余仅作兜底。
# 微软下载源（aka.ms / download.microsoft.com / *.visualstudio.microsoft.com）
# 本身可用，保持直连，不经过镜像。
GITHUB_MIRRORS = (
    "https://gh-proxy.org/",
    "https://v6.gh-proxy.org/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "https://ghfast.top/",
)

_GITHUB_HOSTS = (
    "github.com",
    "raw.githubusercontent.com",
    "api.github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
)


def is_github_url(url: str) -> bool:
    """Whether a URL points at GitHub and should go through a mirror."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host in _GITHUB_HOSTS or host.endswith(".github.com")


# Winetricks verb → display info mapping
# Components with a "gitcode" block download their files directly (GitHub
# release assets go through GITHUB_MIRRORS; GitCode/GitHub source clones are
# already mirrored); components without it fall back to winetricks.
COMPONENT_MAP = {
    "vcrun2019": {
        "label": "Visual C++ 2019",
        "description": "Microsoft Visual C++ 2015-2019 Redistributable",
        "verb": "vcrun2019",
        # 官方 VC++ v14 运行时（VS2015-2022 共享同一运行时）。
        # 链接来自微软《最新支持的 Visual C++ 可再发行包下载》页面：
        # https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist
        "redist": {
            "urls": {
                "x86": "https://aka.ms/vc14/vc_redist.x86.exe",
                "x64": "https://aka.ms/vc14/vc_redist.x64.exe",
            },
            "install_args": "/install /quiet /norestart",
        },
    },
    "vcrun2022": {
        "label": "Visual C++ 2022",
        "description": "Microsoft Visual C++ 2022 Redistributable",
        "verb": "vcrun2022",
        # 与 vcrun2019 相同：v14 运行时在 VS2017-2026 间二进制兼容，
        # 官方建议直接使用最新 v14 包。
        "redist": {
            "urls": {
                "x86": "https://aka.ms/vc14/vc_redist.x86.exe",
                "x64": "https://aka.ms/vc14/vc_redist.x64.exe",
            },
            "install_args": "/install /quiet /norestart",
        },
    },
    "dotnet48": {
        "label": ".NET Framework 4.8",
        "description": "Microsoft .NET Framework 4.8",
        "verb": "dotnet48",
        # 官方 .NET Framework 4.8 运行时脱机安装包（x86+x64 一体）。
        # 链接来自微软 .NET Framework 下载页的 download.visualstudio.microsoft.com
        # CDN（fwlink 的 download.microsoft.com 在 CN 网络不可达）：
        # https://dotnet.microsoft.com/zh-cn/download/dotnet-framework/net48
        "redist": {
            "urls": {
                "x86_x64": "https://download.visualstudio.microsoft.com/download/pr/7afca223-55d2-470a-8edc-6a1739ae3252/abd170b4b0ec15ad0222a809b761a036/ndp48-x86-x64-allos-enu.exe",
            },
            "install_args": "/quiet /norestart",
        },
    },
    "dxvk": {
        "label": "DXVK",
        "description": "DirectX 9/10/11 to Vulkan translation layer",
        "verb": "dxvk",
        # 官方预编译包（无需 meson 编译，避免 "meson: 未找到命令"）。
        # 链接来自 GitHub releases（v2.7.1 → dxvk-2.7.1.tar.gz）。
        "gitcode": {
            "label": "DXVK",
            "version": "2.7.1",
            "type": "precompiled_tarball",
            "tarball_url": "https://github.com/doitsujin/dxvk/releases/download/v2.7.1/dxvk-2.7.1.tar.gz",
            "tarball_file": "dxvk-2.7.1.tar.gz",
            "dlls": ["dxgi", "d3d8", "d3d9", "d3d10core", "d3d11"],
        },
    },
    "vkd3d": {
        "label": "VKD3D",
        "description": "DirectX 12 to Vulkan translation layer",
        "verb": "vkd3d",
        # 与 dxvk 相同：改用预编译包，避免源码编译依赖。
        # vkd3d-proton 只发布 .tar.zst（没有 .tar.gz），需 zstd 解压。
        "gitcode": {
            "label": "VKD3D",
            "version": "2.14.1",
            "type": "precompiled_tarball",
            "tarball_url": "https://github.com/HansKristian-Work/vkd3d-proton/releases/download/v2.14.1/vkd3d-proton-2.14.1.tar.zst",
            "tarball_file": "vkd3d-proton-2.14.1.tar.zst",
            "dlls": ["d3d12", "d3d12core"],
        },
    },
    "faudio": {
        "label": "FAudio",
        "description": "XAudio/X3DAudio reimplementation",
        "verb": "faudio",
        # 预编译包（Kron4ek 构建），与 winetricks 的 faudio verb 同源。
        # 上游 FAudio 源码仓库没有安装脚本，克隆源码在当前环境下无法安装。
        "gitcode": {
            "label": "FAudio",
            "version": "20.07",
            "type": "precompiled_tarball",
            "tarball_url": "https://github.com/Kron4ek/FAudio-Builds/releases/download/20.07/faudio-20.07.tar.xz",
            "tarball_file": "faudio-20.07.tar.xz",
            "dlls": ["FAudio"],
        },
    },
    "gdiplus": {
        "label": "GDI+",
        "description": "GDI+ library",
        "verb": "gdiplus",
    },
    "riched20": {
        "label": "RichEdit 2.0",
        "description": "RichEdit control library",
        "verb": "riched20",
    },
    "msxml3": {
        "label": "MSXML 3.0",
        "description": "Microsoft XML Core Services 3.0",
        "verb": "msxml3",
    },
    "msxml6": {
        "label": "MSXML 6.0",
        "description": "Microsoft XML Core Services 6.0",
        "verb": "msxml6",
        # 官方 Microsoft XML Core Services 6.0 SP2 安全更新 (KB2758696) x64。
        # 链接来自微软下载中心：
        # https://www.microsoft.com/zh-cn/download/details.aspx?id=36303
        "redist": {
            "urls": {
                "x64": "https://download.microsoft.com/download/4/2/e/42e42688-5463-4df9-a843-bf3f0ce16418/msxml6-KB2758696-chs-amd64.exe",
            },
            "install_args": "/quiet /norestart",
            # KB2758696 是自解压 CAB，在 wine 下静默安装会失败；
            # 用 cabextract 提取 msxml6.dll 复制到容器（winetricks 同款做法）。
            "extract_msi": True,
        },
    },
    "corefonts": {
        "label": "Core Fonts",
        "description": "Microsoft core web fonts (Arial, Times, etc.)",
        "verb": "corefonts",
    },
    "cjkfonts": {
        "label": "CJK Fonts",
        "description": "Chinese/Japanese/Korean fonts",
        "verb": "cjkfonts",
    },
    "allfonts": {
        "label": "All Fonts",
        "description": "All common Windows fonts",
        "verb": "allfonts",
        "direct": True,
    },
    "directmusic": {
        "label": "DirectMusic",
        "description": "DirectMusic API",
        "verb": "directmusic",
        # 其依赖的 dmusic32.dll 仅存在于已从微软删除的 apr2006 redist，
        # 当前网络无法获取，排除出"下载基础文件"默认列表以免拖累整体安装。
        "skip_in_base": True,
        "gitcode": {
            "label": "DirectMusic",
            "version": "Jun2010",
            "type": "directx_redist",
            "redist_file": "DirectX_Jun2010_redist.exe",
            "redist_url": "https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/DirectX_Jun2010_redist.exe",
            "dlls": {"dmusic32.dll": ["x86"]},
        },
    },
    "d3dx9": {
        "label": "DirectX 9",
        "description": "DirectX 9 runtime libraries",
        "verb": "d3dx9",
        "gitcode": {
            "label": "DirectX 9",
            "version": "Jun2010",
            "type": "directx_redist",
            "redist_file": "directx_Jun2010_redist.exe",
            "redist_url": "https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/directx_Jun2010_redist.exe",
            "dlls": {
                "d3dx9_43.dll": ["x86", "amd64"],
                "d3dx9_42.dll": ["x86", "amd64"],
                "d3dx9_41.dll": ["x86", "amd64"],
                "d3dx9_40.dll": ["x86", "amd64"],
                "d3dx9_39.dll": ["x86", "amd64"],
                "d3dx9_38.dll": ["x86", "amd64"],
            },
        },
    },
    "d3dx11_43": {
        "label": "DirectX 11",
        "description": "DirectX 11 runtime libraries",
        "verb": "d3dx11_43",
        "gitcode": {
            "label": "DirectX 11",
            "version": "Jun2010",
            "type": "directx_redist",
            "redist_file": "directx_Jun2010_redist.exe",
            "redist_url": "https://download.microsoft.com/download/8/4/A/84A35BF1-DAFE-4AE8-82AF-AD2AE20B6B14/directx_Jun2010_redist.exe",
            "dlls": {
                "d3dx11_43.dll": ["x86", "amd64"],
                "d3dx11_42.dll": ["x86", "amd64"],
            },
        },
    },
}


class ComponentManager:
    """Installs Wine components via winetricks."""

    def __init__(self, config: Config = None):
        self.config = config or Config()
        self._winetricks_path = self._find_winetricks()
        # Mirror prefix that last worked for a GitHub download (None = direct)
        self._github_mirror = None

    def _find_winetricks(self) -> str:
        """Find the winetricks binary on the system."""
        # Resolve the project-integrated winetricks path (full clone, metadata/ shipped)
        project_root = Path(__file__).resolve().parent.parent.parent
        project_wt = project_root / "winetricks" / "src" / "winetricks"
        # Check common locations
        candidates = [
            # Project-integrated full winetricks (ships metadata/fonts/*.vars)
            str(project_wt),
            # System winetricks as fallback
            "/usr/bin/winetricks",
            "/usr/local/bin/winetricks",
            "winetricks",
            # Legacy bundled path (kept for older installs)
            str(project_root / "winetricks" / "winetricks"),
            # Lutris bundled winetricks
            str(Path.home() / ".local/share/lutris/runtime/winetricks/winetricks"),
        ]
        for cmd in candidates:
            try:
                result = subprocess.run(
                    ["which", cmd] if cmd == "winetricks" else [cmd, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return cmd
            except Exception:
                continue
        return "winetricks"

    @property
    def is_available(self) -> bool:
        """Check if winetricks is installed."""
        try:
            result = subprocess.run(
                [self._winetricks_path, "--version"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def install(self, component_name: str, bottle_path: str,
                progress_callback: Callable = None) -> tuple:
        """Install a component.

        For components with a "gitcode" field, downloads from GitCode and
        installs via the appropriate method (tarball+setup, .exe, or zip).
        For all other components, uses winetricks.

        Returns (success: bool, log: str) where log contains the real error
        output when installation fails.
        """
        info = COMPONENT_MAP.get(component_name)
        if not info:
            return False, f"未知组件 '{component_name}'"

        # Custom direct install (bypasses winetricks entirely)
        if info.get("direct"):
            return self._install_direct(component_name, info, bottle_path, progress_callback)

        # Official Microsoft VC++ Redistributable (aka.ms/vc14) — direct
        # download of x86+x64 packages, no git clone needed.
        if "redist" in info:
            return self._install_redist_exe(component_name, info, bottle_path, progress_callback)

        # Custom download (GitHub release assets via mirrors, or a GitCode repo)
        if "gitcode" in info:
            gc = info["gitcode"]
            install_type = gc.get("type", "")
            # DirectX redist → extract DLLs directly
            if install_type == "directx_redist":
                return self._install_directx_redist(component_name, info, bottle_path, progress_callback)
            # Precompiled tarball (DXVK/VKD3D/FAudio) — download, extract, copy DLLs
            if install_type == "precompiled_tarball":
                return self._install_precompiled_tarball(component_name, info, bottle_path, progress_callback)
            # .exe or .zip installer → _install_gitcode_exe
            return self._install_gitcode_exe(component_name, info, bottle_path, progress_callback)

        # Fallback to winetricks for other components
        return self._install_via_winetricks(component_name, info, bottle_path, progress_callback)

    def _git_clone(self, repo: str, dest: str,
                   progress_callback: Callable = None,
                   label: str = "") -> tuple:
        """Clone a git repo (shallow) to dest. Returns (success, error)."""
        if progress_callback:
            progress_callback(0, 100, f"正在克隆 {label}...")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo, dest],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                return False, f"git clone 失败: {result.stderr.strip()[:200]}"
            if progress_callback:
                progress_callback(50, 100, f"{label} 克隆完成")
            return True, ""
        except subprocess.TimeoutExpired:
            return False, "git clone 超时（300秒）"
        except Exception as e:
            return False, f"git clone 异常: {e}"

    def _verify_clone(self, clone_path: str) -> bool:
        """Verify a cloned repo is complete and usable.

        Checks that .git exists and `git fsck` succeeds. A failed/interrupted
        clone leaves a partial .git that `git` commands reject — better to
        detect and re-clone than to misreport "already installed".
        """
        if not Path(clone_path).exists():
            return False
        if not (Path(clone_path) / ".git").exists():
            return False
        try:
            result = subprocess.run(
                ["git", "-C", clone_path, "fsck", "--full"],
                capture_output=True, text=True, timeout=60
            )
            return result.returncode == 0
        except Exception:
            return False

    def _ensure_cloned(self, gc: dict, component_name: str,
                       progress_callback: Callable = None,
                       label: str = "") -> tuple:
        """Ensure the gitcode repo is cloned to cache. Returns (clone_path, error).

        On entry, verifies the existing clone's integrity via `git fsck`.
        If incomplete (interrupted clone, partial .git), deletes it and
        re-clones from scratch.
        """
        repo = gc["repo"]
        # Downloads go to the user-writable cache dir — components_dir is
        # read-only in the .deb install (root-owned /usr/lib/winbridge).
        cache_dir = self.config.cache_dir / component_name
        clone_path = str(cache_dir / "repo")

        # Already cloned? Verify integrity, re-clone if corrupt
        if Path(clone_path).exists():
            if self._verify_clone(clone_path):
                return clone_path, ""
            # Incomplete clone — remove and re-clone
            if progress_callback:
                progress_callback(0, 100, f"缓存不完整，重新下载 {label}...")
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)

        cache_dir.mkdir(parents=True, exist_ok=True)
        ok, err = self._git_clone(repo, clone_path, progress_callback, label)
        if not ok:
            return None, err
        return clone_path, ""

    def _download_candidates(self, url: str) -> List[tuple]:
        """Ordered (mirror_prefix, url) pairs to try for a download.

        GitHub URLs go through the mirror that worked last time first, then
        the remaining mirrors, and the original GitHub URL as a last resort.
        Anything else (e.g. Microsoft download hosts) is returned untouched
        with a prefix of None.
        """
        if not is_github_url(url):
            return [(None, url)]
        mirrors = list(GITHUB_MIRRORS)
        if self._github_mirror in mirrors:
            mirrors.remove(self._github_mirror)
            mirrors.insert(0, self._github_mirror)
        return [(m, f"{m}{url}") for m in mirrors] + [(None, url)]

    def _download_file(self, url: str, dest_path: str,
                       progress_callback: Callable = None,
                       label: str = "") -> tuple:
        """Download a file, routing GitHub URLs through mirrors.

        Each candidate source is tried in turn; the mirror that succeeds is
        remembered so subsequent downloads skip the ones that don't work.
        Returns (success: bool, error: str).
        """
        candidates = self._download_candidates(url)
        last_err = ""
        for prefix, candidate in candidates:
            if progress_callback:
                host = urllib.parse.urlsplit(prefix).hostname if prefix else ""
                suffix = f"（镜像 {host}）" if host else ""
                progress_callback(0, 100, f"正在下载 {label}{suffix}...")
            ok, err = self._download_one(candidate, dest_path, progress_callback,
                                         label, mirrored=bool(prefix))
            if ok:
                self._github_mirror = prefix
                return True, ""
            last_err = err
        if len(candidates) > 1:
            return False, f"下载失败（已尝试 {len(candidates)} 个源）: {last_err}"
        return False, f"下载失败: {last_err}"

    def _download_one(self, url: str, dest_path: str,
                      progress_callback: Callable = None,
                      label: str = "", mirrored: bool = False) -> tuple:
        """Download a single URL with real-time progress and speed reporting.

        Reports percentage, downloaded/total MB, current speed (KB/s), and
        ETA on every ~50KB chunk. Returns (success: bool, error: str).
        """
        import time

        # Microsoft download hosts whose TLS cert chain is sometimes
        # incomplete when served via CN CDN nodes (e.g. ksyuncdn), which
        # makes strict certificate verification fail. The URLs here are
        # hardcoded official Microsoft links, so retrying such hosts
        # without cert verification is acceptable.
        _MS_DOWNLOAD_HOSTS = (
            "download.microsoft.com",
            "download.visualstudio.microsoft.com",
            "aka.ms",
        )

        # Mirrors are either healthy or plainly dead, so don't spend as long
        # on them as on the (usually slower but reliable) official hosts.
        attempts = 2 if mirrored else 3
        timeout = 60 if mirrored else 120

        last_err = None
        for attempt in range(attempts):
            part_path = dest_path + ".part"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "WinBridge/0.1"})
                host = (urllib.parse.urlsplit(url).hostname or "").lower()
                # Microsoft official hosts are hardcoded, and their CN CDN nodes
                # (e.g. ksyuncdn) often serve an incomplete TLS chain. Connect
                # without verification directly — failing first and retrying can
                # stall the UI for 60s+ per attempt (three sequential urlopen
                # calls could freeze the download bar for minutes).
                if host in _MS_DOWNLOAD_HOSTS:
                    import ssl
                    ctx = ssl._create_unverified_context()
                    resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
                else:
                    resp = urllib.request.urlopen(req, timeout=timeout)
                with resp:
                    total = int(resp.headers.get("Content-Length", 0))
                    total_mb = total / (1024 * 1024) if total else 0

                    # Use a partial file to support resume on interruption
                    downloaded = 0
                    start_time = time.time()
                    last_cb_time = start_time
                    last_cb_bytes = 0
                    chunk = 65536  # 64KB chunks for finer speed updates

                    with open(part_path, "wb") as f:
                        while True:
                            buf = resp.read(chunk)
                            if not buf:
                                break
                            f.write(buf)
                            downloaded += len(buf)

                            if progress_callback:
                                now = time.time()
                                # Throttle callbacks to ~5 per second max
                                if now - last_cb_time >= 0.2 or not total:
                                    pct = min(int(downloaded * 100 / total), 99) if total else 50
                                    dl_mb = downloaded / (1024 * 1024)
                                    # Instant speed over the last interval
                                    interval = now - last_cb_time
                                    if interval > 0:
                                        speed = (downloaded - last_cb_bytes) / interval
                                    else:
                                        speed = 0
                                    speed_kb = speed / 1024
                                    if total and speed > 0:
                                        eta_s = (total - downloaded) / speed
                                        eta_m = int(eta_s // 60)
                                        eta_s = int(eta_s % 60)
                                        msg = (f"正在下载 {label}  "
                                               f"{dl_mb:.1f}/{total_mb:.1f}MB  "
                                               f"{speed_kb:.1f}KB/s  "
                                               f"剩余 {eta_m}m{eta_s}s")
                                    else:
                                        msg = (f"正在下载 {label}  "
                                               f"{dl_mb:.1f}/{total_mb:.1f}MB  "
                                               f"{speed_kb:.1f}KB/s")
                                    progress_callback(pct, 100, msg)
                                    last_cb_time = now
                                    last_cb_bytes = downloaded

                    # Finalize: rename .part to dest
                    os.replace(part_path, dest_path)

                if progress_callback:
                    progress_callback(100, 100, f"{label} 下载完成")
                return True, ""
            except Exception as e:
                last_err = e
                # Clean up partial file before retry
                if os.path.exists(part_path):
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                if attempt < attempts - 1:
                    import time as _time
                    _time.sleep(2)
                    continue
        return False, str(last_err)

    @staticmethod
    def _verify_file(filepath: str) -> tuple:
        """Verify the integrity of a downloaded file.

        Checks:
          - File exists and is not empty
          - For archives (.tar.gz/.tar.xz/.zip): verify archive structure
          - For executables (.exe): verify PE header

        Returns (valid: bool, message: str).
        """
        path = Path(filepath)
        if not path.exists():
            return False, "文件不存在"
        if path.stat().st_size == 0:
            return False, "文件为空"

        ext = path.suffix.lower()
        name = path.name.lower()

        # .tar.gz / .tgz
        if name.endswith(".tar.gz") or name.endswith(".tgz"):
            try:
                with tarfile.open(filepath, "r:gz") as tf:
                    members = tf.getmembers()
                    if not members:
                        return False, "压缩包为空"
                return True, ""
            except (tarfile.TarError, EOFError, OSError) as e:
                return False, f"tar.gz 损坏: {e}"

        # .tar.xz
        if name.endswith(".tar.xz"):
            try:
                with tarfile.open(filepath, "r:xz") as tf:
                    members = tf.getmembers()
                    if not members:
                        return False, "压缩包为空"
                return True, ""
            except (tarfile.TarError, EOFError, OSError) as e:
                return False, f"tar.xz 损坏: {e}"

        # .tar.zst / .tzst — tarfile has no zstd support, so verify with the CLI
        if name.endswith(".tar.zst") or name.endswith(".tzst"):
            try:
                result = subprocess.run(["zstd", "-t", filepath],
                                        capture_output=True, text=True, timeout=300)
            except FileNotFoundError:
                # No zstd CLI: fall back to checking the frame magic number
                with open(filepath, "rb") as f:
                    magic = f.read(4)
                if magic != b"\x28\xb5\x2f\xfd":
                    return False, f"非有效的 zstd 压缩包 (头部: {magic.hex()})"
                return True, ""
            except subprocess.TimeoutExpired:
                return False, "zstd 校验超时"
            if result.returncode != 0:
                msg = (result.stderr.strip() or result.stdout.strip())[:200]
                return False, f"tar.zst 损坏: {msg}"
            return True, ""

        # .zip
        if ext == ".zip":
            import zipfile
            try:
                with zipfile.ZipFile(filepath, "r") as zf:
                    bad = zf.testzip()
                    if bad:
                        return False, f"zip 损坏: {bad}"
                return True, ""
            except (zipfile.BadZipFile, EOFError, OSError) as e:
                return False, f"zip 损坏: {e}"

        # .exe — check MZ header
        if ext == ".exe":
            try:
                with open(filepath, "rb") as f:
                    header = f.read(2)
                    if header != b"MZ":
                        return False, f"非有效的 PE 可执行文件 (头部: {header.hex()})"
                return True, ""
            except OSError as e:
                return False, f"无法读取文件: {e}"

        # For unknown types, only check non-empty
        return True, ""

    def _download_and_verify(self, url: str, dest_path: str,
                             progress_callback: Callable = None,
                             label: str = "",
                             retries: int = 1) -> tuple:
        """Download a file and verify its integrity, retrying if corrupted.

        Returns (success: bool, error: str).
        """
        for attempt in range(retries + 1):
            ok, err = self._download_file(url, dest_path, progress_callback, label)
            if not ok:
                return False, err

            valid, msg = self._verify_file(dest_path)
            if valid:
                return True, ""

            # File corrupt — remove and retry
            if progress_callback:
                progress_callback(0, 100, f"文件损坏，正在重新下载 {label}...")
            try:
                os.remove(dest_path)
            except OSError:
                pass

            if attempt < retries:
                continue

            return False, f"文件完整性验证失败 (已重试{retries}次): {msg}"

        return False, "未知错误"

    def _should_use_stdbuf(self, bottle_path: str) -> bool:
        """Whether stdbuf can be used for a bottle's winetricks run.

        stdbuf preloads the 64-bit libstdbuf.so via LD_PRELOAD; on win32
        bottles the 32-bit wine processes cannot load it and spam
        "wrong ELF class: ELFCLASS64" errors on every launch.
        """
        try:
            from .wine import Wine
            arch = Wine().get_prefix_arch(bottle_path)
            return arch != "win32"
        except Exception:
            return True

    def _install_redist_exe(self, component_name: str, info: dict,
                            bottle_path: str,
                            progress_callback: Callable = None) -> tuple:
        """Install a Microsoft VC++ Redistributable from the official aka.ms links.

        Downloads the x86 and x64 packages into the component cache and runs
        each silently via wine. No git clone or winetricks involved.
        """
        redist = info["redist"]
        urls = redist["urls"]
        install_args = redist.get("install_args", "/install /quiet /norestart")
        extract_msi = redist.get("extract_msi", False)
        label = info["label"]

        # Downloads go to the user-writable cache dir — components_dir is
        # read-only in the .deb install (root-owned /usr/lib/winbridge).
        cache_dir = self.config.cache_dir / component_name
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, f"无法创建缓存目录 {cache_dir}: {e}"

        local_files = []
        for arch, url in urls.items():
            if not url:
                continue
            file_name = Path(url).name
            local_path = str(cache_dir / file_name)
            if progress_callback:
                progress_callback(0, 100, f"正在下载 {label} ({arch})...")
            ok, err = self._download_and_verify(
                url, local_path, progress_callback, f"{label} {arch}")
            if not ok:
                return False, err
            local_files.append(local_path)

        if not local_files:
            return False, "redist 配置缺少下载链接"

        # Some Microsoft packages (e.g. the MSXML 6.0 security update) are
        # self-extracting CABs that don't install cleanly under wine with
        # silent flags. Extract the inner DLLs with cabextract and copy them
        # into the bottle instead — same approach winetricks uses.
        if extract_msi:
            return self._install_redist_extract(
                label, local_files, bottle_path, progress_callback)

        # Run each installer silently via wine (x86 first, then x64)
        for local_path in local_files:
            pkg_name = Path(local_path).name
            if progress_callback:
                progress_callback(0, 100, f"正在安装 {label} ({pkg_name}) 到容器...")
            env = os.environ.copy()
            env["WINEPREFIX"] = bottle_path
            env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
            env["WINE"] = "/usr/bin/wine"
            cmd = ["wine", local_path] + install_args.split()
            try:
                result = subprocess.run(cmd, env=env, capture_output=True,
                                        text=True, timeout=600)
            except subprocess.TimeoutExpired:
                return False, f"安装超时（600秒）: {pkg_name}"
            if result.returncode != 0:
                err_out = result.stderr.strip() or result.stdout.strip() or "安装程序执行失败"
                return False, f"{pkg_name} 安装失败: {err_out}"

        if progress_callback:
            progress_callback(100, 100, f"{label} 安装完成")
        return True, ""

    def _install_redist_extract(self, label: str, local_files: list,
                                bottle_path: str,
                                progress_callback: Callable = None) -> tuple:
        """Install a Microsoft package by extracting DLLs with cabextract.

        Used for packages (e.g. MSXML 6.0 security updates) that are
        self-extracting CABs which don't install cleanly under wine with
        silent flags. Extracts the inner .msi, then the DLLs, and copies
        them into the bottle's system dirs — same approach winetricks uses.
        """
        if progress_callback:
            progress_callback(0, 100, f"正在提取 {label}...")

        extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{label}_")
        try:
            # Level 1: self-extracting .exe → .msi
            for exe in local_files:
                result = subprocess.run(
                    ["cabextract", "-L", "-d", extract_dir, exe],
                    capture_output=True, text=True, timeout=120)
                if result.returncode != 0 and "no valid cabinets" in result.stdout:
                    return False, f"不是有效的 CAB 文件，下载可能不完整"

            # Level 2: .msi → DLLs
            msi_files = list(Path(extract_dir).glob("*.msi"))
            if not msi_files:
                return False, f"提取后未找到 .msi 文件"
            for msi in msi_files:
                result = subprocess.run(
                    ["cabextract", "-L", "-d", extract_dir, str(msi)],
                    capture_output=True, text=True, timeout=120)
                if result.returncode != 0 and "no valid cabinets" in result.stdout:
                    return False, f"无法从 {msi.name} 提取文件"

            # Determine bottle architecture to pick the right system dirs
            arch = "win64"
            try:
                from .wine import Wine
                arch = Wine().get_prefix_arch(bottle_path) or "win64"
            except Exception:
                pass

            drive_c = Path(bottle_path) / "drive_c" / "windows"
            sys32 = drive_c / "system32"      # 64-bit DLLs (win64) / all (win32)
            syswow64 = drive_c / "syswow64"   # 32-bit DLLs (win64 only)

            copied = 0
            # DLLs extracted from the MSI carry GUID-suffixed names
            # (e.g. msxml6.dll.86F857F6_A743_463D_B2FE_98CB5F727E09),
            # so match the ".dll." pattern rather than a ".dll" suffix.
            # The 1ECC0691_* GUID is the 64-bit variant, 86F857F6_* is 32-bit.
            for dll in Path(extract_dir).iterdir():
                if not dll.is_file():
                    continue
                name_lower = dll.name.lower()
                if ".dll." not in name_lower:
                    continue
                base = name_lower.split(".dll.")[0] + ".dll"
                is_64bit = "1ecc0691" in name_lower
                if arch == "win64":
                    dst_dir = sys32 if is_64bit else syswow64
                else:
                    dst_dir = sys32  # win32 bottle: everything goes to system32
                dst_dir.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(str(dll), str(dst_dir / base))
                    copied += 1
                except OSError:
                    continue

            if copied == 0:
                return False, f"未找到可复制的 DLL 文件"

            if progress_callback:
                progress_callback(100, 100, f"{label} 安装完成（{copied} 个文件）")
            return True, ""

        except subprocess.TimeoutExpired:
            return False, "提取超时"
        except Exception as e:
            return False, str(e)
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    def _install_gitcode_exe(self, component_name: str, info: dict,
                             bottle_path: str,
                             progress_callback: Callable = None) -> tuple:
        """Install a component from a GitCode .exe or .zip installer."""
        gc = info["gitcode"]
        label = info["label"]
        version = gc["version"]
        install_args = gc.get("install_args", "/quiet /norestart")
        exe_name = gc.get("installer_exe", "")
        setup_type = gc.get("type", "exe")
        target_file = gc.get("file", "")

        if progress_callback:
            progress_callback(0, 100, f"准备安装 {label} {version}...")

        # Clone the gitcode repo to cache
        clone_path, err = self._ensure_cloned(gc, component_name, progress_callback, label)
        if not clone_path:
            return False, err

        # Locate the installer file inside the cloned repo
        if target_file:
            # Search the whole repo for the named file
            matches = list(Path(clone_path).rglob(target_file))
            if not matches:
                return False, f"在仓库中未找到 {target_file}"
            local_path = str(matches[0])
        else:
            # Fallback: assume the file equals the component name + ext
            local_path = str(Path(clone_path) / target_file)

        # Verify the installer file's integrity. A clone can succeed while
        # the target file inside is still partial (rare, but possible with
        # LFS or interrupted checkout) — re-clone if verification fails.
        valid, msg = self._verify_file(local_path)
        if not valid:
            if progress_callback:
                progress_callback(0, 100, f"安装包不完整({msg})，重新下载 {label}...")
            import shutil
            shutil.rmtree(clone_path, ignore_errors=True)
            clone_path, err = self._ensure_cloned(gc, component_name, progress_callback, label)
            if not clone_path:
                return False, err
            # Re-locate the file after re-clone
            if target_file:
                matches = list(Path(clone_path).rglob(target_file))
                if not matches:
                    return False, f"重新下载后仍未找到 {target_file}"
                local_path = str(matches[0])
            else:
                local_path = str(Path(clone_path) / target_file)
            valid, msg = self._verify_file(local_path)
            if not valid:
                return False, f"重新下载后文件仍不完整: {msg}"

        extract_dir = None
        try:
            if setup_type == "zip" and exe_name:
                # Extract .zip to find the installer .exe
                if progress_callback:
                    progress_callback(60, 100, f"正在解压 {label}...")

                import zipfile
                extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{component_name}_")
                with zipfile.ZipFile(local_path, "r") as zf:
                    zf.extractall(extract_dir)

                installer_exe = str(Path(extract_dir) / exe_name)
                if not Path(installer_exe).exists():
                    return False, f"在压缩包中未找到 {exe_name}"
            else:
                # Direct .exe file
                installer_exe = local_path

            if progress_callback:
                progress_callback(80, 100, f"正在安装 {label} 到容器...")

            # Run the installer via wine with silent flags
            env = os.environ.copy()
            env["WINEPREFIX"] = bottle_path
            env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
            env["WINE"] = "/usr/bin/wine"

            cmd = ["wine", installer_exe] + install_args.split()
            result = subprocess.run(
                cmd, env=env, capture_output=True, text=True, timeout=600
            )

            if result.returncode != 0:
                err_out = result.stderr.strip() or result.stdout.strip() or "安装程序执行失败"
                return False, err_out

            if progress_callback:
                progress_callback(100, 100, f"{label} {version} 安装完成")

            return True, ""

        except subprocess.TimeoutExpired:
            return False, f"安装超时（600秒）"
        except Exception as e:
            return False, str(e)
        finally:
            if extract_dir:
                import shutil
                shutil.rmtree(extract_dir, ignore_errors=True)

    @staticmethod
    def _extract_archive(archive_path: str, dest_dir: str) -> tuple:
        """Extract a .tar.gz / .tar.xz / .tar.zst archive into dest_dir.

        Returns (success: bool, error: str).
        """
        path = str(archive_path)
        if path.lower().endswith((".tar.zst", ".tzst")):
            # tarfile (as of Python 3.13) has no zstd support — stream the
            # decompressed bytes from the zstd CLI straight into tarfile.
            try:
                proc = subprocess.Popen(["zstd", "-dc", path],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
            except FileNotFoundError:
                return False, "未找到 zstd 命令，无法解压 .tar.zst（请安装 zstd）"
            try:
                with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
                    tf.extractall(dest_dir)
            except (tarfile.TarError, EOFError, OSError) as e:
                proc.kill()
                proc.wait()
                return False, f"解压失败: {e}"
            finally:
                if proc.stdout:
                    proc.stdout.close()
            err_out = proc.stderr.read().decode("utf-8", "replace").strip() if proc.stderr else ""
            if proc.stderr:
                proc.stderr.close()
            if proc.wait() != 0:
                return False, f"zstd 解压失败: {err_out[:200]}"
            return True, ""

        try:
            with tarfile.open(path, "r:*") as tf:
                tf.extractall(dest_dir)
            return True, ""
        except (tarfile.TarError, EOFError, OSError) as e:
            return False, f"解压失败: {e}"

    def _install_precompiled_tarball(self, component_name: str, info: dict,
                                     bottle_path: str,
                                     progress_callback: Callable = None) -> tuple:
        """Install a precompiled component (DXVK/VKD3D/FAudio) from a release tarball.

        Unlike the source-clone path, this needs no meson/ninja — just download,
        extract, copy the x32/x64 DLLs into the bottle and register overrides.
        """
        gc = info["gitcode"]
        label = info["label"]
        version = gc["version"]
        tarball_url = gc["tarball_url"]
        tarball_file = gc.get("tarball_file", tarball_url.split("/")[-1])
        dlls = gc.get("dlls", [])

        if progress_callback:
            progress_callback(0, 100, f"准备安装 {label} {version}...")

        cache_dir = self.config.cache_dir / component_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        local_path = str(cache_dir / tarball_file)

        if progress_callback:
            progress_callback(30, 100, f"正在下载 {label}...")
        ok, err = self._download_and_verify(tarball_url, local_path, progress_callback, label)
        if not ok:
            return False, err

        if progress_callback:
            progress_callback(70, 100, f"正在解压 {label}...")
        extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{component_name}_")
        try:
            ok, err = self._extract_archive(local_path, extract_dir)
            if not ok:
                return False, err

            # Determine bottle arch for target system dirs
            arch = "win64"
            try:
                from .wine import Wine
                arch = Wine().get_prefix_arch(bottle_path) or "win64"
            except Exception:
                pass

            # In a win64 prefix system32 holds 64-bit DLLs and syswow64 the
            # 32-bit ones; a win32 prefix has only system32 (32-bit).
            drive_c = Path(bottle_path) / "drive_c" / "windows"
            sys32 = drive_c / "system32"
            syswow64 = drive_c / "syswow64"
            sys32.mkdir(parents=True, exist_ok=True)
            if arch == "win64":
                syswow64.mkdir(parents=True, exist_ok=True)

            # Find the extracted directory that holds the binaries
            # (e.g. "dxvk-2.7.1/", or the extraction root itself)
            extracted = Path(extract_dir)
            candidates = [d for d in extracted.iterdir() if d.is_dir()]
            src_dir = extracted
            for d in candidates:
                if (d / "x32").exists() or (d / "x64").exists():
                    src_dir = d
                    break
            else:
                if candidates:
                    src_dir = candidates[0]

            copied = 0
            # x32 → syswow64 on win64 bottles, system32 on win32 bottles
            x32_target = syswow64 if arch == "win64" else sys32
            x32_dir = src_dir / "x32"
            if x32_dir.exists():
                for dll_name in dlls:
                    src_dll = x32_dir / f"{dll_name}.dll"
                    if src_dll.exists():
                        shutil.copy2(str(src_dll), str(x32_target / f"{dll_name}.dll"))
                        copied += 1

            # x64 → system32 (win64 bottles only)
            if arch == "win64":
                x64_dir = src_dir / "x64"
                if x64_dir.exists():
                    for dll_name in dlls:
                        src_dll = x64_dir / f"{dll_name}.dll"
                        if src_dll.exists():
                            shutil.copy2(str(src_dll), str(sys32 / f"{dll_name}.dll"))
                            copied += 1

            if copied == 0:
                return False, "未找到任何需要安装的 DLL 文件"

            # Register DLL overrides in the Wine registry
            try:
                from .wine import Wine
                w = Wine(self.config.wine_path)
                for dll_name in dlls:
                    try:
                        w.run_cmd(bottle_path,
                                  f'reg add "HKCU\\Software\\Wine\\DllOverrides" '
                                  f'/v {dll_name} /d native,builtin /f',
                                  timeout=30)
                    except Exception:
                        pass
            except Exception:
                pass

            if progress_callback:
                progress_callback(100, 100, f"{label} {version} 安装完成（{copied} 个文件）")
            return True, ""

        except Exception as e:
            return False, str(e)
        finally:
            import shutil as _sh
            _sh.rmtree(extract_dir, ignore_errors=True)

    def _install_directx_redist(self, component_name: str, info: dict,
                                bottle_path: str,
                                progress_callback: Callable = None) -> tuple:
        """Install a DirectX redist component by downloading and extracting DLLs."""
        gc = info["gitcode"]
        label = info["label"]
        gc_label = gc.get("label", label)
        version = gc["version"]
        redist_url = gc["redist_url"]
        redist_file = gc["redist_file"]
        dlls = gc["dlls"]

        if progress_callback:
            progress_callback(0, 100, f"准备安装 {gc_label} {version}...")

        # Downloads go to the user-writable cache dir — components_dir is
        # read-only in the .deb install (root-owned /usr/lib/winbridge).
        cache_dir = self.config.cache_dir / component_name
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, f"无法创建缓存目录 {cache_dir}: {e}"
        local_path = str(cache_dir / redist_file)

        # Download the redist if not cached
        if not Path(local_path).exists():
            ok, err = self._download_and_verify(redist_url, local_path, progress_callback, gc_label)
            if not ok:
                return False, err
        else:
            valid, msg = self._verify_file(local_path)
            if not valid:
                try:
                    os.remove(local_path)
                except OSError:
                    pass
                ok, err = self._download_and_verify(redist_url, local_path, progress_callback, gc_label)
                if not ok:
                    return False, f"缓存损坏，重新下载失败: {err}"

        if progress_callback:
            progress_callback(50, 100, f"正在提取 {gc_label}...")

        extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{component_name}_")
        try:
            # First extraction: self-extracting .exe → .cab files
            result = subprocess.run(
                ["cabextract", "-L", "-d", extract_dir, local_path],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0 and "no valid cabinets" in result.stdout:
                return False, f"不是有效的 CAB 文件，下载可能不完整"

            # Find and extract each requested DLL from its cab
            sys32_dir = Path(bottle_path) / "drive_c/windows/system32"
            syswow64_dir = Path(bottle_path) / "drive_c/windows/syswow64"
            installed = []

            for dll_name, arches in dlls.items():
                for arch in arches:
                    cab_pattern = f"*{dll_name.replace('.dll', '')}*{arch}*.cab"
                    cab_files = list(Path(extract_dir).glob(cab_pattern))
                    if not cab_files:
                        continue

                    cab_path = cab_files[0]
                    dll_result = subprocess.run(
                        ["cabextract", "-L", "-F", dll_name, str(cab_path),
                         "-d", str(sys32_dir if arch == "amd64" else syswow64_dir)],
                        capture_output=True, text=True, timeout=30
                    )
                    if dll_result.returncode == 0:
                        installed.append(f"{dll_name}({arch})")

            if not installed:
                return False, f"未找到任何需要安装的 DLL 文件"

            # Register DLL overrides
            for dll_name in dlls:
                env = os.environ.copy()
                env["WINEPREFIX"] = bottle_path
                subprocess.run(
                    ["wine", "reg", "add",
                     f"HKCU\\Software\\Wine\\DllOverrides",
                     "/v", dll_name.replace(".dll", ""),
                     "/d", "native", "/f"],
                    env=env, capture_output=True, timeout=30
                )

            if progress_callback:
                progress_callback(100, 100, f"{gc_label} 安装完成 ({len(installed)} 个文件)")

            return True, ""

        except subprocess.TimeoutExpired:
            return False, f"提取超时"
        except Exception as e:
            return False, str(e)
        finally:
            import shutil
            shutil.rmtree(extract_dir, ignore_errors=True)

    def _install_direct(self, component_name: str, info: dict,
                        bottle_path: str,
                        progress_callback: Callable = None) -> tuple:
        """Direct install from pre-cached files — bypasses winetricks entirely.

        For components like allfonts that have a "direct" flag, this method
        copies all pre-cached font files from the project-integrated
        components/ directory into the bottle's Fonts dir, then registers
        them in the Wine registry. No subprocess is spawned, so there is
        zero risk of hanging.
        """
        if progress_callback:
            progress_callback(0, 100, f"正在安装 {info['label']}...")

        fonts_dir = Path(bottle_path) / "drive_c" / "windows" / "Fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)

        cache_root = self.config.components_dir / "winetricks"
        if not cache_root.exists():
            return False, f"缓存目录不存在: {cache_root}"

        total = 0
        # Walk all subdirectories (calibri/, cambria/, corefonts/, etc.)
        for pkg_dir in cache_root.iterdir():
            if not pkg_dir.is_dir():
                continue
            for font_file in pkg_dir.iterdir():
                if not font_file.is_file():
                    continue
                ext = font_file.suffix.lower()
                if ext not in (".ttf", ".ttc", ".otf"):
                    continue
                dst = fonts_dir / font_file.name
                try:
                    shutil.copy2(str(font_file), str(dst))
                    total += 1
                except OSError:
                    continue

        if progress_callback:
            progress_callback(80, 100, f"正在注册字体到 Wine 注册表...")

        # Register every font in the bottle's Fonts dir
        try:
            from .wine import Wine
            cfg = self.config
            w = Wine(cfg.wine_path)
            registered = w.register_all_fonts(bottle_path)
        except Exception:
            registered = 0

        if progress_callback:
            progress_callback(100, 100, f"{info['label']} 安装完成（{total} 字体，{registered} 已注册）")

        return True, ""

    def _install_via_winetricks(self, component_name: str, info: dict,
                                bottle_path: str,
                                progress_callback: Callable = None) -> tuple:
        """Install a component via winetricks with real-time output."""
        if progress_callback:
            progress_callback(0, 100, f"正在安装 {info['label']}...")

        error_lines = []

        try:
            env = os.environ.copy()
            env["WINEPREFIX"] = bottle_path
            # Disable mono/gecko auto-install (wineboot tries to download
            # them on first run, which hangs in CN networks). Also suppress
            # wine debug output to reduce noise on the pipe.
            env["WINEDLLOVERRIDES"] = "mscoree=d;winemenubuilder.exe=d"
            env["WINEDEBUG"] = "-all,fixme-all"
            env["WINE"] = "/usr/bin/wine"
            # Point winetricks at the project-integrated metadata (fonts/*.vars etc.)
            # so composite verbs like allfonts/cjkfonts enumerate sub-verbs without
            # needing runtime network access.
            project_root = Path(__file__).resolve().parent.parent.parent
            metadata_dir = project_root / "winetricks" / "metadata"
            if metadata_dir.exists():
                env["WINETRICKS_METADATA"] = str(metadata_dir)
            # Force winetricks to use curl instead of aria2c. aria2c hangs on
            # some SourceForge URLs in CN networks (0 B/s until timeout), which
            # freezes the UI. curl is more resilient and respects our timeouts.
            env["WINETRICKS_DOWNLOADER"] = "curl"
            # winetricks fetches many assets (fonts etc.) straight from
            # GitHub; give it the same mirror list so those go through a
            # mirror too. winetricks retries with the next prefix — the
            # original GitHub URL is used as the final fallback.
            env["WINETRICKS_GH_MIRROR"] = " ".join(GITHUB_MIRRORS)
            # Force winetricks to trust the local cache without sha256
            # verification. Our pre-downloaded files in components/ may not
            # match winetricks's recorded sha (different mirror, re-packed),
            # and sha mismatch in -q mode triggers w_askpermission which
            # hangs the install. WINETRICKS_FORCE=1 skips the check entirely.
            env["WINETRICKS_FORCE"] = "1"
            # Use the user-writable cache dir as the winetricks download
            # cache — components_dir is read-only in the .deb install
            # (root-owned /usr/lib/winbridge), and writing there fails with
            # "mkdir: cannot create directory ... Permission denied".
            # NOTE: winetricks builds W_CACHE = ${XDG_CACHE_HOME}/winetricks
            # and does NOT read the WINETRICKS_CACHE env var, so we must set
            # XDG_CACHE_HOME pointing at the parent of our "winetricks/" subdir.
            wt_cache = self.config.cache_dir / "winetricks"
            if not wt_cache.exists():
                wt_cache.mkdir(parents=True, exist_ok=True)
            env["XDG_CACHE_HOME"] = str(self.config.cache_dir)

            # Link pre-cached component files (shipped read-only in the deb,
            # or pre-downloaded in the source tree) into the user cache dir
            # so winetricks can reuse them instead of re-downloading.
            # e.g. msxml3 needs win7sp1's windows6.1-KB976932-X64.exe — if we
            # don't link it, winetricks re-downloads it (947MB) and a partial
            # download (e.g. 853MB) breaks cabextract with a silent failure.
            preset_root = self.config.components_dir / "winetricks"
            if preset_root.exists():
                try:
                    for pkg_dir in preset_root.iterdir():
                        if not pkg_dir.is_dir():
                            continue
                        target_pkg = wt_cache / pkg_dir.name
                        target_pkg.mkdir(parents=True, exist_ok=True)
                        for preset_file in pkg_dir.iterdir():
                            if not preset_file.is_file():
                                continue
                            target_file = target_pkg / preset_file.name
                            if target_file.exists():
                                # Keep it only if it's the same size — a
                                # partial/interrupted download (smaller file)
                                # must be replaced by the preset cache.
                                if target_file.stat().st_size == preset_file.stat().st_size:
                                    continue
                                try:
                                    target_file.unlink()
                                except OSError:
                                    continue
                            try:
                                target_file.symlink_to(preset_file)
                            except OSError:
                                pass
                except OSError:
                    pass

            process = subprocess.Popen(
                # stdbuf -oL forces line-buffered output from winetricks/bash,
                # without it the pipe buffers and the select.select idle timeout
                # can fire prematurely (or the process appears to hang with no
                # output when it's actually running but buffered).
                #
                # BUT stdbuf preloads the 64-bit libstdbuf.so via LD_PRELOAD;
                # on win32 bottles the 32-bit wine processes can't load it and
                # spam "wrong ELF class: ELFCLASS64" errors, so skip stdbuf
                # there (winetricks is a bash script; wine does the installing).
                ["stdbuf", "-oL", self._winetricks_path, "-q", info["verb"]]
                if self._should_use_stdbuf(bottle_path)
                else [self._winetricks_path, "-q", info["verb"]],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,  # unbuffered for real-time \r progress
            )

            # Read output char by char to handle \r (wget/curl progress)
            last_msg = ""
            buf = ""
            speed_pattern = re.compile(
                r'(\d+(?:[,.]\d+)?)\s*([KMGT])(?:[Bb]?)(?:\/s|/s|)'
            )

            def is_error_line(line: str) -> bool:
                """Check if a line looks like an error worth reporting."""
                lower = line.lower().strip()
                # ld.so noise from stdbuf's LD_PRELOAD on 32-bit wine
                # processes ("wrong ELF class: ELFCLASS64") is harmless —
                # it only means the 64-bit libstdbuf.so was skipped.
                if "libstdbuf.so" in lower or "wrong elf class" in lower:
                    return False
                keywords = [
                    "error", "failed", "failure", "fatal", "exception",
                    "traceback", "not found", "cannot", "unable", "denied",
                    "没有那个文件", "找不到", "失败",
                ]
                return any(k in lower for k in keywords)

            def flush_line(line):
                """Process a complete line (ended by \n or \r)."""
                if not line.strip():
                    return
                lower = line.lower()
                # Skip the harmless ld.so LD_PRELOAD noise so it never
                # reaches the progress bar or the error log.
                if "libstdbuf.so" in lower or "wrong elf class" in lower:
                    return
                speed_str = ""
                for match in speed_pattern.finditer(line):
                    val, unit = match.groups()
                    val_clean = val.replace(",", ".")
                    unit_clean = unit.upper() if unit else ""
                    if unit_clean:
                        speed_str = f"  {val_clean} {unit_clean}B/s"
                    else:
                        speed_str = f"  {val_clean} B/s"

                if "downloading" in lower or "download" in lower:
                    if progress_callback:
                        progress_callback(50, 100, f"正在下载{speed_str}  {line[:60]}")
                elif "installing" in lower or "extracting" in lower:
                    if progress_callback:
                        progress_callback(70, 100, f"正在安装{speed_str}  {line[:60]}")
                elif "executing" in lower or "running" in lower:
                    if progress_callback:
                        progress_callback(80, 100, f"正在执行{speed_str}  {line[:60]}")
                elif "warning" in lower or "fixme" in lower:
                    pass
                elif progress_callback:
                    prefix = f"处理中{speed_str}  " if speed_str else "处理中  "
                    progress_callback(50, 100, f"{prefix}{line[:60]}")

                # Collect error lines for the final log
                if is_error_line(line):
                    error_lines.append(line.strip())

            IDLE_TIMEOUT = 300  # 5 minutes without output → kill the process

            while True:
                r, _, _ = select.select([process.stdout], [], [], IDLE_TIMEOUT)
                if not r:
                    # No output for IDLE_TIMEOUT seconds — process is stuck
                    process.kill()
                    process.wait()
                    if progress_callback:
                        progress_callback(0, 100, f"⏰ {info['label']} 安装无响应，已终止")
                    return False, f"安装超时（{IDLE_TIMEOUT}秒无输出）"
                ch = process.stdout.read(1)
                if not ch:
                    break
                ch = ch.decode("utf-8", errors="replace")
                if ch == "\r":
                    # Carriage return — flush current line (wget/curl progress)
                    flush_line(buf)
                    buf = ""
                elif ch == "\n":
                    if buf:
                        flush_line(buf)
                        buf = ""
                else:
                    buf += ch
            # Flush remaining buffer
            if buf.strip():
                flush_line(buf)

            process.wait(timeout=600)

            success = process.returncode == 0
            error_log = "\n".join(error_lines[-20:]) if error_lines else ""

            if progress_callback:
                if success:
                    progress_callback(100, 100, f"{info['label']} 安装完成")
                else:
                    progress_callback(0, 100, f"{info['label']} 安装失败")

            # Auto-register installed fonts into the Wine registry so GDI
            # apps can enumerate them. winetricks only copies font files
            # into drive_c/windows/Fonts/ — without registry entries the
            # apps render ALL text as boxes. Re-run on every install so
            # newly added fonts (e.g. allfonts after corefonts) get picked up.
            if success:
                try:
                    from .wine import Wine
                    cfg = self.config
                    w = Wine(cfg.wine_path)
                    w.register_all_fonts(bottle_path)
                except Exception:
                    pass  # font registration is best-effort, not fatal

            return success, error_log

        except subprocess.TimeoutExpired:
            process.kill()
            if progress_callback:
                progress_callback(0, 100, f"⏰ {info['label']} 安装超时")
            return False, f"安装超时（600秒）"
        except Exception as e:
            err = str(e)
            if progress_callback:
                progress_callback(0, 100, f"安装失败: {err[:50]}")
            return False, err

    def get_available_components(self) -> List[dict]:
        """Get list of available components."""
        return [
            {
                "name": name,
                "label": info["label"],
                "description": info["description"],
                "verb": info["verb"],
            }
            for name, info in COMPONENT_MAP.items()
        ]

    def get_component_info(self, name: str) -> Optional[dict]:
        """Get component info by name."""
        return COMPONENT_MAP.get(name)