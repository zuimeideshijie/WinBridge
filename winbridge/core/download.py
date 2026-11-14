"""Component installer using winetricks for Wine components."""

import contextlib
import hashlib
import json
import os
import re
import select
import shutil
import tarfile
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import Config


class InstallCancelled(Exception):
    """Raised when the user cancels a running component install."""


def check_cancel(cancel_event):
    """Abort the current install if the caller's cancel event is set."""
    if cancel_event is not None and cancel_event.is_set():
        raise InstallCancelled()


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


# Microsoft hosts: reachable directly (mirrors only add failure points), but
# their CN CDN nodes sometimes serve an incomplete TLS chain, so they are
# opened without certificate verification.
_MS_DOWNLOAD_HOSTS = (
    "download.microsoft.com",
    "download.visualstudio.microsoft.com",
    "aka.ms",
)

# A single connection from CN to the Microsoft/GitHub CDNs is usually
# throttled far below the available bandwidth. Files above this size are
# fetched as several parallel range requests, which routinely multiplies
# throughput; servers that ignore Range fall back to one stream.
SEGMENT_MIN_SIZE = 4 * 1024 * 1024
MAX_SEGMENTS = 8
_SEGMENT_MIN_PIECE = 1 * 1024 * 1024


def _open_url(url: str, timeout: int, method: str = None,
              headers: dict = None):
    """urlopen wrapper: MS hosts skip cert verification, others don't."""
    request_headers = {"User-Agent": "WinBridge/0.1"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers, method=method)
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in _MS_DOWNLOAD_HOSTS:
        import ssl
        return urllib.request.urlopen(
            request, timeout=timeout,
            context=ssl._create_unverified_context())
    return urllib.request.urlopen(request, timeout=timeout)


# Release tarballs do not agree on how the 32-bit payload directory is named:
# DXVK ships x32/, vkd3d-proton ships x86/. Both must be accepted, otherwise
# the 32-bit DLLs are silently never installed and 32-bit games keep loading
# Wine's builtin translation layer.
BIN_DIR_32 = ("x32", "x86")
BIN_DIR_64 = ("x64", "amd64")

# PE machine types.
_PE_X86 = 0x014C
_PE_X64 = 0x8664


def pe_machine(path) -> Optional[int]:
    """Machine type from a PE file header (0x14c = x86, 0x8664 = x64)."""
    try:
        with open(path, "rb") as f:
            header = f.read(0x40)
            if header[:2] != b"MZ" or len(header) < 0x40:
                return None
            offset = int.from_bytes(header[0x3C:0x40], "little")
            f.seek(offset)
            sig = f.read(6)
            if sig[:4] != b"PE\0\0":
                return None
            return int.from_bytes(sig[4:6], "little")
    except OSError:
        return None


def pe_is_64bit(path) -> Optional[bool]:
    """Whether a PE file is 64-bit (None when the header is unreadable)."""
    machine = pe_machine(path)
    if machine is None:
        return None
    return machine != _PE_X86


# Microsoft VC++ runtime DLLs that have to be overridden to native. Without
# the override Wine keeps loading its builtin copy, so the redistributable
# looks installed while C++ applications still fail. Same list as winetricks'
# vcrun2019/vcrun2022 verbs; the VS2015-2022 runtimes are link-compatible.
_VCRUNTIME_DLLS = (
    "api-ms-win-crt-private-l1-1-0",
    "api-ms-win-crt-conio-l1-1-0",
    "api-ms-win-crt-heap-l1-1-0",
    "api-ms-win-crt-locale-l1-1-0",
    "api-ms-win-crt-math-l1-1-0",
    "api-ms-win-crt-runtime-l1-1-0",
    "api-ms-win-crt-stdio-l1-1-0",
    "api-ms-win-crt-time-l1-1-0",
    "atl140",
    "concrt140",
    "msvcp140",
    "msvcp140_1",
    "msvcp140_2",
    "msvcp140_atomic_wait",
    "msvcp140_codecvt_ids",
    "vcamp140",
    "vccorlib140",
    "vcomp140",
    "vcruntime140",
    # Only shipped on x64; harmless as an override on win32 prefixes.
    "vcruntime140_1",
)

