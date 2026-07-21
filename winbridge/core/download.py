"""Component installer using winetricks for Wine components."""

import os
import re
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from .config import Config


# Winetricks verb → display info mapping
COMPONENT_MAP = {
    "vcrun2019": {
        "label": "Visual C++ 2019",
        "description": "Microsoft Visual C++ 2015-2019 Redistributable",
        "verb": "vcrun2019",
    },
    "vcrun2022": {
        "label": "Visual C++ 2022",
        "description": "Microsoft Visual C++ 2022 Redistributable",
        "verb": "vcrun2022",
    },
    "dotnet48": {
        "label": ".NET Framework 4.8",
        "description": "Microsoft .NET Framework 4.8",
        "verb": "dotnet48",
    },
    "dxvk": {
        "label": "DXVK",
        "description": "DirectX 9/10/11 to Vulkan translation layer",
        "verb": "dxvk",
    },
    "vkd3d": {
        "label": "VKD3D",
        "description": "DirectX 12 to Vulkan translation layer",
        "verb": "vkd3d",
    },
    "faudio": {
        "label": "FAudio",
        "description": "XAudio/X3DAudio reimplementation",
        "verb": "faudio",
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
    },
    "d3dx9": {
        "label": "DirectX 9",
        "description": "DirectX 9 runtime libraries",
        "verb": "d3dx9",
    },
    "d3dx11_43": {
        "label": "DirectX 11",
        "description": "DirectX 11 runtime libraries",
        "verb": "d3dx11_43",
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
            "/usr/bin/winetricks",
            "/usr/local/bin/winetricks",
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
                progress_callback: Callable = None) -> bool:
        """Install a component via winetricks with real-time output."""
        info = COMPONENT_MAP.get(component_name)
        if not info:
            return False

        if progress_callback:
            progress_callback(0, 100, f"正在安装 {info['label']}...")

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

            if progress_callback:
                if process.returncode == 0:
                    progress_callback(100, 100, f"✅ {info['label']} 安装完成")
                else:
                    progress_callback(0, 100, f"❌ {info['label']} 安装失败")

            return process.returncode == 0

        except subprocess.TimeoutExpired:
            process.kill()
            if progress_callback:
                progress_callback(0, 100, f"⏰ {info['label']} 安装超时")
            return False
        except Exception as e:
            if progress_callback:
                progress_callback(0, 100, f"❌ 安装失败: {str(e)[:50]}")
            return False

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