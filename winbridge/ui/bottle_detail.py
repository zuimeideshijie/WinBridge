"""Bottle detail view widget — Windows-native styled detail panel."""

import os
import subprocess
from pathlib import Path
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QGroupBox, QTabWidget,
    QTextEdit, QComboBox, QLineEdit, QFormLayout, QListWidget,
    QListWidgetItem, QSplitter, QMessageBox, QFileDialog,
    QApplication, QDialog, QDialogButtonBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu,
    QAction, QProgressBar, QSpacerItem, QSizePolicy,
    QTreeWidget, QTreeWidgetItem, QGraphicsDropShadowEffect,
    QStyle,
)

from ..core.bottle import Bottle, BottleManager
from ..core.wine import Wine
from ..core.config import Config
from ..core.download import ComponentManager
from .dialogs import CreateBottleDialog, FirstRunDialog, TaskManagerDialog

FONT_FAMILY = "'Segoe UI', 'Noto Sans CJK SC', 'Microsoft YaHei', 'WenQuanYi Micro Hei', sans-serif"


class _RegistryLoadThread(QThread):
    """Parse the bottle's .reg files in a background thread.

    Reading and tokenizing large registry files on the GUI thread freezes
    the window. This worker only collects the list of key paths; the tree
    widgets themselves are built on the main thread (Qt requirement).
    Emits ``loaded`` with a list of key paths, or nothing if cancelled.
    """
    loaded = pyqtSignal(list)

    def __init__(self, bottle_path: str):
        super().__init__()
        self.bottle_path = bottle_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        key_paths = set()
        # user.reg lives under HKCU, system.reg under HKLM — prefix the key
        # paths so the tree can tell them apart and edits target the right hive.
        for hive, reg_name in (("HKCU", "user.reg"), ("HKLM", "system.reg")):
            if self._cancel:
                return
            reg_path = Path(self.bottle_path) / reg_name
            if not reg_path.exists():
                continue
            try:
                text = reg_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.split("\n"):
                if self._cancel:
                    return
                line = line.strip()
                if not line.startswith("["):
                    continue
                end = line.find("]")
                if end <= 1:
                    continue
                key_path = line[1:end].strip()
                if key_path:
                    key_paths.add(hive + "\\\\" + key_path)
        if not self._cancel and key_paths:
            self.loaded.emit(sorted(key_paths))

# Light file dialog stylesheet
FILE_DIALOG_STYLE = """
    QFileDialog {
        background: #ffffff;
        color: #333333;
    }
    QFileDialog QLabel {
        font-family: 'Segoe UI', sans-serif;
        font-size: 12px;
        color: #333333;
    }
    QFileDialog QLineEdit {
        font-family: 'Segoe UI', sans-serif;
        font-size: 12px;
        border: 1px solid #cccccc;
        border-radius: 3px;
        padding: 4px 8px;
        background: #ffffff;
        color: #333333;
    }
    QFileDialog QComboBox {
        font-family: 'Segoe UI', sans-serif;
        font-size: 12px;
        border: 1px solid #cccccc;
        border-radius: 3px;
        padding: 4px 8px;
        background: #ffffff;
        color: #333333;
    }
    QFileDialog QTreeView {
        font-family: 'Segoe UI', sans-serif;
        font-size: 12px;
        background: #ffffff;
        color: #333333;
        border: 1px solid #e0e0e0;
    }
    QFileDialog QTreeView::item:selected {
        background: #e8f0fe;
        color: #1a1a2e;
    }
    QFileDialog QPushButton {
        font-family: 'Segoe UI', sans-serif;
        font-size: 12px;
        border: 1px solid #cccccc;
        border-radius: 3px;
        padding: 5px 14px;
        background: #f0f0f0;
        color: #333333;
    }
    QFileDialog QPushButton:hover {
        background: #e5e5e5;
    }
    QFileDialog QPushButton:pressed {
        background: #d9d9d9;
    }
    QFileDialog QHeaderView::section {
        font-family: 'Segoe UI', sans-serif;
        font-size: 11px;
        font-weight: 600;
        background: #f5f5f5;
        color: #444444;
        border: 1px solid #e0e0e0;
        padding: 4px 8px;
    }
"""

# Common button styles
BTN_DEFAULT = f"""
    QPushButton {{
        font-family: {FONT_FAMILY};
        border: 1px solid #CBD5E0;
        border-radius: 6px;
        padding: 5px 14px;
        font-size: 12px;
        background: transparent;
        color: #2D3748;
    }}
    QPushButton:hover {{
        background: #EDF2F7;
        border-color: #A0AEC0;
    }}
    QPushButton:pressed {{
        background: #E2E8F0;
    }}
"""

BTN_PRIMARY = f"""
    QPushButton {{
        font-family: {FONT_FAMILY};
        border: 1px solid #2D3748;
        border-radius: 6px;
        padding: 5px 14px;
        font-size: 12px;
        font-weight: 600;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 #2D3748, stop:1 #1A202C);
        color: #FFFFFF;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 #1A202C, stop:1 #171923);
        border-color: #1A202C;
    }}
    QPushButton:pressed {{
        background: #171923;
        border-color: #171923;
    }}
    QPushButton:disabled {{
        background: #CBD5E0;
        border-color: #CBD5E0;
        color: #A0AEC0;
    }}
"""

BTN_SUCCESS = f"""
    QPushButton {{
        font-family: {FONT_FAMILY};
        border: 1px solid #38B2AC;
        border-radius: 6px;
        padding: 5px 14px;
        font-size: 12px;
        font-weight: 600;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 #38B2AC, stop:1 #319795);
        color: #FFFFFF;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 #319795, stop:1 #2C7A7B);
        border-color: #319795;
    }}
    QPushButton:pressed {{
        background: #2C7A7B;
        border-color: #2C7A7B;
    }}
    QPushButton:disabled {{
        background: #CBD5E0;
        border-color: #CBD5E0;
        color: #A0AEC0;
    }}
"""

BTN_DANGER = f"""
    QPushButton {{
        font-family: {FONT_FAMILY};
        border: 1px solid #FC8181;
        border-radius: 6px;
        padding: 5px 14px;
        font-size: 12px;
        font-weight: 600;
        background: #FED7D7;
        color: #C53030;
    }}
    QPushButton:hover {{
        background: #FC8181;
        border-color: #FC8181;
        color: #FFFFFF;
    }}
    QPushButton:pressed {{
        background: #E53E3E;
        border-color: #E53E3E;
    }}
    QPushButton:disabled {{
        background: #EDF2F7;
        border-color: #E2E8F0;
        color: #A0AEC0;
    }}
"""

INPUT_STYLE = f"""
    QLineEdit {{
        font-family: {FONT_FAMILY};
        border: 1px solid #cccccc;
        border-radius: 3px;
        padding: 5px 8px;
        font-size: 12px;
        background: #ffffff;
        color: #333333;
    }}
    QLineEdit:focus {{
        border-color: #4a90d9;
    }}
"""

TEXTEDIT_STYLE = f"""
    QTextEdit {{
        font-family: {FONT_FAMILY};
        border: 1px solid #cccccc;
        border-radius: 3px;
        padding: 5px 8px;
        font-size: 12px;
        background: #ffffff;
        color: #333333;
    }}
    QTextEdit:focus {{
        border-color: #4a90d9;
    }}
"""

