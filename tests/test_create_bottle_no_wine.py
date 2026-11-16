"""A machine without Wine must say so, not fail with "创建失败".

The .deb only Recommends Wine, so a fresh install can have neither a system
Wine nor a downloaded runner.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from winbridge.core import bottle as bottle_module  # noqa: E402
from winbridge.ui import dialogs  # noqa: E402

_app = None


def app():
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def make_config(tmp: Path) -> SimpleNamespace:
    return SimpleNamespace(
        bottles_dir=tmp / "bottles",
        data_dir=tmp / "data",
        cache_dir=tmp / "cache",
        wine_path=str(tmp / "missing" / "wine"),
        wine_arch="win64",
        config_dir=tmp / "config",
    )


class NoUsableWineTests(unittest.TestCase):
    def setUp(self):
        app()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = make_config(Path(self.tmp.name))
        self.patch = mock.patch.object(
            dialogs.WineRuntimeManager, "installed", return_value=[])
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.dialog = dialogs.CreateBottleDialog(self.config)

    def test_no_path_is_reported_instead_of_config_path(self):
        self.assertEqual(self.dialog.get_wine_path(), "")

    def test_hint_says_nothing_is_installed(self):
        self.assertIn("未检测到系统 Wine", self.dialog.wine_ver_hint.text())

    def test_accept_is_refused_without_wine(self):
        with mock.patch.object(QMessageBox, "exec_", return_value=0):
            self.dialog.accept()
        self.assertNotEqual(self.dialog.result(), QDialog.Accepted)

    def test_accept_works_when_a_real_wine_is_selected(self):
        fake = Path(self.tmp.name) / "wine"
        fake.write_text("#!/bin/sh\necho wine-11.0\n")
        fake.chmod(0o755)
        self.dialog.wine_source_combo.addItem("测试", str(fake))
        self.dialog.wine_source_combo.setCurrentIndex(
            self.dialog.wine_source_combo.count() - 1)
        self.assertEqual(self.dialog.get_wine_path(), str(fake))
        self.dialog.accept()
        self.assertEqual(self.dialog.result(), QDialog.Accepted)


class CreateBottleGuardTests(unittest.TestCase):
    def test_create_bottle_refuses_missing_wine(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = make_config(Path(tmp))
            config.bottles_dir.mkdir(parents=True, exist_ok=True)
            manager = bottle_module.BottleManager(config)
            self.assertIsNone(manager.create_bottle("test"))


if __name__ == "__main__":
    unittest.main()