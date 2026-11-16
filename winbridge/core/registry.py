"""Registry helpers shared by the browser UI.

Wine stores its registry in two text files per prefix: ``user.reg`` (HKCU)
and ``system.reg`` (HKLM). Keys inside those files use doubled backslashes
(``Software\\\\Microsoft``), and that is also the separator the tree view
keeps in its item paths. Wine's own ``reg`` command, however, wants a single
backslash — mixing the two makes ``reg add``/``reg delete`` silently target a
key that does not exist.
"""

import re

# Separator used inside the .reg files and by the tree items. It is two
# literal backslashes, not one escaped backslash.
SEP = "\\\\"

REG_TYPES = (
    "REG_SZ",
    "REG_EXPAND_SZ",
    "REG_DWORD",
    "REG_QWORD",
    "REG_MULTI_SZ",
    "REG_BINARY",
)

REG_TYPE_LABELS = {
    "REG_SZ": "字符串 (REG_SZ)",
    "REG_EXPAND_SZ": "可扩展字符串 (REG_EXPAND_SZ)",
    "REG_DWORD": "DWORD (32 位)",
    "REG_QWORD": "QWORD (64 位)",
    "REG_MULTI_SZ": "多字符串 (REG_MULTI_SZ)",
    "REG_BINARY": "二进制 (REG_BINARY)",
}

_VALUE_LINE = re.compile(r'^(@|"(?:[^"\\]|\\.)*")\s*=\s*(.*)$')
_ANY_LINE = re.compile(r'^\[(.*?)\]')
_HEX_BYTES = re.compile(r"[0-9a-fA-F]{2}")
_STR_TYPE = re.compile(r"^str\((\d+)\):(.*)$", re.IGNORECASE)


def split_key(key_path: str) -> tuple:
    """Split a tree path into ``(hive, bare_key)``."""
    hive, _, bare = (key_path or "").partition(SEP)
    return hive, bare


def win_reg_path(key_path: str) -> str:
    """Convert a tree path to the form Wine's ``reg`` command expects."""
    return (key_path or "").replace(SEP, "\\")