COMBO_STYLE = f"""
    QComboBox {{
        font-family: {FONT_FAMILY};
        border: 1px solid #cccccc;
        border-radius: 3px;
        padding: 5px 8px;
        font-size: 12px;
        background: #ffffff;
        color: #333333;
    }}
    QComboBox:focus {{ border-color: #4a90d9; }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        font-family: {FONT_FAMILY};
        background: #ffffff;
        border: 1px solid #cccccc;
        selection-background-color: #4a90d9;
        selection-color: #ffffff;
    }}
"""

TABLE_STYLE = f"""
    QTableWidget {{
        font-family: {FONT_FAMILY};
        border: 1px solid #ffffff;
        border-radius: 3px;
        font-size: 12px;
        background: #ffffff;
        gridline-color: #ffffff;
        color: #333333;
    }}
    QTableWidget::item {{
        padding: 4px 8px;
    }}
    QTableWidget::item:selected {{
        background: #ffffff;
        color: #2D3748;
    }}
    QHeaderView::section {{
        font-family: {FONT_FAMILY};
        background: #f0f0f0;
        border: none;
        border-bottom: 1px solid #cccccc;
        padding: 5px 8px;
        font-weight: 600;
        font-size: 12px;
        color: #444444;
    }}
"""


class BottleDetailWidget(QWidget):
    """Detailed view of a single bottle — Windows native style."""

    bottle_deleted = pyqtSignal(str)
    bottle_updated = pyqtSignal(str)

    def __init__(self, config: Config = None):
        super().__init__()
        self.config = config or Config()
        self.bottle_manager = BottleManager(self.config)
        self.wine = Wine(self.config.wine_path)
        self.component_manager = ComponentManager(self.config)
        self.current_bottle = None
        self.setup_ui()

    def setup_ui(self):
        """Setup the detail view UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # === Top toolbar ===
        toolbar = QFrame()
        toolbar.setFixedHeight(44)
        toolbar.setObjectName("detailToolbar")
        toolbar.setStyleSheet("")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 0, 16, 0)
        toolbar_layout.setSpacing(8)

        self.bottle_title = QLabel("选择容器以查看详情")
        self.bottle_title.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 600;
            color: #1a1a2e;
            font-family: {FONT_FAMILY};
        """)
        toolbar_layout.addWidget(self.bottle_title)

        toolbar_layout.addStretch()

        # Action buttons
        self.btn_run = QPushButton("运行")
        self.btn_run.setStyleSheet(BTN_SUCCESS)
        self.btn_run.clicked.connect(self.run_executable)
        toolbar_layout.addWidget(self.btn_run)

        self.btn_winecfg = QPushButton("winecfg")
        self.btn_winecfg.setStyleSheet(BTN_DEFAULT)
        self.btn_winecfg.clicked.connect(self.open_winecfg)
        toolbar_layout.addWidget(self.btn_winecfg)

        self.btn_taskmgr = QPushButton("任务管理器")
        self.btn_taskmgr.setStyleSheet(BTN_DEFAULT)
        self.btn_taskmgr.clicked.connect(self.open_task_manager)
        toolbar_layout.addWidget(self.btn_taskmgr)

        self.btn_c_drive = QPushButton("前往C盘")
        self.btn_c_drive.setStyleSheet(BTN_DEFAULT)
        self.btn_c_drive.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.btn_c_drive.clicked.connect(self.open_c_drive)
        toolbar_layout.addWidget(self.btn_c_drive)

        toolbar_layout.addStretch()

        self.btn_rename = QPushButton("重命名")
        self.btn_rename.setStyleSheet(BTN_DEFAULT)
        self.btn_rename.clicked.connect(self.rename_bottle)
        toolbar_layout.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.setStyleSheet(BTN_DANGER)
        self.btn_delete.clicked.connect(self.delete_bottle)
        toolbar_layout.addWidget(self.btn_delete)

        layout.addWidget(toolbar)

        # === Content area with tabs ===
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                font-family: {FONT_FAMILY};
                border: none;
                border-bottom: 2px solid transparent;
                padding: 7px 18px;
                font-size: 12px;
                color: #666666;
                min-width: 60px;
            }}
            QTabBar::tab:selected {{
                color: #4a90d9;
                border-bottom: 2px solid #4a90d9;
                font-weight: 600;
            }}
            QTabBar::tab:hover {{
                color: #333333;
            }}
        """)

        # Tab 1: Overview
        self.overview_tab = self._create_overview_tab()
        self.tabs.addTab(self.overview_tab, "概览")

        # Tab 2: Programs
        self.programs_tab = self._create_programs_tab()
        self.tabs.addTab(self.programs_tab, "程序")

        # Tab 3: Components
        self.components_tab = self._create_components_tab()
        self.tabs.addTab(self.components_tab, "组件")

        # Tab 4: Configuration
        self.config_tab = self._create_config_tab()
        self.tabs.addTab(self.config_tab, "配置")

        # Tab 5: Registry
        self.registry_tab = self._create_registry_tab()
        self.tabs.addTab(self.registry_tab, "注册表")
        self._registry_loaded = False

        # Lazy-load registry tree when tab is selected
        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tabs, 1)

        # Disable controls initially
        self.set_controls_enabled(False)

    def _create_info_card(self, title: str, value: str, color: str = "#38B2AC") -> QFrame:
        """Create an info card widget."""
        card = QFrame()
        card.setFixedSize(210, 80)
        card.setObjectName("infoCard")
        card.setStyleSheet(f"""
            QFrame {{
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
            }}
        """)
        # Soft drop shadow for the card
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(12)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(45, 55, 72, 40))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(5)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"""
            font-size: 11px;
            color: #718096;
            font-family: {FONT_FAMILY};
        """)
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setStyleSheet(f"""
            font-size: 15px;
            font-weight: 600;
            color: {color};
            font-family: {FONT_FAMILY};
        """)
        value_label.setWordWrap(True)
        layout.addWidget(value_label)

        return card

    def _create_overview_tab(self) -> QWidget:
        """Create the overview tab."""
        tab = QWidget()
        tab.setStyleSheet("")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Info cards row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        self.card_arch = self._create_info_card("架构", "-", "#3498db")
        cards_layout.addWidget(self.card_arch)

        self.card_winver = self._create_info_card("Windows 版本", "-", "#2ecc71")
        cards_layout.addWidget(self.card_winver)

        self.card_env = self._create_info_card("环境", "-", "#e74c3c")
        cards_layout.addWidget(self.card_env)

        self.card_size = self._create_info_card("大小", "-", "#9b59b6")
        cards_layout.addWidget(self.card_size)

        self.card_created = self._create_info_card("创建时间", "-", "#f39c12")
        cards_layout.addWidget(self.card_created)

        cards_layout.addStretch()
        layout.addLayout(cards_layout)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("detailSep")
        sep.setStyleSheet("max-height: 1px;")
        layout.addWidget(sep)

        # Description section (card)
        desc_card = QFrame()
        desc_card.setStyleSheet(f"""
            QFrame {{
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
                padding: 14px;
            }}
        """)
        desc_card_layout = QVBoxLayout(desc_card)
        desc_card_layout.setContentsMargins(16, 14, 16, 14)
        desc_card_layout.setSpacing(8)

        desc_header = QLabel("描述")
        desc_header.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #2D3748;
            font-family: {FONT_FAMILY};
        """)
        desc_card_layout.addWidget(desc_header)

        self.description_text = QTextEdit()
        self.description_text.setPlaceholderText("添加容器描述...")
        self.description_text.setMaximumHeight(80)
        self.description_text.setStyleSheet(TEXTEDIT_STYLE)
        desc_card_layout.addWidget(self.description_text)

        btn_save_desc = QPushButton("保存描述")
        btn_save_desc.setStyleSheet(BTN_DEFAULT)
        btn_save_desc.clicked.connect(self.save_description)
        btn_save_desc.setFixedWidth(100)
        desc_card_layout.addWidget(btn_save_desc, 0, Qt.AlignLeft)
        layout.addWidget(desc_card)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("detailSep")
        sep2.setStyleSheet("max-height: 1px;")
        layout.addWidget(sep2)

        # Installed components (card)
        comp_card = QFrame()
        comp_card.setStyleSheet(f"""
            QFrame {{
                background: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 10px;
                padding: 14px;
            }}
        """)
        comp_card_layout = QVBoxLayout(comp_card)
        comp_card_layout.setContentsMargins(16, 14, 16, 14)
        comp_card_layout.setSpacing(8)

        comp_header = QLabel("已安装组件")
        comp_header.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #2D3748;
            font-family: {FONT_FAMILY};
        """)
        comp_card_layout.addWidget(comp_header)

        self.components_list = QListWidget()
        self.components_list.setStyleSheet(f"""
            QListWidget {{
                font-family: {FONT_FAMILY};
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                background: #FFFFFF;
                padding: 4px;
                color: #2D3748;
            }}
            QListWidget::item {{
                padding: 4px 8px;
                font-size: 12px;
            }}
            QListWidget::item:hover {{
                background: #EDF2F7;
            }}
        """)
        self.components_list.setMaximumHeight(120)
        comp_card_layout.addWidget(self.components_list)
        layout.addWidget(comp_card)

        layout.addStretch()
        return tab

    def _create_programs_tab(self) -> QWidget:
        """Create the programs tab."""
        tab = QWidget()
        tab.setStyleSheet("")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Quick launch section
        section = QFrame()
        section.setObjectName("detailSection")
        section.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 16px;
            }}
        """)
        section_layout = QVBoxLayout(section)
        section_layout.setSpacing(10)
        section_layout.setContentsMargins(16, 16, 16, 16)

        section_title = QLabel("快速启动")
        section_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        section_layout.addWidget(section_title)

        # File picker
        file_layout = QHBoxLayout()
        file_layout.setSpacing(8)
        self.exe_path = QLineEdit()
        self.exe_path.setPlaceholderText("选择要运行的 .exe 文件...")
        self.exe_path.setStyleSheet(INPUT_STYLE)
        file_layout.addWidget(self.exe_path, 1)

        btn_browse = QPushButton("浏览...")
        btn_browse.setStyleSheet(BTN_DEFAULT)
        btn_browse.clicked.connect(self.browse_exe)
        file_layout.addWidget(btn_browse)

        section_layout.addLayout(file_layout)

        # Args + run
        args_layout = QHBoxLayout()
        args_layout.setSpacing(8)
        self.exe_args = QLineEdit()
        self.exe_args.setPlaceholderText("命令行参数 (可选)")
        self.exe_args.setStyleSheet(INPUT_STYLE)
        args_layout.addWidget(self.exe_args, 1)

        btn_run_exe = QPushButton("运行")
        btn_run_exe.setStyleSheet(BTN_PRIMARY)
        btn_run_exe.clicked.connect(self.run_executable)
        btn_run_exe.setFixedWidth(80)
        args_layout.addWidget(btn_run_exe)

        section_layout.addLayout(args_layout)

        layout.addWidget(section)

        # Shortcuts section
        shortcuts_section = QFrame()
        shortcuts_section.setObjectName("detailSection")
        shortcuts_section.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 16px;
            }}
        """)
        shortcuts_layout = QVBoxLayout(shortcuts_section)
        shortcuts_layout.setSpacing(8)
        shortcuts_layout.setContentsMargins(16, 16, 16, 16)

        shortcuts_title = QLabel("快捷方式")
        shortcuts_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        shortcuts_layout.addWidget(shortcuts_title)

        self.shortcuts_list = QListWidget()
        self.shortcuts_list.setStyleSheet(f"""
            QListWidget {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                background: #ffffff;
                color: #333333;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                font-size: 12px;
            }}
            QListWidget::item:hover {{
                background: #f5f5f5;
            }}
        """)
        shortcuts_layout.addWidget(self.shortcuts_list)

        layout.addWidget(shortcuts_section, 1)
        return tab

    def _create_components_tab(self) -> QWidget:
        """Create the components tab."""
        tab = QWidget()
        tab.setStyleSheet("")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Components section
        section = QFrame()
        section.setObjectName("detailSection")
        section.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 16px;
            }}
        """)
        section_layout = QVBoxLayout(section)
        section_layout.setSpacing(10)
        section_layout.setContentsMargins(16, 16, 16, 16)

        section_title = QLabel("可用组件")
        section_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        section_layout.addWidget(section_title)

        # Component table
        self.comp_table = QTableWidget()
        self.comp_table.setColumnCount(3)
        self.comp_table.setHorizontalHeaderLabels(["组件", "描述", "状态"])
        self.comp_table.horizontalHeader().setStretchLastSection(True)
        self.comp_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.comp_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.comp_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.comp_table.setSelectionMode(QTableWidget.SingleSelection)
        self.comp_table.setStyleSheet(TABLE_STYLE)
        section_layout.addWidget(self.comp_table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.btn_install = QPushButton("安装选中组件")
        self.btn_install.setStyleSheet(BTN_PRIMARY)
        self.btn_install.clicked.connect(self.install_component)
        btn_layout.addWidget(self.btn_install)

        self.btn_uninstall = QPushButton("卸载选中组件")
        self.btn_uninstall.setStyleSheet(BTN_DANGER)
        self.btn_uninstall.clicked.connect(self.uninstall_component)
        btn_layout.addWidget(self.btn_uninstall)

        self.btn_refresh_comp = QPushButton("刷新")
        self.btn_refresh_comp.setStyleSheet(BTN_DEFAULT)
        self.btn_refresh_comp.clicked.connect(self.refresh_components)
        btn_layout.addWidget(self.btn_refresh_comp)

        btn_layout.addStretch()
        section_layout.addLayout(btn_layout)

        layout.addWidget(section)

        # Install progress
        self.comp_progress = QProgressBar()
        self.comp_progress.setVisible(False)
        self.comp_progress.setStyleSheet(f"""
            QProgressBar {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                text-align: center;
                font-size: 10px;
                background: #ffffff;
                color: #333333;
                height: 18px;
            }}
            QProgressBar::chunk {{
                background: #4a90d9;
                border-radius: 2px;
            }}
        """)
        layout.addWidget(self.comp_progress)

        layout.addStretch()
        return tab

    def _create_config_tab(self) -> QWidget:
        """Create the configuration tab."""
        tab = QWidget()
        tab.setStyleSheet("")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Wine configuration section
        section = QFrame()
        section.setObjectName("detailSection")
        section.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 16px;
            }}
        """)
        section_layout = QVBoxLayout(section)
        section_layout.setSpacing(12)
        section_layout.setContentsMargins(16, 16, 16, 16)

        section_title = QLabel("Wine 设置")
        section_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        section_layout.addWidget(section_title)

        # Windows version
        ver_layout = QHBoxLayout()
        ver_layout.setSpacing(8)
        ver_label = QLabel("Windows 版本:")
        ver_label.setStyleSheet(f"""
            font-size: 12px;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        ver_layout.addWidget(ver_label)

        self.winver_combo = QComboBox()
        self.winver_combo.addItems([
            "win11", "win10", "win81", "win8", "win7", "vista",
            "win2003", "winxp", "win2k", "winme", "win98",
            "win95"
        ])
        self.winver_combo.setStyleSheet(COMBO_STYLE)
        self.winver_combo.setFixedWidth(180)
        ver_layout.addWidget(self.winver_combo)

        btn_apply_winver = QPushButton("应用")
        btn_apply_winver.setStyleSheet(BTN_DEFAULT)
        btn_apply_winver.clicked.connect(self.apply_windows_version)
        ver_layout.addWidget(btn_apply_winver)
        ver_layout.addStretch()
        section_layout.addLayout(ver_layout)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("detailSep")
        sep.setStyleSheet("max-height: 1px;")
        section_layout.addWidget(sep)

        # DLL section
        dll_header = QLabel("DLL 覆盖")
        dll_header.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        section_layout.addWidget(dll_header)

        self.dll_table = QTableWidget()
        self.dll_table.setColumnCount(2)
        self.dll_table.setHorizontalHeaderLabels(["DLL", "模式"])
        self.dll_table.horizontalHeader().setStretchLastSection(True)
        self.dll_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.dll_table.setStyleSheet(TABLE_STYLE)
        self.dll_table.setMaximumHeight(150)
        section_layout.addWidget(self.dll_table)

        dll_btn_layout = QHBoxLayout()
        dll_btn_layout.setSpacing(8)
        btn_add_dll = QPushButton("添加")
        btn_add_dll.setStyleSheet(BTN_DEFAULT)
        btn_add_dll.clicked.connect(self.add_dll_override)
        dll_btn_layout.addWidget(btn_add_dll)

        btn_remove_dll = QPushButton("删除")
        btn_remove_dll.setStyleSheet(BTN_DEFAULT)
        btn_remove_dll.clicked.connect(self.remove_dll_override)
        dll_btn_layout.addWidget(btn_remove_dll)
        dll_btn_layout.addStretch()
        section_layout.addLayout(dll_btn_layout)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("detailSep")
        sep2.setStyleSheet("max-height: 1px;")
        section_layout.addWidget(sep2)

        # Environment section
        env_header = QLabel("环境配置")
        env_header.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        section_layout.addWidget(env_header)

        env_layout = QHBoxLayout()
        env_layout.setSpacing(8)
        env_label = QLabel("环境类型:")
        env_label.setStyleSheet(f"""
            font-size: 12px;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        env_layout.addWidget(env_label)

        self.env_combo = QComboBox()
        self.env_combo.addItems(["gaming", "office", "custom"])
        self.env_combo.setStyleSheet(COMBO_STYLE)
        self.env_combo.setFixedWidth(180)
        env_layout.addWidget(self.env_combo)

        btn_apply_env = QPushButton("应用")
        btn_apply_env.setStyleSheet(BTN_DEFAULT)
        btn_apply_env.clicked.connect(self.apply_environment)
        env_layout.addWidget(btn_apply_env)
        env_layout.addStretch()
        section_layout.addLayout(env_layout)

        layout.addWidget(section)
        layout.addStretch()
        return tab

    def _create_registry_tab(self) -> QWidget:
        """Create the registry tab with built-in tree viewer."""
        tab = QWidget()
        tab.setStyleSheet("")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        lbl = QLabel("注册表浏览器")
        lbl.setStyleSheet(f"""
            font-size: 13px; font-weight: 600; color: #333333;
            font-family: {FONT_FAMILY};
        """)
        toolbar.addWidget(lbl)

        btn_refresh_reg = QPushButton("刷新")
        btn_refresh_reg.setStyleSheet(BTN_DEFAULT)
        btn_refresh_reg.setFixedWidth(80)
        btn_refresh_reg.clicked.connect(self._refresh_registry_tree)
        toolbar.addWidget(btn_refresh_reg)

        btn_new_folder = QPushButton("新建文件夹")
        btn_new_folder.setStyleSheet(BTN_PRIMARY)
        btn_new_folder.clicked.connect(lambda: self._add_registry_key(None))
        toolbar.addWidget(btn_new_folder)

        btn_new32 = QPushButton("新建项(32位)")
        btn_new32.setStyleSheet(BTN_DEFAULT)
        btn_new32.clicked.connect(lambda: self._add_registry_key("32"))
        toolbar.addWidget(btn_new32)

        btn_new64 = QPushButton("新建项(64位)")
        btn_new64.setStyleSheet(BTN_DEFAULT)
        btn_new64.clicked.connect(lambda: self._add_registry_key("64"))
        toolbar.addWidget(btn_new64)

        btn_del_key = QPushButton("删除选中项")
        btn_del_key.setStyleSheet(BTN_DANGER)
        btn_del_key.clicked.connect(self._delete_registry_key)
        toolbar.addWidget(btn_del_key)

        self.reg_source_label = QLabel("浏览: user.reg + system.reg")
        self.reg_source_label.setStyleSheet(f"""
            font-size: 11px; color: #999999; font-family: {FONT_FAMILY};
        """)
        toolbar.addWidget(self.reg_source_label)

        # Loading indicator — shown while the tree is being parsed in the
        # background so the UI never freezes.
        self.reg_loading_label = QLabel("注册表正在加载中...")
        self.reg_loading_label.setStyleSheet(f"""
            font-size: 11px; font-weight: 600; color: #ED8936;
            font-family: {FONT_FAMILY};
        """)
        self.reg_loading_label.setVisible(False)
        toolbar.addWidget(self.reg_loading_label)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Splitter: tree on left, value on right
        splitter = QSplitter(Qt.Horizontal)

        # Registry tree
        self.reg_tree = QTreeWidget()
        self.reg_tree.setHeaderLabels(["注册表项"])
        self.reg_tree.setStyleSheet(f"""
            QTreeWidget {{
                font-family: {FONT_FAMILY};
                font-size: 12px;
                border: 1px solid #cccccc;
                border-radius: 3px;
                background: #ffffff;
                color: #333333;
            }}
            QTreeWidget::item {{
                padding: 3px 6px;
            }}
            QTreeWidget::item:selected {{
                background: #4a90d9;
                color: #ffffff;
            }}
        """)
        self.reg_tree.setMinimumWidth(280)
        self.reg_tree.itemClicked.connect(self._on_reg_item_clicked)
        splitter.addWidget(self.reg_tree)

        # Value display area
        self.reg_value_widget = QWidget()
        value_layout = QVBoxLayout(self.reg_value_widget)
        value_layout.setContentsMargins(8, 8, 8, 8)
        value_layout.setSpacing(8)

        self.reg_key_path = QLabel("")
        self.reg_key_path.setStyleSheet(f"""
            font-size: 11px; font-weight: 600; color: #666666;
            font-family: {FONT_FAMILY};
        """)
        self.reg_key_path.setWordWrap(True)
        value_layout.addWidget(self.reg_key_path)

        self.reg_value_table = QTableWidget(0, 2)
        self.reg_value_table.setHorizontalHeaderLabels(["名称", "数据"])
        self.reg_value_table.horizontalHeader().setStretchLastSection(True)
        self.reg_value_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.reg_value_table.setAlternatingRowColors(False)
        self.reg_value_table.verticalHeader().setVisible(False)
        self.reg_value_table.setStyleSheet(f"""
            QTableWidget {{
                font-family: {FONT_FAMILY};
                font-size: 12px;
                border: 1px solid #cccccc;
                border-radius: 3px;
                background: #ffffff;
                color: #333333;
            }}
            QTableWidget::item {{
                padding: 2px 6px;
            }}
            QHeaderView::section {{
                font-family: {FONT_FAMILY};
                font-size: 11px;
                font-weight: 600;
                background: #f5f5f5;
                color: #444444;
                border: 1px solid #cccccc;
                padding: 4px 8px;
            }}
        """)
        value_layout.addWidget(self.reg_value_table, 1)

        splitter.addWidget(self.reg_value_widget)
        splitter.setSizes([350, 350])
        layout.addWidget(splitter, 1)

        # Import .reg file section
        section = QFrame()
        section.setObjectName("detailSection")
        section.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                padding: 12px;
            }}
        """)
        section_layout = QHBoxLayout(section)
        section_layout.setSpacing(8)
        section_layout.setContentsMargins(12, 8, 12, 8)

        section_title = QLabel("导入 .reg 文件:")
        section_title.setStyleSheet(f"""
            font-size: 12px; font-weight: 600; color: #333333;
            font-family: {FONT_FAMILY};
        """)
        section_layout.addWidget(section_title)

        self.reg_file_path = QLineEdit()
        self.reg_file_path.setPlaceholderText("选择 .reg 文件...")
        self.reg_file_path.setStyleSheet(INPUT_STYLE)
        section_layout.addWidget(self.reg_file_path, 1)

        btn_browse_reg = QPushButton("浏览...")
        btn_browse_reg.setStyleSheet(BTN_DEFAULT)
        btn_browse_reg.clicked.connect(self.browse_reg_file)
        section_layout.addWidget(btn_browse_reg)

        btn_import_reg = QPushButton("导入")
        btn_import_reg.setStyleSheet(BTN_PRIMARY)
        btn_import_reg.clicked.connect(self.import_reg_file)
        section_layout.addWidget(btn_import_reg)

        layout.addWidget(section)
        return tab

    def _on_tab_changed(self, index: int):
        """Lazy-load the registry tree when the registry tab is selected.

        Loading runs in a background thread so the UI never freezes; if the
        user switches to another tab, the pending load is cancelled.
        """
        if index == self.tabs.indexOf(self.registry_tab):
            if not self._registry_loaded and self.current_bottle:
                self._refresh_registry_tree()
                self._registry_loaded = True
        else:
            self._cancel_registry_load()

    def _cancel_registry_load(self):
        """Cancel a pending background registry load."""
        thread = getattr(self, "_reg_thread", None)
        if thread is not None and thread.isRunning():
            thread.cancel()
            thread.wait(2000)
        self._reg_thread = None
        self.reg_loading_label.setVisible(False)

    def _refresh_registry_tree(self):
        """Refresh the registry tree asynchronously (never blocks the UI)."""
        self._cancel_registry_load()
        self.reg_tree.clear()
        self.reg_value_table.setRowCount(0)
        self.reg_key_path.setText("")

        if not self.current_bottle:
            return

        self.reg_loading_label.setVisible(True)

        # Parse the .reg files in a worker thread; only the resulting key
        # paths come back to the GUI thread (QTreeWidgetItem must be created
        # on the main thread).
        thread = _RegistryLoadThread(str(self.current_bottle.path))
        thread.loaded.connect(self._on_registry_loaded)
        # Hide the loading hint when the worker finishes (loaded or cancelled)
        thread.finished.connect(lambda: self.reg_loading_label.setVisible(False))
        self._reg_thread = thread
        thread.start()

    def _on_registry_loaded(self, key_paths: list):
        """Build the tree from key paths parsed by the worker thread."""
        self.reg_source_label.setText("浏览: user.reg + system.reg")
        if key_paths:
            self._build_registry_tree(key_paths)
        self.reg_tree.expandToDepth(1)

    def _parse_reg_key_path(self, line: str) -> str:
        """Extract the key path from a .reg line like [Key\\Path] timestamp."""
        start = line.find("[")
        end = line.find("]")
        if start < 0 or end < 0 or end <= start:
            return ""
        key_path = line[start + 1:end].strip()
        return key_path

    def _build_registry_tree(self, key_paths: list):
        """Populate the tree from a list of registry key paths.

        ``key_paths`` is a list of full key paths (e.g.
        "Software\\Microsoft\\Windows NT\\CurrentVersion") parsed in the
        background thread. Keys are added incrementally, reusing existing
        parent nodes so duplicate prefixes don't create duplicates.
        """
        root_items = {}  # top_key -> QTreeWidgetItem

        def ensure_item(parent_item, name, full_path):
            if parent_item is None:
                item = root_items.get(name)
                if item is None:
                    item = QTreeWidgetItem(self.reg_tree, [name])
                    item.setData(0, Qt.UserRole, name)
                    root_items[name] = item
                return item
            for i in range(parent_item.childCount()):
                if parent_item.child(i).text(0) == name:
                    return parent_item.child(i)
            child = QTreeWidgetItem(parent_item, [name])
            child.setData(0, Qt.UserRole, full_path)
            return child

        for key_path in key_paths:
            if not key_path:
                continue
            parts = key_path.split("\\\\")
            cur = None
            full = ""
            for part in parts:
                full = part if not full else full + "\\\\" + part
                cur = ensure_item(cur, part, full)

        self._reg_root_items = root_items

    def _on_reg_item_clicked(self, item, column):
        """Handle clicking a registry tree item."""
        self.reg_value_table.setRowCount(0)

        # Get the full key path (reconstruct in .reg format)
        parts = []
        cur = item
        while cur:
            parts.insert(0, cur.text(0))
            cur = cur.parent()
        key_path = "\\\\".join(parts)

        self.reg_key_path.setText(f"[{key_path}]")

        # Read values from the .reg file for this key (only the hive the
        # key belongs to — user.reg for HKCU, system.reg for HKLM).
        if not self.current_bottle:
            return

        hive, _, bare_key = key_path.partition("\\\\")
        reg_name = "user.reg" if hive == "HKCU" else "system.reg"
        reg_path = self.current_bottle.path / reg_name
        if not reg_path.exists():
            return
        try:
            text = reg_path.read_text(encoding="utf-8", errors="replace")
            self._populate_values_for_key(text, bare_key)
        except Exception:
            pass

    def _get_selected_reg_path(self) -> str:
        """Return the selected tree item's full registry path (HKCU\\… / HKLM\\…)."""
        item = self.reg_tree.currentItem()
        if not item:
            return ""
        parts = []
        cur = item
        while cur:
            parts.insert(0, cur.text(0))
            cur = cur.parent()
        return "\\\\".join(parts)

    def _add_registry_key(self, arch=None):
        """Create a new registry key under the selected key.

        ``arch``: "32" → /reg:32, "64" → /reg:64, None → default view
        (used by the "新建文件夹" button).
        """
        if not self.current_bottle:
            return
        parent = self._get_selected_reg_path()
        if not parent:
            QMessageBox.information(self, "提示", "请先在左侧选择一个注册表项。")
            return
        from PyQt5.QtWidgets import QInputDialog
        title = "新建文件夹" if arch is None else f"新建项 ({arch}位)"
        new_name, ok = QInputDialog.getText(
            self, title, "新项名称:", QLineEdit.Normal, "")
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        # Sanity check: no path separators or [] inside a key name
        if any(c in new_name for c in "\\[]=;"):
            QMessageBox.warning(self, "无效名称", "项名称不能包含 \\ [ ] = ; 字符。")
            return

        new_path = parent + "\\\\" + new_name
        reg_cmd = f"reg add \"{new_path}\" /f"
        if arch == "32":
            reg_cmd += " /reg:32"
        elif arch == "64":
            reg_cmd += " /reg:64"
        try:
            result = self.wine.run_cmd(str(self.current_bottle.path), reg_cmd, timeout=60)
            if result.returncode == 0:
                QMessageBox.information(self, "完成", f"已创建注册表项：\n{new_path}")
                self._refresh_registry_tree()
            else:
                QMessageBox.warning(self, "创建失败",
                    (result.stderr or result.stdout or "wine reg add 返回非零").strip()[:300])
        except Exception as e:
            QMessageBox.warning(self, "创建失败", str(e))

    def _delete_registry_key(self):
        """Delete the selected registry key (and its subkeys)."""
        if not self.current_bottle:
            return
        target = self._get_selected_reg_path()
        if not target:
            QMessageBox.information(self, "提示", "请先在左侧选择一个注册表项。")
            return
        reply = QMessageBox.warning(
            self, "确认删除",
            f"确定要删除注册表项吗？\n{target}\n\n其下的所有子项和值将一并删除！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            result = self.wine.run_cmd(
                str(self.current_bottle.path),
                f"reg delete \"{target}\" /f", timeout=60)
            if result.returncode == 0:
                QMessageBox.information(self, "完成", f"已删除注册表项：\n{target}")
                self._refresh_registry_tree()
            else:
                QMessageBox.warning(self, "删除失败",
                    (result.stderr or result.stdout or "wine reg delete 返回非零").strip()[:300])
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))

    def _populate_values_for_key(self, reg_text: str, target_key: str):
        """Parse .reg text and populate values for a specific key."""
        in_target = False
        for line in reg_text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue

            if stripped.startswith("["):
                current_key = self._parse_reg_key_path(stripped)
                in_target = (current_key == target_key)
                continue

            if not in_target:
                continue

            if stripped.startswith("\"") or stripped.startswith("@"):
                # Value line: "name"=data or @=data
                eq_pos = stripped.find("=")
                if eq_pos < 0:
                    continue

                name = stripped[:eq_pos].strip()
                data = stripped[eq_pos + 1:].strip()

                # Clean up name
                if name == "@":
                    name = "(默认)"
                elif name.startswith("\"") and name.endswith("\""):
                    name = name[1:-1]

                # Clean up data
                if data.startswith("\"") and data.endswith("\""):
                    data = data[1:-1]
                elif data.startswith("dword:"):
                    data = f"0x{data[6:]}"
                elif data.startswith("hex"):
                    data = "(二进制数据)"

                row = self.reg_value_table.rowCount()
                self.reg_value_table.insertRow(row)
                self.reg_value_table.setItem(row, 0, QTableWidgetItem(name))
                self.reg_value_table.setItem(row, 1, QTableWidgetItem(data))

    def set_controls_enabled(self, enabled: bool):
        """Enable or disable controls."""
        for btn in [self.btn_run, self.btn_winecfg, self.btn_delete]:
            btn.setEnabled(enabled)
        self.tabs.setEnabled(enabled)

    def load_bottle(self, bottle: Bottle):
        """Load a bottle for display."""
        self.current_bottle = bottle
        self.set_controls_enabled(True)

        # Update title
        self.bottle_title.setText(bottle.name)

        # Update overview cards
        self._update_info_card(self.card_arch, "架构",
                               bottle.arch.replace("win", "Win"), "#3498db")
        self._update_info_card(self.card_winver, "Windows 版本",
                               bottle.windows_version, "#2ecc71")
        self._update_info_card(self.card_env, "环境",
                               bottle.environment.capitalize(), "#e74c3c")
        self._update_info_card(self.card_size, "大小",
                               bottle.drive_c_size, "#9b59b6")
        self._update_info_card(self.card_created, "创建时间",
                               bottle.created[:10], "#f39c12")

        # Description
        self.description_text.setPlainText(bottle.description)

        # Components
        self.components_list.clear()
        for comp in bottle.installed_components:
            item = QListWidgetItem(comp)
            self.components_list.addItem(item)
        if not bottle.installed_components:
            self.components_list.addItem("(暂无已安装组件)")

        # Configuration tab
        idx = self.winver_combo.findText(bottle.windows_version)
        if idx >= 0:
            self.winver_combo.setCurrentIndex(idx)
        idx = self.env_combo.findText(bottle.environment)
        if idx >= 0:
            self.env_combo.setCurrentIndex(idx)

        # DLL overrides
        self._load_dll_overrides()

        # Programs
        self.exe_path.clear()
        self.exe_args.clear()
        self._load_shortcuts()

        # Components
        self.refresh_components()

        # Registry tree
        self._registry_loaded = False  # Reset so it re-loads on next visit

    def _update_info_card(self, card: QFrame, title: str, value: str,
                          color: str):
        """Update an info card."""
        labels = card.findChildren(QLabel)
        if len(labels) >= 2:
            labels[0].setText(title)
            labels[1].setText(value)
            labels[1].setStyleSheet(f"""
                font-size: 15px;
                font-weight: 600;
                color: {color};
                font-family: {FONT_FAMILY};
            """)

    def _load_dll_overrides(self):
        """Load DLL overrides into the table."""
        if not self.current_bottle:
            return
        self.dll_table.setRowCount(0)
        overrides = self.current_bottle.dll_overrides
        for dll, mode in overrides.items():
            row = self.dll_table.rowCount()
            self.dll_table.insertRow(row)
            self.dll_table.setItem(row, 0, QTableWidgetItem(dll))
            self.dll_table.setItem(row, 1, QTableWidgetItem(mode))

    def _load_shortcuts(self):
        """Load program shortcuts from the bottle and Linux desktop.

        Deduplicates by file basename: when the same .lnk exists both on
        the bottle's Desktop and in its Start Menu, only one entry is
        shown (Desktop wins, since that is what the user actually sees
        inside the Windows desktop).
        """
        self.shortcuts_list.clear()
        found = 0
        # Map basename -> absolute path; first occurrence wins.
        seen = {}

        def _add(lnk_path: Path):
            nonlocal found
            name = lnk_path.name
            if name in seen:
                return
            seen[name] = str(lnk_path)
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, str(lnk_path))
            self.shortcuts_list.addItem(item)
            found += 1

        if self.current_bottle:
            drive_c = self.current_bottle.path / "drive_c"
            if drive_c.exists():
                # Desktop dirs first (higher priority for dedup)
                user = os.environ.get("USER", "root")
                desktop_dirs = [
                    drive_c / "users" / "Public" / "Desktop",
                    drive_c / "users" / "root" / "Desktop",
                    drive_c / "users" / "winuser" / "Desktop",
                    drive_c / "users" / user / "Desktop",
                ]
                for d in desktop_dirs:
                    if d.exists():
                        for exe in d.glob("*.lnk"):
                            _add(exe)

                # Then Start Menu (recursive) — skipped if already on Desktop
                start_menu = drive_c / "users" / user / "Start Menu"
                if start_menu.exists():
                    for exe in start_menu.glob("**/*.lnk"):
                        _add(exe)

                # Also scan Program Files for direct .exe shortcuts
                for pf in [drive_c / "Program Files (x86)",
                           drive_c / "Program Files"]:
                    if pf.exists():
                        for exe in pf.glob("**/*.exe"):
                            _add(exe)

        # Also scan the Linux desktop for .lnk files
        for desktop_dir in [Path.home() / "桌面", Path.home() / "Desktop"]:
            if desktop_dir.exists():
                for lnk in desktop_dir.glob("*.lnk"):
                    _add(lnk)

        if found == 0:
            self.shortcuts_list.addItem("(暂无快捷方式，运行程序后自动生成)")

        # Connect double-click to run
        self.shortcuts_list.itemDoubleClicked.connect(self._run_shortcut)

    def _run_shortcut(self, item):
        """Run a shortcut from the shortcuts list."""
        path = item.data(Qt.UserRole)
        if path and self.current_bottle:
            self.current_bottle.run(path)

    def save_description(self):
        """Save the bottle description."""
        if self.current_bottle:
            self.current_bottle.description = self.description_text.toPlainText()
            self.bottle_updated.emit(self.current_bottle.name)

    def _get_open_file_path(self, title: str, filter_str: str) -> str:
        """Open a light-themed file dialog and return the selected path."""
        from PyQt5.QtCore import QUrl
        from PyQt5.QtWidgets import QDialog
        dialog = QFileDialog(self, title, str(Path.home()), filter_str)
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setAcceptMode(QFileDialog.AcceptOpen)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        dialog.setSidebarUrls([
            QUrl.fromLocalFile(str(Path.home())),
            QUrl.fromLocalFile("/"),
            QUrl.fromLocalFile("/media/zuimeideshijie"),
            QUrl.fromLocalFile("/mnt"),
        ])
        dialog.setStyleSheet(FILE_DIALOG_STYLE)
        if dialog.exec_() == QDialog.Accepted:
            paths = dialog.selectedFiles()
            if paths:
                return paths[0]
        return ""

    def browse_exe(self):
        """Browse for an executable."""
        path = self._get_open_file_path(
            "选择可执行文件",
            "可执行文件 (*.exe *.msi);;所有文件 (*)")
        if path:
            self.exe_path.setText(path)

    def run_executable(self):
        """Run an executable in the current bottle."""
        if not self.current_bottle:
            return
        executable = self.exe_path.text().strip()
        if not executable:
            path = self._get_open_file_path(
                "选择要运行的程序",
                "可执行文件 (*.exe *.msi);;所有文件 (*)")
            if not path:
                return
            executable = path
            self.exe_path.setText(executable)

        args = self.exe_args.text().strip().split() if self.exe_args.text().strip() else None
        self.current_bottle.run(executable, args)

    def open_winecfg(self):
        """Open winecfg for the current bottle."""
        if self.current_bottle:
            self.wine.run(str(self.current_bottle.path), "winecfg", wait=False)

    def open_regedit(self):
        """Open regedit for the current bottle."""
        if self.current_bottle:
            self.wine.run(str(self.current_bottle.path), "regedit", wait=False)

    def open_task_manager(self):
        """Open the Windows-style Task Manager for the current bottle."""
        bottle_path = str(self.current_bottle.path) if self.current_bottle else None
        dialog = TaskManagerDialog(self.wine, bottle_path, self)
        dialog.show()

    def open_c_drive(self):
        """Open the current bottle's C: drive in the system file manager."""
        if not self.current_bottle:
            QMessageBox.information(self, "提示", "请先选择一个容器。")
            return
        drive_c = Path(self.current_bottle.path) / "drive_c"
        if not drive_c.exists():
            QMessageBox.warning(self, "提示", f"C 盘目录不存在：\n{drive_c}")
            return
        try:
            subprocess.Popen(
                ["xdg-open", str(drive_c)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception as e:
            QMessageBox.warning(self, "无法打开目录", str(e))

    def delete_bottle(self):
        """Delete the current bottle with confirmation."""
        if not self.current_bottle:
            return
        reply = QMessageBox.warning(
            self, "确认删除",
            f"确定要删除容器 '{self.current_bottle.name}' 吗？\n"
            f"所有数据将永久丢失！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            name = self.current_bottle.name
            try:
                self.current_bottle.delete()
            except OSError as e:
                QMessageBox.critical(self, "删除失败", str(e))
                return
            self.current_bottle = None
            self.set_controls_enabled(False)
            self.bottle_title.setText("选择容器以查看详情")
            self.bottle_deleted.emit(name)

    def rename_bottle(self):
        """Rename the current bottle."""
        if not self.current_bottle:
            return
        from PyQt5.QtWidgets import QInputDialog
        old_name = self.current_bottle.name
        new_name, ok = QInputDialog.getText(
            self, "重命名容器",
            "新名称:", QLineEdit.Normal, old_name
        )
        if ok and new_name and new_name.strip() != old_name:
            new_name = new_name.strip()
            if self.bottle_manager.rename_bottle(old_name, new_name):
                # Reload the bottle with the new path
                new_path = self.config.bottles_dir / new_name
                self.current_bottle = Bottle(str(new_path))
                self.bottle_title.setText(new_name)
                self.bottle_updated.emit(new_name)
            else:
                QMessageBox.warning(self, "重命名失败",
                    "无法重命名容器。可能同名容器已存在或原容器不存在。")

    def apply_windows_version(self):
        """Apply the selected Windows version."""
        if self.current_bottle:
            version = self.winver_combo.currentText()
            self.current_bottle.windows_version = version
            self.bottle_updated.emit(self.current_bottle.name)
            self._update_info_card(self.card_winver, "Windows 版本",
                                   version, "#2ecc71")

    def apply_environment(self):
        """Apply the selected environment."""
        if self.current_bottle:
            env = self.env_combo.currentText()
            self.current_bottle.environment = env
            self.bottle_updated.emit(self.current_bottle.name)
            self._update_info_card(self.card_env, "环境",
                                   env.capitalize(), "#e74c3c")

    def add_dll_override(self):
        """Add a DLL override."""
        from PyQt5.QtWidgets import QInputDialog
        dll, ok = QInputDialog.getText(self, "添加 DLL 覆盖",
                                        "DLL 名称 (如 d3d9):")
        if ok and dll:
            modes = ["native,builtin", "builtin,native", "native",
                     "builtin", "disable"]
            mode, ok = QInputDialog.getItem(self, "选择覆盖模式",
                                             "模式:", modes, 0, False)
            if ok:
                if self.current_bottle:
                    self.current_bottle.set_dll_override(dll.strip(), mode)
                    self._load_dll_overrides()

    def remove_dll_override(self):
        """Remove selected DLL override."""
        row = self.dll_table.currentRow()
        if row >= 0 and self.current_bottle:
            dll = self.dll_table.item(row, 0).text()
            self.current_bottle.remove_dll_override(dll)
            self._load_dll_overrides()

    def browse_reg_file(self):
        """Browse for a .reg file."""
        path = self._get_open_file_path(
            "选择注册表文件", "注册表文件 (*.reg);;所有文件 (*)")
        if path:
            self.reg_file_path.setText(path)

    def import_reg_file(self):
        """Import a .reg file into the current bottle."""
        if not self.current_bottle:
            return
        path = self.reg_file_path.text().strip()
        if not path:
            return
        self.wine.reg(str(self.current_bottle.path), path)

    def refresh_components(self):
        """Refresh the component list."""
        components = self.component_manager.get_available_components()
        installed = self.current_bottle.installed_components if self.current_bottle else []

        self.comp_table.setRowCount(0)
        for comp in components:
            row = self.comp_table.rowCount()
            self.comp_table.insertRow(row)
            item = QTableWidgetItem(comp.get("label", comp["name"]))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, comp["name"])
            self.comp_table.setItem(row, 0, item)
            desc_item = QTableWidgetItem(comp.get("description", ""))
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self.comp_table.setItem(row, 1, desc_item)
            status = "已安装" if comp["name"] in installed else "可安装"
            status_item = QTableWidgetItem(status)
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            if comp["name"] in installed:
                status_item.setForeground(Qt.darkGreen)
            self.comp_table.setItem(row, 2, status_item)

    def install_component(self):
        """Install the selected component in a background thread.

        Runs component_manager.install() on a QThread so a stuck or
        slow download (subprocess blocking) cannot freeze the UI.
        """
        row = self.comp_table.currentRow()
        if row < 0 or not self.current_bottle:
            QMessageBox.information(self, "提示", "请先选择一个组件。")
            return

        if self.current_bottle:
            item = self.comp_table.item(row, 0)
            name = item.data(Qt.UserRole)
            if not name:
                name = item.text()

            # Check if this component needs winetricks or has its own
            # installer (GitCode / official redist / direct copy)
            comp_info = self.component_manager.get_component_info(name)
            has_own_installer = bool(comp_info and (
                "gitcode" in comp_info or "redist" in comp_info or "direct" in comp_info))
            needs_winetricks = not has_own_installer
            if needs_winetricks and not self.component_manager.is_available:
                QMessageBox.warning(self, "缺少依赖",
                    "未找到 winetricks，无法安装此组件。\n\n"
                    "请安装 winetricks 后重试：\n"
                    "  sudo apt install winetricks\n\n"
                    "或从 https://github.com/Winetricks/winetricks 下载。")
                return

            self.comp_progress.setVisible(True)
            self.comp_progress.setValue(0)
            QApplication.processEvents()

            bottle_path = str(self.current_bottle.path)
            self.comp_status_label = QLabel("准备安装...")
            self.comp_status_label.setStyleSheet(f"""
                font-size: 11px;
                color: #666666;
                font-family: {FONT_FAMILY};
            """)
            parent_widget = self.comp_progress.parentWidget()
            if parent_widget:
                parent_layout = parent_widget.layout()
                if parent_layout:
                    parent_layout.insertWidget(
                        parent_layout.indexOf(self.comp_progress),
                        self.comp_status_label
                    )
            self.comp_status_label.show()

            # Disable the install button while running to prevent re-entry
            for btn in self.findChildren(QPushButton):
                if "安装" in btn.text():
                    btn.setEnabled(False)
                    self._install_btn = btn
                    break

            class InstallCompThread(QThread):
                progress = pyqtSignal(int, int, str)
                finished_sig = pyqtSignal(bool, str, str)  # ok, name, error_log

                def __init__(self, cm, name, bottle_path):
                    super().__init__()
                    self._cm = cm
                    self._name = name
                    self._bottle_path = bottle_path

                def run(self):
                    def on_progress(v, t, m=None):
                        self.progress.emit(v, t, m or "")
                    ok, error_log = self._cm.install(
                        self._name, self._bottle_path, on_progress)
                    self.finished_sig.emit(ok, self._name, error_log)

            self._install_thread = InstallCompThread(
                self.component_manager, name, bottle_path)
            self._install_thread.progress.connect(self._on_install_progress)
            self._install_thread.finished_sig.connect(self._on_install_done)
            self._install_thread.start()

    def _on_install_progress(self, v, t, m=""):
        """Handle install progress updates from the background thread."""
        self.comp_progress.setValue(v)
        if m:
            self.comp_status_label.setText(m)
        QApplication.processEvents()

    def _on_install_done(self, ok: bool, name: str, error_log: str):
        """Handle install completion from the background thread."""
        if ok:
            self.current_bottle.add_component(name)
            self.refresh_components()
            self.comp_progress.setValue(100)
            QMessageBox.information(self, "安装完成",
                                    f"组件 '{name}' 安装成功。")
        else:
            log_text = error_log if error_log else "（无详细输出）"
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("安装失败")
            msg_box.setText(f"组件 '{name}' 安装失败。")
            msg_box.setDetailedText(log_text)
            msg_box.exec_()
        self.comp_progress.setVisible(False)
        if hasattr(self, "_install_btn") and self._install_btn:
            self._install_btn.setEnabled(True)
            self._install_btn = None

    def uninstall_component(self):
        """Uninstall the selected component from the bottle."""
        row = self.comp_table.currentRow()
        if row < 0 or not self.current_bottle:
            QMessageBox.information(self, "提示", "请先选择一个已安装的组件。")
            return

        item = self.comp_table.item(row, 0)
        name = item.data(Qt.UserRole)
        if not name:
            name = item.text()

        if name not in self.current_bottle.installed_components:
            QMessageBox.information(self, "提示", f"组件 '{name}' 尚未安装，无需卸载。")
            return

        reply = QMessageBox.warning(
            self, "确认卸载",
            f"确定要从容器中移除组件 '{name}' 吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.current_bottle.remove_component(name)
        self.refresh_components()
        QMessageBox.information(self, "卸载完成", f"组件 '{name}' 已从记录中移除。")