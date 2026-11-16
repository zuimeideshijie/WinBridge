#!/bin/sh
# WinBridge APT installer.
#
# Usage:
#   sudo bash install.sh
#   sudo bash install.sh --base https://example.com/winbridge/
#
# The script is safe to run again: it rewrites the source file, refreshes the
# index, installs/upgrades winbridge and verifies the installed version.
set -eu

# Every base mirrors the same `apt-repo` branch. Gitee is the default source;
# if it is unreachable the same files are tried through the GitHub mirror chain
# (gh-proxy prefixes, same list WinBridge uses for downloads). The script picks
# the first base that serves the root `Packages` (flat archive), so one slow
# mirror does not block users.
GITHUB_RAW="https://raw.githubusercontent.com/zuimeideshijie/WinBridge/apt-repo/"
DEFAULT_BASES="
https://gitee.com/zuimeideshijie/WinBidge/raw/apt-repo/
https://gh-proxy.org/$GITHUB_RAW
https://v6.gh-proxy.org/$GITHUB_RAW
https://gh-proxy.com/$GITHUB_RAW
https://ghproxy.net/$GITHUB_RAW
$GITHUB_RAW
"
BASE_URL="${WINBRIDGE_APT_BASE:-}"
BASE_URL="${BASE_URL%/}"
CHECK_ONLY="${CHECK_ONLY:-0}"
SOURCE_FILE=/etc/apt/sources.list.d/winbridge.list
KEYRING=/usr/share/keyrings/winbridge-archive-keyring.gpg

usage() {
    cat <<EOF
用法: sudo bash install.sh [--base URL]

  --base URL   使用自定义 APT 源根地址（默认 Gitee，失败再试 GitHub 镜像链）
  --check      只探测各镜像是否已同步，打印可用源后退出（不安装）
  -h, --help   显示帮助
EOF
}

log()  { printf '[WinBridge] %s\n' "$*"; }
warn() { printf '[WinBridge] 警告: %s\n' "$*" >&2; }
die()  { printf '[WinBridge] 错误: %s\n' "$*" >&2; exit 1; }

while [ "$#" -gt 0 ]; do
    case "$1" in
        --base)
            [ "$#" -ge 2 ] || die "--base 缺少 URL"
            BASE_URL="${2%/}"
            shift 2
            ;;
        --check)
            CHECK_ONLY=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "未知参数: $1"
            ;;
    esac
done

# ---- environment ---------------------------------------------------------
[ "$(uname -s)" = "Linux" ] || die "只支持 Linux"

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-} ${ID_LIKE:-}" in
        *debian*|*ubuntu*) ;;
        *) warn "当前发行版不是 Debian/Ubuntu 系，仍将尝试使用 apt" ;;
    esac
fi

command -v apt-get >/dev/null 2>&1 || die "找不到 apt-get，当前系统不是 deb 系"
command -v dpkg >/dev/null 2>&1 || die "找不到 dpkg"
command -v dpkg-query >/dev/null 2>&1 || die "找不到 dpkg-query"

if command -v curl >/dev/null 2>&1; then
    HTTP=curl
elif command -v wget >/dev/null 2>&1; then
    HTTP=wget
else
    die "需要 curl 或 wget 下载仓库文件"
fi

ARCH=$(dpkg --print-architecture)
case "$ARCH" in
    amd64|i386) ;;
    *) die "当前仓库只提供 amd64/i386 索引，检测到 $ARCH" ;;
esac

if [ "$CHECK_ONLY" = "1" ]; then
    SUDO=
