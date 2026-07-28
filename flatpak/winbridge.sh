#!/bin/bash
# WinBridge - 启动脚本（支持 Flatpak 和直接运行）

# 检测是否运行在 Flatpak 环境中
if [ -d "/app/lib/winbridge" ]; then
    # Flatpak 模式
    SCRIPT_DIR="/app/lib/winbridge"
    PYTHON_EXTRA="/app/lib/python3.12/site-packages"
else
    # 直接运行模式（从项目目录启动）
    SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    PYTHON_EXTRA=""
fi

export PYTHONPATH="$SCRIPT_DIR:$PYTHON_EXTRA:$PYTHONPATH"
export WINETRICKS_PATH="$SCRIPT_DIR/winetricks/winetricks"

# 确保数据目录存在
mkdir -p "$HOME/.local/share/winbridge/bottles"
mkdir -p "$HOME/.config/winbridge"
mkdir -p "$HOME/.cache/winetricks"

cd "$SCRIPT_DIR"
exec python3 "$SCRIPT_DIR/main.py"
