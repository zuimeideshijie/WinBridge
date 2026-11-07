"""Theme manager for WinBridge — one design system, light and dark.

Visual rules (kept deliberately narrow so the app looks like a tool, not a
template):

* Flat surfaces only. No gradients, no drop shadows, no rounded pills.
* One accent colour per theme; everything else is neutral grey.
* Hierarchy comes from type scale and surface tints, not from colour.
* Every widget style lives here. Screens code sets ``objectName`` roles
  (``btnPrimary``, ``card``, ``sectionTitle`` ...) instead of inline QSS.
"""

from enum import Enum


class ThemeMode(Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


THEMES = {
    "light": {
        "name": "明色",
        # Surfaces
        "bg_app": "#F4F5F7",
        "bg_surface": "#FFFFFF",
        "bg_surface_alt": "#FAFBFC",
        "bg_sunken": "#EDEFF3",
        "bg_input": "#FFFFFF",
        "bg_hover": "#EDF0F4",
        "bg_selected": "#E3ECF9",
        "bg_header": "#FFFFFF",
        "bg_sidebar": "#FAFBFC",
        "bg_toolbar": "#FFFFFF",
        "bg_status": "#FAFBFC",
        # Lines
        "border": "#DDE1E6",
        "border_strong": "#C6CBD2",
        "border_focus": "#1F6FEB",
        # Text
        "text_primary": "#171A1F",
        "text_secondary": "#4B5563",
        "text_muted": "#7C8698",
        "text_disabled": "#A8B0BC",
        "text_on_accent": "#FFFFFF",
        # Accent
        "accent": "#1F6FEB",
        "accent_hover": "#1A5FC9",
        "accent_pressed": "#1650AC",
        "accent_soft": "#E8F0FD",
        # Status
        "success": "#1A7F37",
        "success_soft": "#E6F4EA",
        "warning": "#9A6700",
        "warning_soft": "#FFF4E0",
        "danger": "#CF222E",
        "danger_soft": "#FDECEC",
        # Neutral chip
        "chip_bg": "#EDEFF3",
        "chip_text": "#4B5563",
        # Tooltip
        "tooltip_bg": "#1F242C",
        "tooltip_text": "#F2F4F7",
        # Scrollbar
        "scroll_bg": "transparent",
        "scroll_handle": "#C9CFD8",
        "scroll_handle_hover": "#AEB6C2",
        # Selection in tables / lists
        "table_header_bg": "#F7F8FA",
        "table_alt_row": "#FBFCFD",
        "code_bg": "#F6F7F9",
    },
    "dark": {
        "name": "暗色",
        # Surfaces
        "bg_app": "#101317",
        "bg_surface": "#171B21",
        "bg_surface_alt": "#1C2129",
        "bg_sunken": "#0C0F13",
        "bg_input": "#1B2028",
        "bg_hover": "#222833",
        "bg_selected": "#1E2E45",
        "bg_header": "#171B21",
        "bg_sidebar": "#13171C",
        "bg_toolbar": "#171B21",
        "bg_status": "#13171C",
        # Lines
        "border": "#2A313B",
        "border_strong": "#3A424E",
        "border_focus": "#4C8DF6",
        # Text
        "text_primary": "#E7EAF0",
        "text_secondary": "#A7B0BD",
        "text_muted": "#78828F",
        "text_disabled": "#4E5764",
        "text_on_accent": "#FFFFFF",
        # Accent
        "accent": "#4C8DF6",
        "accent_hover": "#6BA0FF",
        "accent_pressed": "#3C79D8",
        "accent_soft": "#17263C",
        # Status
        "success": "#3FB950",
        "success_soft": "#12281A",
        "warning": "#D29922",
        "warning_soft": "#2A2113",
        "danger": "#F85149",
        "danger_soft": "#2C1618",
        # Neutral chip
        "chip_bg": "#222833",
        "chip_text": "#A7B0BD",
        # Tooltip
        "tooltip_bg": "#2A313B",
        "tooltip_text": "#E7EAF0",
        # Scrollbar
        "scroll_bg": "transparent",
        "scroll_handle": "#39414D",
        "scroll_handle_hover": "#4A5462",
        # Selection in tables / lists
        "table_header_bg": "#1C2129",
        "table_alt_row": "#1A1F26",
        "code_bg": "#12161B",
    },
}


class ThemeManager:
    """Owns the active palette and builds the application stylesheet."""

    def __init__(self, config=None):
        self.config = config
        self._mode = ThemeMode.LIGHT
        self._active = "light"
        self._palette = {}
        self._load()

    # ------------------------------------------------------------------ state
    def _load(self):
        saved = self.config.get("theme_mode", "system") if self.config else "system"
        self.set_mode(saved, save=False)

    def set_mode(self, mode: str, save: bool = True):
        """Set theme mode: 'light', 'dark' or 'system'."""
        if mode not in ("light", "dark", "system"):
            mode = "system"
        self._mode = ThemeMode(mode)
        if mode == "system":
            self._active = self._detect_system()
        else:
            self._active = mode
        self._palette = THEMES[self._active]
        if save and self.config:
            self.config.set("theme_mode", mode)

    def _detect_system(self) -> str:
        """Detect the desktop's light/dark preference."""
        try:
            import subprocess
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=2,
            )
            if "dark" in result.stdout.lower():
                return "dark"
        except Exception:
            pass
        # KDE stores the active scheme in kdeglobals
        try:
            from pathlib import Path
            kdeglobals = Path.home() / ".config" / "kdeglobals"
            if kdeglobals.exists():
                for line in kdeglobals.read_text(errors="ignore").splitlines():
                    if line.startswith("ColorScheme") and "Dark" in line:
                        return "dark"
        except Exception:
            pass
        return "light"

    # ---------------------------------------------------------------- access
    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def active(self) -> str:
        return self._active

    @property
    def is_dark(self) -> bool:
        return self._active == "dark"

    @property
    def palette(self) -> dict:
        return dict(self._palette)

    def get(self, key: str, default: str = "") -> str:
        return self._palette.get(key, default)

    # ------------------------------------------------------------ qt palette
    def build_palette(self):
        """QPalette for parts Qt draws itself (checkbox marks, combo arrows).

        The stylesheet handles colours for styled widgets; native-drawn
        pieces and disabled text still read the application palette, so it
        has to follow the same tokens.
        """
        from PyQt5.QtGui import QColor, QPalette

        p = self._palette
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(p["bg_app"]))
        pal.setColor(QPalette.WindowText, QColor(p["text_primary"]))
        pal.setColor(QPalette.Base, QColor(p["bg_input"]))
        pal.setColor(QPalette.AlternateBase, QColor(p["bg_surface_alt"]))
        pal.setColor(QPalette.Text, QColor(p["text_primary"]))
        pal.setColor(QPalette.Button, QColor(p["bg_surface"]))
        pal.setColor(QPalette.ButtonText, QColor(p["text_primary"]))
        pal.setColor(QPalette.BrightText, QColor(p["danger"]))
        pal.setColor(QPalette.Highlight, QColor(p["accent"]))
        pal.setColor(QPalette.HighlightedText, QColor(p["text_on_accent"]))
        pal.setColor(QPalette.ToolTipBase, QColor(p["tooltip_bg"]))
        pal.setColor(QPalette.ToolTipText, QColor(p["tooltip_text"]))
        pal.setColor(QPalette.PlaceholderText, QColor(p["text_muted"]))
        pal.setColor(QPalette.Mid, QColor(p["border"]))
        pal.setColor(QPalette.Light, QColor(p["bg_surface"]))
        pal.setColor(QPalette.Dark, QColor(p["border_strong"]))
        for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
            pal.setColor(QPalette.Disabled, role, QColor(p["text_disabled"]))
        return pal

    # ------------------------------------------------------------- stylesheet
    def generate_stylesheet(self) -> str:
        """Build the global stylesheet from the active palette."""
        p = self._palette
        c = {k: v for k, v in p.items()}
        # Qt stylesheets need a filesystem path for images
        from pathlib import Path

        c["check_icon"] = (Path(__file__).parent.parent
                           / "resources" / "check.png").as_posix()

        return """
/* ============================== base ============================== */
QWidget {{
    color: {text_primary};
    background: transparent;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {bg_app};
}}
QWidget#page, QWidget#welcomePage {{
    background: {bg_app};
}}
QToolTip {{
    background: {tooltip_bg};
    color: {tooltip_text};
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}

/* ============================== surfaces ============================== */
QFrame#appHeader {{
    background: {bg_header};
    border: none;
    border-bottom: 1px solid {border};
}}
QFrame#appSidebar {{
    background: {bg_sidebar};
    border: none;
    border-right: 1px solid {border};
}}
QWidget#sidebarHeader {{
    background: {bg_sidebar};
    border-bottom: 1px solid {border};
}}
QWidget#sidebarBottom {{
    background: {bg_sidebar};
    border-top: 1px solid {border};
}}
QFrame#toolbar, QFrame#detailToolbar {{
    background: {bg_toolbar};
    border: none;
    border-bottom: 1px solid {border};
}}
QFrame#card, QFrame#welcomeCard, QFrame#detailSection,
QFrame#infoCard, QFrame#panel {{
    background: {bg_surface};
    border: 1px solid {border};
    border-radius: 8px;
}}
QFrame#divider, QFrame#detailSep {{
    background: {border};
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
QWidget#statusBar {{
    background: {bg_status};
}}

/* ============================== typography ============================== */
QLabel#appTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#pageTitle {{
    font-size: 20px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#dialogTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#toolbarTitle {{
    font-size: 15px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#sectionTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#sectionLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {text_muted};
    letter-spacing: 0.6px;
}}
QLabel#fieldLabel {{
    font-size: 12px;
    color: {text_secondary};
}}
QLabel#muted, QLabel#hint {{
    font-size: 12px;
    color: {text_muted};
}}
QLabel#metricValue {{
    font-size: 16px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#metricKey {{
    font-size: 11px;
    color: {text_muted};
}}
QLabel#itemName {{
    font-size: 13px;
    font-weight: 600;
    color: {text_primary};
}}
QLabel#itemDetail {{
    font-size: 11px;
    color: {text_muted};
}}
QLabel#mono, QLineEdit#mono {{
    font-family: "JetBrains Mono", "DejaVu Sans Mono", "Consolas", monospace;
    font-size: 12px;
}}
QLabel#statusOk {{ color: {success}; }}
QLabel#statusWarn {{ color: {warning}; }}
QLabel#statusErr {{ color: {danger}; }}

/* ============================== chips / badges ============================== */
QLabel#chip, QLabel#chipNeutral {{
    background: {chip_bg};
    color: {chip_text};
    border: none;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#chipAccent {{
    background: {accent_soft};
    color: {accent};
    border: none;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#chipGaming {{
    background: {danger_soft};
    color: {danger};
    border: none;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#chipOffice {{
    background: {accent_soft};
    color: {accent};
    border: none;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#chipCustom {{
    background: {success_soft};
    color: {success};
    border: none;
    border-radius: 4px;
    padding: 1px 7px;
    font-size: 11px;
    font-weight: 500;
}}
QLabel#avatar {{
    background: {accent_soft};
    color: {accent};
    border: none;
    border-radius: 6px;
    font-size: 15px;
    font-weight: 600;
}}
QLabel#regInfo {{
    background: {bg_sunken};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 12px;
    color: {text_secondary};
}}

/* ============================== buttons ============================== */
QPushButton {{
    background: {bg_surface};
    color: {text_primary};
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 12px;
}}
QPushButton:hover {{
    background: {bg_hover};
}}
QPushButton:pressed {{
    background: {bg_selected};
}}
QPushButton:disabled {{
    color: {text_disabled};
    border-color: {border};
    background: transparent;
}}
QPushButton#btnPrimary {{
    background: {accent};
    color: {text_on_accent};
    border: 1px solid {accent};
    font-weight: 600;
}}
QPushButton#btnPrimary:hover {{
    background: {accent_hover};
    border-color: {accent_hover};
}}
QPushButton#btnPrimary:pressed {{
    background: {accent_pressed};
    border-color: {accent_pressed};
}}
QPushButton#btnPrimary:disabled {{
    background: {border};
    border-color: {border};
    color: {text_muted};
}}
QPushButton#btnDefault {{
    background: {bg_surface};
    color: {text_primary};
    border: 1px solid {border_strong};
}}
QPushButton#btnDefault:hover {{
    background: {bg_hover};
}}
QPushButton#btnDanger {{
    background: transparent;
    color: {danger};
    border: 1px solid {border_strong};
}}
QPushButton#btnDanger:hover {{
    background: {danger_soft};
    border-color: {danger};
}}
QPushButton#btnGhost {{
    background: transparent;
    border: 1px solid transparent;
    color: {text_secondary};
}}
QPushButton#btnGhost:hover {{
    background: {bg_hover};
    color: {text_primary};
}}
QPushButton#btnLink {{
    background: transparent;
    border: none;
    color: {accent};
    padding: 2px 4px;
}}
QPushButton#btnLink:hover {{
    color: {accent_hover};
    text-decoration: underline;
}}

/* ============================== inputs ============================== */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: {bg_input};
    color: {text_primary};
    border: 1px solid {border_strong};
    border-radius: 6px;
    padding: 6px 9px;
    font-size: 12px;
    selection-background-color: {accent};
    selection-color: {text_on_accent};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: {border_focus};
}}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {{
    color: {text_disabled};
    background: {bg_sunken};
}}
QLineEdit#search {{
    padding: 6px 9px;
}}
QComboBox QAbstractItemView {{
    background: {bg_surface};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px;
    outline: none;
    selection-background-color: {bg_selected};
    selection-color: {text_primary};
}}

/* ============================== checkboxes / radios ============================== */
QCheckBox, QRadioButton {{
    spacing: 8px;
    color: {text_primary};
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {border_strong};
    border-radius: 3px;
    background: {bg_input};
}}
QCheckBox::indicator:hover {{
    border-color: {accent};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: url({check_icon});
}}
QCheckBox::indicator:disabled {{
    border-color: {border};
    background: {bg_sunken};
}}
QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {border_strong};
    border-radius: 8px;
    background: {bg_input};
}}
QRadioButton::indicator:hover {{
    border-color: {accent};
}}
QRadioButton::indicator:checked {{
    border: 4px solid {accent};
    background: {bg_input};
}}

/* ============================== lists & trees ============================== */
QListWidget, QListView, QTreeWidget, QTreeView {{
    background: {bg_surface};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item, QTreeWidget::item, QTreeView::item {{
    padding: 4px 6px;
    border: none;
}}
QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover {{
    background: {bg_hover};
}}
QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {{
    background: {bg_selected};
    color: {text_primary};
}}
QListWidget#sidebarList, QListWidget#plainList {{
    background: transparent;
    border: none;
    border-radius: 0;
}}
QListWidget#sidebarList::item {{
    padding: 0px;
    border-radius: 6px;
}}
QListWidget#sidebarList::item:hover {{
    background: {bg_hover};
}}
QListWidget#sidebarList::item:selected {{
    background: {bg_selected};
}}

/* ============================== tables ============================== */
QTableWidget, QTableView {{
    background: {bg_surface};
    alternate-background-color: {table_alt_row};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    gridline-color: {border};
    font-size: 12px;
    outline: none;
}}
QTableWidget::item, QTableView::item {{
    padding: 5px 8px;
    border: none;
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {bg_selected};
    color: {text_primary};
}}
QHeaderView::section {{
    background: {table_header_bg};
    color: {text_muted};
    border: none;
    border-bottom: 1px solid {border};
    border-right: 1px solid {border};
    padding: 5px 8px;
    font-size: 11px;
    font-weight: 600;
}}
QHeaderView::section:last {{
    border-right: none;
}}
QTableCornerButton::section {{
    background: {table_header_bg};
    border: none;
    border-bottom: 1px solid {border};
}}

/* ============================== tabs ============================== */
QTabWidget::pane {{
    border: none;
    background: {bg_app};
    top: -1px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {text_muted};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 14px;
    font-size: 12px;
    min-width: 48px;
}}
QTabBar::tab:hover {{
    color: {text_primary};
}}
QTabBar::tab:selected {{
    color: {text_primary};
    border-bottom: 2px solid {accent};
}}

/* ============================== group box ============================== */
QGroupBox {{
    background: {bg_surface};
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-size: 12px;
    font-weight: 600;
    color: {text_primary};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {text_secondary};
}}

/* ============================== progress ============================== */
QProgressBar {{
    background: {bg_sunken};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: {text_muted};
    font-size: 10px;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 4px;
}}
QProgressBar#progressLabeled {{
    height: 16px;
    border-radius: 4px;
    font-size: 10px;
}}

/* ============================== menu bar ============================== */
QMenuBar {{
    background: {bg_app};
    border: none;
    padding: 2px 6px;
    font-size: 12px;
}}
QMenuBar::item {{
    padding: 4px 9px;
    border-radius: 4px;
    background: transparent;
}}
QMenuBar::item:selected {{
    background: {bg_hover};
}}
QMenu {{
    background: {bg_surface};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
    font-size: 12px;
}}
QMenu::item {{
    padding: 5px 22px 5px 16px;
    border-radius: 4px;
    color: {text_primary};
}}
QMenu::item:selected {{
    background: {bg_selected};
    color: {text_primary};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 8px;
}}

/* ============================== status bar ============================== */
QStatusBar {{
    background: {bg_status};
    border-top: 1px solid {border};
    color: {text_muted};
    font-size: 11px;
}}
QStatusBar::item {{
    border: none;
}}

/* ============================== scrollbars ============================== */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {scroll_handle};
    border-radius: 3px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {scroll_handle_hover};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {scroll_handle};
    border-radius: 3px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {scroll_handle_hover};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ============================== splitter ============================== */
QSplitter::handle {{
    background: {border};
}}
QSplitter::handle:vertical {{
    height: 1px;
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
""".format(**c)