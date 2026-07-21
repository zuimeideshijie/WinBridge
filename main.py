#!/usr/bin/env python3
"""WinBridge - A Bottles-like Wine prefix manager.

Based on the cloned Wine build at ~/wine.
"""

import sys
import os

# Ensure the project root is in the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase
from winbridge.core.config import Config
from winbridge.core.theme import ThemeManager
from winbridge.ui.main_window import MainWindow

# Module-level theme manager singleton
_theme_manager = None


def get_theme() -> ThemeManager:
    """Get the global theme manager instance."""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager()
    return _theme_manager


def _find_cjk_font() -> str:
    """Find the best available UI font on the system."""
    fd = QFontDatabase()
    families = fd.families()
    preferred = [
        "Segoe UI",
        "Noto Sans CJK SC",
        "Microsoft YaHei",
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "Noto Sans CJK TC",
        "Noto Sans CJK JP",
        "Noto Sans CJK KR",
        "Noto Sans",
    ]
    for name in preferred:
        if name in families:
            return name
    for f in families:
        if "CJK" in f and "SC" in f and "Noto Sans" in f:
            return f
    return "sans-serif"


def apply_theme(app, theme_manager: ThemeManager):
    """Apply the current theme to the application."""
    font_name = _find_cjk_font()
    font = QFont(font_name, 10)
    font.setStyleHint(QFont.SansSerif, QFont.PreferDefault)
    app.setFont(font)

    # Generate and apply the global stylesheet from the theme
    stylesheet = theme_manager.generate_stylesheet()
    app.setStyleSheet(stylesheet)


def main():
    """Application entry point."""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("WinBridge")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("WinBridge")

    # Initialize theme
    config = Config()
    # Initialize theme manager with config
    _theme_manager = ThemeManager(config)

    # Apply initial theme
    apply_theme(app, _theme_manager)

    window = MainWindow(config, _theme_manager)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()