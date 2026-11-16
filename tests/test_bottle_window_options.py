"""Tests for the two window switches and per-shortcut launch arguments."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from winbridge.core.bottle import Bottle


def make_bottle(path: Path) -> Bottle:
    path.mkdir(parents=True, exist_ok=True)
    (path / "user.reg").write_text('WINE REGISTRY Version 2\n\n', encoding="utf-8")
    return Bottle(str(path), config=SimpleNamespace(
        wine_path="/usr/bin/wine", wine_arch="win64"))


class ShortcutArgsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bottle = make_bottle(Path(self.tmp.name) / "bottle")
        self.addCleanup(self.tmp.cleanup)
        self.bottle.add_shortcut("Qwen", "/tmp/Qwen.exe")

    def test_defaults_to_no_arguments(self):
        self.assertEqual(self.bottle.shortcut_args("/tmp/Qwen.exe"), [])

    def test_round_trip_through_bottle_json(self):
        self.assertTrue(self.bottle.set_shortcut_args(
            "/tmp/Qwen.exe", ["--disable-features=Windows10CustomTitlebar"]))
        reloaded = Bottle(str(self.bottle.path), config=SimpleNamespace(
            wine_path="/usr/bin/wine", wine_arch="win64"))
        self.assertEqual(reloaded.shortcut_args("/tmp/Qwen.exe"),
                         ["--disable-features=Windows10CustomTitlebar"])

    def test_clearing_drops_the_key(self):
        self.bottle.set_shortcut_args("/tmp/Qwen.exe", ["-x"])
        self.bottle.set_shortcut_args("/tmp/Qwen.exe", [])
        entry = self.bottle.shortcuts[0]
        self.assertNotIn("args", entry)
        self.assertEqual(self.bottle.shortcut_args("/tmp/Qwen.exe"), [])

    def test_unknown_target_is_not_saved(self):
        self.assertFalse(self.bottle.set_shortcut_args("/tmp/nope.exe", ["-x"]))

    def test_launch_shortcut_passes_stored_arguments(self):
        self.bottle.set_shortcut_args("/tmp/Qwen.exe", ["--flag"])
        with mock.patch.object(Bottle, "run", return_value=True) as run:
            self.assertTrue(self.bottle.launch_shortcut("/tmp/Qwen.exe"))
        run.assert_called_once_with("/tmp/Qwen.exe", ["--flag"])

    def test_launch_shortcut_without_arguments_passes_none(self):
        with mock.patch.object(Bottle, "run", return_value=True) as run:
            self.bottle.launch_shortcut("/tmp/Qwen.exe")
        run.assert_called_once_with("/tmp/Qwen.exe", None)


class WindowOptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bottle"
        self.bottle = make_bottle(self.path)
        self.addCleanup(self.tmp.cleanup)
        self.commands = []

        def fake_reg(command):
            self.commands.append(command)
            return True, ""

        self.bottle._run_reg = fake_reg

    def write_user_reg(self, *sections: str):
        lines = ["WINE REGISTRY Version 2", ""]
        for section in sections:
            lines.append(section)
        (self.path / "user.reg").write_text("\n".join(lines) + "\n",
                                            encoding="utf-8")

    def test_decorated_defaults_to_on(self):
        self.assertTrue(self.bottle.window_decorated)

    def test_reads_decorated_from_user_reg(self):
        self.write_user_reg('[Software\\\\Wine\\\\X11 Driver] 1',
                            '"Decorated"="N"')
        self.assertFalse(self.bottle.window_decorated)

    def test_set_decorated_writes_reg_value(self):
        ok, error = self.bottle.set_window_decorated(False)
        self.assertTrue(ok, error)
        self.assertEqual(self.commands,
                         ["reg add 'HKCU\\Software\\Wine\\X11 Driver' "
                          "/v Decorated /t REG_SZ /d N /f"])

    def test_virtual_desktop_defaults_to_off(self):
        self.assertEqual(self.bottle.virtual_desktop, "")

    def test_reads_virtual_desktop_from_user_reg(self):
        self.write_user_reg('[Software\\\\Wine\\\\Explorer\\\\Desktops] 1',
                            '"Default"="1280x720"')
        self.assertEqual(self.bottle.virtual_desktop, "1280x720")

    def test_set_virtual_desktop_writes_size(self):
        ok, error = self.bottle.set_virtual_desktop("1920x1080")
        self.assertTrue(ok, error)
        self.assertEqual(
            self.commands,
            ["reg add 'HKCU\\Software\\Wine\\Explorer\\Desktops' "
             "/v Default /t REG_SZ /d 1920x1080 /f"])

    def test_fullwidth_multiply_sign_is_accepted(self):
        ok, _error = self.bottle.set_virtual_desktop("1920×1080")
        self.assertTrue(ok)
        self.assertIn("/d 1920x1080", self.commands[0])

    def test_rejects_bad_size(self):
        ok, error = self.bottle.set_virtual_desktop("big")
        self.assertFalse(ok)
        self.assertIn("宽x高", error)
        self.assertEqual(self.commands, [])

    def test_empty_size_deletes_the_value(self):
        self.write_user_reg('[Software\\\\Wine\\\\Explorer\\\\Desktops] 1',
                            '"Default"="1280x720"')
        ok, error = self.bottle.set_virtual_desktop("")
        self.assertTrue(ok, error)
        self.assertEqual(
            self.commands,
            ["reg delete 'HKCU\\Software\\Wine\\Explorer\\Desktops' "
             "/v Default /f"])


if __name__ == "__main__":
    unittest.main()