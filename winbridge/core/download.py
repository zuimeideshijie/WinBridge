"""Component installer using winetricks for Wine components."""

import os
import re
import tarfile
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional

from .config import Config


# Winetricks verb → display info mapping
# Components with "gitcode" use direct GitCode mirror downloads;
# components without it fall back to winetricks.
COMPONENT_MAP = {
    "vcrun2019": {
        "label": "Visual C++ 2019",
        "description": "Microsoft Visual C++ 2015-2019 Redistributable",
        "verb": "vcrun2019",
        "gitcode": {
            "repo": "https://gitcode.com/gh_mirrors/vc/vcredist.git",
            "version": "0.105.0",
            "file": "VisualCppRedist_AIO_x86_x64.exe",
            "install_args": "/ai9 /quiet /norestart",
        },
    },
    "vcrun2022": {
        "label": "Visual C++ 2022",
        "description": "Microsoft Visual C++ 2022 Redistributable",
        "verb": "vcrun2022",
        "gitcode": {
            "repo": "https://gitcode.com/gh_mirrors/vc/vcredist.git",
            "version": "0.105.0",
            "file": "VisualCppRedist_AIO_x86_x64.exe",
            "install_args": "/ai9 /quiet /norestart",
        },
    },
    "dotnet48": {
        "label": ".NET Framework 4.8",
        "description": "Microsoft .NET Framework 4.8",
        "verb": "dotnet48",
        "gitcode": {
            "repo": "https://gitcode.com/open-source-toolkit/769c4.git",
            "version": "4.8",
            "type": "zip",
            "installer_exe": "ndp48-x86-x64-allos-enu.exe",
            "install_args": "/quiet /norestart",
        },
    },
    "dxvk": {
        "label": "DXVK",
        "description": "DirectX 9/10/11 to Vulkan translation layer",
        "verb": "dxvk",
        "gitcode": {
            "repo": "https://gitcode.com/gh_mirrors/dx/dxvk.git",
            "version": "2.7.1",
            "setup_script": "setup_dxvk.sh",
        },
    },
    "vkd3d": {
        "label": "VKD3D",
        "description": "DirectX 12 to Vulkan translation layer",
        "verb": "vkd3d",
        "gitcode": {
            "repo": "https://gitcode.com/gh_mirrors/vk/vkd3d-proton.git",
            "version": "2.14.1",
            "setup_script": "setup_vkd3d_proton.sh",
        },
    },
    "faudio": {
        "label": "FAudio",
        "description": "XAudio/X3DAudio reimplementation",
        "verb": "faudio",
        "gitcode": {
            "repo": "https://gitcode.com/gh_mirrors/fa/FAudio.git",
            "version": "20.07",
            "setup_script": "wine_setup_faudio.sh",
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
    },
    "corefonts": {
        "label": "Core Fonts",
        "description": "Microsoft core web fonts (Arial, Times, etc.)",
        "verb": "corefonts",
        "gitcode": {
            "url": "https://gitcode.com/gh_mirrors/co/corefonts/-/archive/master/corefonts.zip",
            "version": "latest",
            "setup_script": "",
        },
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
    },
    "directmusic": {
        "label": "DirectMusic",
        "description": "DirectMusic API",
        "verb": "directmusic",
        "gitcode": {
            "label": "DirectMusic",
            "version": "apr2006",
            "type": "directx_redist",
            "redist_file": "directx_apr2006_redist.exe",
            "redist_url": "https://web.archive.org/web/20100920035904/https://download.microsoft.com/download/3/9/7/3972f80c-5711-4e14-9483-959d48a2d03b/directx_apr2006_redist.exe",
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
            "redist_url": "https://files.holarse-linuxgaming.de/mirrors/microsoft/directx_Jun2010_redist.exe",
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
            "redist_url": "https://files.holarse-linuxgaming.de/mirrors/microsoft/directx_Jun2010_redist.exe",
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

    def _find_winetricks(self) -> str:
        """Find the winetricks binary on the system."""
        # Check common locations
        candidates = [
            "winetricks",
            # Project-integrated winetricks
            str(Path(__file__).resolve().parent.parent.parent / "winetricks" / "winetricks"),
            "/usr/bin/winetricks",
            "/usr/local/bin/winetricks",
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

        # Use custom GitCode installer if configured
        if "gitcode" in info:
            gc = info["gitcode"]
            install_type = gc.get("type", "")
            # DirectX redist → extract DLLs directly
            if install_type == "directx_redist":
                return self._install_directx_redist(component_name, info, bottle_path, progress_callback)
            # tarball + setup script → _install_from_gitcode (DXVK/VKD3D)
            if "setup_script" in gc:
                return self._install_from_gitcode(component_name, info, bottle_path, progress_callback)
            # .exe or .zip installer → _install_gitcode_exe (vcrun, dotnet48)
            return self._install_gitcode_exe(component_name, info, bottle_path, progress_callback)

        # Fallback to winetricks for other components
        return self._install_via_winetricks(component_name, info, bottle_path, progress_callback)

    def _git_clone(self, repo: str, dest: str,
                   progress_callback: Callable = None,
                   label: str = "") -> tuple:
        """Clone a git repo (shallow) to dest. Returns (success, error)."""
        if progress_callback:
            progress_callback(0, 100, f"📥 正在克隆 {label}...")
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo, dest],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                return False, f"git clone 失败: {result.stderr.strip()[:200]}"
            if progress_callback:
                progress_callback(50, 100, f"✅ {label} 克隆完成")
            return True, ""
        except subprocess.TimeoutExpired:
            return False, "git clone 超时（300秒）"
        except Exception as e:
            return False, f"git clone 异常: {e}"

    def _ensure_cloned(self, gc: dict, component_name: str,
                       progress_callback: Callable = None,
                       label: str = "") -> tuple:
        """Ensure the gitcode repo is cloned to cache. Returns (clone_path, error)."""
        repo = gc["repo"]
        cache_dir = self.config.components_dir / component_name
        clone_path = str(cache_dir / "repo")

        # Already cloned? Try to update
        if Path(clone_path).exists() and (Path(clone_path) / ".git").exists():
            return clone_path, ""

        cache_dir.mkdir(parents=True, exist_ok=True)
        ok, err = self._git_clone(repo, clone_path, progress_callback, label)
        if not ok:
            return None, err
        return clone_path, ""

    def _download_file(self, url: str, dest_path: str,
                       progress_callback: Callable = None,
                       label: str = "") -> tuple:
        """Download a file with progress reporting.

        Returns (success: bool, error: str).
        """
        if progress_callback:
            progress_callback(0, 100, f"📥 正在下载 {label}...")

        try:
            def report(block_count, block_size, total_size):
                if progress_callback and total_size > 0:
                    pct = min(int(block_count * block_size * 100 / total_size), 99)
                    downloaded = block_count * block_size / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    progress_callback(pct, 100,
                        f"📥 正在下载 {label}  ({downloaded:.1f}/{total_mb:.1f} MB)")

            urllib.request.urlretrieve(url, dest_path, reporthook=report)
            return True, ""
        except Exception as e:
            return False, f"下载失败: {e}"

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
                progress_callback(0, 100, f"⚠ 文件损坏，正在重新下载 {label}...")
            try:
                os.remove(dest_path)
            except OSError:
                pass

            if attempt < retries:
                continue

            return False, f"文件完整性验证失败 (已重试{retries}次): {msg}"

        return False, "未知错误"

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

        extract_dir = None
        try:
            if setup_type == "zip" and exe_name:
                # Extract .zip to find the installer .exe
                if progress_callback:
                    progress_callback(60, 100, f"📦 正在解压 {label}...")

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
                progress_callback(80, 100, f"⚙ 正在安装 {label} 到容器...")

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
                progress_callback(100, 100, f"✅ {label} {version} 安装完成")

            return True, ""

        except subprocess.TimeoutExpired:
            return False, f"安装超时（600秒）"
        except Exception as e:
            return False, str(e)
        finally:
            if extract_dir:
                import shutil
                shutil.rmtree(extract_dir, ignore_errors=True)

    def _install_from_gitcode(self, component_name: str, info: dict,
                              bottle_path: str,
                              progress_callback: Callable = None) -> tuple:
        """Install a component (DXVK/VKD3D) from a GitCode release tarball."""
        gc = info["gitcode"]
        label = info["label"]
        version = gc["version"]
        url = gc["url"]
        setup_script = gc["setup_script"]

        if progress_callback:
            progress_callback(0, 100, f"准备安装 {label} {version}...")

        # Clone the gitcode repo to cache
        clone_path, err = self._ensure_cloned(gc, component_name, progress_callback, label)
        if not clone_path:
            return False, err

        if progress_callback:
            progress_callback(60, 100, f"📦 正在准备 {label}...")

        # The cloned repo IS the extracted content; find setup script
        setup_path = Path(clone_path) / setup_script
        if not setup_path.exists():
            # Search recursively
            matches = list(Path(clone_path).rglob(setup_script))
            if not matches:
                return False, f"在仓库中未找到安装脚本 {setup_script}"
            setup_path = matches[0]

        try:
            if progress_callback:
                progress_callback(80, 100, f"⚙ 正在安装 {label} 到容器...")

            # Run the setup script
            result = subprocess.run(
                ["bash", str(setup_path), "install", bottle_path],
                capture_output=True, text=True, timeout=300
            )

            if result.returncode != 0:
                err_out = result.stderr.strip() or result.stdout.strip() or "安装脚本执行失败"
                return False, err_out

            if progress_callback:
                progress_callback(100, 100, f"✅ {label} {version} 安装完成")

            return True, ""

        except subprocess.TimeoutExpired:
            return False, f"安装超时（300秒）"
        except Exception as e:
            return False, str(e)

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

        cache_dir = self.config.components_dir / component_name
        cache_dir.mkdir(parents=True, exist_ok=True)
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
            progress_callback(50, 100, f"📦 正在提取 {gc_label}...")

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
                progress_callback(100, 100, f"✅ {gc_label} 安装完成 ({len(installed)} 个文件)")

            return True, ""

        except subprocess.TimeoutExpired:
            return False, f"提取超时"
        except Exception as e:
            return False, str(e)
        finally:
            import shutil
            shutil.rmtree(extract_dir, ignore_errors=True)

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
            env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
            env["WINE"] = "/usr/bin/wine"

            process = subprocess.Popen(
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
                speed_str = ""
                for match in speed_pattern.finditer(line):
                    val, unit = match.groups()
                    val_clean = val.replace(",", ".")
                    unit_clean = unit.upper() if unit else ""
                    if unit_clean:
                        speed_str = f" ⚡{val_clean} {unit_clean}B/s"
                    else:
                        speed_str = f" ⚡{val_clean} B/s"

                if "downloading" in lower or "download" in lower:
                    if progress_callback:
                        progress_callback(50, 100, f"📥{speed_str} {line[:60]}")
                elif "installing" in lower or "extracting" in lower:
                    if progress_callback:
                        progress_callback(70, 100, f"📦{speed_str} {line[:60]}")
                elif "executing" in lower or "running" in lower:
                    if progress_callback:
                        progress_callback(80, 100, f"⚙{speed_str} {line[:60]}")
                elif "warning" in lower or "fixme" in lower:
                    pass
                elif progress_callback:
                    prefix = f"📥{speed_str}" if speed_str else "📥 "
                    progress_callback(50, 100, f"{prefix}{line[:60]}")

                # Collect error lines for the final log
                if is_error_line(line):
                    error_lines.append(line.strip())

            while True:
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
                    progress_callback(100, 100, f"✅ {info['label']} 安装完成")
                else:
                    progress_callback(0, 100, f"❌ {info['label']} 安装失败")

            return success, error_log

        except subprocess.TimeoutExpired:
            process.kill()
            if progress_callback:
                progress_callback(0, 100, f"⏰ {info['label']} 安装超时")
            return False, f"安装超时（600秒）"
        except Exception as e:
            err = str(e)
            if progress_callback:
                progress_callback(0, 100, f"❌ 安装失败: {err[:50]}")
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