_VCRUNTIME_OVERRIDES = {name: "native,builtin" for name in _VCRUNTIME_DLLS}


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
            # 0 = ok, 3010/1641 = reboot requested, 1638 = newer version present.
            "success_codes": [0, 3010, 1641, 1638],
            "overrides": _VCRUNTIME_OVERRIDES,
            "verify_dlls": {"msvcp140.dll": ["x86", "x64"],
                            "vcruntime140.dll": ["x86", "x64"]},
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
            "success_codes": [0, 3010, 1641, 1638],
            "overrides": _VCRUNTIME_OVERRIDES,
            "verify_dlls": {"msvcp140.dll": ["x86", "x64"],
                            "vcruntime140.dll": ["x86", "x64"]},
        },
    },
    "dotnet48": {
        "label": ".NET Framework 4.8",
        "description": "Microsoft .NET Framework 4.8",
        "verb": "dotnet48",
        # winetricks 必须用 dotnet48 verb：直接跑 ndp48 的 /quiet 安装器
        # 在 Wine 下只会留下一个装不完整的运行时（winetricks 会先移除 mono、
        # 装 dotnet40、切到 win7 模式并以 fusion=b 启动安装器）。
        # fusion=b 与安装耗时较长（含 dotnet40 前置），单独放开这两项。
        "winetricks_env": {"WINEDLLOVERRIDES": "fusion=b;winemenubuilder.exe=d"},
        "winetricks_idle_timeout": 900,
        # winetricks 会用单连接 curl 从微软拉这两个包（约 123MB），CN 网络下
        # 明显更慢。先用 WinBridge 的多线程分片下载器按官方 URL 下好并校验
        # sha256 放进 winetricks 的缓存目录，winetricks 直接复用、不再自下载。
        "winetricks_files": [
            {
                "cache_dir": "dotnet40",
                "file": "dotNetFx40_Full_x86_x64.exe",
                "url": "https://download.microsoft.com/download/9/5/A/95A9616B-7A37-4AF6-BC36-D6EA96C8DAAE/dotNetFx40_Full_x86_x64.exe",
                "sha256": "65e064258f2e418816b304f646ff9e87af101e4c9552ab064bb74d281c38659f",
            },
            {
                "cache_dir": "dotnet48",
                "file": "ndp48-x86-x64-allos-enu.exe",
                "url": "https://download.visualstudio.microsoft.com/download/pr/7afca223-55d2-470a-8edc-6a1739ae3252/abd170b4b0ec15ad0222a809b761a036/ndp48-x86-x64-allos-enu.exe",
                "sha256": "95889d6de3f2070c07790ad6cf2000d33d9a1bdfc6a381725ab82ab1c314fd53",
            },
        ],
        # winetricks 会把容器切到 win7 再装；装完恢复容器原本的 Windows 版本。
        "restore_winver": True,
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
        # 上游 wine_setup_faudio.sh 会把 x64/ 里**所有** dll（xaudio2_7、
        # xactengine3_7、x3daudio1_7 等）连同各自覆盖一起装上；只装
        # FAudio.dll 并不会被任何内置 xaudio2 使用。
        "gitcode": {
            "label": "FAudio",
            "version": "20.07",
            "type": "precompiled_tarball",
            "tarball_url": "https://github.com/Kron4ek/FAudio-Builds/releases/download/20.07/faudio-20.07.tar.xz",
            "tarball_file": "faudio-20.07.tar.xz",
            "all_dlls": True,
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
        # Wine 11 的 msiexec 对这个 2005 年的 msi 会返回 84（读取 summary
        # information 出错）而 winetricks 因此判定失败、跳过后续 64 位步骤；
        # 但 32 位 dll 是 .NET 4.x 安装器必需的（32 位安装器加载
        # system32→syswow64 的 msxml3）。装完直接从 msi 里取出 32 位
        # msxml3.dll/msxml3r.dll 落到 syswow64，并以此判定成功。
        # 预置的 components/winetricks/msxml3/msxml3.msi 曾被截断
        # （651KB vs 官方 1070592 字节），校验后不再使用。
        "msi_assets": {
            "url": "https://media.codeweavers.com/pub/other/msxml3.msi",
            "sha256": "f9c678f8217e9d4f9647e8a1f6d89a7c26a57b9e9e00d39f7487493dd7b4e36c",
            "cache_dir": "msxml3",
            "file": "msxml3.msi",
            "assets": {"msxml3.dll": ["x86"], "msxml3r.dll": ["x86"]},
        },
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
            # 复制了原生 dll 但没写覆盖时 Wine 仍加载内置 msxml6，
            # 表现为「装完没反应」——winetricks 同样显式覆盖。
            # msxml6r.dll 是 msxml6 的资源库，一并覆盖以保持二进制配套。
            "overrides": {"msxml6": "native,builtin",
                          "msxml6r": "native,builtin"},
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
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=5
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
                capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def install(self, component_name: str, bottle_path: str,
                progress_callback: Callable = None,
                cancel_event=None) -> tuple:
        """Install a component.

        Returns (success, log, overrides, files): `log` carries the real error
        output when installation fails, `overrides` the DLL overrides that
        were applied and `files` the DLLs placed under drive_c/windows (both
        mirrored into bottle.json so uninstall can revert them).

        `cancel_event` is a threading.Event set by the UI's cancel button.
        Cancelling aborts a running download (partial .part removed), stops
        winetricks, and returns (False, "已取消", {}, []) without touching
        the bottle metadata.
        """
        info = COMPONENT_MAP.get(component_name)
        if not info:
            return False, f"未知组件 '{component_name}'", {}, []

        try:
            # Custom direct install (bypasses winetricks entirely)
            if info.get("direct"):
                return self._install_direct(component_name, info, bottle_path,
                                            progress_callback, cancel_event)

            # Microsoft packages (VC++ redistributables, MSXML security updates)
            if "redist" in info:
                return self._install_redist_exe(component_name, info, bottle_path,
                                                progress_callback, cancel_event)

            # Release assets downloaded through GITHUB_MIRRORS
            if "gitcode" in info:
                install_type = info["gitcode"].get("type", "")
                if install_type == "directx_redist":
                    return self._install_directx_redist(
                        component_name, info, bottle_path, progress_callback,
                        cancel_event)
                if install_type == "precompiled_tarball":
                    return self._install_precompiled_tarball(
                        component_name, info, bottle_path, progress_callback,
                        cancel_event)
                return False, f"不支持的组件安装类型 '{install_type}'", {}, []

            # Fallback to winetricks for other components
            return self._install_via_winetricks(component_name, info, bottle_path,
                                                progress_callback, cancel_event)
        except InstallCancelled:
            if progress_callback:
                progress_callback(0, 100, f"{info['label']} 已取消")
            return False, "已取消", {}, []

    def uninstall(self, component_name: str, bottle_path: str,
                  files: List[str] = None, overrides: dict = None,
                  keep_overrides=None,
                  progress_callback: Callable = None) -> tuple:
        """Revert the files and DLL overrides a component installed.

        Same semantics as Bottles' DLLComponent.uninstall(): a <dll>.bck
        backup wins (it is the file the component replaced), otherwise the
        DLL we placed is removed so Wine loads the runner's builtin again.
        The override values are deleted, not just left behind — otherwise
        "卸载" would keep the native DLL in use.

        `files` are paths relative to drive_c/windows; `keep_overrides` are
        DLL names that another installed component still needs.

        Returns (success: bool, log: str).
        """
        files = list(files or [])
        overrides = dict(overrides or {})
        keep = {self._dll_override_name(name) for name in (keep_overrides or [])}

        if progress_callback:
            progress_callback(0, 100, "正在还原组件文件...")

        windows = Path(bottle_path) / "drive_c" / "windows"
        restored, removed, problems = 0, 0, []
        for rel_path in files:
            target = windows / rel_path
            backup = target.with_name(target.name + ".bck")
            try:
                if backup.exists():
                    os.replace(str(backup), str(target))
                    restored += 1
                elif target.exists():
                    os.remove(str(target))
                    removed += 1
            except OSError as e:
                problems.append(f"{rel_path}: {e}")

        drop = [name for name in overrides
                if self._dll_override_name(name) not in keep]
        if drop:
            if progress_callback:
                progress_callback(60, 100, "正在移除 DLL 覆盖...")
            ok, err = self._delete_dll_overrides(bottle_path, drop,
                                                 progress_callback)
            if not ok:
                problems.append(err)

        if progress_callback:
            progress_callback(100, 100, f"{component_name} 已卸载")

        if problems:
            return False, "\n".join(problems)
        return True, ""

    def _delete_dll_overrides(self, bottle_path: str, names,
                              progress_callback: Callable = None) -> tuple:
        """Remove HKCU DllOverrides values and verify they are gone."""
        wanted = {self._dll_override_name(name): "-" for name in names}
        if not wanted:
            return True, ""
        try:
            from .wine import Wine
            wine = Wine(self.config.wine_path)
        except Exception as e:
            return False, f"无法移除 DLL 覆盖: {e}"

        last_err = self._import_dll_overrides(wine, bottle_path, wanted)
        applied = self._read_dll_overrides(wine, bottle_path)
        remaining = [name for name in wanted if name in applied]
        if not remaining:
            return True, ""

        for name in remaining:
            try:
                result = wine.run_cmd(
                    bottle_path,
                    f'reg delete "HKCU\\Software\\Wine\\DllOverrides" '
                    f'/v "{name}" /f',
                    timeout=60)
            except Exception as e:
                last_err = str(e)
                continue
            if result.returncode != 0:
                last_err = (result.stdout + result.stderr).strip()[:200]

        applied = self._read_dll_overrides(wine, bottle_path)
        remaining = [name for name in wanted if name in applied]
        if remaining:
            return False, (f"DLL 覆盖移除失败（{', '.join(sorted(remaining))}）："
                           f"{last_err or '注册表仍能读到该值'}")
        return True, ""

    def _suspend_app_overrides(self, bottle_path: str) -> dict:
        """Temporarily drop the app-wide ('*') DLL overrides.

        `*msxml3=native` style values are aimed at the user's programs, but a
        Microsoft installer is a program too: with an incompatible native
        msxml3/gdiplus loaded, the .NET 4.0 setup dies with 0xe06d7363
        (reproduced on a clean prefix: no overrides → rc=0, with them → rc=99).
        They are removed for the duration of the install and put back after.

        Returns the removed overrides so the caller can restore them.
        """
        try:
            from .wine import Wine
            wine = Wine(self.config.wine_path)
            applied = self._read_dll_overrides(wine, bottle_path)
        except Exception:
            return {}
        suspended = {name: mode for name, mode in applied.items()
                     if name.startswith("*")}
        if suspended:
            self._delete_dll_overrides(bottle_path, list(suspended))
        return suspended

    def _restore_dll_overrides(self, bottle_path: str, overrides: dict):
        """Put back overrides removed by _suspend_app_overrides."""
        if overrides:
            self._set_dll_overrides(bottle_path, overrides)

    @contextlib.contextmanager
    def _suspended_app_overrides(self, bottle_path: str):
        """Run a block with the app-wide overrides removed and restored."""
        suspended = self._suspend_app_overrides(bottle_path)
        try:
            yield suspended
        finally:
            self._restore_dll_overrides(bottle_path, suspended)

    # ---- bottle layout / DLL placement helpers -------------------------

    @staticmethod
    def _bottle_arch(bottle_path: str) -> str:
        """'win32' or 'win64' for a prefix (win64 when it cannot be read)."""
        try:
            from .wine import Wine
            arch = Wine().get_prefix_arch(bottle_path)
            return arch if arch in ("win32", "win64") else "win64"
        except Exception:
            return "win64"

    def _system_dirs(self, bottle_path: str,
                     arch: str = None) -> Dict[str, Optional[Path]]:
        """Target directories by payload arch.

        A win64 prefix keeps 32-bit DLLs in syswow64 and 64-bit ones in
        system32; a win32 prefix only has system32.
        """
        arch = arch or self._bottle_arch(bottle_path)
        win = Path(bottle_path) / "drive_c" / "windows"
        if arch == "win64":
            return {"x86": win / "syswow64", "x64": win / "system32"}
        return {"x86": win / "system32", "x64": None}

    @staticmethod
    def _dll_override_name(name: str) -> str:
        """Registry value name for a DLL override ('d3d9.dll' → 'd3d9')."""
        name = name.strip().lower()
        return name[:-4] if name.endswith(".dll") else name

    @staticmethod
    def _windows_relative(bottle_path: str, target: Path) -> str:
        """Path of a file inside drive_c/windows (stored in bottle.json)."""
        try:
            return str(Path(target).relative_to(
                Path(bottle_path) / "drive_c" / "windows"))
        except ValueError:
            return str(target)

    @staticmethod
    def _install_dll_file(source: Path, target: Path) -> bool:
        """Copy a DLL into the prefix atomically, backing up what it replaces.

        <dll>.bck keeps the previous file so uninstall can restore it instead
        of losing a user's own DLL, and the temp-file + os.replace dance means
        a failed copy never leaves a truncated DLL behind for Wine to load.
        """
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = target.with_name(target.name + ".bck")
            if target.exists() and not backup.exists():
                shutil.copy2(str(target), str(backup))
            fd, temp_path = tempfile.mkstemp(
                dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
            os.close(fd)
            try:
                shutil.copy2(str(source), temp_path)
                os.replace(temp_path, str(target))
            except OSError:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(temp_path)
                raise
            return True
        except OSError:
            return False

    @staticmethod
    def _find_bin_dir(root: Path, names) -> Optional[Path]:
        for name in names:
            candidate = Path(root) / name
            if candidate.is_dir():
                return candidate
        return None

    @classmethod
    def _locate_package_root(cls, root: Path) -> Path:
        """Directory of an extracted tarball that holds x32/x64 (or x86/x64)."""
        root = Path(root)
        if cls._find_bin_dir(root, BIN_DIR_32 + BIN_DIR_64):
            return root
        children = sorted(p for p in root.iterdir() if p.is_dir())
        for child in children:
            if cls._find_bin_dir(child, BIN_DIR_32 + BIN_DIR_64):
                return child
        return children[0] if children else root

    def _read_dll_overrides(self, wine, bottle_path: str) -> Dict[str, str]:
        """Read back HKCU DllOverrides (empty dict when unreadable)."""
        try:
            result = wine.run_cmd(
                bottle_path, 'reg query "HKCU\\Software\\Wine\\DllOverrides"',
                timeout=60)
        except Exception:
            return {}
        overrides = {}
        for line in result.stdout.splitlines():
            match = re.match(r"^\s+(\S+)\s+REG_SZ\s+(\S+)\s*$", line)
            if match:
                overrides[match.group(1).lower()] = match.group(2)
        return overrides

    @staticmethod
    def _override_reg_text(overrides: Dict[str, str]) -> str:
        """REGEDIT body for a set of overrides; '-' deletes a value."""
        lines = ["Windows Registry Editor Version 5.00", "",
                 r"[HKEY_CURRENT_USER\Software\Wine\DllOverrides]"]
        for name, mode in overrides.items():
            # "value=-" deletes the value (REGEDIT syntax) — uninstall needs
            # that so Wine really falls back to its builtin DLL.
            lines.append(f'"{name}"=-' if mode in (None, "-")
                         else f'"{name}"="{mode}"')
        return "\r\n".join(lines) + "\r\n"

    def _import_dll_overrides(self, wine, bottle_path: str,
                              overrides: Dict[str, str]) -> str:
        """Write several overrides with a single regedit import.

        Every `wine` invocation starts a wineserver (seconds of overhead), so
        a component with 20+ DLLs would otherwise take a minute just to
        register them. Returns "" on success, an error string otherwise.
        """
        reg_path = None
        try:
            fd, reg_path = tempfile.mkstemp(prefix="winbridge_ov_", suffix=".reg")
            with os.fdopen(fd, "w", encoding="utf-16") as handle:
                handle.write(self._override_reg_text(overrides))
            result = wine.run_cmd(bottle_path, f'regedit /S "{reg_path}"',
                                  timeout=120)
            if result.returncode != 0:
                return (result.stdout + result.stderr).strip()[:200]
            return ""
        except Exception as e:
            return str(e)
        finally:
            if reg_path:
                try:
                    os.remove(reg_path)
                except OSError:
                    pass

    def _set_dll_overrides(self, bottle_path: str, overrides: dict,
                           progress_callback: Callable = None) -> tuple:
        """Write HKCU DllOverrides and verify Wine reads them back.

        A native DLL copied into the prefix is ignored while Wine keeps its
        builtin loaded — that is exactly what "安装成功但没效果" looks like.
        The values are imported in one go and then read back; anything that
        did not land is written individually and reported as an error if it
        still does not stick.

        Returns (success: bool, error: str).
        """
        wanted = {self._dll_override_name(k): v
                  for k, v in (overrides or {}).items()}
        if not wanted:
            return True, ""
        try:
            from .wine import Wine
            wine = Wine(self.config.wine_path)
        except Exception as e:
            return False, f"无法写入 DLL 覆盖: {e}"

        if progress_callback:
            progress_callback(95, 100, "正在注册 DLL 覆盖...")

        last_err = self._import_dll_overrides(wine, bottle_path, wanted)
        applied = self._read_dll_overrides(wine, bottle_path)
        missing = {n: m for n, m in wanted.items() if applied.get(n) != m}
        if not missing:
            return True, ""

        # Import did not take (e.g. regedit unavailable) — try one by one.
        for name, mode in missing.items():
            try:
                result = wine.run_cmd(
                    bottle_path,
                    f'reg add "HKCU\\Software\\Wine\\DllOverrides" '
                    f'/v "{name}" /d "{mode}" /f',
                    timeout=60)
            except Exception as e:
                last_err = str(e)
                continue
            if result.returncode != 0:
                last_err = (result.stdout + result.stderr).strip()[:200]

        applied = self._read_dll_overrides(wine, bottle_path)
        missing = {n: m for n, m in wanted.items() if applied.get(n) != m}
        if not missing:
            return True, ""

        detail = last_err or "注册表读回的覆盖值与预期不一致"
        return False, (
            f"DLL 覆盖写入失败（{', '.join(sorted(missing))}）：{detail}\n"
            f"文件已复制，但 Wine 仍会加载内置 DLL，组件不会生效。")

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
                       label: str = "",
                       cancel_event=None) -> tuple:
        """Download a file, routing GitHub URLs through mirrors.

        Each candidate source is tried in turn; the mirror that succeeds is
        remembered so subsequent downloads skip the ones that don't work.
        Returns (success: bool, error: str).
        """
        candidates = self._download_candidates(url)
        last_err = ""
        for prefix, candidate in candidates:
            check_cancel(cancel_event)
            if progress_callback:
                host = urllib.parse.urlsplit(prefix).hostname if prefix else ""
                suffix = f"（镜像 {host}）" if host else ""
                progress_callback(0, 100, f"正在下载 {label}{suffix}...")
            ok, err = self._download_one(candidate, dest_path, progress_callback,
                                         label, mirrored=bool(prefix),
                                         cancel_event=cancel_event)
            if ok:
                self._github_mirror = prefix
                return True, ""
            last_err = err
        if len(candidates) > 1:
            return False, f"下载失败（已尝试 {len(candidates)} 个源）: {last_err}"
        return False, f"下载失败: {last_err}"

    @staticmethod
    def _probe_download(url: str, timeout: int = 30) -> tuple:
        """(size, supports_ranges) for a URL; (0, False) when unknown."""
        try:
            with _open_url(url, min(timeout, 30), method="HEAD") as resp:
                size = int(resp.headers.get("Content-Length") or 0)
                ranges = "bytes" in (
                    resp.headers.get("Accept-Ranges") or "").lower()
                if size and ranges:
                    return size, True
        except Exception:
            pass
        # Some CDNs only advertise range support on a GET
        try:
            with _open_url(url, min(timeout, 30),
                           headers={"Range": "bytes=0-0"}) as resp:
                if getattr(resp, "status", None) == 206:
                    total = resp.headers.get("Content-Range", "").rsplit("/", 1)[-1]
                    if total.isdigit():
                        return int(total), True
        except Exception:
            pass
        return 0, False

    @staticmethod
    def _progress_message(label: str, done: int, total: int,
                          speed: float = 0) -> tuple:
        """(percent, message) with MB/speed/ETA for the download bar."""
        if not total:
            return 50, f"正在下载 {label}  {done / (1024 * 1024):.1f}MB"
        percent = min(int(done * 100 / total), 99)
        message = (f"正在下载 {label}  "
                   f"{done / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f}MB")
        if speed > 0:
            message += f"  {speed / 1024:.1f}KB/s"
            if done < total:
                left = int((total - done) / speed)
                message += f"  剩余 {left // 60}m{left % 60}s"
        return percent, message

    def _download_segmented(self, url: str, dest_path: str, size: int,
                            progress_callback: Callable, label: str,
                            cancel_event) -> bool:
        """Fetch a large file with parallel range requests.

        Returns False when the server or proxy cannot serve ranges — the
        caller then falls back to a single stream, so a mirror lying about
        range support never breaks an install.
        """
        import threading

        segments = min(MAX_SEGMENTS, max(2, size // _SEGMENT_MIN_PIECE))
        piece = size // segments
        ranges = [
            (i * piece, size - 1 if i == segments - 1 else (i + 1) * piece - 1)
            for i in range(segments)
        ]
        part_paths = [f"{dest_path}.seg{i}" for i in range(segments)]
        lock = threading.Lock()
        state = {"done": 0, "error": None, "cancelled": False,
                 "last_report": 0.0, "last_bytes": 0, "last_time": time.time()}

        def report():
            now = time.time()
            with lock:
                done = state["done"]
                elapsed = now - state["last_time"]
                if elapsed <= 0:
                    return
                speed = (done - state["last_bytes"]) / elapsed
                state["last_time"] = now
                state["last_bytes"] = done
                if now - state["last_report"] < 0.2 and done < size:
                    return
                state["last_report"] = now
            if progress_callback:
                percent, message = ComponentManager._progress_message(
                    label, done, size, speed)
                progress_callback(percent, 100, message)

        def worker(index: int, start: int, end: int):
            try:
                with _open_url(url, 60, headers={
                        "Range": f"bytes={start}-{end}"}) as resp:
                    if getattr(resp, "status", None) != 206:
                        raise OSError("服务器不支持分段下载")
                    with open(part_paths[index], "wb") as handle:
                        while True:
                            buf = resp.read(65536)
                            if not buf:
                                break
                            check_cancel(cancel_event)
                            handle.write(buf)
                            with lock:
                                state["done"] += len(buf)
                            report()
            except InstallCancelled:
                with lock:
                    state["cancelled"] = True
            except Exception as exc:  # noqa: BLE001 - fall back below
                with lock:
                    state["error"] = exc

        def cleanup():
            for part in part_paths:
                with contextlib.suppress(OSError):
                    os.remove(part)

        try:
            threads = [threading.Thread(target=worker, args=(i, s, e), daemon=True)
                       for i, (s, e) in enumerate(ranges)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            if state["cancelled"]:
                raise InstallCancelled()
            if state["error"] is not None:
                return False
            received = sum(os.path.getsize(p) for p in part_paths
                           if os.path.exists(p))
            if received != size:
                return False

            temp_path = dest_path + ".part"
            with open(temp_path, "wb") as out:
                for part in part_paths:
                    with open(part, "rb") as src:
                        shutil.copyfileobj(src, out, 1024 * 256)
            os.replace(temp_path, dest_path)
            return True
        except InstallCancelled:
            raise
        except (OSError, RuntimeError):
            return False
        finally:
            cleanup()

    def _download_stream(self, url: str, dest_path: str,
                         progress_callback: Callable, label: str,
                         cancel_event, timeout: int):
        """Single-connection download with resumable .part file."""
        part_path = dest_path + ".part"
        with _open_url(url, timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            last_time = time.time()
            last_bytes = 0

            with open(part_path, "wb") as handle:
                while True:
                    buf = resp.read(65536)
                    if not buf:
                        break
                    # Checked per chunk (~64KB) so cancelling a slow download
                    # stops within a fraction of a second.
                    check_cancel(cancel_event)
                    handle.write(buf)
                    downloaded += len(buf)

                    if progress_callback:
                        now = time.time()
                        if now - last_time >= 0.2 or not total:
                            elapsed = now - last_time
                            speed = ((downloaded - last_bytes) / elapsed
                                     if elapsed > 0 else 0)
                            percent, message = ComponentManager._progress_message(
                                label, downloaded, total, speed)
                            progress_callback(percent, 100, message)
                            last_time = now
                            last_bytes = downloaded

            os.replace(part_path, dest_path)

    def _download_one(self, url: str, dest_path: str,
                      progress_callback: Callable = None,
                      label: str = "", mirrored: bool = False,
                      cancel_event=None) -> tuple:
        """Download a single URL with real-time progress and speed reporting.

        Large files are split into parallel range requests (faster from CN);
        everything else streams single-connection. Returns (success, error).
        """
        # Mirrors are either healthy or plainly dead, so don't spend as long
        # on them as on the (usually slower but reliable) official hosts.
        attempts = 2 if mirrored else 3
        timeout = 60 if mirrored else 120

        last_err = None
        for attempt in range(attempts):
            check_cancel(cancel_event)
            part_path = dest_path + ".part"
            try:
                size, ranges = self._probe_download(url, timeout)
                if ranges and size >= SEGMENT_MIN_SIZE:
                    if self._download_segmented(
                            url, dest_path, size, progress_callback, label,
                            cancel_event):
                        if progress_callback:
                            progress_callback(100, 100, f"{label} 下载完成")
                        return True, ""
                self._download_stream(url, dest_path, progress_callback, label,
                                      cancel_event, timeout)
                if progress_callback:
                    progress_callback(100, 100, f"{label} 下载完成")
                return True, ""
            except InstallCancelled:
                with contextlib.suppress(OSError):
                    os.remove(part_path)
                raise
            except Exception as e:
                last_err = e
                with contextlib.suppress(OSError):
                    os.remove(part_path)
                if attempt < attempts - 1:
                    time.sleep(2)
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
                                        capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=300)
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
                             retries: int = 1,
                             cancel_event=None) -> tuple:
        """Download a file and verify its integrity, retrying if corrupted.

        Returns (success: bool, error: str).
        """
        for attempt in range(retries + 1):
            ok, err = self._download_file(url, dest_path, progress_callback,
                                          label, cancel_event=cancel_event)
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

    def _install_redist_exe(self, component_name: str, info: dict,
                            bottle_path: str,
                            progress_callback: Callable = None,
                            cancel_event=None) -> tuple:
        """Install a Microsoft redistributable downloaded from its official URL.

        Downloads the x86 and x64 packages into the component cache, runs each
        silently via wine, then verifies the runtime DLLs really are in the
        prefix and registers the DLL overrides that make Wine load them.
        """
        redist = info["redist"]
        urls = redist["urls"]
        install_args = redist.get("install_args", "/install /quiet /norestart")
        extract_msi = redist.get("extract_msi", False)
        label = info["label"]
        check_cancel(cancel_event)

        # Downloads go to the user-writable cache dir — components_dir is
        # read-only in the .deb install (root-owned /usr/lib/winbridge).
        cache_dir = self.config.cache_dir / component_name
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, f"无法创建缓存目录 {cache_dir}: {e}", {}, []

        local_files = []
        for arch_key, url in urls.items():
            if not url:
                continue
            file_name = Path(url).name
            local_path = str(cache_dir / file_name)
            if Path(local_path).exists():
                valid, _ = self._verify_file(local_path)
                if not valid:
                    try:
                        os.remove(local_path)
                    except OSError:
                        pass
            if not Path(local_path).exists():
                if progress_callback:
                    progress_callback(0, 100, f"正在下载 {label} ({arch_key})...")
                ok, err = self._download_and_verify(
                    url, local_path, progress_callback, f"{label} {arch_key}",
                    cancel_event=cancel_event)
                if not ok:
                    return False, err, {}, []
            local_files.append(local_path)

        if not local_files:
            return False, "redist 配置缺少下载链接", {}, []

        # Some Microsoft packages (e.g. the MSXML 6.0 security update) are
        # self-extracting CABs that don't install cleanly under wine with
        # silent flags. Extract the inner DLLs with cabextract and copy them
        # into the bottle instead — same approach winetricks uses.
        if extract_msi:
            return self._install_redist_extract(
                label, local_files, bottle_path, progress_callback,
                redist.get("overrides", {}), cancel_event)

        bottle_arch = self._bottle_arch(bottle_path)
        success_codes = set(redist.get("success_codes", (0,)))

        # Run each installer silently via wine (x86 first, then x64). App-wide
        # overrides (e.g. *msxml3=native) crash Microsoft installers, so they
        # are suspended for the whole run and restored afterwards.
        with self._suspended_app_overrides(bottle_path):
            for local_path in local_files:
                check_cancel(cancel_event)
                pkg_name = Path(local_path).name
                if bottle_arch == "win32" and "x64" in pkg_name:
                    continue  # a 64-bit redistributable is useless in a win32 prefix
                if progress_callback:
                    progress_callback(0, 100, f"正在安装 {label} ({pkg_name}) 到容器...")
                env = os.environ.copy()
                env["WINEPREFIX"] = bottle_path
                env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
                wine_bin = self.config.wine_path or "/usr/bin/wine"
                env["WINE"] = wine_bin
                cmd = [wine_bin, local_path] + install_args.split()
                try:
                    result = subprocess.run(cmd, env=env, capture_output=True,
                                            text=True, encoding="utf-8",
                                            errors="replace", timeout=900)
                except subprocess.TimeoutExpired:
                    return False, f"安装超时（900秒）: {pkg_name}", {}, []
                if result.returncode not in success_codes:
                    err_out = (result.stderr.strip() or result.stdout.strip()
                               or f"退出码 {result.returncode}")
                    return False, f"{pkg_name} 安装失败: {err_out}", {}, []

        # The redistributable's own MSI skips files when Wine's builtin
        # reports a higher version (wine bug 57518), leaving a runtime that
        # looks installed but cannot load. Overlay the core DLLs straight
        # from the package, then make Wine actually prefer the native ones.
        check_cancel(cancel_event)
        problems = self._overlay_redist_dlls(
            label, local_files, bottle_path,
            list(redist.get("verify_dlls", {})), progress_callback)
        if problems:
            return False, problems, {}, []

        overrides = redist.get("overrides", {})
        ok, err = self._set_dll_overrides(bottle_path, overrides, progress_callback)
        if not ok:
            return False, err, {}, []

        if progress_callback:
            progress_callback(100, 100, f"{label} 安装完成")
        # An MSI install is not reversible by copying files back — uninstall
        # only drops the record and the overrides, so no files are tracked.
        return True, "", overrides, []

    @staticmethod
    def _payload_matches_arch(path, arch_key: str) -> bool:
        """Whether a PE file's machine type fits 'x86' / 'x64'."""
        is_64bit = pe_is_64bit(path)
        if is_64bit is None:
            return True
        return is_64bit if arch_key == "x64" else not is_64bit

    @staticmethod
    def _cab_member_base(name: str) -> str:
        """Normalize a cab member name ('msvcp140.dll_x86' → 'msvcp140')."""
        base = name.lower()
        for suffix in ("_x86", "_x64", "_amd64"):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        if base.endswith(".dll"):
            base = base[:-4]
        return base

    def _overlay_redist_dlls(self, label: str, packages: list, bottle_path: str,
                             dll_names: list,
                             progress_callback: Callable = None) -> str:
        """Ensure the core runtime DLLs in the prefix are the package's own.

        Some installers silently skip a DLL whose Wine builtin reports a newer
        version (wine bug 57518). Cab members are matched by name and sorted
        by PE machine type, so this does not depend on how a given package
        release names its cabs or suffixes its members.

        Returns "" on success, an error message otherwise.
        """
        if not dll_names:
            return ""
        targets = self._system_dirs(bottle_path)
        wanted = [self._dll_override_name(name) for name in dll_names]

        missing = [(name, key, target) for name in wanted
                   for key, target in targets.items()
                   if target and not (target / f"{name}.dll").exists()]
        if not missing:
            return ""

        if progress_callback:
            progress_callback(98, 100, f"正在补齐 {label} 运行时文件...")

        extract_root = tempfile.mkdtemp(prefix=f"winbridge_{label}_runtime_")
        try:
            cabs = Path(extract_root) / "cabs"
            files = Path(extract_root) / "files"
            cabs.mkdir()
            files.mkdir()
            for package in packages:
                subprocess.run(
                    ["cabextract", "-q", "-L", "-F", "a*", "-d", str(cabs), package],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180)
            for cab in sorted(cabs.iterdir()):
                subprocess.run(
                    ["cabextract", "-q", "-L", "-d", str(files), str(cab)],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=300)

            available = {}
            for member in files.iterdir():
                if not member.is_file():
                    continue
                available.setdefault(self._cab_member_base(member.name), []).append(member)

            unresolved = []
            for name, key, target in missing:
                sources = [f for f in available.get(name, [])
                           if self._payload_matches_arch(f, key)]
                if not sources:
                    unresolved.append(f"{name}.dll({key})")
                    continue
                if not self._install_dll_file(sources[0], target / f"{name}.dll"):
                    unresolved.append(f"{name}.dll({key}, 写入失败)")

            if unresolved:
                return (f"运行时文件缺失：{', '.join(unresolved)}"
                        f"（安装程序未写入，也无法从安装包中提取）")
            return ""
        except (OSError, subprocess.SubprocessError) as e:
            return f"补齐运行时文件失败: {e}"
        finally:
            shutil.rmtree(extract_root, ignore_errors=True)

    def _install_redist_extract(self, label: str, local_files: list,
                                bottle_path: str,
                                progress_callback: Callable = None,
                                overrides: dict = None,
                                cancel_event=None) -> tuple:
        """Install a Microsoft package by extracting DLLs with cabextract.

        Used for packages (e.g. MSXML 6.0 security updates) that are
        self-extracting CABs which don't install cleanly under wine with
        silent flags. Extracts the inner .msi, then the DLLs, and copies
        them into the bottle's system dirs — same approach winetricks uses.
        """
        if progress_callback:
            progress_callback(0, 100, f"正在提取 {label}...")

        check_cancel(cancel_event)
        extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{label}_")
        try:
            # Level 1: self-extracting .exe → .msi
            for exe in local_files:
                result = subprocess.run(
                    ["cabextract", "-L", "-d", extract_dir, exe],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120)
                if result.returncode != 0 and "no valid cabinets" in result.stdout:
                    return False, "不是有效的 CAB 文件，下载可能不完整", {}, []

            # Level 2: .msi → DLLs
            msi_files = list(Path(extract_dir).glob("*.msi"))
            if not msi_files:
                return False, "提取后未找到 .msi 文件", {}, []
            for msi in msi_files:
                result = subprocess.run(
                    ["cabextract", "-L", "-d", extract_dir, str(msi)],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120)
                if result.returncode != 0 and "no valid cabinets" in result.stdout:
                    return False, f"无法从 {msi.name} 提取文件", {}, []

            targets = self._system_dirs(bottle_path)

            copied = 0
            installed_files = []
            # DLLs extracted from the MSI carry GUID-suffixed names
            # (e.g. msxml6.dll.86F857F6_A743_463D_B2FE_98CB5F727E09), so
            # match the ".dll." pattern and classify 32/64-bit by the PE
            # header instead of hardcoding GUIDs.
            for dll in Path(extract_dir).iterdir():
                if not dll.is_file():
                    continue
                name_lower = dll.name.lower()
                if ".dll." not in name_lower:
                    continue
                base = name_lower.split(".dll.")[0] + ".dll"
                key = "x64" if pe_is_64bit(dll) else "x86"
                target = targets.get(key)
                if not target:
                    continue  # 64-bit payload in a win32 prefix
                dst = target / base
                if not self._install_dll_file(dll, dst):
                    continue
                installed_files.append(self._windows_relative(bottle_path, dst))
                copied += 1

            if copied == 0:
                return False, "未找到可复制的 DLL 文件", {}, []

            overrides = overrides or {}
            missing = sorted({f"{name}.dll" for name in overrides
                              for target in targets.values()
                              if target and not (target / f"{name}.dll").exists()})
            if missing:
                return False, f"提取后缺少 {', '.join(missing)}", {}, []

            ok, err = self._set_dll_overrides(bottle_path, overrides, progress_callback)
            if not ok:
                return False, err, {}, []

            if progress_callback:
                progress_callback(100, 100, f"{label} 安装完成（{copied} 个文件）")
            return True, "", overrides, installed_files

        except subprocess.TimeoutExpired:
            return False, "提取超时", {}, []
        except Exception as e:
            return False, str(e), {}, []
        finally:
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
                                     progress_callback: Callable = None,
                                     cancel_event=None) -> tuple:
        """Install a precompiled component (DXVK/VKD3D/FAudio) from a release tarball.

        Needs no meson/ninja: download, extract, copy the 32/64-bit DLLs into
        the bottle and register the overrides that make Wine load them.
        """
        gc = info["gitcode"]
        label = info["label"]
        version = gc["version"]
        tarball_url = gc["tarball_url"]
        tarball_file = gc.get("tarball_file", tarball_url.split("/")[-1])
        dlls = list(gc.get("dlls", []))
        all_dlls = bool(gc.get("all_dlls"))
        override_mode = gc.get("override_mode", "native")

        if progress_callback:
            progress_callback(0, 100, f"准备安装 {label} {version}...")

        cache_dir = self.config.cache_dir / component_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        local_path = str(cache_dir / tarball_file)

        # Reuse a cached archive instead of downloading it again
        if Path(local_path).exists():
            valid, _ = self._verify_file(local_path)
            if not valid:
                try:
                    os.remove(local_path)
                except OSError:
                    pass
        if not Path(local_path).exists():
            if progress_callback:
                progress_callback(30, 100, f"正在下载 {label}...")
            ok, err = self._download_and_verify(
                tarball_url, local_path, progress_callback, label,
                cancel_event=cancel_event)
            if not ok:
                return False, err, {}, []

        check_cancel(cancel_event)
        if progress_callback:
            progress_callback(70, 100, f"正在解压 {label}...")
        extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{component_name}_")
        try:
            ok, err = self._extract_archive(local_path, extract_dir)
            if not ok:
                return False, err, {}, []

            arch = self._bottle_arch(bottle_path)
            targets = self._system_dirs(bottle_path, arch)
            src_dir = self._locate_package_root(Path(extract_dir))

            copied: Dict[str, List[str]] = {}
            installed_files: List[str] = []
            for arch_key, dir_names in (("x86", BIN_DIR_32), ("x64", BIN_DIR_64)):
                target = targets.get(arch_key)
                if not target:
                    continue
                source = self._find_bin_dir(src_dir, dir_names)
                if not source:
                    continue
                names = (sorted(p.stem for p in source.glob("*.dll"))
                         if all_dlls or not dlls else dlls)
                target.mkdir(parents=True, exist_ok=True)
                for name in names:
                    src_dll = source / f"{name}.dll"
                    if not src_dll.exists():
                        continue
                    # Never place a 64-bit DLL in syswow64 (or vice versa):
                    # Wine silently ignores a wrong-arch payload.
                    if not self._payload_matches_arch(src_dll, arch_key):
                        continue
                    dst = target / f"{name}.dll"
                    if not self._install_dll_file(src_dll, dst):
                        return False, f"写入 {dst.name} 失败", {}, []
                    copied.setdefault(arch_key, []).append(name)
                    installed_files.append(
                        self._windows_relative(bottle_path, dst))

            if not copied:
                return False, "未找到任何需要安装的 DLL 文件", {}, []
            if arch == "win64" and "x64" not in copied:
                return False, f"{label} 压缩包中没有 64 位 DLL，无法安装到 64 位容器", {}, []

            overrides = {name: override_mode
                         for names in copied.values() for name in names}
            ok, err = self._set_dll_overrides(bottle_path, overrides, progress_callback)
            if not ok:
                return False, err, {}, []

            total = sum(len(names) for names in copied.values())
            note = ""
            if arch == "win64" and "x86" not in copied:
                # e.g. FAudio 20.07 ships x64 only (upstream dropped the
                # broken 32-bit builds) — 32-bit programs keep the builtin.
                note = "；此版本不含 32 位 DLL，32 位程序仍使用内置版本"
            if progress_callback:
                progress_callback(100, 100,
                                  f"{label} {version} 安装完成（{total} 个文件）{note}")
            return True, "", overrides, installed_files

        except Exception as e:
            return False, str(e), {}, []
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    def _install_directx_redist(self, component_name: str, info: dict,
                                bottle_path: str,
                                progress_callback: Callable = None,
                                cancel_event=None) -> tuple:
        """Install a DirectX redist component by downloading and extracting DLLs."""
        gc = info["gitcode"]
        label = info["label"]
        gc_label = gc.get("label", label)
        version = gc["version"]
        redist_url = gc["redist_url"]
        redist_file = gc["redist_file"]
        dlls = gc["dlls"]
        check_cancel(cancel_event)

        if progress_callback:
            progress_callback(0, 100, f"准备安装 {gc_label} {version}...")

        # Downloads go to the user-writable cache dir — components_dir is
        # read-only in the .deb install (root-owned /usr/lib/winbridge).
        cache_dir = self.config.cache_dir / component_name
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return False, f"无法创建缓存目录 {cache_dir}: {e}", {}, []
        local_path = str(cache_dir / redist_file)

        # Download the redist if not cached
        if not Path(local_path).exists():
            ok, err = self._download_and_verify(
                redist_url, local_path, progress_callback, gc_label,
                cancel_event=cancel_event)
            if not ok:
                return False, err, {}, []
        else:
            valid, msg = self._verify_file(local_path)
            if not valid:
                try:
                    os.remove(local_path)
                except OSError:
                    pass
                ok, err = self._download_and_verify(
                    redist_url, local_path, progress_callback, gc_label,
                    cancel_event=cancel_event)
                if not ok:
                    return False, f"缓存损坏，重新下载失败: {err}", {}, []

        check_cancel(cancel_event)
        if progress_callback:
            progress_callback(50, 100, f"正在提取 {gc_label}...")

        # The redist's cab files are named <name>_x86.cab / <name>_x64.cab —
        # there is no "amd64" spelling, so map the config's arch keys first.
        cab_suffix = {"x86": "x86", "x64": "x64", "amd64": "x64"}
        targets = self._system_dirs(bottle_path)

        extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{component_name}_")
        try:
            # First extraction: self-extracting .exe → .cab files
            result = subprocess.run(
                ["cabextract", "-L", "-d", extract_dir, local_path],
                capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180
            )
            if result.returncode != 0 and "no valid cabinets" in result.stdout:
                return False, "不是有效的 CAB 文件，下载可能不完整", {}, []

            installed, missing, installed_files = [], [], []
            staged = Path(extract_dir) / "dlls"
            for dll_name, arches in dlls.items():
                for arch in arches:
                    arch_key = "x64" if cab_suffix.get(arch, arch) == "x64" else "x86"
                    target = targets.get(arch_key)
                    if not target:
                        continue  # 64-bit payload in a win32 prefix
                    suffix = cab_suffix.get(arch, arch)
                    cab_files = sorted(Path(extract_dir).glob(
                        f"*{dll_name.replace('.dll', '')}*{suffix}*.cab"))
                    stage_dir = staged / arch_key
                    stage_dir.mkdir(parents=True, exist_ok=True)
                    extracted = False
                    for cab_path in cab_files:
                        dll_result = subprocess.run(
                            ["cabextract", "-L", "-F", dll_name, str(cab_path),
                             "-d", str(stage_dir)],
                            capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60)
                        if dll_result.returncode == 0 and (stage_dir / dll_name).exists():
                            extracted = True
                            break
                    if extracted:
                        dst = target / dll_name
                        if not self._install_dll_file(stage_dir / dll_name, dst):
                            return False, f"写入 {dll_name} 失败", {}, []
                        installed_files.append(
                            self._windows_relative(bottle_path, dst))
                        installed.append(f"{dll_name}({arch_key})")
                    else:
                        missing.append(f"{dll_name}({arch_key})")

            if not installed:
                return False, f"未找到任何需要安装的 DLL 文件（缺少 {', '.join(missing)}）", {}, []
            if missing:
                return False, (f"以下 DLL 未能从 {redist_file} 中提取：{', '.join(missing)}\n"
                               f"安装不完整，相关程序仍会提示缺少 DLL。"), {}, []

            # winetricks overrides these as native ("native" alone: the DLL is
            # required, not optional like a native,builtin fallback).
            overrides = {self._dll_override_name(name): "native" for name in dlls}
            ok, err = self._set_dll_overrides(bottle_path, overrides, progress_callback)
            if not ok:
                return False, err, {}, []

            if progress_callback:
                progress_callback(100, 100, f"{gc_label} 安装完成 ({len(installed)} 个文件)")

            return True, "", overrides, installed_files

        except subprocess.TimeoutExpired:
            return False, "提取超时", {}, []
        except Exception as e:
            return False, str(e), {}, []
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

    def _install_direct(self, component_name: str, info: dict,
                        bottle_path: str,
                        progress_callback: Callable = None,
                        cancel_event=None) -> tuple:
        """Direct install from pre-cached files — bypasses winetricks entirely.

        For components like allfonts that have a "direct" flag, this method
        copies all pre-cached font files from the project-integrated
        components/ directory into the bottle's Fonts dir, then registers
        them in the Wine registry. No subprocess is spawned, so there is
        zero risk of hanging.
        """
        if progress_callback:
            progress_callback(0, 100, f"正在安装 {info['label']}...")

        check_cancel(cancel_event)
        fonts_dir = Path(bottle_path) / "drive_c" / "windows" / "Fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)

        cache_root = self.config.components_dir / "winetricks"
        if not cache_root.exists():
            return False, f"缓存目录不存在: {cache_root}", {}, []

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

        return True, "", {}, []

    @staticmethod
    def _cab_integrity_ok(path) -> bool:
        """Whether an MSI/CAB payload is structurally complete.

        A truncated preset MSI still looks like a valid container (msxml3 was
        shipped at 651KB instead of 1MB) but has no readable cabinets, so
        winetricks "installs" nothing while printing progress. `cabextract -t`
        walks the folders and catches exactly that.

        Files that are not MSI/CAB containers, or too large to test quickly,
        are accepted — this must never block an install on a false positive.
        """
        path = Path(path)
        try:
            size = path.stat().st_size
            with open(path, "rb") as handle:
                magic = handle.read(4)
        except OSError:
            return False
        if magic not in (b"\xd0\xcf\x11\xe0", b"MSCF") or size > 128 * 1024 * 1024:
            return True
        try:
            result = subprocess.run(
                ["cabextract", "-t", str(path)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120)
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return True  # cannot verify — don't block

    def _install_msi_assets(self, info: dict, bottle_path: str,
                            progress_callback: Callable = None) -> tuple:
        """Install DLLs straight out of a component's MSI.

        Wine 11's msiexec returns 84 ("summary information" read error) for the
        2005-era msxml3 MSI while still unpacking the files, so winetricks
        treats the verb as failed and skips its follow-up x64 step. Extracting
        the DLLs ourselves is deterministic and also repairs a prefix where a
        truncated preset MSI installed nothing.

        Returns (success, installed files).
        """
        spec = info.get("msi_assets")
        if not spec:
            return False, []
        preset_msi = (self.config.components_dir / "winetricks"
                      / spec["cache_dir"] / spec["file"])
        cache_msi = (self.config.cache_dir / "winetricks"
                     / spec["cache_dir"] / spec["file"])
        msi_path = cache_msi if cache_msi.exists() else preset_msi
        if not msi_path.exists():
            msi_path.parent.mkdir(parents=True, exist_ok=True)
            ok, _ = self._download_and_verify(
                spec["url"], str(msi_path), progress_callback, info["label"])
            if not ok:
                return False, []
        if not self._cab_integrity_ok(msi_path):
            with contextlib.suppress(OSError):
                msi_path.unlink()
            return False, []

        targets = self._system_dirs(bottle_path)
        extract_dir = tempfile.mkdtemp(prefix=f"winbridge_{info['label']}_msi_")
        installed_files = []
        try:
            subprocess.run(
                ["cabextract", "-q", "-L", "-d", extract_dir, str(msi_path)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180)
            members = {}
            for member in Path(extract_dir).iterdir():
                if not member.is_file():
                    continue
                name = member.name.lower()
                # MSI stores payloads with a GUID suffix: msxml3.dll.c8c0…
                base = name.split(".dll")[0] + ".dll" if ".dll" in name else name
                members.setdefault(base, []).append(member)

            for asset, arches in (spec.get("assets") or {}).items():
                for arch in arches:
                    arch_key = "x64" if arch in ("x64", "amd64") else "x86"
                    target_dir = targets.get(arch_key)
                    sources = [m for m in members.get(asset.lower(), [])
                               if self._payload_matches_arch(m, arch_key)]
                    if not target_dir or not sources:
                        continue
                    destination = target_dir / asset
                    if self._install_dll_file(sources[0], destination):
                        installed_files.append(
                            self._windows_relative(bottle_path, destination))
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)

        return bool(installed_files), installed_files

    @staticmethod
    def _sha256_file(path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _predownload_winetricks_files(self, info: dict, wt_cache: Path,
                                      progress_callback: Callable = None,
                                      cancel_event=None):
        """Fetch winetricks' big payloads with our parallel downloader.

        winetricks pulls these from the same Microsoft URLs over a single
        curl connection, which is markedly slower from CN. Downloading them
        here (sha256-verified) lets winetricks reuse its cache and skip its
        own download entirely.
        """
        for entry in info.get("winetricks_files", []) or []:
            destination = wt_cache / entry["cache_dir"] / entry["file"]
            expected = (entry.get("sha256") or "").lower()
            if destination.exists():
                if not expected or self._sha256_file(destination) == expected:
                    continue
                with contextlib.suppress(OSError):
                    os.remove(destination)

            destination.parent.mkdir(parents=True, exist_ok=True)
            ok, err = self._download_and_verify(
                entry["url"], str(destination), progress_callback,
                info["label"], cancel_event=cancel_event)
            if not ok:
                # Fall through: winetricks will download it itself.
                continue
            if expected and self._sha256_file(destination) != expected:
                # A mirror/proxy served something else — never leave it where
                # winetricks would pick it up without checking.
                with contextlib.suppress(OSError):
                    os.remove(destination)
                if progress_callback:
                    progress_callback(0, 100, f"{entry['file']} 校验失败，改用官方源重试...")

    def _install_via_winetricks(self, component_name: str, info: dict,
                                bottle_path: str,
                                progress_callback: Callable = None,
                                cancel_event=None) -> tuple:
        """Install a component via winetricks with real-time output."""
        check_cancel(cancel_event)
        if progress_callback:
            progress_callback(0, 100, f"正在安装 {info['label']}...")

        error_lines = []

        # winetricks drives Microsoft installers (dotnet40/ndp48, msxml, ...)
        # which crash with 0xe06d7363 when app-wide overrides are active.
        suspended = self._suspend_app_overrides(bottle_path)
        try:
            env = os.environ.copy()
            env["WINEPREFIX"] = bottle_path
            # Disable mono/gecko auto-install (wineboot tries to download
            # them on first run, which hangs in CN networks). Also suppress
            # wine debug output to reduce noise on the pipe.
            env["WINEDLLOVERRIDES"] = "mscoree=d;winemenubuilder.exe=d"
            env["WINEDEBUG"] = "-all,fixme-all"
            env["WINE"] = self.config.wine_path or "/usr/bin/wine"
            # Verbs that need their own override set (dotnet48 runs its
            # installer with fusion=b and must not have mscoree disabled).
            env.update(info.get("winetricks_env", {}))
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
                            if not self._cab_integrity_ok(preset_file):
                                # Truncated MSI/CAB (msxml3 shipped at 651KB
                                # instead of 1MB). Handing it to winetricks
                                # makes it "install" nothing while printing
                                # progress, so let winetricks download it.
                                if progress_callback:
                                    progress_callback(
                                        50, 100,
                                        f"预置文件 {preset_file.name} 校验失败，将重新下载")
                                continue
                            target_file = target_pkg / preset_file.name
                            if target_file.exists():
                                # Keep it only if it's the same size and still
                                # complete — a partial download or a broken
                                # preset must be replaced.
                                if (target_file.stat().st_size
                                        == preset_file.stat().st_size
                                        and self._cab_integrity_ok(target_file)):
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

            # Get winetricks' own large payloads through the parallel
            # downloader first, so it doesn't crawl them over one connection.
            self._predownload_winetricks_files(
                info, wt_cache, progress_callback, cancel_event)
            check_cancel(cancel_event)

            process = subprocess.Popen(
                # No stdbuf: its LD_PRELOAD libstdbuf.so leaks into every wine
                # child, and a 32-bit installer aborts with
                # "ld.so: … Assertion `new->l_relocated' failed". winetricks is
                # a bash script (each echo is a write syscall), so its own
                # progress still shows up promptly; wine's own output isn't
                # needed in real time.
                [self._winetricks_path, "-q", info["verb"]],
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

            idle_timeout = int(info.get("winetricks_idle_timeout", 300))
            idle_deadline = time.monotonic() + idle_timeout

            while True:
                if cancel_event is not None and cancel_event.is_set():
                    process.kill()
                    process.wait()
                    if progress_callback:
                        progress_callback(0, 100, f"{info['label']} 已取消")
                    return False, "已取消", {}, []
                if time.monotonic() > idle_deadline:
                    # No output for idle_timeout seconds — process is stuck
                    process.kill()
                    process.wait()
                    if progress_callback:
                        progress_callback(0, 100, f"⏰ {info['label']} 安装无响应，已终止")
                    return False, f"安装超时（{idle_timeout}秒无输出）", {}, []

                # Poll at most a second so the cancel button reacts promptly
                wait = 1.0 if cancel_event is not None else max(
                    0.0, idle_deadline - time.monotonic())
                r, _, _ = select.select([process.stdout], [], [], wait)
                if not r:
                    continue
                idle_deadline = time.monotonic() + idle_timeout
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

            # Components whose MSI winetricks cannot drive to completion (Wine
            # 11 returns 84 for the old msxml3 MSI) are repaired by extracting
            # the needed DLLs straight from the package. Present DLLs are what
            # actually matters for the user's apps, not msiexec's exit code.
            installed_files = []
            if info.get("msi_assets"):
                repaired, installed_files = self._install_msi_assets(
                    info, bottle_path, progress_callback)
                if repaired and not success:
                    success = True
                    error_log = ""

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
            # The overrides winetricks just wrote are read back so the bottle
            # metadata can mirror them.
            applied_overrides = {}
            if success:
                try:
                    from .wine import Wine
                    cfg = self.config
                    w = Wine(cfg.wine_path)
                    w.register_all_fonts(bottle_path)
                    applied_overrides = self._read_dll_overrides(w, bottle_path)
                except Exception:
                    pass  # font registration is best-effort, not fatal

            # winetricks' dotnet verbs switch the prefix to win7 to install;
            # the bottle's own Windows version is put back in `finally` so a
            # failed/cancelled install does not leave it at winxp/win7.

            return success, error_log, applied_overrides, installed_files

        except subprocess.TimeoutExpired:
            process.kill()
            if progress_callback:
                progress_callback(0, 100, f"⏰ {info['label']} 安装超时")
            return False, f"安装超时（600秒）", {}, []
        except Exception as e:
            err = str(e)
            if progress_callback:
                progress_callback(0, 100, f"安装失败: {err[:50]}")
            return False, err, {}, []
        finally:
            if info.get("restore_winver"):
                self._restore_windows_version(bottle_path)
            self._restore_dll_overrides(bottle_path, suspended)

    def _restore_windows_version(self, bottle_path: str):
        """Undo a winver change made by an installer (best effort)."""
        try:
            meta = json.loads(
                (Path(bottle_path) / "bottle.json").read_text("utf-8"))
        except (OSError, ValueError):
            return
        version = meta.get("windows_version")
        if not version:
            return
        try:
            from .wine import Wine
            Wine(self.config.wine_path).set_win_version(bottle_path, version)
        except Exception:
            pass

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