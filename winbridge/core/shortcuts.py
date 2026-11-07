"""Shortcut discovery, icon extraction and desktop entries.

Shortcuts are stored per bottle (``bottle.json``) so that deleting a ``.lnk``
from the Windows desktop does not make the program disappear from WinBridge.
Discovery only ever looks inside the bottle — the Linux desktop is never
scanned for shortcuts.
"""

import hashlib
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

# Program Files scan limits: deep enough for normal installs, shallow enough
# to stay fast on a prefix with a big game installed.
_MAX_DEPTH = 3
_MAX_PROGRAMS = 400

# Installers and helpers are not "applications" users launch
_SKIP_PATTERNS = re.compile(
    r"^(unins\d*|uninstall.*|setup|install|update|updater|crashreport.*|"
    r"vc_?redist.*|dxsetup|dotnet.*|helper)\.exe$",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# icon extraction (PE resources → .ico)
# --------------------------------------------------------------------------
def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _rva_to_offset(data: bytes, sections, rva: int):
    for vaddr, vsize, rawptr, rawsize in sections:
        span = max(vsize, rawsize)
        if vaddr <= rva < vaddr + span:
            return rawptr + (rva - vaddr)
    return None


def _dir_entry_count(data: bytes, base: int) -> int:
    """Number of entries in a resource directory (named + id entries)."""
    if base + 16 > len(data):
        return 0
    return _u16(data, base + 12) + _u16(data, base + 14)


def _read_resource_tree(data: bytes, base: int):
    """Return {type_id: {name_id: [(lang_id, data_rva, size)]}}."""
    if base is None or base + 16 > len(data):
        return {}
    tree = {}
    for i in range(_dir_entry_count(data, base)):
        entry = base + 16 + i * 8
        if entry + 8 > len(data):
            break
        type_id = _u32(data, entry)
        type_off = _u32(data, entry + 4)
        if not type_off & 0x80000000:
            continue
        name_dir = base + (type_off & 0x7FFFFFFF)
        if name_dir + 16 > len(data):
            continue
        names = {}
        for j in range(_dir_entry_count(data, name_dir)):
            n_entry = name_dir + 16 + j * 8
            if n_entry + 8 > len(data):
                break
            name_id = _u32(data, n_entry)
            name_off = _u32(data, n_entry + 4)
            if not name_off & 0x80000000:
                continue
            lang_dir = base + (name_off & 0x7FFFFFFF)
            if lang_dir + 16 > len(data):
                continue
            langs = []
            for k in range(_dir_entry_count(data, lang_dir)):
                l_entry = lang_dir + 16 + k * 8
                if l_entry + 8 > len(data):
                    break
                lang_id = _u32(data, l_entry)
                data_off = _u32(data, l_entry + 4)
                if data_off & 0x80000000:
                    continue
                d_entry = base + data_off
                if d_entry + 16 > len(data):
                    continue
                data_rva = _u32(data, d_entry)
                size = _u32(data, d_entry + 4)
                langs.append((lang_id, data_rva, size))
            if langs:
                names[name_id] = langs
        if names:
            tree[type_id] = names
    return tree


def _icon_size(image: bytes):
    """(width, height, planes, bpp) for a raw RT_ICON blob."""
    if image[:8] == b"\x89PNG\r\n\x1a\n" and len(image) >= 24:
        width = struct.unpack_from(">I", image, 16)[0]
        height = struct.unpack_from(">I", image, 20)[0]
        return width, height, 1, 32
    if len(image) >= 16:
        header_size = struct.unpack_from("<I", image, 0)[0]
        if header_size >= 40:
            width, height = struct.unpack_from("<ii", image, 4)
            planes, bpp = struct.unpack_from("<HH", image, 12)
            return width, abs(height) // 2, planes, bpp
    return 0, 0, 1, 32


def _section_table(data: bytes, opt: int, opt_size: int, num_sections: int):
    sections = []
    start = opt + opt_size
    for i in range(num_sections):
        off = start + i * 40
        if off + 40 > len(data):
            break
        vsize = _u32(data, off + 8)
        vaddr = _u32(data, off + 12)
        rawsize = _u32(data, off + 16)
        rawptr = _u32(data, off + 20)
        sections.append((vaddr, vsize, rawptr, rawsize))
    return sections


def _build_ico(entries, data: bytes) -> bytes:
    """entries: [(width, height, planes, bpp, image_bytes)]"""
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory = b""
    images = b""
    for width, height, planes, bpp, image in entries:
        directory += struct.pack(
            "<BBBBHHII",
            0 if width >= 256 else width,
            0 if height >= 256 else height,
            0, 0, planes or 1, bpp or 32, len(image), offset,
        )
        images += image
        offset += len(image)
    return header + directory + images


def extract_icon(exe_path: Path, cache_dir: Path) -> str:
    """Extract the best icon group from a PE file into the icon cache.

    Returns the cached ``.ico`` path, or "" when the file has no icon
    resources (or is not a PE file at all).
    """
    exe_path = Path(exe_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(str(exe_path).encode("utf-8", "replace")).hexdigest()[:16]
    out_path = cache_dir / f"{key}.ico"
    try:
        if out_path.stat().st_mtime >= exe_path.stat().st_mtime:
            return str(out_path)
    except OSError:
        pass

    try:
        data = exe_path.read_bytes()
    except OSError:
        return ""

    try:
        if data[:2] != b"MZ":
            return ""
        pe = _u32(data, 0x3C)
        if data[pe:pe + 4] != b"PE\0\0":
            return ""
        coff = pe + 4
        num_sections = _u16(data, coff + 2)
        opt_size = _u16(data, coff + 16)
        opt = coff + 20
        magic = _u16(data, opt)
        if magic == 0x20B:
            dd = opt + 112
        elif magic == 0x10B:
            dd = opt + 96
        else:
            return ""
        if dd + 16 > len(data):
            return ""
        res_rva = _u32(data, dd + 16)
        if not res_rva:
            return ""
        sections = _section_table(data, opt, opt_size, num_sections)
        base = _rva_to_offset(data, sections, res_rva)
        tree = _read_resource_tree(data, base)
        groups = tree.get(14) or {}
        icons = tree.get(3) or {}
        if not icons:
            return ""

        # Prefer an icon group (it carries the intended size set)
        best = None
        for name_id, langs in groups.items():
            _, grp_rva, grp_size = langs[0]
            grp_off = _rva_to_offset(data, sections, grp_rva)
            if grp_off is None or grp_off + 6 > len(data):
                continue
            count = _u16(data, grp_off + 4)
            entries = []
            total = 0
            for i in range(count):
                ent = grp_off + 6 + i * 14
                if ent + 14 > len(data):
                    break
                width, height, colors, _, planes, bpp, size, icon_id = struct.unpack_from(
                    "<BBBBHHIH", data, ent)
                icon_langs = icons.get(icon_id)
                if not icon_langs:
                    continue
                _, img_rva, img_size = icon_langs[0]
                img_off = _rva_to_offset(data, sections, img_rva)
                if img_off is None:
                    continue
                image = data[img_off:img_off + img_size]
                if not image:
                    continue
                entries.append((width, height, planes, bpp, image))
                total += width * height
            if entries and (best is None or total > best[0]):
                best = (total, entries)

        if best is None:
            # Wine executables often ship RT_ICON without RT_GROUP_ICON —
            # build the icon straight from the largest blobs.
            entries = []
            for name_id, langs in icons.items():
                _, img_rva, img_size = langs[0]
                img_off = _rva_to_offset(data, sections, img_rva)
                if img_off is None:
                    continue
                image = data[img_off:img_off + img_size]
                if not image:
                    continue
                width, height, planes, bpp = _icon_size(image)
                entries.append((width, height, planes, bpp, image))
            if not entries:
                return ""
            entries.sort(key=lambda e: e[0] * e[1], reverse=True)
            best = (0, entries[:6])

        ico = _build_ico(best[1], data)
        out_path.write_bytes(ico)
        return str(out_path)
    except (struct.error, IndexError, ValueError, OSError):
        return ""


# --------------------------------------------------------------------------
# .lnk → target resolution
# --------------------------------------------------------------------------
_ASCII_RUN = re.compile(rb"[\x20-\x7e]{4,}")


def _utf16_runs(data: bytes):
    """Yield printable UTF-16LE runs (Wine stores target paths this way)."""
    out = []
    chunk = bytearray()
    for i in range(0, len(data) - 1, 2):
        lo, hi = data[i], data[i + 1]
        if hi == 0 and 0x20 <= lo < 0x7F:
            chunk.append(lo)
        else:
            if len(chunk) >= 4:
                out.append(chunk.decode("ascii", "ignore"))
            chunk.clear()
    if len(chunk) >= 4:
        out.append(chunk.decode("ascii", "ignore"))
    return out


_WINDOWS_VARS = {
    "programfiles": "Program Files",
    "programfiles(x86)": "Program Files (x86)",
    "programw6432": "Program Files",
    "systemroot": "windows",
    "windir": "windows",
    "systemdrive": "",
    "userprofile": "users",
    "appdata": "users/AppData/Roaming",
    "localappdata": "users/AppData/Local",
    "programdata": "ProgramData",
}


def _expand_windows_path(raw: str) -> str:
    """Turn a Windows path string into a bottle-relative path component."""
    path = raw.strip().strip('"').replace("/", "\\")

    def var(match):
        name = match.group(1).lower()
        return _WINDOWS_VARS.get(name, match.group(0))

    path = re.sub(r"%([^%]+)%", var, path)
    path = re.sub(r"^[A-Za-z]:\\?", "", path)     # drop "C:\"
    path = re.sub(r"^\\\\\?\\", "", path)
    path = re.sub(r"^\\\\", "", path)
    path = path.replace("\\\\", "\\").lstrip("\\")
    return path


def lnk_target(lnk_path: Path, bottle_path: Path) -> Path:
    """Best-effort resolution of a .lnk's target to a file inside the bottle."""
    try:
        data = Path(lnk_path).read_bytes()
    except OSError:
        return None

    runs = _utf16_runs(data)
    runs += [m.group().decode("ascii", "ignore") for m in _ASCII_RUN.finditer(data)]

    candidates = []
    for run in runs:
        if run.lower().endswith((".exe", ".bat", ".cmd", ".msi")):
            candidates.append(run)

    drive_c = Path(bottle_path) / "drive_c"
    lnk_dir = Path(lnk_path).parent
    for raw in candidates:
        rel = _expand_windows_path(raw)
        if not rel:
            continue
        parts = [p for p in rel.split("\\") if p]
        if len(parts) > 1:
            # Path inside the prefix (var-expanded or "C:\...")
            target = drive_c.joinpath(*parts)
            if target.is_file():
                return target
        else:
            # Bare filename: next to the .lnk, then the usual program dirs
            for base in (lnk_dir, drive_c / "Program Files",
                         drive_c / "Program Files (x86)", drive_c / "windows"):
                target = base / parts[0]
                if target.is_file():
                    return target
    return None


# --------------------------------------------------------------------------
# discovery inside one bottle
# --------------------------------------------------------------------------
def _desktop_dirs(bottle_path: Path):
    drive_c = Path(bottle_path) / "drive_c"
    users = drive_c / "users"
    dirs = [drive_c / "users" / "Public" / "Desktop"]
    if users.exists():
        for user_dir in users.iterdir():
            if user_dir.is_dir():
                dirs.append(user_dir / "Desktop")
    return [d for d in dirs if d.is_dir()]


def _start_menu_dirs(bottle_path: Path):
    drive_c = Path(bottle_path) / "drive_c"
    users = drive_c / "users"
    dirs = []
    if users.exists():
        for user_dir in users.iterdir():
            if (user_dir / "Start Menu").is_dir():
                dirs.append(user_dir / "Start Menu")
    programdata = drive_c / "ProgramData" / "Microsoft" / "Windows" / "Start Menu"
    if programdata.is_dir():
        dirs.append(programdata)
    return dirs


def _program_files(bottle_path: Path):
    drive_c = Path(bottle_path) / "drive_c"
    return [d for d in (drive_c / "Program Files", drive_c / "Program Files (x86)") if d.is_dir()]


def discover(bottle_path) -> list:
    """Applications the bottle offers: name, target, source, icon = ""."""
    bottle_path = Path(bottle_path)
    found = []
    seen = set()
    seen_names = set()

    def add(name, target, source):
        key = str(Path(target).resolve())
        if key in seen:
            return
        # 32/64-bit builds of the same program share a name — show one entry
        name_key = (name.strip().lower(), Path(key).name.lower())
        if name_key in seen_names:
            return
        seen.add(key)
        seen_names.add(name_key)
        found.append({"name": name, "target": key, "source": source, "icon": ""})

    for lnk in [p for d in _desktop_dirs(bottle_path) for p in d.glob("*.lnk")]:
        target = lnk_target(lnk, bottle_path)
        if target:
            add(lnk.stem, target, "lnk")

    for start_menu in _start_menu_dirs(bottle_path):
        for lnk in list(start_menu.glob("**/*.lnk"))[:200]:
            target = lnk_target(lnk, bottle_path)
            if target:
                add(lnk.stem, target, "lnk")

    count = 0
    for root in _program_files(bottle_path):
        base_depth = len(root.parts)
        for exe in root.glob("**/*.exe"):
            if count >= _MAX_PROGRAMS:
                break
            if len(exe.parts) - base_depth > _MAX_DEPTH:
                continue
            if _SKIP_PATTERNS.match(exe.name):
                continue
            count += 1
            add(exe.stem, exe, "exe")

    found.sort(key=lambda s: s["name"].lower())
    return found


def merge(stored: list, discovered: list) -> tuple:
    """Merge stored shortcuts with a fresh discovery pass.

    Stored entries win (they keep user renames and survive deleted .lnk
    files); newly discovered targets are appended. Returns
    (merged_list, changed).
    """
    merged = [dict(s) for s in (stored or [])]
    known = {s.get("target") for s in merged}
    for item in discovered:
        if item["target"] in known:
            continue
        merged.append(dict(item))
        known.add(item["target"])

    # Collapse 32/64-bit twins and old duplicates: same display name and
    # same executable name, preferring entries whose file still exists.
    unique = {}
    for item in merged:
        target = item.get("target", "")
        key = ((item.get("name") or "").strip().lower(),
               Path(target).name.lower())
        current = unique.get(key)
        if current is None or (not Path(current.get("target", "")).exists()
                               and Path(target).exists()):
            unique[key] = item
    merged = list(unique.values())
    merged.sort(key=lambda s: (s.get("name") or "").lower())
    return merged, merged != (stored or [])


# --------------------------------------------------------------------------
# uninstall an application
# --------------------------------------------------------------------------
def _app_root(target: Path, bottle_path: Path):
    """The folder that belongs to one application, or None if unsure.

    Only well-known install locations are accepted — never the shared root
    of Program Files or the Windows directory — so uninstalling cannot take
    unrelated programs with it.
    """
    drive_c = Path(bottle_path) / "drive_c"
    try:
        rel = Path(target).resolve().relative_to(drive_c.resolve())
    except (ValueError, OSError):
        return None
    parts = rel.parts

    if len(parts) >= 3 and parts[0] in ("Program Files", "Program Files (x86)"):
        return drive_c / parts[0] / parts[1]
    if len(parts) >= 4 and parts[0] == "ProgramData":
        return drive_c.joinpath(*parts[:3])
    if len(parts) >= 7 and parts[0] == "users" and parts[2] == "AppData":
        if parts[3] == "Local" and parts[4] == "Programs":
            return drive_c.joinpath(*parts[:6])
        if parts[3] in ("Local", "Roaming"):
            return drive_c.joinpath(*parts[:6])
    return None


def _dir_size(path: Path) -> int:
    total = 0
    for item in Path(path).rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def plan_uninstall(target, bottle_path) -> dict:
    """Describe what uninstalling a program would remove.

    Returns ``{target, root, size, shortcuts}`` or None when the program is
    not installed in a removable per-application folder.
    """
    target = Path(target)
    root = _app_root(target, bottle_path)
    if root is None or not root.is_dir():
        return None

    related = []
    for directory in _desktop_dirs(bottle_path) + _start_menu_dirs(bottle_path):
        for lnk in list(directory.glob("**/*.lnk"))[:400]:
            resolved = lnk_target(lnk, bottle_path)
            if resolved and Path(resolved).is_relative_to(root):
                related.append(str(lnk))

    return {
        "target": str(target),
        "root": str(root),
        "size": _dir_size(root),
        "shortcuts": related,
    }


def remove_app(plan: dict) -> tuple:
    """Delete the application folder and its shortcuts. Returns (ok, error)."""
    if not plan:
        return False, "没有可删除的内容"
    root = Path(plan["root"])
    if len(root.parts) < 4:          # refuse anything suspiciously shallow
        return False, f"拒绝删除过浅的路径：{root}"
    errors = []
    try:
        shutil.rmtree(root)
    except OSError as exc:
        errors.append(f"删除 {root.name} 失败：{exc}")
    for lnk in plan.get("shortcuts", []):
        try:
            Path(lnk).unlink()
        except OSError:
            pass
    # Desktop launchers pointing at this program would dead-link too
    try:
        for entry in desktop_dir().glob("*.desktop"):
            try:
                text = entry.read_text(encoding="utf-8", errors="ignore")
                if plan["target"] in text:
                    entry.unlink()
            except OSError:
                continue
    except OSError:
        pass
    return (not errors), "; ".join(errors)


# --------------------------------------------------------------------------
# Linux desktop entries
# --------------------------------------------------------------------------
def desktop_dir() -> Path:
    """The user's XDG desktop directory."""
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True,
                             text=True, timeout=3)
        path = out.stdout.strip()
        if path and Path(path).is_dir():
            return Path(path)
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in (Path.home() / "Desktop", Path.home() / "桌面"):
        if candidate.is_dir():
            return candidate
    return Path.home() / "Desktop"


def _png_icon(ico_path: str, cache_dir: Path) -> str:
    """Desktop entries want PNG; convert the cached .ico when possible."""
    if not ico_path:
        return ""
    ico = Path(ico_path)
    png = ico.with_suffix(".png")
    if png.exists() and png.stat().st_mtime >= ico.stat().st_mtime:
        return str(png)
    try:
        result = subprocess.run(["convert", str(ico) + "[0]", str(png)],
                                capture_output=True, timeout=20)
        if result.returncode == 0 and png.exists():
            return str(png)
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def create_desktop_entry(bottle, name: str, target: str, icon: str = "",
                         app_command: str = "winbridge") -> tuple:
    """Write a .desktop launcher for one program onto the Linux desktop."""
    desktop = desktop_dir()
    desktop.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[/\\:*?\"<>|]", "_", name).strip() or "program"
    path = desktop / f"{safe}.desktop"
    icon_png = _png_icon(icon, Path(icon).parent if icon else Path("/tmp"))
    if not icon_png:
        icon_png = str(Path(__file__).parent.parent / "resources" / "logo.png")

    content = "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={name}",
        f"Comment=通过 WinBridge 在容器「{bottle.name}」中运行",
        f'Exec={app_command} --bottle "{bottle.name}" --run "{target}"',
        f"Icon={icon_png}",
        "Terminal=false",
        "Categories=Wine;Game;",
        "StartupNotify=true",
        "",
    ])
    try:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
    except OSError as exc:
        return False, str(exc)
    # GNOME only launches desktop files it considers trusted
    try:
        subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    return True, str(path)