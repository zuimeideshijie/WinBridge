#!/usr/bin/env bash
# Build and install the WinBridge flatpak sandbox runtime.
#
# It is a deliberately tiny flatpak app: the payload is nothing but bash. Its
# only job is to hand Wine the runtime's own graphics stack (Mesa/glvnd/
# Vulkan) while the prefix, the Wine binary and every program stay on the host.
#
# Usage:
#   bash packaging/build-sandbox-runtime.sh            # build + install (user)
#   bash packaging/build-sandbox-runtime.sh --uninstall
#
# Requirements: flatpak, and the org.freedesktop.Platform runtime with its
# Compat.i386 / GL32 extensions (see the checks below).
set -euo pipefail

APP_ID="io.github.zuimeideshijie.WinBridgeRuntime"
ARCH="x86_64"
BASE_RUNTIME="org.freedesktop.Platform"

die() { echo "错误: $*" >&2; exit 1; }

command -v flatpak >/dev/null || die "未安装 flatpak"

if [ "${1:-}" = "--uninstall" ]; then
    flatpak uninstall --user --noninteractive -y "$APP_ID" || true
    echo "已卸载 $APP_ID"
    exit 0
fi

# Newest installed runtime branch (25.08, 24.08 …)
BRANCH="$(flatpak list --runtime --columns=ref 2>/dev/null \
    | sed -n "s|^${BASE_RUNTIME}/${ARCH}/||p" | sort -V | tail -1)"
[ -n "$BRANCH" ] || die "未找到 ${BASE_RUNTIME} 运行时，请先安装：flatpak install ${BASE_RUNTIME}"

for ext in "${BASE_RUNTIME}.Compat.i386" "${BASE_RUNTIME}.GL32.default"; do
    if ! flatpak list --runtime --columns=ref | grep -q "^${ext}/"; then
        echo "提示: 缺少 ${ext}，沙箱里跑不了 32 位程序，正在安装…"
        flatpak install --noninteractive -y "${ext}/${ARCH}/${BRANCH}" || \
            die "安装 ${ext} 失败"
    fi
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
# The repo has to outlive the script: it stays the app's origin, so keep it in
# the user data dir instead of /tmp.
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/winbridge/sandbox-runtime"
REPO="$DATA_DIR/repo"
BUILD="$WORK/build"
rm -rf "$REPO"
mkdir -p "$REPO" "$BUILD/files/lib/GL32" "$BUILD/files/lib/i386-linux-gnu"

cat > "$BUILD/metadata" <<EOF
[Application]
name=${APP_ID}
runtime=${BASE_RUNTIME}/${ARCH}/${BRANCH}
command=bash
EOF

# build-finish writes the [Context] permissions and marks the dir final.
# multiarch is what lets 32-bit Wine run at all; devel/per-app-dev-shm match
# what Bottles needs for the same job.
flatpak build-finish "$BUILD" \
    --command=bash \
    --share=network --share=ipc \
    --socket=x11 --socket=wayland --socket=pulseaudio \
    --device=all \
    --allow=devel --allow=multiarch --allow=per-app-dev-shm >/dev/null

# The two empty dirs above are mount points for the i386/GL32 extensions.
cat >> "$BUILD/metadata" <<EOF

[Extension ${BASE_RUNTIME}.Compat.i386]
directory=lib/i386-linux-gnu
version=${BRANCH}

[Extension ${BASE_RUNTIME}.GL32.default]
directory=lib/GL32
version=${BRANCH}
subdirectories=true
EOF

flatpak build-export "$REPO" "$BUILD" >/dev/null
flatpak build-update-repo "$REPO" >/dev/null

flatpak remote-delete --user --force winbridge-sandbox >/dev/null 2>&1 || true
flatpak remote-add --user --no-gpg-verify winbridge-sandbox "$REPO" >/dev/null
# Reinstalling from scratch keeps this script idempotent: the app holds no
# state, and a leftover install would block `flatpak install` with "already
# installed from remote …".
if flatpak list --app --columns=ref | grep -q "^${APP_ID}/"; then
    flatpak uninstall --user --noninteractive -y "$APP_ID" >/dev/null 2>&1 || \
        flatpak uninstall --noninteractive -y "$APP_ID" >/dev/null 2>&1 || true
fi
flatpak install --user --noninteractive -y winbridge-sandbox "$APP_ID" 2>&1 | tail -3

echo
echo "已安装沙箱运行时: $APP_ID (runtime ${BASE_RUNTIME}/${BRANCH})"
echo "在 WinBridge 新建容器时即可选择「flatpak 沙箱」。"