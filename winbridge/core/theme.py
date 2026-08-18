"""Theme manager for WinBridge — light, dark, and follow-system."""

import json
from pathlib import Path
from enum import Enum


class ThemeMode(Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


THEMES = {
    "light": {
        "name": "明色模式",
        # Backgrounds
        "bg_primary": "#F7FAFC",
        "bg_secondary": "#FFFFFF",
        "bg_tertiary": "#EDF2F7",
        "bg_card": "#FFFFFF",
        "bg_input": "#FAFAFA",
        "bg_input_focus": "#FFFFFF",
        "bg_header": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2D3748, stop:1 #1A202C)",
        "bg_sidebar": "#ffffff",
        "bg_sidebar_header": "#f8f9fa",
        "bg_sidebar_bottom": "#f8f9fa",
        "bg_toolbar": "#ffffff",
        "bg_tab": "#ffffff",
        "bg_tab_selected": "#ffffff",
        "bg_hover": "#f5f7fa",
        "bg_selected": "#e8f0fe",
        "bg_group": "#ffffff",
        "bg_progress_bg": "#eeeeee",
        "bg_progress_chunk": "#38B2AC",
        "bg_badge": "rgba(255,255,255,0.1)",
        "bg_card_border": "#e0e0e0",
        # Text colors
        "text_primary": "#2D3748",
        "text_secondary": "#2D3748",
        "text_tertiary": "#718096",
        "text_muted": "#A0AEC0",
        "text_light": "#A0AEC0",
        "text_white": "#FFFFFF",
        "text_link": "#38B2AC",
        "text_disabled": "#CBD5E0",
        "text_on_dark": "rgba(255,255,255,0.7)",
        # Borders
        "border_primary": "#E2E8F0",
        "border_secondary": "#EDF2F7",
        "border_focus": "#38B2AC",
        "border_input": "#E2E8F0",
        # Accent colors
        "accent_primary": "#2D3748",
        "accent_primary_hover": "#1A202C",
        "accent_primary_pressed": "#171923",
        "accent_success": "#38B2AC",
        "accent_success_hover": "#319795",
        "accent_warning": "#ED8936",
        "accent_danger": "#E53E3E",
        "accent_danger_hover": "#C53030",
        "accent_info": "#3182CE",
        "accent_info_hover": "#2B6CB0",
        "accent_purple": "#805AD5",
        "accent_purple_hover": "#6B46C1",
        "accent_muted": "#A0AEC0",
        "accent_muted_hover": "#718096",
        # Environment badges
        "env_gaming": "#E53E3E",
        "env_office": "#3182CE",
        "env_custom": "#38B2AC",
        # Status bar
        "status_bg": "#f8f9fa",
        "status_border": "#e0e0e0",
        # Menu
        "menu_bg": "#ffffff",
        "menu_border": "#dddddd",
        "menu_item_hover": "#4a90d9",
        "menu_item_hover_text": "#ffffff",
        # Table
        "table_bg": "#ffffff",
        "table_header_bg": "#f0f2f5",
        "table_border": "#eeeeee",
        "table_header_border": "#dddddd",
        "table_alt_row": "#fafafa",
        # Tooltip
        "tooltip_bg": "#333333",
        "tooltip_text": "#ffffff",
        # Scrollbar
        "scrollbar_bg": "#f0f0f0",
        "scrollbar_handle": "#cccccc",
        "scrollbar_handle_hover": "#aaaaaa",
        # Tab
        "tab_border": "transparent",
        "tab_selected_border": "#38B2AC",
        "tab_text": "#718096",
        "tab_text_selected": "#2D3748",
        "tab_text_hover": "#333333",
        "tab_bg_hover": "#f8f9fa",
        # Button specific
        "btn_default_bg": "#38B2AC",
        "btn_default_text": "#FFFFFF",
        "btn_default_hover": "#319795",
        "btn_primary_bg": "#2D3748",
        "btn_primary_text": "#FFFFFF",
        "btn_primary_hover": "#1A202C",
        "btn_primary_disabled_bg": "#CBD5E0",
        "btn_primary_disabled_text": "#A0AEC0",
        "btn_secondary_bg": "transparent",
        "btn_secondary_text": "#2D3748",
        "btn_secondary_border": "#CBD5E0",
        "btn_secondary_hover_bg": "#EDF2F7",
        "btn_secondary_hover_border": "#A0AEC0",
        # QGroupBox
        "groupbox_bg": "#ffffff",
        "groupbox_border": "#e0e0e0",
        "groupbox_title": "#555555",
        # QComboBox dropdown
        "dropdown_bg": "#ffffff",
        "dropdown_text": "#333333",
        "dropdown_selection_bg": "#4a90d9",
        "dropdown_selection_text": "#ffffff",
        # Progress bar
        "progress_text": "#555555",
        # Header accent
        "header_title": "#ffffff",
        "header_badge_bg": "rgba(255,255,255,0.1)",
        "header_badge_text": "rgba(255,255,255,0.7)",
        # Welcome card
        "welcome_card_bg": "#ffffff",
        "welcome_card_border": "#e0e0e0",
        # Info cards
        "infocard_bg": "#ffffff",
        "infocard_border": "#e0e0e0",
        # Description
        "desc_bg": "#fafafa",
        "desc_focus_bg": "#ffffff",
        "desc_border": "#e0e0e0",
        "desc_focus_border": "#4a90d9",
        # DLL table
        "dll_table_bg": "#ffffff",
        "dll_table_border": "#e0e0e0",
        "dll_table_grid": "#f0f0f0",
        # Components
        "comp_table_bg": "#ffffff",
        "comp_table_grid": "#f0f0f0",
        "comp_table_header_bg": "#f8f9fa",
        "comp_table_header_border": "#e0e0e0",
        # Icon
        "icon_bg": "#38B2AC",
        "icon_text": "#ffffff",
        # Bottle item
        "bottle_item_bg": "#ffffff",
        "bottle_item_border": "#e0e0e0",
        "bottle_item_hover_bg": "#f5f7fa",
        "bottle_item_hover_border": "#4a90d9",
        "bottle_item_name": "#1a1a2e",
        "bottle_item_detail": "#888888",
        # Quick launch
        "quicklaunch_bg": "#fafafa",
        "quicklaunch_focus_bg": "#ffffff",
        # Shortcuts
        "shortcuts_bg": "#fafafa",
        # Registry info
        "reg_info_bg": "#e8f0fe",
        "reg_info_text": "#333333",
        "reg_info_border": "#4a90d940",
        # Dialog
        "dialog_bg": "#f5f6fa",
        "dialog_label": "#333333",
        "dialog_subtitle": "#888888",
        "dialog_title": "#1a1a2e",
        # Environment hint
        "env_hint": "#777777",
        # Error dialog
        "error_bg": "#fff5f5",
        "error_border": "#fed7d7",
        "error_text": "#c53030",
        # Success dialog
        "success_bg": "#f0fff4",
        "success_border": "#c6f6d5",
        "success_text": "#276749",
    },
    "dark": {
        "name": "暗色模式",
        # Backgrounds
        "bg_primary": "#1a1a2e",
        "bg_secondary": "#16213e",
        "bg_tertiary": "#1e2a4a",
        "bg_card": "#1e2a4a",
        "bg_input": "#2a3a5c",
        "bg_input_focus": "#2a3a5c",
        "bg_header": "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f0f23, stop:1 #16213e)",
        "bg_sidebar": "#16213e",
        "bg_sidebar_header": "#1e2a4a",
        "bg_sidebar_bottom": "#1e2a4a",
        "bg_toolbar": "#16213e",
        "bg_tab": "#16213e",
        "bg_tab_selected": "#16213e",
        "bg_hover": "#2a3a5c",
        "bg_selected": "#2a4a7a",
        "bg_group": "#1e2a4a",
        "bg_progress_bg": "#2a3a5c",
        "bg_progress_chunk": "#4a90d9",
        "bg_badge": "rgba(255,255,255,0.05)",
        "bg_card_border": "#2a3a5c",
        # Text colors
        "text_primary": "#e0e0e0",
        "text_secondary": "#cccccc",
        "text_tertiary": "#aaaaaa",
        "text_muted": "#888888",
        "text_light": "#666666",
        "text_white": "#ffffff",
        "text_link": "#6aafe6",
        "text_disabled": "#555555",
        "text_on_dark": "rgba(255,255,255,0.5)",
        # Borders
        "border_primary": "#2a3a5c",
        "border_secondary": "#2a3a5c",
        "border_focus": "#6aafe6",
        "border_input": "#2a3a5c",
        # Accent colors
        "accent_primary": "#6aafe6",
        "accent_primary_hover": "#5a9fd6",
        "accent_primary_pressed": "#4a8fc6",
        "accent_success": "#27ae60",
        "accent_success_hover": "#219a52",
        "accent_warning": "#f39c12",
        "accent_danger": "#e74c3c",
        "accent_danger_hover": "#c0392b",
        "accent_info": "#5a9fd6",
        "accent_info_hover": "#4a8fc6",
        "accent_purple": "#9b59b6",
        "accent_purple_hover": "#8e44ad",
        "accent_muted": "#5a6a8a",
        "accent_muted_hover": "#4a5a7a",
        # Environment badges
        "env_gaming": "#e74c3c",
        "env_office": "#3498db",
        "env_custom": "#2ecc71",
        # Status bar
        "status_bg": "#16213e",
        "status_border": "#2a3a5c",
        # Menu
        "menu_bg": "#16213e",
        "menu_border": "#2a3a5c",
        "menu_item_hover": "#6aafe6",
        "menu_item_hover_text": "#ffffff",
        # Table
        "table_bg": "#1e2a4a",
        "table_header_bg": "#16213e",
        "table_border": "#2a3a5c",
        "table_header_border": "#2a3a5c",
        "table_alt_row": "#1a2a48",
        # Tooltip
        "tooltip_bg": "#2a3a5c",
        "tooltip_text": "#e0e0e0",
        # Scrollbar
        "scrollbar_bg": "#1e2a4a",
        "scrollbar_handle": "#3a4a6c",
        "scrollbar_handle_hover": "#4a5a7c",
        # Tab
        "tab_border": "transparent",
        "tab_selected_border": "#6aafe6",
        "tab_text": "#888888",
        "tab_text_selected": "#6aafe6",
        "tab_text_hover": "#cccccc",
        "tab_bg_hover": "#2a3a5c",
        # Button specific
        "btn_default_bg": "#5a6a8a",
        "btn_default_text": "#ffffff",
        "btn_default_hover": "#4a5a7a",
        "btn_primary_bg": "#6aafe6",
        "btn_primary_text": "#ffffff",
        "btn_primary_hover": "#5a9fd6",
        "btn_primary_disabled_bg": "#3a4a6c",
        "btn_primary_disabled_text": "#666666",
        "btn_secondary_bg": "transparent",
        "btn_secondary_text": "#aaaaaa",
        "btn_secondary_border": "#3a4a6c",
        "btn_secondary_hover_bg": "#2a3a5c",
        "btn_secondary_hover_border": "#5a6a8a",
        # QGroupBox
        "groupbox_bg": "#1e2a4a",
        "groupbox_border": "#2a3a5c",
        "groupbox_title": "#aaaaaa",
        # QComboBox dropdown
        "dropdown_bg": "#16213e",
        "dropdown_text": "#cccccc",
        "dropdown_selection_bg": "#6aafe6",
        "dropdown_selection_text": "#ffffff",
        # Progress bar
        "progress_text": "#aaaaaa",
        # Header accent
        "header_title": "#ffffff",
        "header_badge_bg": "rgba(255,255,255,0.05)",
        "header_badge_text": "rgba(255,255,255,0.5)",
        # Welcome card
        "welcome_card_bg": "#1e2a4a",
        "welcome_card_border": "#2a3a5c",
        # Info cards
        "infocard_bg": "#1e2a4a",
        "infocard_border": "#2a3a5c",
        # Description
        "desc_bg": "#2a3a5c",
        "desc_focus_bg": "#2a3a5c",
        "desc_border": "#2a3a5c",
        "desc_focus_border": "#6aafe6",
        # DLL table
        "dll_table_bg": "#1e2a4a",
        "dll_table_border": "#2a3a5c",
        "dll_table_grid": "#2a3a5c",
        # Components
        "comp_table_bg": "#1e2a4a",
        "comp_table_grid": "#2a3a5c",
        "comp_table_header_bg": "#16213e",
        "comp_table_header_border": "#2a3a5c",
        # Icon
        "icon_bg": "#6aafe6",
        "icon_text": "#ffffff",
        # Bottle item
        "bottle_item_bg": "transparent",
        "bottle_item_border": "transparent",
        "bottle_item_hover_bg": "#2a3a5c",
        "bottle_item_hover_border": "#6aafe6",
        "bottle_item_name": "#e0e0e0",
        "bottle_item_detail": "#888888",
        # Quick launch
        "quicklaunch_bg": "#2a3a5c",
        "quicklaunch_focus_bg": "#2a3a5c",
        # Shortcuts
        "shortcuts_bg": "#2a3a5c",
        # Registry info
        "reg_info_bg": "#1a2a48",
        "reg_info_text": "#cccccc",
        "reg_info_border": "#6aafe640",
        # Dialog
        "dialog_bg": "#16213e",
        "dialog_label": "#cccccc",
        "dialog_subtitle": "#888888",
        "dialog_title": "#e0e0e0",
        # Environment hint
        "env_hint": "#888888",
        # Error dialog
        "error_bg": "#2a1a1a",
        "error_border": "#4a2a2a",
        "error_text": "#fc8181",
        # Success dialog
        "success_bg": "#1a2a1a",
        "success_border": "#2a4a2a",
        "success_text": "#68d391",
    },
}


class ThemeManager:
    """Manages application themes."""

    def __init__(self, config=None):
        self.config = config
        self._mode = ThemeMode.LIGHT
        self._palette = {}
        self._load()

    def _load(self):
        """Load theme preference from config."""
        if self.config:
            saved = self.config.get("theme_mode", "light")
        else:
            saved = "light"
        self.set_mode(saved)

    def set_mode(self, mode: str):
        """Set theme mode: 'light', 'dark', or 'system'."""
        if mode == "system":
            self._mode = ThemeMode.SYSTEM
            active = self._detect_system()
        elif mode == "dark":
            self._mode = ThemeMode.DARK
            active = "dark"
        else:
            self._mode = ThemeMode.LIGHT
            active = "light"

        self._palette = THEMES.get(active, THEMES["light"])
        if self.config:
            self.config.set("theme_mode", mode)
            self.config.save()

    def _detect_system(self) -> str:
        """Detect system dark/light mode via DBus or file."""
        try:
            import subprocess
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=3
            )
            if "dark" in result.stdout.lower():
                return "dark"
        except Exception:
            pass
        # KDE check
        try:
            p = Path.home() / ".config" / "kdeglobals"
            if p.exists():
                for line in p.read_text().splitlines():
                    if "ColorScheme" in line and "Dark" in line:
                        return "dark"
        except Exception:
            pass
        return "light"

    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def is_dark(self) -> bool:
        return self._palette.get("name", "") == "暗色模式"

    def get(self, key: str, default: str = "") -> str:
        return self._palette.get(key, default)

    @property
    def palette(self) -> dict:
        return self._palette.copy()

    def generate_stylesheet(self) -> str:
        """Generate the comprehensive global application stylesheet."""
        p = self._palette
        return f"""
        /* === Base === */
        QWidget {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            color: {p["text_secondary"]};
        }}
        QMainWindow {{
            background-color: {p["bg_primary"]};
        }}
        QFrame#appHeader {{
            background: {p["bg_header"]};
        }}
        QFrame#appSidebar {{
            background: {p["bg_sidebar"]};
            border-right: 1px solid {p["border_primary"]};
        }}
        QWidget#sidebarHeader {{
            background: {p["bg_sidebar_header"]};
            border-bottom: 1px solid {p["border_primary"]};
        }}
        QWidget#sidebarBottom {{
            background: {p["bg_sidebar_bottom"]};
            border-top: 1px solid {p["border_primary"]};
        }}
        QWidget#welcomePage {{
            background: {p["bg_primary"]};
        }}
        QFrame#welcomeCard {{
            background: {p["bg_card"]};
            border-radius: 6px;
            border: 1px solid {p["border_primary"]};
        }}
        QFrame#detailToolbar {{
            background: {p["bg_toolbar"]};
            border-bottom: 1px solid {p["border_primary"]};
        }}
        QFrame#detailSection {{
            background: {p["bg_card"]};
            border: 1px solid {p["border_primary"]};
            border-radius: 4px;
            padding: 16px;
        }}
        QFrame#infoCard {{
            background: {p["bg_card"]};
            border: 1px solid {p["border_primary"]};
            border-radius: 4px;
        }}
        QFrame#detailSep {{
            background: {p["border_primary"]};
            max-height: 1px;
        }}
        QLabel#regInfo {{
            background: {p["reg_info_bg"]};
            border: 1px solid {p["reg_info_border"]};
            border-radius: 3px;
            padding: 10px 14px;
            font-size: 12px;
        }}
        QPushButton#btnPrimary {{
            background: {p["accent_primary"]};
            color: {p["btn_primary_text"]};
            border-radius: 8px;
            padding: 12px 24px;
            font-size: 14px;
            font-weight: bold;
        }}
        QPushButton#btnPrimary:hover {{
            background: {p["accent_primary_hover"]};
        }}

        /* === Menu Bar === */
        QMenuBar {{
            background: {p["bg_tertiary"]};
            border-bottom: 1px solid {p["border_primary"]};
            font-size: 12px;
            color: {p["text_secondary"]};
        }}
        QMenuBar::item:selected {{
            background: {p["bg_hover"]};
        }}
        QMenu {{
            background: {p["menu_bg"]};
            border: 1px solid {p["menu_border"]};
            border-radius: 6px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 24px;
            border-radius: 4px;
            color: {p["text_secondary"]};
        }}
        QMenu::item:selected {{
            background: {p["menu_item_hover"]};
            color: {p["menu_item_hover_text"]};
        }}
        QMenu::separator {{
            height: 1px;
            background: {p["border_primary"]};
            margin: 4px 8px;
        }}

        /* === Status Bar === */
        QStatusBar {{
            background: {p["status_bg"]};
            border-top: 1px solid {p["status_border"]};
            font-size: 12px;
            color: {p["text_muted"]};
        }}

        /* === Tooltip === */
        QToolTip {{
            background: {p["tooltip_bg"]};
            color: {p["tooltip_text"]};
            border: none;
            border-radius: 4px;
            padding: 4px 8px;
            font-size: 12px;
        }}

        /* === Scrollbar === */
        QScrollBar:vertical {{
            background: {p["scrollbar_bg"]};
            width: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background: {p["scrollbar_handle"]};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {p["scrollbar_handle_hover"]};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar:horizontal {{
            background: {p["scrollbar_bg"]};
            height: 10px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal {{
            background: {p["scrollbar_handle"]};
            border-radius: 5px;
            min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {p["scrollbar_handle_hover"]};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

        /* === Tab Widget === */
        QTabWidget::pane {{
            border: none;
            background: {p["bg_primary"]};
        }}
        QTabBar::tab {{
            background: {p["bg_tab"]};
            border: none;
            border-bottom: 2px solid {p["tab_border"]};
            padding: 8px 20px;
            font-size: 13px;
            color: {p["tab_text"]};
            min-width: 80px;
        }}
        QTabBar::tab:selected {{
            color: {p["tab_text_selected"]};
            border-bottom: 2px solid {p["tab_selected_border"]};
            font-weight: bold;
        }}
        QTabBar::tab:hover {{
            color: {p["tab_text_hover"]};
            background: {p["tab_bg_hover"]};
        }}

        /* === QGroupBox === */
        QGroupBox {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            background: {p["groupbox_bg"]};
            border-radius: 8px;
            border: 1px solid {p["groupbox_border"]};
            padding: 16px;
            padding-top: 24px;
            font-weight: bold;
            color: {p["text_secondary"]};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 4px 8px;
            color: {p["groupbox_title"]};
        }}

        /* === QPushButton === */
        QPushButton {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            color: {p["text_secondary"]};
            border: 1px solid {p["border_primary"]};
            border-radius: 4px;
            padding: 6px 16px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background: {p["bg_hover"]};
        }}
        QPushButton:pressed {{
            background: {p["bg_selected"]};
        }}
        QPushButton:disabled {{
            color: {p["text_disabled"]};
        }}

        /* === QLineEdit === */
        QLineEdit {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            border: 1px solid {p["border_input"]};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 13px;
            background: {p["bg_input"]};
            color: {p["text_secondary"]};
        }}
        QLineEdit:focus {{
            border-color: {p["border_focus"]};
            background: {p["bg_input_focus"]};
        }}
        QLineEdit::placeholder {{
            color: {p["text_light"]};
        }}

        /* === QTextEdit === */
        QTextEdit {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            border: 1px solid {p["border_input"]};
            border-radius: 6px;
            padding: 8px;
            font-size: 13px;
            background: {p["bg_input"]};
            color: {p["text_secondary"]};
        }}
        QTextEdit:focus {{
            border-color: {p["border_focus"]};
            background: {p["bg_input_focus"]};
        }}

        /* === QComboBox === */
        QComboBox {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            border: 1px solid {p["border_input"]};
            border-radius: 6px;
            padding: 8px 12px;
            font-size: 13px;
            background: {p["bg_input"]};
            color: {p["text_secondary"]};
        }}
        QComboBox:focus {{
            border-color: {p["border_focus"]};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            color: {p["dropdown_text"]};
            background: {p["dropdown_bg"]};
            selection-background-color: {p["dropdown_selection_bg"]};
            selection-color: {p["dropdown_selection_text"]};
        }}

        /* === QRadioButton === */
        QRadioButton {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            font-size: 13px;
            spacing: 8px;
            color: {p["text_secondary"]};
        }}
        QRadioButton::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 9px;
            border: 2px solid {p["border_secondary"]};
        }}
        QRadioButton::indicator:checked {{
            background: {p["accent_primary"]};
            border-color: {p["accent_primary"]};
        }}

        /* === QCheckBox === */
        QCheckBox {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            font-size: 13px;
            spacing: 8px;
            color: {p["text_secondary"]};
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 3px;
            border: 2px solid {p["border_secondary"]};
        }}
        QCheckBox::indicator:checked {{
            background: {p["accent_primary"]};
            border-color: {p["accent_primary"]};
        }}

        /* === QListWidget / QListWidgetItem === */
        QListWidget {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            background: {p["bg_sidebar"]};
            border: none;
            outline: none;
            color: {p["text_secondary"]};
        }}
        QListWidget::item {{
            border: none;
            background: transparent;
            padding: 0px;
            color: {p["text_secondary"]};
        }}
        QListWidget::item:selected {{
            background: {p["bg_selected"]};
            border-radius: 8px;
            color: {p["text_secondary"]};
        }}

        /* === QTableWidget === */
        QTableWidget {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            border: 1px solid {p["border_primary"]};
            border-radius: 6px;
            background: {p["table_bg"]};
            gridline-color: {p["table_border"]};
            font-size: 12px;
            color: {p["text_secondary"]};
        }}
        QTableWidget::item {{
            padding: 4px 8px;
            color: {p["text_secondary"]};
        }}
        QTableWidget::item:selected {{
            background: {p["bg_selected"]};
            color: {p["text_secondary"]};
        }}
        QHeaderView::section {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            background: {p["table_header_bg"]};
            border: none;
            border-bottom: 1px solid {p["table_header_border"]};
            padding: 6px 8px;
            font-weight: bold;
            font-size: 12px;
            color: {p["text_tertiary"]};
        }}

        /* === QProgressBar === */
        QProgressBar {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            border: 1px solid {p["border_primary"]};
            border-radius: 8px;
            background: {p["bg_progress_bg"]};
            text-align: center;
            font-size: 11px;
            height: 20px;
            color: {p["progress_text"]};
        }}
        QProgressBar::chunk {{
            background: {p["bg_progress_chunk"]};
            border-radius: 7px;
        }}

        /* === QLabel === */
        QLabel {{
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            color: {p["text_secondary"]};
        }}

        /* === QDialog === */
        QDialog {{
            background: {p["dialog_bg"]};
        }}

        /* === QFrame === */
        QFrame {{
            color: {p["text_secondary"]};
        }}
        """