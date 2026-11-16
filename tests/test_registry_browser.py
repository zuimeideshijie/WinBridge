"""Tests for the registry helpers and the value editor."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from winbridge.core import registry


def sample_reg_text() -> str:
    return "\n".join([
        "WINE REGISTRY Version 2",
        "",
        "[Software\\\\Demo] 1",
        '"OldString"="hello"',
        '"Dword"=dword:00000019',
        '"Binary"=hex:01,02,ab',
        '"MultiOld"=hex(7):61,00,00,00,62,00,00,00,00,00',
        '"MultiNew"=str(7):"a\\0b\\0"',
        '"Expand"=str(2):"%TEMP%\\\\x"',
        "@=\"default\"",
        "",
        "[Software\\\\Demo\\\\Child] 1",
        '"Other"="x"',
    ]) + "\n"


class DecodeValueTests(unittest.TestCase):
    def test_old_and_new_string_forms(self):
        self.assertEqual(registry.decode_value('"hello"'), ("REG_SZ", "hello"))
        self.assertEqual(registry.decode_value('str(2):"%TEMP%\\\\x"'),
                         ("REG_EXPAND_SZ", "%TEMP%\\x"))

    def test_multi_string_both_forms(self):
        self.assertEqual(
            registry.decode_value('hex(7):61,00,00,00,62,00,00,00,00,00'),
            ("REG_MULTI_SZ", "a\nb"))
        self.assertEqual(registry.decode_value('str(7):"a\\0b\\0"'),
                         ("REG_MULTI_SZ", "a\nb"))

    def test_numbers_and_binary(self):
        self.assertEqual(registry.decode_value("dword:00000019"),
                         ("REG_DWORD", "25"))
        self.assertEqual(
            registry.decode_value("hex(b):02,00,00,00,01,00,00,00"),
            ("REG_QWORD", "4294967298"))
        self.assertEqual(registry.decode_value("hex:01,02,ab"),
                         ("REG_BINARY", "01 02 AB"))


class ParseValuesTests(unittest.TestCase):
    def test_reads_only_the_requested_key(self):
        key = "HKCU" + registry.SEP + "Software" + registry.SEP + "Demo"
        values = registry.parse_values(sample_reg_text(), key)
        names = [value["display_name"] for value in values]
        self.assertIn("OldString", names)
        self.assertIn("(默认)", names)
        self.assertNotIn("Other", names)
        by_name = {value["name"]: value for value in values}
        self.assertEqual(by_name["MultiNew"]["data"], "a\nb")
        self.assertEqual(by_name["Dword"]["type"], "REG_DWORD")

    def test_tree_path_uses_doubled_backslashes(self):
        key = "HKLM" + registry.SEP + "System" + registry.SEP + "Current"
        self.assertEqual(registry.win_reg_path(key),
                         "HKLM\\System\\Current")


class NormalizeValueTests(unittest.TestCase):
    def test_dword_accepts_hex(self):
        self.assertEqual(registry.normalize_value("REG_DWORD", "0x10"),
                         ("16", ""))

    def test_bad_dword_is_rejected(self):
        _, error = registry.normalize_value("REG_DWORD", "not-a-number")
        self.assertTrue(error)

    def test_binary_strips_separators(self):
        self.assertEqual(registry.normalize_value("REG_BINARY", "01 02 ab"),
                         ("0102ab", ""))
        _, error = registry.normalize_value("REG_BINARY", "0x1")
        self.assertTrue(error)

    def test_multi_string_uses_wine_separator(self):
        self.assertEqual(registry.normalize_value("REG_MULTI_SZ", "a\nb\n"),
                         ("a\\0b", ""))

    def test_add_value_args_for_default_value(self):
        args, error = registry.add_value_args("", "REG_SZ", "hi")
        self.assertEqual(error, "")
        self.assertEqual(args, ["/ve", "/t", "REG_SZ", "/d", "hi", "/f"])


class RegistryBrowserTests(unittest.TestCase):
    """The value table must show names, types and decoded data."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt5.QtWidgets import QApplication
        except ImportError:  # pragma: no cover
            raise unittest.SkipTest("PyQt5 未安装")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = Path(self.tmp.name) / "bottle"
        (self.prefix / "drive_c").mkdir(parents=True)
        (self.prefix / "user.reg").write_text(sample_reg_text(), encoding="utf-8")
        (self.prefix / "system.reg").write_text("WINE REGISTRY Version 2\n",
                                               encoding="utf-8")
        self.config = SimpleNamespace(
            wine_path="/usr/bin/wine", wine_arch="win64",
            cache_dir=Path(self.tmp.name) / "cache",
            components_dir=Path(self.tmp.name) / "components",
            bottles_dir=Path(self.tmp.name) / "bottles",
            data_dir=Path(self.tmp.name),
            get=lambda key, default=None: default,
        )
        self.addCleanup(self.tmp.cleanup)

        from winbridge.core.bottle import Bottle
        from winbridge.ui.bottle_detail import BottleDetailWidget
        self.widget = BottleDetailWidget(self.config)
        self.widget.current_bottle = Bottle(str(self.prefix), config=self.config)
        self.key = (f"HKCU{registry.SEP}Software{registry.SEP}Demo")

    def test_values_are_loaded_with_types(self):
        self.widget._build_registry_tree([self.key])
        self.widget._select_registry_match(self.key)

        names = [self.widget.reg_value_table.item(row, 0).text()
                 for row in range(self.widget.reg_value_table.rowCount())]
        self.assertIn("Dword", names)
        self.assertIn("(默认)", names)
        row = names.index("Dword")
        self.assertEqual(self.widget.reg_value_table.item(row, 1).text(),
                         "REG_DWORD")
        self.assertEqual(self.widget.reg_value_table.item(row, 2).text(), "25")

    def test_selected_value_entry_matches_row(self):
        self.widget._build_registry_tree([self.key])
        self.widget._select_registry_match(self.key)
        self.widget.reg_value_table.selectRow(0)
        entry = self.widget._selected_value_entry()
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "OldString")

    def test_search_finds_keys_and_values(self):
        self.widget._build_registry_tree([self.key])
        matches = self.widget._collect_registry_matches("demo")
        self.assertTrue(any(path.endswith("Demo") for path, _name in matches))
        matches = self.widget._collect_registry_matches("oldstring")
        self.assertIn(("HKCU" + registry.SEP + "Software" + registry.SEP
                       + "Demo", "OldString"), matches)


if __name__ == "__main__":
    unittest.main()