#!/bin/sh
# Build a static APT repository for Gitee raw / any HTTPS host.
#
# Layout:
#   apt-repo/
#     pool/main/winbridge_*.deb
#     dists/stable/main/binary-amd64/Packages{,.gz}
#     dists/stable/main/binary-i386/Packages{,.gz}
#     dists/stable/Release
#     dists/stable/InRelease        (when signed)
#     dists/stable/Release.gpg      (when signed)
#     public.key                    (when signed)
#
# Usage:
#   packaging/build-apt-repo.sh                 # use debian/winbridge_*.deb
#   packaging/build-apt-repo.sh path/to/a.deb   # explicit deb(s)
#   WINBRIDGE_GPG_KEY=<key-id> packaging/build-apt-repo.sh
#   APT_REPO_DIR=/srv/winbridge-apt packaging/build-apt-repo.sh
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
REPO=${APT_REPO_DIR:-"$ROOT/apt-repo"}
POOL="$REPO/pool/main"
DISTS="$REPO/dists/stable"

if [ "$#" -gt 0 ]; then
    DEBS="$*"
else
    DEBS=$(ls "$ROOT"/debian/winbridge_*.deb 2>/dev/null || true)
fi
if [ -z "$DEBS" ]; then
    echo "没有找到 deb。先运行 packaging/build-deb.sh，或把 deb 路径作为参数传入。" >&2
    exit 1
fi

for deb in $DEBS; do
    case "$deb" in
        /*) absolute="$deb" ;;
        *) absolute="$(pwd)/$deb" ;;
    esac
    if [ ! -f "$absolute" ]; then
        echo "找不到文件: $deb" >&2
        exit 1
    fi
    NORMALIZED_DEBS="${NORMALIZED_DEBS:-} $absolute"
done
DEBS="$NORMALIZED_DEBS"

echo "==> 构建 APT 仓库: $REPO"
mkdir -p "$POOL" \
         "$DISTS/main/binary-amd64" \
         "$DISTS/main/binary-i386"

for deb in $DEBS; do
    cp -f "$deb" "$POOL/"
    echo "    + $(basename "$deb")"
done

# One-liner installer lives next to the repository files so users can fetch
# it from the same base URL.
if [ -f "$ROOT/packaging/install.sh" ]; then
    cp -f "$ROOT/packaging/install.sh" "$REPO/install.sh"
    chmod 0755 "$REPO/install.sh"
    echo "    + install.sh"
fi

# Package index. `Filename` must be relative to the repository root, so run
# from $REPO and point at pool/main.
cd "$REPO"
if command -v apt-ftparchive >/dev/null 2>&1; then
    apt-ftparchive packages pool/main > "$DISTS/main/binary-amd64/Packages"
elif command -v dpkg-scanpackages >/dev/null 2>&1; then
    dpkg-scanpackages --multiversion pool/main \
        > "$DISTS/main/binary-amd64/Packages"
else
    echo "需要 apt-ftparchive（apt-utils）或 dpkg-scanpackages（dpkg-dev）。" >&2
    exit 1
fi

# The package is Architecture: all; both architectures can share the index.
for arch in amd64 i386; do
    if [ "$arch" != "amd64" ]; then
        cp -f "$DISTS/main/binary-amd64/Packages" \
              "$DISTS/main/binary-$arch/Packages"
    fi
    gzip -9c "$DISTS/main/binary-$arch/Packages" \
        > "$DISTS/main/binary-$arch/Packages.gz"
done

# Never leave previous index/signature files where apt-ftparchive would
# checksum them (including Release itself) as part of the new Release.
rm -f "$DISTS/Release" "$DISTS/InRelease" "$DISTS/Release.gpg" \
      "$REPO/public.key"
REL_TMP="$REPO/.Release.tmp"

apt-ftparchive \
    -o APT::FTPArchive::Release::Origin=WinBridge \
    -o APT::FTPArchive::Release::Label=WinBridge \
    -o APT::FTPArchive::Release::Suite=stable \
    -o APT::FTPArchive::Release::Codename=stable \
    -o APT::FTPArchive::Release::Architectures="amd64 i386" \
    -o APT::FTPArchive::Release::Components=main \
    -o APT::FTPArchive::Release::Description="WinBridge APT repository" \
    release dists/stable > "$REL_TMP"
mv "$REL_TMP" "$DISTS/Release"

if [ -n "${WINBRIDGE_GPG_KEY:-}" ]; then
    gpg --batch --yes --default-key "$WINBRIDGE_GPG_KEY" \
        --clearsign -o "$DISTS/InRelease" "$DISTS/Release"
    gpg --batch --yes --default-key "$WINBRIDGE_GPG_KEY" \
        -abs -o "$DISTS/Release.gpg" "$DISTS/Release"
    gpg --batch --yes --default-key "$WINBRIDGE_GPG_KEY" \
        --armor --export "$WINBRIDGE_GPG_KEY" > "$REPO/public.key"
    echo "==> 已用 GPG 密钥 $WINBRIDGE_GPG_KEY 签名"
else
    echo "==> 未签名（未设置 WINBRIDGE_GPG_KEY）"
    echo "    测试可先用 [trusted=yes]，正式发布请生成并配置 GPG 密钥。"
fi

echo "==> 完成"
echo "    仓库目录: $REPO"
if [ -f "$DISTS/InRelease" ]; then
    echo "    源: deb [signed-by=/usr/share/keyrings/winbridge-archive-keyring.gpg] https://gitee.com/zuimeideshijie/WinBidge/raw/apt-repo/ stable main"
else
    echo "    源: deb [trusted=yes] https://gitee.com/zuimeideshijie/WinBidge/raw/apt-repo/ stable main"
fi
echo "    Gitee 仓库名是 WinBidge（human_name 才是 WinBridge），地址不能写成 WinBridge。"