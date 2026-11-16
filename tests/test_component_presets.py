"""Tests for locating pre-downloaded component payloads.

The .deb and a source checkout resolve ``components_dir`` differently, and
older trees keep the winetricks presets under "winetricks-cache" instead of
"winetricks". Getting this wrong is silent: every component still "works",
it just re-downloads hundreds of megabytes first, which is exactly where
installs fail on a slow network.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from winbridge.core.config import Config
from winbridge.core.download import ComponentManager


def make_manager(root: Path, cache_dir: Path = None) -> ComponentManager:
    manager = ComponentManager.__new__(ComponentManager)
    manager.config = SimpleNamespace(
        components_dir=root,
        cache_dir=cache_dir or root / "cache",
        wine_path="/usr/bin/wine",
    )
    manager._github_mirror = None
    return manager


class ComponentsDirSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def make(self, name: str, preset: str = None) -> Path:
        path = self.root / name
        path.mkdir(parents=True)
        if preset:
            (path / preset / "corefonts").mkdir(parents=True)
        return path

    def test_prefers_dir_with_new_presets(self):
        empty = self.make("empty")
        full = self.make("full", "winetricks")
        self.assertEqual(
            Config.pick_components_dir([empty, full], self.root / "fallback"),
            full)

    def test_accepts_legacy_winetricks_cache(self):
        legacy = self.make("legacy", "winetricks-cache")
        empty = self.make("empty")
        self.assertEqual(
            Config.pick_components_dir([empty, legacy], self.root / "fallback"),
            legacy)

    def test_falls_back_to_first_existing_without_presets(self):
        empty = self.make("empty")
        self.assertEqual(
            Config.pick_components_dir([empty, self.root / "missing"],
                                       self.root / "fallback"),
            empty)

    def test_falls_back_when_nothing_exists(self):
        fallback = self.root / "fallback"
        self.assertEqual(
            Config.pick_components_dir([self.root / "missing"], fallback),
            fallback)

    def test_presets_dir_prefers_new_name(self):
        root = self.make("bottle", "winetricks")
        (root / "winetricks-cache").mkdir()
        config = Config.__new__(Config)
        config.components_dir = root
        self.assertEqual(config.presets_dir, root / "winetricks")

    def test_presets_dir_uses_legacy_name(self):
        root = self.make("bottle", "winetricks-cache")
        config = Config.__new__(Config)
        config.components_dir = root
        self.assertEqual(config.presets_dir, root / "winetricks-cache")


class PresetLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "components"
        self.root.mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def test_preset_dirs_accepts_legacy_name(self):
        legacy = self.root / "winetricks-cache"
        legacy.mkdir()
        manager = make_manager(self.root)
        self.assertEqual(manager._preset_dirs(), [legacy])

    def test_preset_dirs_lists_both_names(self):
        new = self.root / "winetricks"
        legacy = self.root / "winetricks-cache"
        new.mkdir()
        legacy.mkdir()
        manager = make_manager(self.root)
        self.assertEqual(manager._preset_dirs(), [new, legacy])

    def test_payload_dirs_include_cache(self):
        legacy = self.root / "winetricks-cache"
        legacy.mkdir()
        cache = self.root / "cache" / "winetricks"
        cache.mkdir(parents=True)
        manager = make_manager(self.root)
        self.assertEqual(manager._payload_dirs(), [legacy, cache])

    def test_allfonts_copies_from_legacy_preset(self):
        package = self.root / "winetricks-cache" / "corefonts"
        package.mkdir(parents=True)
        (package / "arial.ttf").write_bytes(b"\0\0\1\0" + b"\0" * 16)
        bottle = Path(self.tmp.name) / "bottle"
        (bottle / "drive_c").mkdir(parents=True)

        manager = make_manager(self.root)
        with mock.patch.object(ComponentManager, "_wine_for_bottle",
                               side_effect=RuntimeError("no wine in tests")):
            ok, error, overrides, _files = manager._install_direct(
                "allfonts", {"label": "All Fonts"}, str(bottle))
        self.assertTrue(ok, error)
        self.assertTrue(
            (bottle / "drive_c/windows/Fonts/arial.ttf").exists())
        self.assertEqual(overrides, {})

    def test_allfonts_reports_missing_presets(self):
        bottle = Path(self.tmp.name) / "bottle"
        bottle.mkdir()
        manager = make_manager(self.root)
        ok, error, _overrides, _files = manager._install_direct(
            "allfonts", {"label": "All Fonts"}, str(bottle))
        self.assertFalse(ok)
        self.assertIn("没有找到预置字体缓存", error)


if __name__ == "__main__":
    unittest.main()