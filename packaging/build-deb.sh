#!/bin/sh
# Build a .deb for WinBridge without debhelper.
#   ./packaging/build-deb.sh          -> debian/winbridge_<version>_all.deb
set -eu

cd "$(dirname "$0")/.."
ROOT=$(pwd)
VERSION=$(python3 -c "import re,pathlib;print(re.search(r'\"([^\"]+)\"', pathlib.Path('winbridge/__init__.py').read_text().split('__version__')[1]).group(1))")
NAME=winbridge
BUILD="$ROOT/build/deb"
PKG="$BUILD/${NAME}_${VERSION}_all"
OUT="$ROOT/debian"

echo "==> 打包 $NAME $VERSION"
rm -rf "$BUILD"
mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/lib/$NAME" \
         "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/256x256/apps" \
         "$PKG/usr/share/doc/$NAME"

# --- payload -------------------------------------------------------------
cp "$ROOT/main.py" "$PKG/usr/lib/$NAME/"
mkdir -p "$PKG/usr/lib/$NAME/winbridge"
cp "$ROOT/winbridge/__init__.py" "$PKG/usr/lib/$NAME/winbridge/"
cp -r "$ROOT/winbridge/core" "$ROOT/winbridge/ui" "$ROOT/winbridge/resources" \
      "$PKG/usr/lib/$NAME/winbridge/"
find "$PKG/usr/lib/$NAME" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$PKG/usr/lib/$NAME" -name '*.pyc' -delete

# Bundled winetricks (ComponentManager looks for winetricks/src/winetricks)
mkdir -p "$PKG/usr/lib/$NAME/winetricks"
cp -r "$ROOT/winetricks/src" "$ROOT/winetricks/metadata" "$ROOT/winetricks/files" \
      "$PKG/usr/lib/$NAME/winetricks/"
cp "$ROOT/winetricks/COPYING" "$PKG/usr/lib/$NAME/winetricks/"
find "$PKG/usr/lib/$NAME/winetricks" -name '__pycache__' -type d -prune -exec rm -rf {} +

# --- launcher, desktop entry, icon --------------------------------------
cat > "$PKG/usr/bin/$NAME" <<'LAUNCHER'
#!/bin/sh
exec python3 /usr/lib/winbridge/main.py "$@"
LAUNCHER
chmod 0755 "$PKG/usr/bin/$NAME"

cat > "$PKG/usr/share/applications/$NAME.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=WinBridge
Name[zh_CN]=WinBridge
GenericName=Wine Prefix Manager
GenericName[zh_CN]=Wine 容器管理器
Comment=Manage Wine bottles and Windows applications
Comment[zh_CN]=管理 Wine 容器与 Windows 应用
Exec=winbridge
Icon=winbridge
Terminal=false
Categories=Utility;Emulator;
Keywords=wine;bottle;windows;
StartupNotify=true
DESKTOP

convert "$ROOT/winbridge/resources/logo.png" -resize 256x256 \
        "$PKG/usr/share/icons/hicolor/256x256/apps/$NAME.png"

# --- metadata ------------------------------------------------------------
INSTALLED_SIZE=$(du -sk "$PKG" | cut -f1)
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: $NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $INSTALLED_SIZE
Maintainer: zuimeideshijie <zuimeideshijie@zuimeideshijie.zuimeideshijie.com>
Depends: python3 (>= 3.8), python3-pyqt5, wine | wine64 | wine-stable, cabextract, p7zip-full, curl, zstd, xdg-utils
Recommends: imagemagick, glib2.0-bin, desktop-file-utils
Homepage: https://gitcode.com/2503_90323139/WinBridge
Description: Wine bottle manager with a modern Qt interface
 WinBridge creates and manages Wine prefixes (bottles), installs common
 Windows components (vcrun, dotnet, DXVK, VKD3D, FAudio, fonts) and launches
 Windows applications from a per-bottle shortcut list.
 .
 Downloads are routed through GitHub mirrors by default and Microsoft
 redistributables are fetched directly.
CONTROL

cat > "$PKG/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
POSTINST

cat > "$PKG/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = purge ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
fi
exit 0
POSTRM
chmod 0755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

cat > "$PKG/usr/share/doc/$NAME/copyright" <<COPYRIGHT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: WinBridge
Source: https://gitcode.com/2503_90323139/WinBridge

Files: *
Copyright: 2026 zuimeideshijie
License: MIT
COPYRIGHT

printf '%s\n' \
  "$NAME ($VERSION) unstable; urgency=medium" "" \
  "  * Release $VERSION." "" \
  " -- zuimeideshijie <zuimeideshijie@zuimeideshijie.zuimeideshijie.com>  $(date -R)" \
  > "$BUILD/changelog.Debian"
gzip -9n -c "$BUILD/changelog.Debian" > "$PKG/usr/share/doc/$NAME/changelog.Debian.gz"
chmod 0644 "$PKG/usr/share/doc/$NAME/copyright" \
           "$PKG/usr/share/doc/$NAME/changelog.Debian.gz"

# md5sums for dpkg
( cd "$PKG" && find usr -type f -exec md5sum {} + | sort -k2 ) > "$PKG/DEBIAN/md5sums"

# --- build ---------------------------------------------------------------
mkdir -p "$OUT"
dpkg-deb --root-owner-group -Zxz --build "$PKG" "$OUT/${NAME}_${VERSION}_all.deb" >/dev/null
echo "==> 完成: $OUT/${NAME}_${VERSION}_all.deb"
dpkg-deb -I "$OUT/${NAME}_${VERSION}_all.deb" | sed -n '1,14p'