def _unescape_string(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in ('"', "\\"):
                out.append(nxt)
                i += 2
                continue
        out.append(char)
        i += 1
    return "".join(out)


def _hex_bytes(data: str) -> bytes:
    return bytes(int(pair, 16) for pair in _HEX_BYTES.findall(data))


def _utf16(data: bytes) -> str:
    return data.decode("utf-16-le", "replace")


def decode_value(raw: str) -> tuple:
    """Return ``(type_name, display_text)`` for one .reg value payload."""
    value = (raw or "").strip()
    low = value.lower()

    # Wine 11 writes strings as str(<regtype>):"…" (older versions use
    # hex(2):/hex(7): for the same types, which is handled below).
    typed = _STR_TYPE.match(value)
    if typed:
        type_number = int(typed.group(1))
        payload = typed.group(2).strip()
        if payload.startswith('"'):
            inner = payload[1:-1] if payload.endswith('"') else payload[1:]
            if type_number == 7:
                parts = [_unescape_string(part)
                         for part in inner.split("\\0") if part]
                return "REG_MULTI_SZ", "\n".join(parts)
            if type_number == 2:
                return "REG_EXPAND_SZ", _unescape_string(inner)
            return "REG_SZ", _unescape_string(inner)
        if payload.lower().startswith("hex"):
            data = _hex_bytes(payload[payload.find(":") + 1:]
                              if ":" in payload else payload[3:])
            if type_number in (4,):
                return "REG_DWORD", str(int.from_bytes(data, "little"))
            if type_number in (11,):
                return "REG_QWORD", str(int.from_bytes(data, "little"))
            return "REG_BINARY", data.hex(" ").upper()
        return "REG_SZ", payload

    if value.startswith('"'):
        inner = value[1:-1] if value.endswith('"') else value[1:]
        return "REG_SZ", _unescape_string(inner)

    if low.startswith("dword:"):
        try:
            return "REG_DWORD", str(int(value[6:], 16))
        except ValueError:
            return "REG_DWORD", value[6:]

    if low.startswith("hex(b):"):
        data = _hex_bytes(value[6:])
        number = int.from_bytes(data, "little") if data else 0
        return "REG_QWORD", str(number)

    if low.startswith("hex(2):"):
        return "REG_EXPAND_SZ", _utf16(_hex_bytes(value[6:]).rstrip(b"\0"))

    if low.startswith("hex(7):"):
        text = _utf16(_hex_bytes(value[6:]))
        parts = [part for part in text.split("\0") if part]
        return "REG_MULTI_SZ", "\n".join(parts)

    if low.startswith("hex"):
        data = _hex_bytes(value[value.find(":") + 1:] if ":" in value else value[3:])
        return "REG_BINARY", data.hex(" ").upper()

    return "REG_SZ", value


def parse_values(text: str, key_path: str) -> list:
    """Values of one key from a ``.reg`` file's text.

    ``key_path`` uses the tree separator (doubled backslashes). Returns a
    list of ``{name, display_name, type, data, raw}`` dictionaries.
    """
    _, target = split_key(key_path)
    if not target:
        return []

    values = []
    in_target = False
    pending = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if pending:
            line = pending + line
            pending = ""
        if not line:
            continue
        # Long hex payloads are wrapped over several lines with a trailing "\".
        if line.endswith("\\"):
            pending = line[:-1]
            continue

        section = _ANY_LINE.match(line)
        if section:
            in_target = section.group(1).strip() == target
            continue
        if not in_target:
            continue

        match = _VALUE_LINE.match(line)
        if not match:
            continue
        raw_name, payload = match.group(1), match.group(2)
        if raw_name == "@":
            name = ""
        else:
            name = _unescape_string(raw_name[1:-1])

        type_name, display = decode_value(payload)
        values.append({
            "name": name,
            "display_name": name or "(默认)",
            "type": type_name,
            "data": display,
            "raw": payload,
        })
    return values


def normalize_value(type_name: str, data: str) -> tuple:
    """Validate one value for ``reg add``. Returns ``(text, error)``."""
    if type_name in ("REG_DWORD", "REG_QWORD"):
        text = (data or "").strip()
        try:
            number = int(text, 0)
        except ValueError:
            return "", "请输入十进制或 0x 开头的十六进制整数。"
        if number < 0 or number > (0xFFFFFFFF if type_name == "REG_DWORD"
                                   else 0xFFFFFFFFFFFFFFFF):
            return "", "数值超出该类型的取值范围。"
        return str(number), ""

    if type_name == "REG_BINARY":
        cleaned = re.sub(r"0x|[\s,:;-]", "", data or "", flags=re.IGNORECASE)
        if not re.fullmatch(r"[0-9a-fA-F]*", cleaned):
            return "", "二进制数据只能包含十六进制数字（可加空格分隔）。"
        if len(cleaned) % 2:
            return "", "二进制数据必须是整字节（每字节两位十六进制）。"
        return cleaned.lower(), ""

    if type_name == "REG_MULTI_SZ":
        # Wine's reg accepts the "\0" escape sequence between strings.
        lines = [line for line in (data or "").splitlines() if line != ""]
        return "\\0".join(lines), ""

    return data or "", ""


def add_value_args(name: str, type_name: str, data: str) -> tuple:
    """Arguments for ``reg add`` after the key path.

    Returns ``(args, error)``; ``args`` contains the /v|/ve, /t and /d
    switches in the order Wine's parser expects.
    """
    normalized, error = normalize_value(type_name, data)
    if error:
        return [], error
    args = []
    if name:
        args += ["/v", name]
    else:
        args += ["/ve"]
    args += ["/t", type_name, "/d", normalized, "/f"]
    return args, ""