"""Tests for the "add program" and "run the app's own uninstaller" changes."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from winbridge.core import shortcuts
from winbridge.core.bottle import Bottle


def make_bottle(path: Path) -> Bottle:
    return Bottle(str(path), config=SimpleNamespace(
        wine_path="/usr/bin/wine", wine_arch="win64"))


def make_app(bottle: Path, name: str = "MyApp") -> Path:
    """A program installed under Program Files, like a real installer."""
    app_dir = bottle / "drive_c" / "Program Files" / name
    app_dir.mkdir(parents=True)
    exe = app_dir / f"{name}.exe"
    exe.write_bytes(b"MZ" + b"\0" * 64)
    return exe


def write_registry(bottle: Path, key: str, values: dict):
    """Write a single Uninstall section the way wine stores it."""
    lines = [f"[Software\\\\Microsoft\\\\Windows\\\\CurrentVersion"
             f"\\\\Uninstall\\\\{key}] 1"]
    lines += [f'"{name}"="{value}"' for name, value in values.items()]
    (bottle / "system.reg").write_text(
        "WINE REGISTRY Version 2\n\n" + "\n".join(lines) + "\n\n",
        encoding="utf-8")


class FindUninstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bottle = Path(self.tmp.name) / "bottle"
        self.bottle.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_finds_innosetup_uninstaller_next_to_app(self):
        exe = make_app(self.bottle)
        uninstaller = exe.parent / "unins000.exe"
        uninstaller.write_bytes(b"MZ" + b"\0" * 64)

        plan = shortcuts.plan_uninstall(exe, self.bottle)
        program, args = shortcuts.find_uninstaller(plan, self.bottle)

        self.assertEqual(program, str(uninstaller))
        self.assertEqual(args, [])

    def test_finds_differently_named_uninstaller(self):
        exe = make_app(self.bottle)
        uninstaller = exe.parent / "Uninstall MyApp.exe"
        uninstaller.write_bytes(b"MZ" + b"\0" * 64)

        plan = shortcuts.plan_uninstall(exe, self.bottle)
        program, _ = shortcuts.find_uninstaller(plan, self.bottle)

        self.assertEqual(program, str(uninstaller))

    def test_ignores_non_pe_files(self):
        exe = make_app(self.bottle)
        fake = exe.parent / "uninstall.exe"
        fake.write_text("not an executable")
        plan = shortcuts.plan_uninstall(exe, self.bottle)
        self.assertEqual(shortcuts.find_uninstaller(plan, self.bottle), ("", []))

    def test_falls_back_to_registry_uninstall_string(self):
        exe = make_app(self.bottle)
        # Uninstaller lives below the app root, so the folder scan misses it
        bin_dir = exe.parent / "bin"
        bin_dir.mkdir()
        uninstaller = bin_dir / "uninstall.exe"
        uninstaller.write_bytes(b"MZ" + b"\0" * 64)
        write_registry(self.bottle, "MyApp", {
            "DisplayName": "My App",
            "InstallLocation": r"C:\\Program Files\\MyApp\\",
            "UninstallString": r"C:\\Program Files\\MyApp\\bin\\uninstall.exe /S",
        })

        plan = shortcuts.plan_uninstall(exe, self.bottle)
        program, args = shortcuts.find_uninstaller(plan, self.bottle)

        self.assertEqual(program, str(uninstaller))
        self.assertEqual(args, ["/S"])

    def test_msi_entry_becomes_msiexec(self):
        exe = make_app(self.bottle)
        write_registry(self.bottle, "{1234}", {
            "DisplayName": "My App",
            "InstallLocation": r"C:\\Program Files\\MyApp\\",
            "UninstallString": "MsiExec.exe /X{1234}",
        })

        plan = shortcuts.plan_uninstall(exe, self.bottle)
        program, args = shortcuts.find_uninstaller(plan, self.bottle)

        self.assertEqual(program, "msiexec")
        self.assertEqual(args, ["/X{1234}"])

    def test_registry_entry_for_another_app_is_ignored(self):
        exe = make_app(self.bottle)
        write_registry(self.bottle, "Other", {
            "InstallLocation": r"C:\\Program Files\\Other\\",
            "UninstallString": r"C:\\Program Files\\Other\\uninstall.exe",
        })

        plan = shortcuts.plan_uninstall(exe, self.bottle)
        self.assertEqual(shortcuts.find_uninstaller(plan, self.bottle), ("", []))


class AddShortcutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bottle"
        self.path.mkdir()
        self.addCleanup(self.tmp.cleanup)
        self.bottle = make_bottle(self.path)

    def test_add_and_reload(self):
        self.assertTrue(self.bottle.add_shortcut(
            "PCL", "/home/zuimeideshijie/Desktop/Plain Craft Launcher 2.exe",
            "exe", "/tmp/icon.ico"))

        reloaded = make_bottle(self.path)
        targets = [s["target"] for s in reloaded.shortcuts]
        self.assertIn("/home/zuimeideshijie/Desktop/Plain Craft Launcher 2.exe",
                      targets)

    def test_duplicate_target_is_rejected(self):
        target = "/tmp/app.exe"
        self.assertTrue(self.bottle.add_shortcut("App", target))
        self.assertFalse(self.bottle.add_shortcut("App again", target))
        self.assertEqual(len(self.bottle.shortcuts), 1)


class MissingTargetTests(unittest.TestCase):
    """The 刷新 button offers to drop shortcuts whose program is gone."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_reports_only_vanished_programs(self):
        alive = self.dir / "alive.exe"
        alive.write_bytes(b"MZ")
        entries = [
            {"name": "Alive", "target": str(alive)},
            {"name": "Gone", "target": str(self.dir / "gone.exe")},
            {"name": "NoTarget"},
        ]
        missing = shortcuts.missing_targets(entries)
        self.assertEqual([entry["name"] for entry in missing], ["Gone"])

    def test_empty_input(self):
        self.assertEqual(shortcuts.missing_targets([]), [])
        self.assertEqual(shortcuts.missing_targets(None), [])


class ForgetUnderTests(unittest.TestCase):
    """Deleting an app folder drops all of its sibling shortcut entries."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bottle"
        self.path.mkdir()
        self.addCleanup(self.tmp.cleanup)
        self.bottle = make_bottle(self.path)

    def test_drops_entries_inside_the_removed_folder(self):
        app_dir = self.path / "drive_c" / "Program Files" / "MyApp"
        app_dir.mkdir(parents=True)
        main = app_dir / "MyApp.exe"
        updater = app_dir / "Update.exe"
        for exe in (main, updater):
            exe.write_bytes(b"MZ")
        other = self.path / "drive_c" / "Program Files" / "Other.exe"
        other.write_bytes(b"MZ")

        self.bottle.add_shortcut("MyApp", str(main))
        self.bottle.add_shortcut("Update", str(updater))
        self.bottle.add_shortcut("Other", str(other))

        removed = self.bottle.forget_shortcuts_under(app_dir)

        self.assertEqual(removed, 2)
        self.assertEqual([s["name"] for s in self.bottle.shortcuts], ["Other"])

    def test_keeps_everything_when_nothing_matches(self):
        entry = self.path / "drive_c" / "Program Files" / "App.exe"
        entry.parent.mkdir(parents=True)
        entry.write_bytes(b"MZ")
        self.bottle.add_shortcut("App", str(entry))

        self.assertEqual(
            self.bottle.forget_shortcuts_under(self.path / "drive_c" / "Nothing"),
            0)
        self.assertEqual(len(self.bottle.shortcuts), 1)


if __name__ == "__main__":
    unittest.main()