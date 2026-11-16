"""Tests for the one-click Wine runner installer."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from winbridge.core import wine_runtimes
from winbridge.core.wine_runtimes import WineRuntimeManager


def make_manager(tmp: Path):
    config = SimpleNamespace(
        data_dir=tmp,
        cache_dir=tmp / "cache",
        components_dir=tmp / "components",
        wine_path="/usr/bin/wine",
    )
    return WineRuntimeManager(config)


class ResolveAssetTests(unittest.TestCase):
    def test_picks_the_matching_asset(self):
        releases = [{
            "tag_name": "11.22",
            "assets": [
                {"name": "wine-11.22-x86.tar.xz", "size": 1,
                 "browser_download_url": "https://example/x86"},
                {"name": "wine-11.22-amd64.tar.xz", "size": 2,
                 "browser_download_url": "https://example/amd64"},
            ],
        }]
        with mock.patch.object(wine_runtimes, "_fetch_releases",
                               return_value=releases):
            asset = wine_runtimes.resolve_asset("wine11")
        self.assertEqual(asset["name"], "wine-11.22-amd64.tar.xz")
        self.assertEqual(asset["url"], "https://example/amd64")

    def test_skips_releases_without_the_expected_asset(self):
        releases = [
            {"tag_name": "12.0", "assets": [
                {"name": "wine-12.0-amd64.tar.xz", "size": 1,
                 "browser_download_url": "https://example/12"}]},
            {"tag_name": "11.9", "assets": [
                {"name": "wine-11.9-amd64.tar.xz", "size": 1,
                 "browser_download_url": "https://example/11"}]},
        ]
        with mock.patch.object(wine_runtimes, "_fetch_releases",
                               return_value=releases):
            asset = wine_runtimes.resolve_asset("wine11")
        self.assertEqual(asset["version"], "11.9")

    def test_offline_falls_back_to_the_pinned_release(self):
        with mock.patch.object(wine_runtimes, "_fetch_releases",
                               return_value=[]):
            asset = wine_runtimes.resolve_asset("wine11")
        self.assertEqual(asset["version"], "11.22")
        self.assertIn("wine-11.22-amd64.tar.xz", asset["url"])

    def test_soda_prefers_stable_over_experimental(self):
        releases = [
            {"tag_name": "soda-11.0-38-experimental", "assets": [
                {"name": "soda-11.0-38-experimental-x86_64.tar.xz",
                 "size": 1, "browser_download_url": "https://example/exp"}]},
            {"tag_name": "soda-11.0-10", "assets": [
                {"name": "soda-11.0-10-x86_64.tar.xz", "size": 1,
                 "browser_download_url": "https://example/stable"}]},
        ]
        with mock.patch.object(wine_runtimes, "_fetch_releases",
                               return_value=releases):
            asset = wine_runtimes.resolve_asset("soda")
        self.assertEqual(asset["version"], "soda-11.0-10")
        self.assertEqual(asset["url"], "https://example/stable")


class VersionKeyTests(unittest.TestCase):
    def test_prefixes_are_ignored(self):
        self.assertEqual(WineRuntimeManager.version_key("soda-11.0-10"),
                         (11, 0, 10))
        self.assertEqual(WineRuntimeManager.version_key("GE-Proton11-12"),
                         (11, 12))
        self.assertEqual(WineRuntimeManager.version_key("wine-11.22"),
                         (11, 22))

    def test_ordering(self):
        self.assertLess(WineRuntimeManager.version_key("soda-11.0-9"),
                        WineRuntimeManager.version_key("soda-11.0-10"))


class CheckUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.manager = make_manager(self.root)

    def add_runner(self, build_id: str, version: str, name: str = None):
        runner = self.root / "runners" / (name or f"{build_id}-{version}")
        (runner / "bin").mkdir(parents=True)
        wine = runner / "bin" / "wine"
        wine.write_text("")
        (runner / "runner.json").write_text(json.dumps({
            "id": build_id, "label": build_id, "version": version,
            "wine_path": str(wine),
        }), encoding="utf-8")

    def test_reports_newer_release(self):
        self.add_runner("soda", "soda-11.0-9")
        with mock.patch.object(wine_runtimes, "resolve_asset",
                               return_value={"version": "soda-11.0-10"}):
            updates = self.manager.check_updates()
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["latest_version"], "soda-11.0-10")

    def test_ignores_same_version_and_unknown_ids(self):
        self.add_runner("soda", "soda-11.0-10")
        self.add_runner("manual", "1.0", name="manual")
        with mock.patch.object(wine_runtimes, "resolve_asset",
                               return_value={"version": "soda-11.0-10"}):
            updates = self.manager.check_updates()
        self.assertEqual(updates, [])


class DeleteRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.manager = make_manager(self.root)

    def make_runner(self):
        runner = self.root / "runners" / "soda-soda-11.0-9"
        (runner / "bin").mkdir(parents=True)
        wine = runner / "bin" / "wine"
        wine.write_text("")
        (runner / "runner.json").write_text(json.dumps({
            "id": "soda", "label": "Soda 11", "version": "soda-11.0-9",
            "wine_path": str(wine),
        }), encoding="utf-8")
        return self.manager.installed()[0]

    def test_deletes_a_managed_runner(self):
        runner = self.make_runner()
        ok, _message = self.manager.delete_runner(runner)
        self.assertTrue(ok)
        self.assertFalse(Path(runner["path"]).exists())

    def test_refuses_a_path_outside_the_runner_directory(self):
        outside = self.root / "somewhere-else"
        outside.mkdir()
        ok, _message = self.manager.delete_runner(
            {"path": str(outside), "wine_path": str(outside / "bin" / "wine")})
        self.assertFalse(ok)
        self.assertTrue(outside.exists())


class SystemWinePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.wine_root = self.root / "wine-stable"
        (self.wine_root / "bin").mkdir(parents=True)
        self.wine = self.wine_root / "bin" / "wine"
        self.wine.write_text("")
        self.config = SimpleNamespace(
            wine_path=str(self.wine), data_dir=self.root,
            cache_dir=self.root / "cache",
            components_dir=self.root / "components")
        self.manager = WineRuntimeManager(self.config)

    def test_portable_tree_plan(self):
        with mock.patch.object(self.manager, "_dpkg_packages",
                               return_value=[]), \
             mock.patch.object(wine_runtimes.shutil, "which",
                               return_value="/usr/bin/pkexec"):
            plan = self.manager.system_wine_removal_plan()
        self.assertTrue(plan["removable"])
        self.assertEqual(plan["root"], str(self.wine_root))
        self.assertIn("pkexec", plan["command"])

    def test_package_managed_plan_uses_apt(self):
        fake_path = self.wine_root / "bin" / "wine"
        with mock.patch.object(self.manager, "_dpkg_packages",
                               return_value=["wine-stable"]), \
             mock.patch.object(wine_runtimes.shutil, "which",
                               return_value="/usr/bin/apt-get"):
            plan = self.manager.system_wine_removal_plan()
        self.assertTrue(plan["removable"])
        self.assertEqual(plan["packages"], ["wine-stable"])
        self.assertEqual(plan["command"][:4],
                         ["pkexec", "apt-get", "remove", "-y"])
        self.assertIn(str(fake_path), plan["path"])


class InstalledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.manager = make_manager(self.root)

    def test_reads_runner_json(self):
        runner = self.root / "runners" / "wine11-11.22"
        (runner / "bin").mkdir(parents=True)
        wine = runner / "bin" / "wine"
        wine.write_text("")
        (runner / "runner.json").write_text(json.dumps({
            "id": "wine11", "label": "Wine 11", "version": "11.22",
            "wine_path": str(wine),
        }), encoding="utf-8")

        installed = self.manager.installed()
        self.assertEqual(len(installed), 1)
        self.assertEqual(installed[0]["wine_path"], str(wine))

    def test_accepts_a_hand_installed_tree(self):
        runner = self.root / "runners" / "manual"
        (runner / "files" / "bin").mkdir(parents=True)
        (runner / "files" / "bin" / "wine").write_text("")

        installed = self.manager.installed()
        self.assertEqual(len(installed), 1)
        self.assertTrue(installed[0]["wine_path"].endswith("files/bin/wine"))

    def test_ignores_directories_without_wine(self):
        (self.root / "runners" / "broken").mkdir(parents=True)
        self.assertEqual(self.manager.installed(), [])


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_plain_wine_layout(self):
        (self.root / "wine-11.22" / "bin").mkdir(parents=True)
        (self.root / "wine-11.22" / "bin" / "wine").write_text("")
        source, relative = WineRuntimeManager._find_wine_root(
            self.root, "bin/wine")
        self.assertEqual(source, self.root / "wine-11.22")
        self.assertEqual(relative, "bin/wine")

    def test_proton_layout(self):
        (self.root / "GE-Proton" / "files" / "bin").mkdir(parents=True)
        (self.root / "GE-Proton" / "files" / "bin" / "wine").write_text("")
        source, relative = WineRuntimeManager._find_wine_root(
            self.root, "files/bin/wine")
        self.assertEqual(source, self.root / "GE-Proton")
        self.assertEqual(relative, "files/bin/wine")

    def test_flatten_archive_without_top_directory(self):
        extract = self.root / "extract"
        (extract / "bin").mkdir(parents=True)
        (extract / "bin" / "wine").write_text("")
        dest = self.root / "dest"
        WineRuntimeManager._move_tree(extract, dest, flatten=True)
        self.assertTrue((dest / "bin" / "wine").is_file())


class AvailableBuildsTests(unittest.TestCase):
    def test_exposes_the_requested_versions(self):
        ids = [build["id"] for build in wine_runtimes.available_builds()]
        self.assertEqual(ids, ["wine11", "soda", "proton11", "winege"])
        self.assertTrue(all(build["description"] for build in
                            wine_runtimes.available_builds()))


if __name__ == "__main__":
    unittest.main()