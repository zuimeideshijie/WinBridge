"""Unit tests for the flatpak sandbox runtime plumbing.

These cover the parts that decide *how* a sandboxed bottle invokes Wine —
path rewriting, mount points, environment — plus the container-side switch.
Nothing here needs flatpak, Wine or a real prefix.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from winbridge.core import sandbox
from winbridge.core.bottle import Bottle
from winbridge.core.sandbox import SandboxRuntime


class WineRootTests(unittest.TestCase):
    def test_resolves_symlinked_wine_into_its_own_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "wine-stable"
            (root / "bin").mkdir(parents=True)
            (root / "lib").mkdir()
            real = root / "bin" / "wine"
            real.write_text("")
            link = Path(tmp) / "usr-bin-wine"
            link.symlink_to(real)

            self.assertEqual(sandbox.wine_root(str(link)), root)

    def test_rejects_system_wine(self):
        # A distro Wine lives in /usr; bind-mounting /usr would replace the
        # sandbox runtime's libc, so it must be refused.
        with mock.patch.object(sandbox.os.path, "realpath",
                               return_value="/usr/bin/wine"):
            self.assertIsNone(sandbox.wine_root("/usr/bin/wine"))


class SandboxCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # A fake GL extension deployment: lib/dri plus a Vulkan ICD.
        self.ext = Path(self.tmp.name) / "GL.default/files"
        (self.ext / "lib" / "dri").mkdir(parents=True)
        (self.ext / "lib" / "vulkan" / "icd.d").mkdir(parents=True)
        (self.ext / "lib" / "vulkan" / "icd.d" / "intel_icd.json").write_text("{}")
        self.patches = [
            mock.patch.object(sandbox, "extension_files",
                              lambda ext_id: [self.ext] if "GL" in ext_id else []),
            mock.patch.object(sandbox, "wine_root",
                              return_value=Path("/opt/wine-stable")),
        ]
        for p in self.patches:
            p.start()
        self.runtime = SandboxRuntime()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_mounts_home_wine_and_graphics_extensions(self):
        with mock.patch.object(sandbox.os.path, "realpath",
                               return_value="/opt/wine-stable/bin/wine"):
            cmd = self.runtime.command(["/usr/bin/wine", "run.exe"],
                                       "/usr/bin/wine", {"WINEPREFIX": "/p"})
        self.assertEqual(cmd[:2], ["flatpak", "run"])
        self.assertIn("--filesystem=home", cmd)
        self.assertIn("--filesystem=/opt/wine-stable:ro", cmd)
        self.assertIn(f"--filesystem={self.ext}:ro", cmd)
        self.assertIn("--command=bash", cmd)
        script = cmd[-1]
        self.assertIn("WINEPREFIX=/p", script)
        # The host-only /usr/bin symlink is replaced by its real target.
        self.assertIn("/opt/wine-stable/bin/wine", script)
        self.assertNotIn("/usr/bin/wine run.exe", script)

    def test_graphics_env_points_at_sandbox_mesa(self):
        with mock.patch.object(sandbox.os.path, "realpath",
                               return_value="/opt/wine-stable/bin/wine"):
            cmd = self.runtime.command(["/opt/wine-stable/bin/wine"],
                                       "/opt/wine-stable/bin/wine", {})
        script = cmd[-1]
        self.assertIn(f"LIBGL_DRIVERS_PATH={self.ext}/lib/dri", script)
        self.assertIn(f"VK_DRIVER_FILES=", script)

    def test_shell_command_keeps_wine_command_string(self):
        cmd = self.runtime.shell_command("wine reg query HKLM\\X",
                                         "/opt/wine-stable/bin/wine",
                                         {"WINEPREFIX": "/p"})
        self.assertEqual(cmd[:2], ["flatpak", "run"])
        self.assertIn("WINEPREFIX=/p", cmd[-1])
        self.assertIn("reg query HKLM\\X", cmd[-1])


class PrefixRuntimeLookupTests(unittest.TestCase):
    def _prefix(self, tmp, payload=None):
        prefix = Path(tmp) / "bottle"
        prefix.mkdir()
        if payload is not None:
            (prefix / "bottle.json").write_text(json.dumps(payload))
        return prefix

    def test_reads_flatpak_from_bottle_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = self._prefix(tmp, {"sandbox": "flatpak"})
            with mock.patch.object(sandbox, "app_installed", return_value=True):
                sandbox.forget_prefix_cache(str(prefix))
                self.assertIsNotNone(sandbox.sandbox_for_prefix(str(prefix)))
            sandbox.forget_prefix_cache(str(prefix))

    def test_host_mode_and_missing_app_mean_no_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = self._prefix(tmp, {"sandbox": "host"})
            self.assertIsNone(sandbox.sandbox_for_prefix(str(host)))

            legacy = Path(tmp) / "legacy"
            legacy.mkdir()
            (legacy / "bottle.json").write_text("{}")
            self.assertIsNone(sandbox.sandbox_for_prefix(str(legacy)))

            wanted = Path(tmp) / "wanted"
            wanted.mkdir()
            (wanted / "bottle.json").write_text('{"sandbox": "flatpak"}')
            with mock.patch.object(sandbox, "app_installed", return_value=False):
                sandbox.forget_prefix_cache(str(wanted))
                self.assertIsNone(sandbox.sandbox_for_prefix(str(wanted)))


class BottleRunTests(unittest.TestCase):
    def test_workdir_is_the_program_folder(self):
        # Old engines resolve their data files relative to the cwd; launching
        # from WinBridge's own directory makes them fail to initialize.
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "bottle"
            prefix.mkdir()
            (prefix / "user.reg").write_text("WINE REGISTRY Version 2\n")
            exe = Path(tmp) / "Game" / "Bin" / "Player.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("")

            bottle = Bottle(str(prefix))
            captured = {}
            bottle.wine = mock.Mock()
            bottle.wine.run.side_effect = lambda *a, **kw: captured.update(kw)

            self.assertTrue(bottle.run(str(exe)))
            self.assertEqual(captured.get("workdir"), str(exe.parent))


class CreateDialogRadioGroupsTests(unittest.TestCase):
    """Architecture and runtime must stay two independent radio groups.

    Qt auto-exclusives radio buttons that share a parent, so adding the
    runtime pair silently joined the arch pair: picking "flatpak 沙箱"
    unchecked the architecture.
    """

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:  # pragma: no cover - PyQt5 is a hard dependency
            raise unittest.SkipTest("PyQt5 未安装")
        cls.app = QApplication.instance() or QApplication([])

    def test_picking_runtime_keeps_architecture(self):
        from winbridge.ui.dialogs import CreateBottleDialog
        dialog = CreateBottleDialog()
        dialog.runtime_sandbox.setChecked(True)
        self.assertTrue(dialog.arch_64.isChecked())
        self.assertFalse(dialog.arch_32.isChecked())
        self.assertEqual(dialog.get_sandbox(), "flatpak")

    def test_picking_architecture_keeps_runtime(self):
        from winbridge.ui.dialogs import CreateBottleDialog
        dialog = CreateBottleDialog()
        dialog.runtime_sandbox.setChecked(True)
        dialog.arch_32.setChecked(True)
        self.assertFalse(dialog.arch_64.isChecked())
        self.assertTrue(dialog.runtime_sandbox.isChecked())
        self.assertEqual(dialog.get_sandbox(), "flatpak")


if __name__ == "__main__":
    unittest.main()