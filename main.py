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

    # Fusion renders identically on every desktop, so the stylesheet and the
    # palette are the only things that decide how the app looks.
    app.setStyle("Fusion")
    app.setPalette(theme_manager.build_palette())

    # Generate and apply the global stylesheet from the theme
    stylesheet = theme_manager.generate_stylesheet()
    app.setStyleSheet(stylesheet)


def _parse_launch_args(argv):
    """Parse ``--bottle NAME --run TARGET`` (used by desktop shortcuts)."""
    bottle = target = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--bottle" and i + 1 < len(argv):
            bottle = argv[i + 1]
            i += 2
        elif arg == "--run" and i + 1 < len(argv):
            target = argv[i + 1]
            i += 2
        else:
            i += 1
    return bottle, target


def _launch_and_exit(config, bottle_name: str, target: str):
    """Run a program inside a bottle without showing the window."""
    from winbridge.core.bottle import BottleManager

    manager = BottleManager(config)
    bottle = manager.get_bottle(bottle_name)
    if not bottle:
        print(f"未找到容器: {bottle_name}", file=sys.stderr)
        return 2
    if not os.path.exists(target):
        print(f"程序不存在: {target}", file=sys.stderr)
        return 3
    bottle.run(target)
    return 0


def main():
    """Application entry point."""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("WinBridge")
    app.setApplicationVersion("1.2.2")
    app.setOrganizationName("WinBridge")

    # Initialize theme
    config = Config()

    # Desktop shortcuts launch straight into the program, no window
    launch_bottle, launch_target = _parse_launch_args(sys.argv[1:])
    if launch_bottle and launch_target:
        sys.exit(_launch_and_exit(config, launch_bottle, launch_target))

    # Initialize theme manager with config
    _theme_manager = ThemeManager(config)

    # Apply initial theme
    apply_theme(app, _theme_manager)

    window = MainWindow(config, _theme_manager)
    window.show()

    # If launched with a file argument (double-click .exe/.msi/.lnk),
    # defer handling until the event loop starts so the window is shown first.
    file_args = [a for a in sys.argv[1:] if not a.startswith("-") and a != "winbridge"]
    if file_args:
        from PyQt5.QtCore import QTimer
        target = file_args[0]
        QTimer.singleShot(100, lambda: _open_file_in_window(window, target))

    sys.exit(app.exec_())


def _open_file_in_window(window, file_path):
    """Open a file (double-clicked .exe/.msi/.lnk) inside the main window.

    Shows an informative message for now; a future version will route the
    file to the appropriate bottle and launch it via Wine.
    """
    from PyQt5.QtWidgets import QMessageBox
    import os
    if not os.path.exists(file_path):
        return
    QMessageBox.information(
        window,
        "打开文件",
        f"已接收到文件:\n{file_path}\n\n请在 WinBridge 界面中选择对应容器并运行。",
    )


if __name__ == "__main__":
    main()