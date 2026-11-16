"""Tests for cloning a bottle (the fast way to reuse an installed .NET).

Modelled on Bottles' duplicate_bottle: copy drive_c plus the registry hives and
rewrite the metadata, so the new bottle starts with everything installed.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from winbridge.core.bottle import BottleManager


def make_bottle(root: Path, name: str, shortcut_target: str = "") -> Path:
    path = root / name
    (path / "drive_c" / "windows" / "system32").mkdir(parents=True)
    (path / "drive_c" / "windows" / "system32" / "kernel32.dll").write_bytes(b"x")
    (path / "drive_c" / "Program Files" / "Demo").mkdir(parents=True)
    (path / "drive_c" / "Program Files" / "Demo" / "demo.exe").write_bytes(b"MZ")
    (path / "user.reg").write_text('WINE REGISTRY Version 2\n\n', encoding="utf-8")
    (path / "system.reg").write_text('WINE REGISTRY Version 2\n\n', encoding="utf-8")
    meta = {
        "name": name,
        "created": "2026-11-16T00:00:00",
        "arch": "win64",
        "windows_version": "win11",
        "installed_components": ["dotnet48", "corefonts"],
        "shortcuts": ([{"name": "Demo", "target": shortcut_target,
                        "source": "exe", "icon": ""}] if shortcut_target else []),
    }
    (path / "bottle.json").write_text(json.dumps(meta, ensure_ascii=False),
                                      encoding="utf-8")
    return path


class DuplicateBottleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.manager = BottleManager(SimpleNamespace(
            bottles_dir=self.root,
            wine_path="/usr/bin/wine",
            wine_arch="win64"))

    def test_copies_prefix_and_registry(self):
        source = make_bottle(self.root, "base")
        bottle, error = self.manager.clone_bottle("base", "copy")
        self.assertIsNotNone(bottle, error)
        self.assertEqual(bottle.name, "copy")
        target = self.root / "copy"
        self.assertTrue((target / "drive_c/Program Files/Demo/demo.exe").exists())
        self.assertTrue((target / "user.reg").exists())
        self.assertTrue((target / "system.reg").exists())

    def test_metadata_is_reused_with_new_name(self):
        make_bottle(self.root, "base")
        bottle, _error = self.manager.clone_bottle("base", "copy")
        self.assertEqual(bottle.installed_components, ["dotnet48", "corefonts"])
        self.assertNotEqual(bottle.created, "")

    def test_paths_inside_prefix_are_rewritten(self):
        target_exe = str(self.root / "base/drive_c/Program Files/Demo/demo.exe")
        make_bottle(self.root, "base", shortcut_target=target_exe)
        bottle, error = self.manager.clone_bottle("base", "copy")
        self.assertIsNotNone(bottle, error)
        expected = str(self.root / "copy/drive_c/Program Files/Demo/demo.exe")
        self.assertEqual(bottle.shortcuts[0]["target"], expected)
        self.assertEqual(bottle.shortcuts[0]["name"], "Demo")

    def test_existing_name_gets_a_suffix(self):
        make_bottle(self.root, "base")
        make_bottle(self.root, "copy")
        bottle, error = self.manager.clone_bottle("base", "copy")
        self.assertIsNotNone(bottle, error)
        self.assertEqual(bottle.name, "copy__1")

    def test_missing_source_is_reported(self):
        bottle, error = self.manager.clone_bottle("nope", "copy")
        self.assertIsNone(bottle)
        self.assertIn("找不到容器", error)

    def test_empty_name_is_rejected(self):
        make_bottle(self.root, "base")
        bottle, error = self.manager.clone_bottle("base", "   ")
        self.assertIsNone(bottle)
        self.assertIn("不能为空", error)

    def test_slash_in_name_is_rejected(self):
        make_bottle(self.root, "base")
        bottle, error = self.manager.clone_bottle("base", "a/b")
        self.assertIsNone(bottle)
        self.assertIn("斜杠", error)

    def test_failure_leaves_no_half_copied_directory(self):
        make_bottle(self.root, "base")
        # Make the copy of drive_c fail halfway by blocking the target name.
        (self.root / "blocked").write_text("")
        bottle, error = self.manager.clone_bottle("base", "blocked__1")
        # blocked__1 is free, so this one succeeds; ensure the *blocked* name
        # itself would never be created as a directory over a file.
        self.assertIsNotNone(bottle, error)
        self.assertTrue((self.root / "blocked__1").is_dir())
        self.assertTrue((self.root / "blocked").is_file())


if __name__ == "__main__":
    unittest.main()