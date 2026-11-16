"""Tests for the task manager's selection handling and process naming."""

import os
import tempfile
import unittest
from pathlib import Path

from winbridge.core.wine import Wine


class RunnerEnvironmentTests(unittest.TestCase):
    def test_portable_runner_adds_its_own_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wine-runner"
            (root / "bin").mkdir(parents=True)
            (root / "lib").mkdir()
            wine = root / "bin" / "wine"
            wine.write_text("")

            environment = {"LD_LIBRARY_PATH": "/existing"}
            Wine(str(wine))._apply_runner_env(environment)
            parts = environment["LD_LIBRARY_PATH"].split(":")
            self.assertIn(str(root / "lib"), parts)
            self.assertEqual(parts[-1], "/existing")

    def test_distro_wine_is_left_alone(self):
        from unittest import mock
        environment = {}
        # /usr/bin/wine is a symlink to a portable tree on this machine, so
        # pin the resolved path to a real distro location.
        with mock.patch("winbridge.core.wine.Path.resolve",
                        return_value=Path("/usr/bin/wine")):
            Wine("/usr/bin/wine")._apply_runner_env(environment)
        self.assertNotIn("LD_LIBRARY_PATH", environment)


class ProcessNameTests(unittest.TestCase):
    def test_wine_command_reports_the_exe_name(self):
        self.assertEqual(
            Wine._process_name(["/usr/bin/wine", "C:\\Games\\App\\game.exe"]),
            "game.exe")

    def test_plain_binary_falls_back_to_its_basename(self):
        self.assertEqual(Wine._process_name(["/usr/bin/wineserver"]),
                         "wineserver")


class FakeWine:
    def __init__(self, processes):
        self.processes = processes
        self.queried = []

    def list_processes(self, bottle_path=None):
        self.queried.append(bottle_path)
        return list(self.processes)

    def kill_process(self, pid):
        return True

    wine_path = "/usr/bin/wine"


def make_process(pid: str, cpu: str = "1.0"):
    return {"pid": pid, "name": f"game{pid}.exe", "cpu": cpu,
            "memory": "2.0", "status": "S", "user": "me",
            "exe_path": f"game{pid}.exe"}


class TaskManagerSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("PyQt5 未安装")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from winbridge.ui.dialogs import TaskManagerDialog
        self.fake = FakeWine([make_process("100"), make_process("200")])
        self.dialog = TaskManagerDialog(self.fake, "/tmp/bottle")
        self.dialog.timer.stop()
        self.addCleanup(self.dialog.close)

    def test_refresh_keeps_the_selected_pid(self):
        self.dialog.process_table.selectRow(1)
        self.assertEqual(self.dialog._selected_pid(), "200")

        # Values change every 3 s; the process list itself does not.
        self.fake.processes = [make_process("100", "9.9"),
                               make_process("200", "8.8")]
        self.dialog.refresh_processes()

        self.assertEqual(self.dialog._selected_pid(), "200")
        self.assertTrue(self.dialog.btn_end.isEnabled())

    def test_selection_disappears_when_the_process_exits(self):
        self.dialog.process_table.selectRow(0)
        self.fake.processes = [make_process("200")]
        self.dialog.refresh_processes()
        self.assertEqual(self.dialog._selected_pid(), "")
        self.assertFalse(self.dialog.btn_end.isEnabled())

    def test_bottle_path_is_passed_to_the_process_list(self):
        self.dialog.refresh_processes()
        self.assertEqual(self.fake.queried[-1], "/tmp/bottle")


if __name__ == "__main__":
    unittest.main()