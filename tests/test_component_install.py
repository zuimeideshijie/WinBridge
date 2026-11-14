"""Unit tests for the component installer's payload placement logic.

These cover the parts that decide *where* a DLL goes and *which* cab/archive
member to use — the bugs that made components report success without taking
effect. Nothing here needs Wine or a real prefix.
"""

import os
import struct
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from winbridge.core import download
from winbridge.core.download import COMPONENT_MAP, ComponentManager


def write_pe(path: Path, machine: int) -> Path:
    """Write a minimal file that looks like a PE image with `machine`."""
    pe_offset = 0x80
    header = bytearray(pe_offset + 24)
    header[0:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, pe_offset)
    header[pe_offset:pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<H", header, pe_offset + 4, machine)
    path.write_bytes(bytes(header))
    return path


def make_manager(cache_dir: Path = None, components_dir: Path = None):
    """ComponentManager without winetricks discovery or config side effects."""
    manager = ComponentManager.__new__(ComponentManager)
    manager.config = SimpleNamespace(
        cache_dir=cache_dir or Path(tempfile.gettempdir()),
        components_dir=components_dir or Path(tempfile.gettempdir()),
        wine_path="/usr/bin/wine",
    )
    manager._github_mirror = None
    return manager


class PeMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_x86(self):
        path = write_pe(self.dir / "a.dll", 0x014C)
        self.assertEqual(download.pe_machine(path), 0x014C)
        self.assertFalse(download.pe_is_64bit(path))

    def test_x64(self):
        path = write_pe(self.dir / "a.dll", 0x8664)
        self.assertEqual(download.pe_machine(path), 0x8664)
        self.assertTrue(download.pe_is_64bit(path))

    def test_non_pe(self):
        path = self.dir / "a.dll"
        path.write_bytes(b"not a PE file at all")
        self.assertIsNone(download.pe_machine(path))
        self.assertIsNone(download.pe_is_64bit(path))


class CabMemberTests(unittest.TestCase):
    def test_override_name_strips_extension(self):
        self.assertEqual(ComponentManager._dll_override_name("d3d9.dll"), "d3d9")
        self.assertEqual(ComponentManager._dll_override_name("D3D11"), "d3d11")
        self.assertEqual(ComponentManager._dll_override_name("msvcp140.dll"),
                         "msvcp140")

    def test_cab_member_suffixes(self):
        self.assertEqual(ComponentManager._cab_member_base("msvcp140.dll_x86"),
                         "msvcp140")
        self.assertEqual(ComponentManager._cab_member_base("msvcp140.dll_x64"),
                         "msvcp140")
        self.assertEqual(ComponentManager._cab_member_base("msvcp140.dll"),
                         "msvcp140")

    def test_cab_member_does_not_merge_versioned_dlls(self):
        # msvcp140_1.dll must not be treated as msvcp140.dll
        self.assertEqual(ComponentManager._cab_member_base("msvcp140_1.dll_x86"),
                         "msvcp140_1")
        self.assertNotEqual(ComponentManager._cab_member_base("msvcp140_1.dll"),
                            ComponentManager._cab_member_base("msvcp140.dll"))


class PackageLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_dxvk_x32_x64(self):
        pkg = self.root / "dxvk-2.7.1"
        (pkg / "x32").mkdir(parents=True)
        (pkg / "x64").mkdir()
        self.assertEqual(ComponentManager._locate_package_root(self.root), pkg)
        self.assertEqual(
            ComponentManager._find_bin_dir(pkg, download.BIN_DIR_32).name, "x32")

    def test_vkd3d_x86_x64(self):
        # vkd3d-proton ships x86/, not x32/ — this used to lose 32-bit DLLs
        pkg = self.root / "vkd3d-proton-2.14.1"
        (pkg / "x86").mkdir(parents=True)
        (pkg / "x64").mkdir()
        self.assertEqual(ComponentManager._locate_package_root(self.root), pkg)
        self.assertEqual(
            ComponentManager._find_bin_dir(pkg, download.BIN_DIR_32).name, "x86")

    def test_layout_at_archive_root(self):
        (self.root / "x64").mkdir()
        self.assertEqual(ComponentManager._locate_package_root(self.root),
                         self.root)

    def test_unknown_layout_falls_back_to_first_dir(self):
        (self.root / "a-first").mkdir()
        (self.root / "b-second").mkdir()
        self.assertEqual(ComponentManager._locate_package_root(self.root),
                         self.root / "a-first")


class SystemDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write_arch(self, arch: str):
        (self.prefix / "user.reg").write_text(
            f'WINE REGISTRY Version 2\n#arch={arch}\n', encoding="utf-8")

    def test_win64_places_32bit_in_syswow64(self):
        self.write_arch("win64")
        dirs = make_manager()._system_dirs(str(self.prefix))
        self.assertEqual(dirs["x86"].name, "syswow64")
        self.assertEqual(dirs["x64"].name, "system32")

    def test_win32_has_no_64bit_target(self):
        self.write_arch("win32")
        dirs = make_manager()._system_dirs(str(self.prefix))
        self.assertEqual(dirs["x86"].name, "system32")
        self.assertIsNone(dirs["x64"])

    def test_missing_registry_defaults_to_win64(self):
        dirs = make_manager()._system_dirs(str(self.prefix))
        self.assertEqual(dirs["x86"].name, "syswow64")


class PayloadArchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_payload_matching(self):
        dll32 = write_pe(self.dir / "a32.dll", 0x014C)
        dll64 = write_pe(self.dir / "a64.dll", 0x8664)
        manager = make_manager()
        self.assertTrue(manager._payload_matches_arch(dll32, "x86"))
        self.assertFalse(manager._payload_matches_arch(dll32, "x64"))
        self.assertTrue(manager._payload_matches_arch(dll64, "x64"))
        self.assertFalse(manager._payload_matches_arch(dll64, "x86"))


class ComponentConfigTests(unittest.TestCase):
    def test_tarball_components_declare_dlls(self):
        for name, info in COMPONENT_MAP.items():
            gc = info.get("gitcode", {})
            if gc.get("type") != "precompiled_tarball":
                continue
            with self.subTest(component=name):
                self.assertTrue(gc.get("dlls") or gc.get("all_dlls"),
                                "precompiled tarball needs dlls/all_dlls")

    def test_directx_components_use_x86_x64_arch_keys(self):
        for name, info in COMPONENT_MAP.items():
            gc = info.get("gitcode", {})
            if gc.get("type") != "directx_redist":
                continue
            for dll, arches in gc["dlls"].items():
                with self.subTest(component=name, dll=dll):
                    self.assertTrue(set(arches) <= {"x86", "x64", "amd64"})

    def test_msxml_extract_declares_override(self):
        redist = COMPONENT_MAP["msxml6"]["redist"]
        self.assertTrue(redist.get("extract_msi"))
        self.assertEqual(redist["overrides"].get("msxml6"), "native,builtin")

    def test_vcrun_declares_overrides_and_verification(self):
        for name in ("vcrun2019", "vcrun2022"):
            redist = COMPONENT_MAP[name]["redist"]
            with self.subTest(component=name):
                self.assertEqual(redist["overrides"].get("msvcp140"),
                                 "native,builtin")
                self.assertIn("msvcp140.dll", redist["verify_dlls"])
                self.assertIn(3010, redist["success_codes"])

    def test_dotnet_uses_winetricks(self):
        # A bare ndp48 /quiet install leaves an unusable runtime; the verb
        # does the mono removal / dotnet40 prerequisite / winver dance.
        info = COMPONENT_MAP["dotnet48"]
        self.assertNotIn("redist", info)
        self.assertEqual(info["verb"], "dotnet48")
        self.assertIn("fusion=b", info["winetricks_env"]["WINEDLLOVERRIDES"])
        self.assertNotIn("mscoree=d", info["winetricks_env"]["WINEDLLOVERRIDES"])
        self.assertTrue(info["restore_winver"])


class DllFileTests(unittest.TestCase):
    """Install/uninstall file handling (backup + atomic replace + revert)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.windows = self.root / "drive_c" / "windows"
        self.addCleanup(self.tmp.cleanup)
        self.manager = make_manager()

    def test_install_keeps_backup_of_replaced_dll(self):
        target = self.windows / "system32" / "d3d11.dll"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"wine-builtin-or-older-component")
        source = self.root / "d3d11.dll"
        source.write_bytes(b"dxvk")

        self.assertTrue(ComponentManager._install_dll_file(source, target))

        self.assertEqual(target.read_bytes(), b"dxvk")
        self.assertEqual(target.with_name("d3d11.dll.bck").read_bytes(),
                         b"wine-builtin-or-older-component")

    def test_second_install_does_not_overwrite_the_backup(self):
        target = self.windows / "system32" / "dxgi.dll"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"original")
        first = self.root / "first.dll"
        first.write_bytes(b"dxvk-2.6")
        second = self.root / "second.dll"
        second.write_bytes(b"dxvk-2.7")

        ComponentManager._install_dll_file(first, target)
        ComponentManager._install_dll_file(second, target)

        self.assertEqual(target.read_bytes(), b"dxvk-2.7")
        self.assertEqual(target.with_name("dxgi.dll.bck").read_bytes(),
                         b"original")

    def test_no_backup_when_target_did_not_exist(self):
        target = self.windows / "syswow64" / "d3d12.dll"
        source = self.root / "d3d12.dll"
        source.write_bytes(b"vkd3d")

        ComponentManager._install_dll_file(source, target)

        self.assertTrue(target.exists())
        self.assertFalse(target.with_name("d3d12.dll.bck").exists())

    def test_uninstall_restores_backup(self):
        target = self.windows / "system32" / "d3d11.dll"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"dxvk")
        target.with_name("d3d11.dll.bck").write_bytes(b"previous-native")

        ok, log = self.manager.uninstall(
            "dxvk", str(self.root), files=["system32/d3d11.dll"])

        self.assertTrue(ok, log)
        self.assertEqual(target.read_bytes(), b"previous-native")
        self.assertFalse(target.with_name("d3d11.dll.bck").exists())

    def test_uninstall_removes_dll_without_backup(self):
        target = self.windows / "syswow64" / "xaudio2_7.dll"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"faudio")

        ok, log = self.manager.uninstall(
            "faudio", str(self.root), files=["syswow64/xaudio2_7.dll"])

        self.assertTrue(ok, log)
        self.assertFalse(target.exists())

    def test_uninstall_keeps_overrides_other_components_need(self):
        target = self.windows / "system32" / "d3d9.dll"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"dxvk")
        calls = {}

        def fake_delete(bottle_path, names, progress_callback=None):
            calls["names"] = list(names)
            return True, ""

        self.manager._delete_dll_overrides = fake_delete
        ok, log = self.manager.uninstall(
            "dxvk", str(self.root), files=["system32/d3d9.dll"],
            overrides={"d3d9": "native", "dxgi": "native"},
            keep_overrides=["D3D9"])

        self.assertTrue(ok, log)
        self.assertEqual([n.lower() for n in calls["names"]], ["dxgi"])

    def test_override_reg_text_deletes_values(self):
        text = ComponentManager._override_reg_text(
            {"d3d11": "native", "d3d9": "-"})

        self.assertIn(r"[HKEY_CURRENT_USER\Software\Wine\DllOverrides]", text)
        self.assertIn('"d3d11"="native"', text)
        self.assertIn('"d3d9"=-', text)


class BottleRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "mybottle"
        self.path.mkdir()
        self.addCleanup(self.tmp.cleanup)
        from winbridge.core.bottle import Bottle
        self.bottle = Bottle(
            str(self.path),
            config=SimpleNamespace(wine_path="/usr/bin/wine", wine_arch="win64"),
        )

    def test_component_record_round_trip(self):
        self.bottle.add_component("dxvk")
        self.bottle.set_component_record(
            "dxvk", ["system32/d3d11.dll", "syswow64/d3d11.dll"],
            {"d3d11": "native", "dxgi": "native"})

        from winbridge.core.bottle import Bottle
        reloaded = Bottle(
            str(self.path),
            config=SimpleNamespace(wine_path="/usr/bin/wine", wine_arch="win64"),
        )
        record = reloaded.get_component_record("dxvk")
        self.assertEqual(record["files"],
                         ["system32/d3d11.dll", "syswow64/d3d11.dll"])
        self.assertEqual(record["overrides"]["dxgi"], "native")

    def test_component_overrides_excludes_the_one_being_removed(self):
        self.bottle.set_component_record("dxvk", [], {"d3d11": "native"})
        self.bottle.set_component_record("d3dx9", [], {"d3dx9_43": "native"})

        self.assertEqual(self.bottle.component_overrides(exclude="dxvk"),
                         ["d3dx9_43"])
        self.assertEqual(sorted(self.bottle.component_overrides()),
                         ["d3d11", "d3dx9_43"])

    def test_drop_component_record(self):
        self.bottle.set_component_record("dxvk", ["system32/d3d11.dll"],
                                         {"d3d11": "native"})
        self.bottle.drop_component_record("dxvk")
        self.assertEqual(self.bottle.component_records, {})


class DownloadTests(unittest.TestCase):
    """Progress formatting, range downloads, and cancel of the downloader."""

    def test_progress_message_formats_speed_and_eta(self):
        percent, message = ComponentManager._progress_message(
            "DXVK", 2 * 1024 * 1024, 10 * 1024 * 1024, 1024 * 1024)
        self.assertEqual(percent, 20)
        self.assertIn("2.0/10.0MB", message)
        self.assertIn("1024.0KB/s", message)
        self.assertIn("剩余 0m8s", message)

    def test_progress_message_without_total(self):
        percent, message = ComponentManager._progress_message("DXVK", 1234, 0)
        self.assertEqual(percent, 50)
        self.assertIn("DXVK", message)

    def test_cancel_before_download_raises(self):
        event = threading.Event()
        event.set()
        manager = make_manager(cache_dir=Path(tempfile.gettempdir()))
        with self.assertRaises(download.InstallCancelled):
            manager._download_one("http://127.0.0.1:1/none", "/tmp/unused.bin",
                                  cancel_event=event)


class RangeServerTests(unittest.TestCase):
    """End-to-end download tests against a local Range-capable server."""

    PAYLOAD = bytes(range(256)) * (5 * 4096)  # 5 MiB of deterministic bytes

    @classmethod
    def setUpClass(cls):
        import http.server
        import socketserver

        payload = cls.PAYLOAD

        class Handler(http.server.BaseHTTPRequestHandler):
            support_ranges = True

            def log_message(self, *args):  # silence test output
                pass

            def _send_headers(self, status, length, extra=None):
                self.send_response(status)
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges",
                                 "bytes" if self.support_ranges else "none")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()

            def do_HEAD(self):
                self._send_headers(200, len(payload))

            def do_GET(self):
                header = self.headers.get("Range", "")
                try:
                    if self.support_ranges and header.startswith("bytes="):
                        start_s, _, end_s = header[6:].partition("-")
                        start = int(start_s or 0)
                        end = int(end_s) if end_s else len(payload) - 1
                        chunk = payload[start:end + 1]
                        self._send_headers(206, len(chunk), {
                            "Content-Range": f"bytes {start}-{end}/{len(payload)}"})
                        self.wfile.write(chunk)
                    else:
                        self._send_headers(200, len(payload))
                        self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # client cancelled mid-download

        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/file.bin"
        # Make sure urllib doesn't route loopback through an env proxy
        cls._saved_env = {k: os.environ.get(k) for k in ("no_proxy", "NO_PROXY")}
        os.environ["no_proxy"] = "127.0.0.1,localhost"
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        for key, value in cls._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.manager = make_manager(cache_dir=self.dir)

    def test_probe_reports_size_and_ranges(self):
        size, ranges = ComponentManager._probe_download(self.url)
        self.assertEqual(size, len(self.PAYLOAD))
        self.assertTrue(ranges)

    def test_probe_on_server_without_ranges(self):
        RangeServerTests.server.RequestHandlerClass.support_ranges = False
        try:
            size, ranges = ComponentManager._probe_download(self.url)
            self.assertFalse(ranges)
        finally:
            RangeServerTests.server.RequestHandlerClass.support_ranges = True

    def test_download_one_uses_segments_and_verifies_bytes(self):
        dest = self.dir / "file.bin"
        ok, err = self.manager._download_one(self.url, str(dest))
        self.assertTrue(ok, err)
        self.assertEqual(dest.read_bytes(), self.PAYLOAD)
        # No stray segment/partial files left behind
        leftovers = [p.name for p in self.dir.iterdir() if p.name != "file.bin"]
        self.assertEqual(leftovers, [])

    def test_segmented_download_returns_false_without_range_support(self):
        dest = self.dir / "file.bin"
        RangeServerTests.server.RequestHandlerClass.support_ranges = False
        try:
            ok = self.manager._download_segmented(
                self.url, str(dest), len(self.PAYLOAD), None, "test", None)
        finally:
            RangeServerTests.server.RequestHandlerClass.support_ranges = True
        self.assertFalse(ok)
        self.assertFalse(dest.exists())

    def test_cancel_during_segmented_download(self):
        event = threading.Event()
        dest = self.dir / "file.bin"
        event.set()
        with self.assertRaises(download.InstallCancelled):
            self.manager._download_segmented(
                self.url, str(dest), len(self.PAYLOAD), None, "test", event)
        self.assertFalse(dest.exists())


class CabIntegrityTests(unittest.TestCase):
    """Preset MSI/CAB files must be complete before winetricks sees them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_truncated_msi_is_rejected(self):
        # Real msxml3.msi shipped at 651KB: CFB header but no readable cabinet
        broken = self.dir / "msxml3.msi"
        broken.write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 4096)
        self.assertFalse(ComponentManager._cab_integrity_ok(broken))

    def test_non_cab_payload_is_accepted(self):
        font = self.dir / "font.ttf"
        font.write_bytes(b"\x00\x01\x00\x00" + b"\0" * 128)
        self.assertTrue(ComponentManager._cab_integrity_ok(font))

    def test_missing_file_is_rejected(self):
        self.assertFalse(
            ComponentManager._cab_integrity_ok(self.dir / "nope.msi"))


if __name__ == "__main__":
    unittest.main()