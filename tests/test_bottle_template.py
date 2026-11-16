"""Tests for the base template that makes new bottles come with .NET + fonts.

The template is a prepared prefix; creating a bottle from it is a copy instead
of a ~15 minute component install.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from winbridge.core import download
from winbridge.core.bottle import BottleManager


def make_prefix(root: Path, name: str, meta: dict = None) -> Path:
    path = root / name
    (path / "drive_c/windows/system32").mkdir(parents=True)
    (path / "drive_c/windows/system32/kernel32.dll").write_bytes(b"x")
    (path / "user.reg").write_text("WINE REGISTRY Version 2\n\n", encoding="utf-8")
    (path / "system.reg").write_text("WINE REGISTRY Version 2\n\n", encoding="utf-8")
    (path / "bottle.json").write_text(
        json.dumps(meta or {"name": name, "arch": "win64"}, ensure_ascii=False),
        encoding="utf-8")
    return path


def make_manager(tmp: Path) -> BottleManager:
    bottles = tmp / "bottles"
    bottles.mkdir()
    return BottleManager(SimpleNamespace(
        bottles_dir=bottles,
        data_dir=tmp / "data",
        cache_dir=tmp / "cache",
        wine_path="/opt/wine/bin/wine",
        wine_arch="win64"))


class TemplateKeyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = make_manager(self.root)

    def test_key_includes_arch_and_runtime(self):
        key = self.manager.template_key("win64", "/opt/wine-11/bin/wine")
        self.assertEqual(key, "win64-wine-11")

    def test_different_runtimes_get_different_keys(self):
        first = self.manager.template_key("win64", "/opt/soda-11/bin/wine")
        second = self.manager.template_key("win64", "/opt/ge-proton11/bin/wine")
        self.assertNotEqual(first, second)

    def test_template_missing_before_creation(self):
        self.assertFalse(self.manager.template_exists(
            "win64", "/opt/wine-11/bin/wine"))


class TemplateFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = make_manager(self.root)
        self.bottles = self.root / "bottles"

    def test_save_then_create_from_template(self):
        source = make_prefix(self.bottles, "prepared",
                             {"name": "prepared", "arch": "win64",
                              "installed_components": ["dotnet48"]})
        bottle = __import__("winbridge.core.bottle", fromlist=["Bottle"]).Bottle(
            str(source), config=self.manager.config)
        key = self.manager.save_template(bottle)
        self.assertEqual(key, "win64-wine")
        self.assertTrue(self.manager.template_exists("win64", "/opt/wine/bin/wine"))

        created, error = self.manager.bottle_from_template(
            "fresh", "win64", "/opt/wine/bin/wine")
        self.assertIsNotNone(created, error)
        self.assertEqual(created.name, "fresh")
        self.assertEqual(created.installed_components, ["dotnet48"])
        self.assertTrue((self.bottles / "fresh/drive_c/windows/system32/kernel32.dll").exists())

    def test_existing_name_gets_suffix_in_bottles_dir(self):
        source = make_prefix(self.bottles, "prepared")
        bottle = __import__("winbridge.core.bottle", fromlist=["Bottle"]).Bottle(
            str(source), config=self.manager.config)
        self.manager.save_template(bottle)
        make_prefix(self.bottles, "fresh")
        created, error = self.manager.bottle_from_template(
            "fresh", "win64", "/opt/wine/bin/wine")
        self.assertIsNotNone(created, error)
        self.assertEqual(created.name, "fresh__1")

    def test_sandboxed_bottle_is_not_templated(self):
        source = make_prefix(self.bottles, "prepared",
                             {"name": "prepared", "sandbox": "flatpak"})
        bottle = __import__("winbridge.core.bottle", fromlist=["Bottle"]).Bottle(
            str(source), config=self.manager.config)
        self.assertIsNone(self.manager.save_template(bottle))


class InstallDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = make_manager(self.root)
        self.bottle_path = make_prefix(self.root / "bottles", "target")
        self.bottle = __import__("winbridge.core.bottle", fromlist=["Bottle"]).Bottle(
            str(self.bottle_path), config=self.manager.config)

    def test_installs_every_default_and_records_them(self):
        calls = []

        class FakeManager:
            def __init__(self, config):
                self.config = config

            def install(self, name, path, progress=None, cancel_event=None):
                calls.append(name)
                return True, "", {"*mscoree": "native"}, []

        with mock.patch.object(download, "ComponentManager", FakeManager):
            failures = self.manager.install_default_components(self.bottle)

        self.assertEqual(failures, [])
        self.assertEqual(calls, list(BottleManager.DEFAULT_COMPONENTS))
        self.assertEqual(sorted(self.bottle.installed_components),
                         sorted(BottleManager.DEFAULT_COMPONENTS))
        self.assertEqual(self.bottle.dll_overrides.get("*mscoree"), "native")

    def test_failed_component_is_reported_and_others_continue(self):
        def fake_install(self_, name, path, progress=None, cancel_event=None):
            if name == "cjkfonts":
                return False, "下载失败", {}, []
            return True, "", {}, []

        with mock.patch.object(download.ComponentManager, "install", fake_install):
            failures = self.manager.install_default_components(self.bottle)

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], "cjkfonts")
        self.assertIn("dotnet48", self.bottle.installed_components)
        self.assertNotIn("cjkfonts", self.bottle.installed_components)

    def test_cancel_stops_early(self):
        import threading

        event = threading.Event()
        seen = []

        class FakeManager:
            def __init__(self, config):
                self.config = config

            def install(self, name, path, progress=None, cancel_event=None):
                seen.append(name)
                event.set()          # 第一个组件后立刻请求取消
                return True, "", {}, []

        with mock.patch.object(download, "ComponentManager", FakeManager):
            self.manager.install_default_components(self.bottle, cancel_event=event)

        self.assertEqual(seen, [BottleManager.DEFAULT_COMPONENTS[0]])


if __name__ == "__main__":
    unittest.main()

class CreateOrCloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = make_manager(self.root)
        self.bottles = self.root / "bottles"

    def _prepared_bottle(self):
        from winbridge.core.bottle import Bottle
        path = make_prefix(self.bottles, "prepared",
                           {"name": "prepared", "arch": "win64"})
        return Bottle(str(path), config=self.manager.config)

    def test_uses_template_when_present_and_preinstall_wanted(self):
        self.manager.save_template(self._prepared_bottle())
        bottle, from_template = self.manager.create_or_clone(
            "fresh", arch="win64", windows_version="win11",
            wine_path="/opt/wine/bin/wine", preinstall=True)
        self.assertIsNotNone(bottle)
        self.assertTrue(from_template)
        self.assertEqual(bottle.name, "fresh")
        self.assertEqual(bottle.windows_version, "win11")

    def test_ignores_template_without_preinstall(self):
        self.manager.save_template(self._prepared_bottle())
        # preinstall off -> falls through to create_bottle, which cannot work
        # without a real Wine, so the result is None (never a silent copy).
        bottle, from_template = self.manager.create_or_clone(
            "fresh", arch="win64", wine_path="/opt/wine/bin/wine",
            preinstall=False)
        self.assertIsNone(bottle)
        self.assertFalse(from_template)

    def test_ignores_template_for_sandbox(self):
        self.manager.save_template(self._prepared_bottle())
        bottle, from_template = self.manager.create_or_clone(
            "fresh", arch="win64", wine_path="/opt/wine/bin/wine",
            sandbox="flatpak", preinstall=True)
        self.assertIsNone(bottle)
        self.assertFalse(from_template)