elif [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "需要 root 或 sudo 权限"
    sudo -v || die "sudo 授权失败"
    SUDO=sudo
else
    SUDO=
fi

AVAIL_KB=$(df -Pk /usr 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "${AVAIL_KB:-}" ] && [ "$AVAIL_KB" -lt 51200 ]; then
    warn "/usr 可用空间不足 50MB，安装可能失败"
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

download() {
    if [ "$HTTP" = "curl" ]; then
        curl -fsSL --connect-timeout 10 --max-time 60 "$1" -o "$2"
    else
        wget -q -T 30 -O "$2" "$1"
    fi
}

# Flat archive: <base>/Packages is the only index we depend on. A dists-style
# repo needs Release, and every mirror caches each path separately — a stale
# Release next to a fresh Packages makes apt abort with "Hash 校验和不符".
if [ -n "$BASE_URL" ]; then
    CANDIDATES="$BASE_URL"
else
    CANDIDATES="$DEFAULT_BASES"
fi

CHOSEN=""
for candidate in $CANDIDATES; do
    candidate="${candidate%/}"
    log "检查源: $candidate"
    if download "$candidate/Packages" "$TMP_DIR/Packages" 2>/dev/null \
            && grep -q '^Package: winbridge' "$TMP_DIR/Packages"; then
        CHOSEN="$candidate"
        break
    fi
    warn "该源暂不可用（可能还没同步），尝试下一个"
done

[ -n "$CHOSEN" ] || die "所有源都还没有可用的 Packages 索引。
可能是刚发布、镜像仍在同步（通常几分钟到一小时）。请稍后重试，
或用 --base 指定一个自建源地址。"
BASE_URL="$CHOSEN"
log "使用源: $BASE_URL"
if [ "$CHECK_ONLY" = "1" ]; then
    log "检测结果: $BASE_URL （索引含 $(grep -c '^Package: winbridge' "$TMP_DIR/Packages") 个 winbridge 条目）"
    exit 0
fi

OLD_VERSION=$(dpkg-query -W -f='${Version}' winbridge 2>/dev/null || true)
if [ -n "$OLD_VERSION" ]; then
    log "检测到已安装版本: $OLD_VERSION"
else
    log "未检测到已安装的 winbridge"
fi

# ---- source + optional signature ----------------------------------------
SIGNED=0
if download "$BASE_URL/public.key" "$TMP_DIR/public.key" 2>/dev/null \
        && [ -s "$TMP_DIR/public.key" ] \
        && grep -q 'BEGIN PGP PUBLIC KEY BLOCK' "$TMP_DIR/public.key"; then
    if command -v gpg >/dev/null 2>&1; then
        log "检测到签名公钥，使用 signed-by 源"
        gpg --batch --yes --dearmor < "$TMP_DIR/public.key" \
            > "$TMP_DIR/keyring.gpg" \
            || die "GPG 公钥解析失败"
        $SUDO install -d -m 0755 "$(dirname "$KEYRING")"
        $SUDO install -m 0644 "$TMP_DIR/keyring.gpg" "$KEYRING"
        SIGNED=1
    else
        warn "仓库提供了 public.key，但系统没有 gpg，暂用 trusted=yes"
        warn "建议安装 gnupg 后重新运行本脚本"
    fi
else
    warn "仓库当前未提供 public.key，使用 trusted=yes（仅测试源）"
fi

if [ "$SIGNED" -eq 1 ]; then
    SOURCE_LINE="deb [signed-by=$KEYRING] $BASE_URL ./"
else
    SOURCE_LINE="deb [trusted=yes] $BASE_URL ./"
fi

printf '%s\n' "$SOURCE_LINE" | $SUDO tee "$SOURCE_FILE" >/dev/null
log "已写入源: $SOURCE_FILE"

# Only refresh this source; unrelated third-party repos should not break the
# installer.
log "更新 APT 索引..."
if ! $SUDO apt-get update \
        -o Dir::Etc::sourcelist="$SOURCE_FILE" \
        -o Dir::Etc::sourceparts="-" \
        -o APT::Get::List-Cleanup="0" \
        -o Acquire::http::No-Cache=true \
        -o Acquire::https::No-Cache=true; then
    die "apt-get update 失败，请检查网络、代理或 $SOURCE_FILE"
fi

# ---- install -------------------------------------------------------------
log "安装/升级 winbridge..."
if ! $SUDO env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y winbridge; then
    die "apt-get install winbridge 失败"
fi

# ---- verify --------------------------------------------------------------
STATUS=$(dpkg-query -W -f='${Status}' winbridge 2>/dev/null || true)
VERSION=$(dpkg-query -W -f='${Version}' winbridge 2>/dev/null || true)
[ "$STATUS" = "install ok installed" ] || die "安装后状态异常: ${STATUS:-未知}"
[ -n "$VERSION" ] || die "无法读取已安装版本"
[ -x /usr/bin/winbridge ] || die "缺少 /usr/bin/winbridge"
[ -f /usr/lib/winbridge/main.py ] || die "缺少 /usr/lib/winbridge/main.py"

CODE_VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' \
    /usr/lib/winbridge/winbridge/__init__.py 2>/dev/null | head -n 1)
[ -n "$CODE_VERSION" ] || die "无法读取安装版代码版本"
if [ "$CODE_VERSION" != "$VERSION" ]; then
    warn "deb 版本 $VERSION 与代码版本 $CODE_VERSION 不一致"
fi

log "安装完成: winbridge $VERSION"
log "源: $BASE_URL"
log "启动命令: winbridge"