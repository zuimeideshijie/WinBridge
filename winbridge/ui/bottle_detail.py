"""Bottle detail view widget — Windows-native styled detail panel."""

import os
import subprocess
import threading
from pathlib import Path
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QThread, QTimer
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QGridLayout, QGroupBox, QTabWidget,
    QTextEdit, QComboBox, QLineEdit, QFormLayout, QListWidget,
    QListWidgetItem, QSplitter, QMessageBox, QFileDialog,
    QApplication, QDialog, QDialogButtonBox, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu,
    QAction, QProgressBar, QSpacerItem, QSizePolicy,
    QTreeWidget, QTreeWidgetItem,
    QStyle,
)

from ..core import shortcuts
from ..core.bottle import (Bottle, BottleManager, ENVIRONMENT_LABELS,
                           environment_key, environment_label)
from ..core.wine import Wine
from ..core.config import Config
from ..core.download import ComponentManager
from ..core.theme import ThemeManager
from .dialogs import CreateBottleDialog, FirstRunDialog, TaskManagerDialog


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


class _IconLoadThread(QThread):
    """Extract program icons off the GUI thread.

    Parsing PE resources takes a few milliseconds per file, but a bottle can
    hold hundreds of executables — doing it inline would stall the tab, so
    icons are filled in as they become available.
    """
    icons_ready = pyqtSignal(dict)

    def __init__(self, entries: list, cache_dir):
        super().__init__()
        self._entries = list(entries)
        self._cache_dir = Path(cache_dir)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        result = {}
        for entry in self._entries:
            if self._cancel:
                return
            target = entry.get("target", "")
            if not target:
                continue
            icon = shortcuts.extract_icon(target, self._cache_dir)
            if icon:
                result[target] = icon
        if result and not self._cancel:
            self.icons_ready.emit(result)


class BottleDetailWidget(QWidget):
    """Detailed view of a single bottle."""

    bottle_deleted = pyqtSignal(str)
    bottle_updated = pyqtSignal(str)

    def __init__(self, config: Config = None):
        super().__init__()
        self.config = config or Config()
        self.bottle_manager = BottleManager(self.config)
        self.wine = Wine(self.config.wine_path)
        self.component_manager = ComponentManager(self.config)
        self.theme = ThemeManager(self.config)
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
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 0, 16, 0)
        toolbar_layout.setSpacing(8)

        self.bottle_title = QLabel("选择容器以查看详情")
        self.bottle_title.setObjectName("toolbarTitle")
        toolbar_layout.addWidget(self.bottle_title)

        toolbar_layout.addStretch()

        # Action buttons
        self.btn_run = QPushButton("运行")
        self.btn_run.setObjectName("btnPrimary")
        self.btn_run.clicked.connect(self.run_executable)
        toolbar_layout.addWidget(self.btn_run)

        self.btn_winecfg = QPushButton("winecfg")
        self.btn_winecfg.setObjectName("btnDefault")
        self.btn_winecfg.clicked.connect(self.open_winecfg)
        toolbar_layout.addWidget(self.btn_winecfg)

        self.btn_taskmgr = QPushButton("任务管理器")
        self.btn_taskmgr.setObjectName("btnDefault")
        self.btn_taskmgr.clicked.connect(self.open_task_manager)
        toolbar_layout.addWidget(self.btn_taskmgr)

        self.btn_c_drive = QPushButton("前往C盘")
        self.btn_c_drive.setObjectName("btnDefault")
        self.btn_c_drive.setIcon(self.style().standardIcon(QStyle.SP_DirIcon))
        self.btn_c_drive.clicked.connect(self.open_c_drive)
        toolbar_layout.addWidget(self.btn_c_drive)

        toolbar_layout.addStretch()

        self.btn_rename = QPushButton("重命名")
        self.btn_rename.setObjectName("btnDefault")
        self.btn_rename.clicked.connect(self.rename_bottle)
        toolbar_layout.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.setObjectName("btnDanger")
        self.btn_delete.clicked.connect(self.delete_bottle)
        toolbar_layout.addWidget(self.btn_delete)

        layout.addWidget(toolbar)

        # === Content area with tabs ===
        self.tabs = QTabWidget()

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

        # Tab 5: Registry — the browser itself opens in its own window, so the
        # main window stays usable while the (large) registry tree loads.
        self.registry_panel = self._create_registry_tab()
        self.registry_tab = QWidget()
        self.tabs.addTab(self.registry_tab, "注册表")
        self._registry_loaded = False
        self._reg_index = {}
        self._registry_window = None
        self._last_tab_index = 0

        # Lazy-load registry tree when tab is selected
        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tabs, 1)

        # Left-aligned table headers read better than the centred default
        for table in (self.comp_table, self.dll_table, self.reg_value_table):
            table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Disable controls initially
        self.set_controls_enabled(False)

    def _create_info_card(self, title: str, value: str) -> QFrame:
        """Create a metric card for the overview row."""
        card = QFrame()
        card.setObjectName("infoCard")
        card.setMinimumHeight(70)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("metricKey")
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setWordWrap(True)
        layout.addWidget(value_label)

        return card

    def _create_overview_tab(self) -> QWidget:
        """Create the overview tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        # Info cards row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)

        self.card_arch = self._create_info_card("架构", "-")
        cards_layout.addWidget(self.card_arch)

        self.card_winver = self._create_info_card("Windows 版本", "-")
        cards_layout.addWidget(self.card_winver)

        self.card_env = self._create_info_card("环境", "-")
        cards_layout.addWidget(self.card_env)

        self.card_size = self._create_info_card("大小", "-")
        cards_layout.addWidget(self.card_size)

        self.card_created = self._create_info_card("创建时间", "-")
        cards_layout.addWidget(self.card_created)

        layout.addLayout(cards_layout)

        # Description section (card)
        desc_card = QFrame()
        desc_card.setObjectName("card")
        desc_card_layout = QVBoxLayout(desc_card)
        desc_card_layout.setContentsMargins(16, 14, 16, 14)
        desc_card_layout.setSpacing(8)

        desc_header = QLabel("描述")
        desc_header.setObjectName("sectionTitle")
        desc_card_layout.addWidget(desc_header)

        self.description_text = QTextEdit()
        self.description_text.setPlaceholderText("添加容器描述...")
        self.description_text.setMaximumHeight(80)
        desc_card_layout.addWidget(self.description_text)

        btn_save_desc = QPushButton("保存描述")
        btn_save_desc.setObjectName("btnDefault")
        btn_save_desc.clicked.connect(self.save_description)
        desc_card_layout.addWidget(btn_save_desc, 0, Qt.AlignLeft)
        layout.addWidget(desc_card)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("detailSep")
        layout.addWidget(sep2)

        # Installed components (card)
        comp_card = QFrame()
        comp_card_layout = QVBoxLayout(comp_card)
        comp_card_layout.setContentsMargins(16, 14, 16, 14)
        comp_card_layout.setSpacing(8)

        comp_header = QLabel("已安装组件")
        comp_header.setObjectName("sectionTitle")
        comp_card_layout.addWidget(comp_header)

        self.components_list = QListWidget()
        self.components_list.setObjectName("plainList")
        self.components_list.setMaximumHeight(120)
        comp_card_layout.addWidget(self.components_list)
        layout.addWidget(comp_card)

        layout.addStretch()
        return tab

    def _create_programs_tab(self) -> QWidget:
        """Create the programs tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Quick launch section
        section = QFrame()
        section.setObjectName("detailSection")
        section_layout = QVBoxLayout(section)
        section_layout.setSpacing(10)
        section_layout.setContentsMargins(16, 16, 16, 16)

        section_title = QLabel("快速启动")
        section_title.setObjectName("sectionTitle")
        section_layout.addWidget(section_title)

        # File picker
        file_layout = QHBoxLayout()
        file_layout.setSpacing(8)
        self.exe_path = QLineEdit()
        self.exe_path.setPlaceholderText("选择要运行的 .exe 文件...")
        file_layout.addWidget(self.exe_path, 1)

        btn_browse = QPushButton("浏览...")
        btn_browse.setObjectName("btnDefault")
        btn_browse.clicked.connect(self.browse_exe)
        file_layout.addWidget(btn_browse)

        section_layout.addLayout(file_layout)

        # Args + run
        args_layout = QHBoxLayout()
        args_layout.setSpacing(8)
        self.exe_args = QLineEdit()
        self.exe_args.setPlaceholderText("命令行参数 (可选)")
        args_layout.addWidget(self.exe_args, 1)

        btn_run_exe = QPushButton("运行")
        btn_run_exe.setObjectName("btnPrimary")
        btn_run_exe.clicked.connect(self.run_executable)
        btn_run_exe.setFixedWidth(80)
        args_layout.addWidget(btn_run_exe)

        section_layout.addLayout(args_layout)

        layout.addWidget(section)

        # Shortcuts section
        shortcuts_section = QFrame()
        shortcuts_section.setObjectName("detailSection")
        shortcuts_layout = QVBoxLayout(shortcuts_section)
        shortcuts_layout.setSpacing(8)
        shortcuts_layout.setContentsMargins(16, 16, 16, 16)

        shortcuts_title = QLabel("快捷方式")
        shortcuts_title.setObjectName("sectionTitle")
        shortcuts_layout.addWidget(shortcuts_title)

        self.shortcuts_list = QListWidget()
        self.shortcuts_list.setObjectName("plainList")
        self.shortcuts_list.setIconSize(QSize(26, 26))
        self.shortcuts_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.shortcuts_list.customContextMenuRequested.connect(self._shortcut_menu)
        self.shortcuts_list.itemDoubleClicked.connect(self._run_shortcut)
        shortcuts_layout.addWidget(self.shortcuts_list)

        shortcuts_hint = QLabel("双击运行 · 右键可打开、重命名、添加到桌面或卸载")
        shortcuts_hint.setObjectName("hint")

        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addWidget(shortcuts_hint, 1)

        self.btn_refresh_programs = QPushButton("刷新")
        self.btn_refresh_programs.setObjectName("btnDefault")
        self.btn_refresh_programs.setToolTip("重新扫描容器里的程序和快捷方式，并补全图标")
        self.btn_refresh_programs.clicked.connect(self.refresh_programs)
        footer.addWidget(self.btn_refresh_programs)

        self.btn_add_program = QPushButton("添加程序")
        self.btn_add_program.setObjectName("btnDefault")
        self.btn_add_program.setToolTip("选择一个 .exe，把它加入快捷方式列表")
        self.btn_add_program.clicked.connect(self.add_program_shortcut)
        footer.addWidget(self.btn_add_program)

        shortcuts_layout.addLayout(footer)

        layout.addWidget(shortcuts_section, 1)
        return tab

    def _create_components_tab(self) -> QWidget:
        """Create the components tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Components section
        section = QFrame()
        section.setObjectName("detailSection")
        section_layout = QVBoxLayout(section)
        section_layout.setSpacing(10)
        section_layout.setContentsMargins(16, 16, 16, 16)

        section_title = QLabel("可用组件")
        section_title.setObjectName("sectionTitle")
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
        self.comp_table.verticalHeader().setVisible(False)
        self.comp_table.setShowGrid(False)
        self.comp_table.setAlternatingRowColors(True)
        section_layout.addWidget(self.comp_table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        self.btn_install = QPushButton("安装选中组件")
        self.btn_install.setObjectName("btnPrimary")
        self.btn_install.clicked.connect(self.install_component)
        btn_layout.addWidget(self.btn_install)

        # Only visible while an install is running: aborts the download (or
        # the winetricks run) and leaves the bottle untouched.
        self.btn_cancel_comp = QPushButton("取消")
        self.btn_cancel_comp.setObjectName("btnDefault")
        self.btn_cancel_comp.setToolTip("取消正在下载/安装的组件")
        self.btn_cancel_comp.setVisible(False)
        self.btn_cancel_comp.clicked.connect(self.cancel_component_install)
        btn_layout.addWidget(self.btn_cancel_comp)

        self.btn_uninstall = QPushButton("卸载选中组件")
        self.btn_uninstall.setObjectName("btnDanger")
        self.btn_uninstall.clicked.connect(self.uninstall_component)
        btn_layout.addWidget(self.btn_uninstall)

        self.btn_refresh_comp = QPushButton("刷新")
        self.btn_refresh_comp.setObjectName("btnDefault")
        self.btn_refresh_comp.clicked.connect(self.refresh_components)
        btn_layout.addWidget(self.btn_refresh_comp)

        btn_layout.addStretch()
        section_layout.addLayout(btn_layout)

        layout.addWidget(section)

        # Install progress
        self.comp_progress = QProgressBar()
        self.comp_progress.setVisible(False)
        self.comp_progress.setObjectName("progressLabeled")
        layout.addWidget(self.comp_progress)

        layout.addStretch()
        return tab

    def _create_config_tab(self) -> QWidget:
        """Create the configuration tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Wine configuration section
        section = QFrame()
        section.setObjectName("detailSection")
        section_layout = QVBoxLayout(section)
        section_layout.setSpacing(12)
        section_layout.setContentsMargins(16, 16, 16, 16)

        section_title = QLabel("Wine 设置")
        section_title.setObjectName("sectionTitle")
        section_layout.addWidget(section_title)

        # Windows version
        ver_layout = QHBoxLayout()
        ver_layout.setSpacing(8)
        ver_label = QLabel("Windows 版本")
        ver_label.setObjectName("fieldLabel")
        ver_layout.addWidget(ver_label)

        self.winver_combo = QComboBox()
        self.winver_combo.addItems([
            "win11", "win10", "win81", "win8", "win7", "vista",
            "win2003", "winxp", "win2k", "winme", "win98",
            "win95"
        ])
        self.winver_combo.setFixedWidth(180)
        ver_layout.addWidget(self.winver_combo)

        btn_apply_winver = QPushButton("应用")
        btn_apply_winver.setObjectName("btnDefault")
        btn_apply_winver.clicked.connect(self.apply_windows_version)
        ver_layout.addWidget(btn_apply_winver)
        ver_layout.addStretch()
        section_layout.addLayout(ver_layout)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setObjectName("detailSep")
        section_layout.addWidget(sep)

        # DLL section
        dll_header = QLabel("DLL 覆盖")
        dll_header.setObjectName("sectionTitle")
        section_layout.addWidget(dll_header)

        self.dll_table = QTableWidget()
        self.dll_table.setColumnCount(2)
        self.dll_table.setHorizontalHeaderLabels(["DLL", "模式"])
        self.dll_table.horizontalHeader().setStretchLastSection(True)
        self.dll_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.dll_table.setMaximumHeight(150)
        self.dll_table.verticalHeader().setVisible(False)
        self.dll_table.setShowGrid(False)
        section_layout.addWidget(self.dll_table)

        dll_btn_layout = QHBoxLayout()
        dll_btn_layout.setSpacing(8)
        btn_add_dll = QPushButton("添加")
        btn_add_dll.setObjectName("btnDefault")
        btn_add_dll.clicked.connect(self.add_dll_override)
        dll_btn_layout.addWidget(btn_add_dll)

        btn_remove_dll = QPushButton("删除")
        btn_remove_dll.setObjectName("btnDefault")
        btn_remove_dll.clicked.connect(self.remove_dll_override)
        dll_btn_layout.addWidget(btn_remove_dll)
        dll_btn_layout.addStretch()
        section_layout.addLayout(dll_btn_layout)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setObjectName("detailSep")
        section_layout.addWidget(sep2)

        # Environment section
        env_header = QLabel("环境配置")
        env_header.setObjectName("sectionTitle")
        section_layout.addWidget(env_header)

        env_layout = QHBoxLayout()
        env_layout.setSpacing(8)
        env_label = QLabel("环境类型")
        env_label.setObjectName("fieldLabel")
        env_layout.addWidget(env_label)

        self.env_combo = QComboBox()
        for key, label in ENVIRONMENT_LABELS.items():
            self.env_combo.addItem(label, key)
        self.env_combo.setFixedWidth(180)
        env_layout.addWidget(self.env_combo)

        btn_apply_env = QPushButton("应用")
        btn_apply_env.setObjectName("btnDefault")
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
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        lbl = QLabel("注册表浏览器")
        lbl.setObjectName("sectionTitle")
        toolbar.addWidget(lbl)

        btn_refresh_reg = QPushButton("刷新")
        btn_refresh_reg.setObjectName("btnDefault")
        btn_refresh_reg.setFixedWidth(80)
        btn_refresh_reg.clicked.connect(self._refresh_registry_tree)
        toolbar.addWidget(btn_refresh_reg)

        btn_new_folder = QPushButton("新建文件夹")
        btn_new_folder.setObjectName("btnDefault")
        btn_new_folder.clicked.connect(lambda: self._add_registry_key(None))
        toolbar.addWidget(btn_new_folder)

        btn_new32 = QPushButton("新建项(32位)")
        btn_new32.setObjectName("btnDefault")
        btn_new32.clicked.connect(lambda: self._add_registry_key("32"))
        toolbar.addWidget(btn_new32)

        btn_new64 = QPushButton("新建项(64位)")
        btn_new64.setObjectName("btnDefault")
        btn_new64.clicked.connect(lambda: self._add_registry_key("64"))
        toolbar.addWidget(btn_new64)

        btn_del_key = QPushButton("删除选中项")
        btn_del_key.setObjectName("btnDanger")
        btn_del_key.clicked.connect(self._delete_registry_key)
        toolbar.addWidget(btn_del_key)

        self.reg_source_label = QLabel("浏览: user.reg + system.reg")
        self.reg_source_label.setObjectName("hint")
        toolbar.addWidget(self.reg_source_label)

        # Loading indicator — shown while the tree is being parsed in the
        # background so the UI never freezes.
        self.reg_loading_label = QLabel("注册表正在加载中...")
        self.reg_loading_label.setObjectName("statusWarn")
        self.reg_loading_label.setVisible(False)
        toolbar.addWidget(self.reg_loading_label)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Splitter: tree on left, value on right
        splitter = QSplitter(Qt.Horizontal)

        # Registry tree
        self.reg_tree = QTreeWidget()
        self.reg_tree.setHeaderLabels(["注册表项"])
        self.reg_tree.setMinimumWidth(280)
        self.reg_tree.itemClicked.connect(self._on_reg_item_clicked)
        # Branches are created lazily as they are expanded (17k keys)
        self.reg_tree.itemExpanded.connect(self._on_reg_item_expanded)
        splitter.addWidget(self.reg_tree)

        # Value display area
        self.reg_value_widget = QWidget()
        value_layout = QVBoxLayout(self.reg_value_widget)
        value_layout.setContentsMargins(8, 8, 8, 8)
        value_layout.setSpacing(8)

        self.reg_key_path = QLabel("")
        self.reg_key_path.setObjectName("mono")
        self.reg_key_path.setWordWrap(True)
        value_layout.addWidget(self.reg_key_path)

        self.reg_value_table = QTableWidget(0, 2)
        self.reg_value_table.setHorizontalHeaderLabels(["名称", "数据"])
        self.reg_value_table.horizontalHeader().setStretchLastSection(True)
        self.reg_value_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.reg_value_table.setAlternatingRowColors(False)
        self.reg_value_table.verticalHeader().setVisible(False)
        value_layout.addWidget(self.reg_value_table, 1)

        splitter.addWidget(self.reg_value_widget)
        splitter.setSizes([350, 350])
        layout.addWidget(splitter, 1)

        # Import .reg file section
        section = QFrame()
        section.setObjectName("detailSection")
        section_layout = QHBoxLayout(section)
        section_layout.setSpacing(8)
        section_layout.setContentsMargins(12, 8, 12, 8)

        section_title = QLabel("导入 .reg 文件")
        section_title.setObjectName("sectionTitle")
        section_layout.addWidget(section_title)

        self.reg_file_path = QLineEdit()
        self.reg_file_path.setPlaceholderText("选择 .reg 文件...")
        section_layout.addWidget(self.reg_file_path, 1)

        btn_browse_reg = QPushButton("浏览...")
        btn_browse_reg.setObjectName("btnDefault")
        btn_browse_reg.clicked.connect(self.browse_reg_file)
        section_layout.addWidget(btn_browse_reg)

        btn_import_reg = QPushButton("导入")
        btn_import_reg.setObjectName("btnPrimary")
        btn_import_reg.clicked.connect(self.import_reg_file)
        section_layout.addWidget(btn_import_reg)

        layout.addWidget(section)
        return tab

    def _on_tab_changed(self, index: int):
        """Clicking the 注册表 tab opens the registry browser in its own window.

        The tab is only a launcher: selection snaps back to the previous tab,
        so the main window keeps showing the page the user was on. The tree is
        parsed in a background thread, exactly as before.
        """
        if index == self.tabs.indexOf(self.registry_tab):
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(max(0, self._last_tab_index))
            self.tabs.blockSignals(False)
            self.open_registry_window()
            return
        self._last_tab_index = index

    def open_registry_window(self):
        """Show (or re-raise) the standalone registry browser window."""
        if not self.current_bottle:
            return
        if self._registry_window is None:
            window = QDialog(self.window())
            window.setObjectName("registryWindow")
            window.setWindowTitle(f"注册表 - {self.current_bottle.name}")
            window.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint
                                  | Qt.WindowMinMaxButtonsHint)
            window.setSizeGripEnabled(True)
            window_layout = QVBoxLayout(window)
            window_layout.setContentsMargins(0, 0, 0, 0)
            window_layout.addWidget(self.registry_panel)
            window.resize(1080, 720)
            self._registry_window = window

        self._registry_window.show()
        self._registry_window.raise_()
        self._registry_window.activateWindow()
        if not self._registry_loaded:
            self._registry_loaded = True
            self._refresh_registry_tree()

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
        self._reg_index = {}
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
        # Only the two hives are expanded eagerly: their direct children are
        # a few dozen items. Everything deeper is created on demand, because
        # materialising all ~17k keys at once freezes both windows.
        for i in range(self.reg_tree.topLevelItemCount()):
            self.reg_tree.topLevelItem(i).setExpanded(True)

    def _parse_reg_key_path(self, line: str) -> str:
        """Extract the key path from a .reg line like [Key\\Path] timestamp."""
        start = line.find("[")
        end = line.find("]")
        if start < 0 or end < 0 or end <= start:
            return ""
        key_path = line[start + 1:end].strip()
        return key_path

    def _build_registry_tree(self, key_paths: list):
        """Index the key paths and create only the two hive roots.

        ``key_paths`` are full paths ("HKCU\\Software\\…"). They are folded
        into a nested dict in one pass (O(n) instead of the previous
        sibling-scan, which was O(n²) and froze the UI on 17k keys). Tree
        items are then created lazily as branches are expanded — see
        ``_on_reg_item_expanded``.
        """
        index = {}
        for key_path in key_paths:
            if not key_path:
                continue
            node = index
            for part in key_path.split("\\\\"):
                node = node.setdefault(part, {})

        self._reg_index = index
        self.reg_tree.clear()
        self._reg_root_items = {}
        for root_name in ("HKCU", "HKLM"):
            children = index.get(root_name)
            if not children:
                continue
            item = QTreeWidgetItem(self.reg_tree, [root_name])
            item.setData(0, Qt.UserRole, root_name)
            self._reg_root_items[root_name] = item
            self._mark_registry_children(item, children)

    def _mark_registry_children(self, item, children: dict):
        """Attach a placeholder child so the expand arrow shows up."""
        if not children:
            return
        placeholder = QTreeWidgetItem(item, ["加载中…"])
        placeholder.setFlags(Qt.NoItemFlags)
        item.setData(0, Qt.UserRole + 1, True)

    @staticmethod
    def _item_key_path(item) -> str:
        """Full key path of a tree item ("HKCU\\Software\\…")."""
        parts = []
        current = item
        while current is not None:
            parts.insert(0, current.text(0))
            current = current.parent()
        return "\\\\".join(parts)

    def _on_reg_item_expanded(self, item):
        """Create one level of children the first time a branch is opened."""
        if not item.data(0, Qt.UserRole + 1):
            return
        item.setData(0, Qt.UserRole + 1, False)
        item.takeChildren()  # drop the "加载中…" placeholder

        node = self._reg_index
        for part in self._item_key_path(item).split("\\\\"):
            node = node.get(part)
            if not isinstance(node, dict):
                return
        self.reg_tree.setUpdatesEnabled(False)
        try:
            for name in sorted(node):
                child = QTreeWidgetItem(item, [name])
                child.setData(0, Qt.UserRole, name)
                self._mark_registry_children(child, node[name])
        finally:
            self.reg_tree.setUpdatesEnabled(True)

    def _on_reg_item_clicked(self, item, column):
        """Handle clicking a registry tree item."""
        self.reg_value_table.setRowCount(0)
        if item is None or not item.flags() & Qt.ItemIsSelectable:
            return  # the "加载中…" placeholder

        key_path = self._item_key_path(item)
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
                               bottle.arch.replace("win", "Win"))
        self._update_info_card(self.card_winver, "Windows 版本",
                               bottle.windows_version)
        self._update_info_card(self.card_env, "环境",
                               environment_label(bottle.environment))
        self._update_info_card(self.card_size, "大小",
                               bottle.drive_c_size)
        self._update_info_card(self.card_created, "创建时间",
                               bottle.created[:10])

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
        idx = self.env_combo.findData(environment_key(bottle.environment))
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
        if self._registry_window is not None:
            # The window belongs to the previous bottle: hide it and drop its
            # tree so the next open shows the new bottle's keys.
            self._registry_window.hide()
            self.reg_tree.clear()
            self.reg_value_table.setRowCount(0)
            self.reg_source_label.setText("浏览: user.reg + system.reg")

    def _update_info_card(self, card: QFrame, title: str, value: str):
        """Update an info card."""
        labels = card.findChildren(QLabel)
        if len(labels) >= 2:
            labels[0].setText(title)
            labels[1].setText(value)

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
        """Load this bottle's applications into the list.

        The stored list is merged with a fresh scan of the bottle only, so
        shortcuts survive deleting the Windows ``.lnk`` and nothing from the
        host desktop ever leaks in.
        """
        self.shortcuts_list.clear()
        self._shortcut_items = {}
        # Drop a previous icon pass before starting another one
        thread = getattr(self, "_icon_thread", None)
        if thread is not None and thread.isRunning():
            thread.cancel()
            thread.wait(1000)
        if not self.current_bottle:
            return

        discovered = shortcuts.discover(self.current_bottle.path)
        merged, changed = shortcuts.merge(self.current_bottle.shortcuts, discovered)
        if changed:
            self.current_bottle.shortcuts = merged

        fallback = self.style().standardIcon(QStyle.SP_FileIcon)
        muted = QColor(self.theme.get("text_muted"))
        for entry in merged:
            target = entry.get("target", "")
            name = entry.get("name") or Path(target).stem
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, target)
            icon_path = entry.get("icon") or ""
            has_icon = bool(icon_path) and Path(icon_path).exists()
            item.setIcon(QIcon(icon_path) if has_icon else fallback)
            item.setSizeHint(QSize(0, 36))
            if Path(target).exists():
                item.setToolTip(target)
            else:
                item.setForeground(muted)
                item.setToolTip(f"文件不存在：{target}")
            self.shortcuts_list.addItem(item)
            self._shortcut_items[target] = item

        if not merged:
            placeholder = QListWidgetItem("此容器中还没有可启动的程序")
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setForeground(muted)
            self.shortcuts_list.addItem(placeholder)
            return

        pending = [e for e in merged
                   if not (e.get("icon") and Path(e["icon"]).exists())]
        if pending:
            self._icon_bottle = self.current_bottle.name
            self._icon_thread = _IconLoadThread(
                pending, self.config.cache_dir / "icons")
            self._icon_thread.icons_ready.connect(self._on_icons_ready)
            self._icon_thread.start()

    def _on_icons_ready(self, icons: dict):
        """Attach icons extracted in the background and remember them."""
        if not icons or not self.current_bottle:
            return
        # Ignore results that arrived after switching to another bottle
        if getattr(self, "_icon_bottle", None) != self.current_bottle.name:
            return
        entries = self.current_bottle.shortcuts
        for entry in entries:
            icon = icons.get(entry.get("target"))
            if not icon:
                continue
            entry["icon"] = icon
            item = self._shortcut_items.get(entry["target"])
            if item is not None:
                item.setIcon(QIcon(icon))
        self.current_bottle.shortcuts = entries

    def _shortcut_menu(self, pos):
        """Right-click menu: open, rename, add to desktop, uninstall."""
        item = self.shortcuts_list.itemAt(pos)
        target = item.data(Qt.UserRole) if item else None
        if not target:
            return
        menu = QMenu(self.shortcuts_list)
        action_open = menu.addAction("打开")
        action_rename = menu.addAction("重命名")
        action_desktop = menu.addAction("添加到桌面")
        menu.addSeparator()
        action_uninstall = menu.addAction("卸载")
        action_uninstall.setToolTip("运行应用自带的卸载程序")
        action_force = menu.addAction("强制删除目录…")
        chosen = menu.exec_(self.shortcuts_list.mapToGlobal(pos))
        if chosen is action_open:
            self._run_shortcut(item)
        elif chosen is action_rename:
            self._rename_shortcut(item)
        elif chosen is action_desktop:
            self._shortcut_to_desktop(item)
        elif chosen is action_uninstall:
            self._uninstall_shortcut(item)
        elif chosen is action_force:
            self._force_remove_shortcut(item)

    def refresh_programs(self):
        """Rescan the bottle's programs, offering to drop dead shortcuts."""
        if not self.current_bottle:
            return
        self._load_shortcuts()

        missing = shortcuts.missing_targets(self.current_bottle.shortcuts)
        if not missing:
            return

        names = "\n".join(
            "· " + (entry.get("name") or Path(entry["target"]).stem)
            for entry in missing[:10])
        extra = (f"\n… 还有 {len(missing) - 10} 个"
                 if len(missing) > 10 else "")
        reply = QMessageBox.question(
            self, "清理失效快捷方式",
            f"发现 {len(missing)} 个快捷方式指向的程序已不存在：\n\n"
            f"{names}{extra}\n\n是否删除这些快捷方式？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return

        for entry in missing:
            self.current_bottle.forget_shortcut(entry["target"])
        self._load_shortcuts()

    def add_program_shortcut(self):
        """Pick an .exe on disk and list it under 快捷方式."""
        if not self.current_bottle:
            return
        path = self._get_open_file_path(
            "选择要添加的程序",
            "可执行文件 (*.exe);;所有文件 (*)")
        if not path:
            return

        target = str(Path(path))
        name = Path(target).stem
        icon = ""
        try:
            icon = shortcuts.extract_icon(
                Path(target), self.config.cache_dir / "icons") or ""
        except Exception:
            icon = ""

        if not self.current_bottle.add_shortcut(name, target, "exe", icon):
            QMessageBox.information(
                self, "已存在",
                f"「{name}」已经在快捷方式列表里了。")
            return
        self._load_shortcuts()

    def _uninstall_shortcut(self, item):
        """Uninstall a program, preferring its own uninstaller."""
        target = item.data(Qt.UserRole)
        if not target or not self.current_bottle:
            return
        name = item.text()
        plan = shortcuts.plan_uninstall(target, self.current_bottle.path)
        program, args = (shortcuts.find_uninstaller(
            plan, self.current_bottle.path) if plan else ("", []))
        if program:
            self._run_app_uninstaller(item, name, program, args)
            return
        self._force_remove_shortcut(item, name, plan)

    def _run_app_uninstaller(self, item, name: str, program: str, args: list):
        """Start the application's own uninstaller GUI."""
        if program == "msiexec":
            shown = "msiexec " + " ".join(args)
        else:
            shown = program
        reply = QMessageBox.question(
            self, "卸载",
            f"将启动「{name}」自带的卸载程序：\n{shown}\n\n"
            "请在随后弹出的窗口里完成卸载。\n"
            "卸载完成后列表可能仍显示条目，可再用「强制删除目录」清理残留。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        ok = self.current_bottle.run(program, args or None)
        if not ok:
            QMessageBox.warning(
                self, "无法启动卸载程序",
                f"未能启动：\n{shown}\n\n可改用「强制删除目录」。")
            return
        # The uninstaller removes files asynchronously; refresh once it had a
        # chance to create its UI, and again when the user comes back.
        QTimer.singleShot(4000, self._load_shortcuts)
        QMessageBox.information(
            self, "已启动卸载程序",
            f"「{name}」的卸载程序已启动，请在弹出的窗口里继续。")

    def _force_remove_shortcut(self, item, name: str = None, plan: dict = None):
        """Delete the program's own folder and shortcuts, after confirmation."""
        target = item.data(Qt.UserRole)
        if not target or not self.current_bottle:
            return

        # The list is rebuilt below, which destroys ``item`` — keep the name
        name = name or item.text()
        if plan is None:
            plan = shortcuts.plan_uninstall(target, self.current_bottle.path)
        if not plan:
            QMessageBox.information(
                self, "无法卸载",
                "没有找到「" + name + "」自带的卸载程序，而且它不在 "
                "Program Files、ProgramData 或 AppData\\Local\\Programs "
                "等独立目录中。\n\n"
                "系统自带程序（notepad、winecfg 等）请通过容器或组件管理。")
            return

        size = float(plan["size"])
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                size_text = f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
                break
            size /= 1024

        reply = QMessageBox.warning(
            self, "确认卸载",
            f"将删除应用「{name}」的整个目录：\n"
            f"{plan['root']}\n\n"
            f"占用空间：{size_text}\n"
            f"同时删除 {len(plan['shortcuts'])} 个容器内快捷方式。\n\n"
            "注册表中的残留设置不会被清理，此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        ok, error = shortcuts.remove_app(plan)
        # The app's sibling entries (updater, uninstaller, translator…) die
        # with the folder too — leaving them behind yields "程序文件不存在".
        self.current_bottle.forget_shortcuts_under(plan["root"])
        self.current_bottle.forget_shortcut(target)
        self._load_shortcuts()
        if ok:
            QMessageBox.information(self, "卸载完成", f"已删除「{name}」。")
        else:
            QMessageBox.warning(self, "卸载未完成", error)

    def _rename_shortcut(self, item):
        """Rename the shortcut label (the program file is left untouched)."""
        target = item.data(Qt.UserRole)
        if not target or not self.current_bottle:
            return
        from PyQt5.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "重命名快捷方式", "名称:", QLineEdit.Normal, item.text())
        new_name = new_name.strip()
        if ok and new_name and new_name != item.text():
            if self.current_bottle.rename_shortcut(target, new_name):
                item.setText(new_name)

    def _shortcut_to_desktop(self, item):
        """Write a .desktop launcher for this program on the Linux desktop."""
        target = item.data(Qt.UserRole)
        if not target or not self.current_bottle:
            return
        entry = next((e for e in self.current_bottle.shortcuts
                      if e.get("target") == target), {})
        icon = entry.get("icon") or ""
        if not icon or not Path(icon).exists():
            icon = shortcuts.extract_icon(target, self.config.cache_dir / "icons")
        ok, result = shortcuts.create_desktop_entry(
            self.current_bottle, item.text(), target, icon, self._launch_command())
        if ok:
            QMessageBox.information(self, "已添加到桌面", f"桌面快捷方式已创建：\n{result}")
        else:
            QMessageBox.warning(self, "添加失败", result)

    def _launch_command(self) -> str:
        """Command a desktop entry should use to start this program."""
        import shutil
        import sys
        found = shutil.which("winbridge")
        if found:
            return f'"{found}"'
        script = Path(sys.argv[0]).resolve()
        if script.suffix == ".py":
            return f'"{sys.executable}" "{script}"'
        return f'"{script}"'

    def _run_shortcut(self, item):
        """Run a shortcut from the shortcuts list."""
        target = item.data(Qt.UserRole)
        if not target or not self.current_bottle:
            return
        if not Path(target).exists():
            reply = QMessageBox.question(
                self, "程序不存在",
                f"程序文件不存在：\n{target}\n\n是否删除这个快捷方式？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self.current_bottle.forget_shortcut(target)
                self._load_shortcuts()
            return
        self.current_bottle.run(target)

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
                                   version)

    def apply_environment(self):
        """Apply the selected environment."""
        if self.current_bottle:
            env = self.env_combo.currentData()
            self.current_bottle.environment = env
            self.bottle_updated.emit(self.current_bottle.name)
            self._update_info_card(self.card_env, "环境",
                                   environment_label(env))

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
            # Colour comes from the palette so it stays legible in dark mode
            colour = self.theme.get("success" if comp["name"] in installed else "text_muted")
            status_item.setForeground(QColor(colour))
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
            self.comp_status_label.setObjectName("muted")
            parent_widget = self.comp_progress.parentWidget()
            if parent_widget:
                parent_layout = parent_widget.layout()
                if parent_layout:
                    parent_layout.insertWidget(
                        parent_layout.indexOf(self.comp_progress),
                        self.comp_status_label
                    )
            self.comp_status_label.show()

            # Disable the action buttons while running and expose "取消"
            self._cancel_event = threading.Event()
            self.btn_install.setEnabled(False)
            self.btn_uninstall.setEnabled(False)
            self.btn_refresh_comp.setEnabled(False)
            self.btn_cancel_comp.setEnabled(True)
            self.btn_cancel_comp.setVisible(True)

            class InstallCompThread(QThread):
                progress = pyqtSignal(int, int, str)
                # ok, name, error_log, overrides, files placed by the installer
                finished_sig = pyqtSignal(bool, str, str, dict, list)

                def __init__(self, cm, name, bottle_path, cancel_event):
                    super().__init__()
                    self._cm = cm
                    self._name = name
                    self._bottle_path = bottle_path
                    self._cancel_event = cancel_event

                def run(self):
                    def on_progress(v, t, m=None):
                        self.progress.emit(v, t, m or "")
                    ok, error_log, overrides, files = self._cm.install(
                        self._name, self._bottle_path, on_progress,
                        cancel_event=self._cancel_event)
                    self.finished_sig.emit(ok, self._name, error_log,
                                           overrides or {}, files or [])

            self._install_thread = InstallCompThread(
                self.component_manager, name, bottle_path, self._cancel_event)
            self._install_thread.progress.connect(self._on_install_progress)
            self._install_thread.finished_sig.connect(self._on_install_done)
            self._install_thread.start()

    def cancel_component_install(self):
        """Ask the running install to stop (download / winetricks / extract)."""
        event = getattr(self, "_cancel_event", None)
        if not event or event.is_set():
            return
        event.set()
        self.btn_cancel_comp.setEnabled(False)
        if hasattr(self, "comp_status_label") and self.comp_status_label:
            self.comp_status_label.setText("正在取消...")
        QApplication.processEvents()

    def _on_install_progress(self, v, t, m=""):
        """Handle install progress updates from the background thread."""
        self.comp_progress.setValue(v)
        if m:
            self.comp_status_label.setText(m)
        QApplication.processEvents()

    def _on_install_done(self, ok: bool, name: str, error_log: str,
                         overrides: dict = None, files: list = None):
        """Handle install completion from the background thread."""
        cancelled = bool(getattr(self, "_cancel_event", None)
                         and self._cancel_event.is_set())
        if ok:
            self.current_bottle.add_component(name)
            # Mirror what the installer actually put in the prefix, so the
            # DLL overrides tab matches reality and uninstall can revert it.
            for dll, mode in (overrides or {}).items():
                self.current_bottle.set_dll_override(dll, mode)
            self.current_bottle.set_component_record(
                name, files or [], overrides or {})
            self.refresh_components()
            if overrides:
                self._load_dll_overrides()
            self.comp_progress.setValue(100)
            QMessageBox.information(self, "安装完成",
                                    f"组件 '{name}' 安装成功。")
        elif cancelled:
            # User pressed "取消": not an error, nothing was recorded.
            self.comp_progress.setValue(0)
            QMessageBox.information(self, "已取消",
                                    f"已取消安装组件 '{name}'。\n"
                                    f"未完成的下载文件已删除，容器未做任何改动。")
            self.refresh_components()
        else:
            log_text = error_log if error_log else "（无详细输出）"
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("安装失败")
            msg_box.setText(f"组件 '{name}' 安装失败。")
            msg_box.setDetailedText(log_text)
            msg_box.exec_()
        self._reset_components_busy()

    def _reset_components_busy(self):
        """Restore the component tab buttons after an install/uninstall."""
        self.comp_progress.setVisible(False)
        self.btn_install.setEnabled(True)
        self.btn_uninstall.setEnabled(True)
        self.btn_refresh_comp.setEnabled(True)
        self.btn_cancel_comp.setEnabled(True)
        self.btn_cancel_comp.setVisible(False)
        if getattr(self, "_cancel_event", None):
            self._cancel_event.clear()

    def uninstall_component(self):
        """Uninstall the selected component from the bottle.

        Components that recorded what they put in the prefix get their DLLs
        reverted (backup restored, otherwise removed) and their overrides
        dropped, in a worker thread — registry work spawns wine. Components
        installed by winetricks or an MSI have no file record, so only the
        record is removed and the dialog says so.
        """
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

        record = self.current_bottle.get_component_record(name)
        files = record.get("files", [])
        overrides = record.get("overrides", {})

        if files or overrides:
            detail = (f"将还原 {len(files)} 个 DLL 文件"
                      f"（有备份的恢复原文件，否则删除）"
                      f"并移除 {len(overrides)} 条 DLL 覆盖。")
        else:
            detail = ("该组件由 winetricks / 微软安装包安装，没有可回滚的文件记录：\n"
                      "卸载只移除记录和覆盖，容器内已装的文件需自行处理。")

        reply = QMessageBox.warning(
            self, "确认卸载",
            f"确定要从容器中卸载组件 '{name}' 吗？\n\n{detail}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        if not (files or overrides):
            self.current_bottle.remove_component(name)
            self.current_bottle.drop_component_record(name)
            self.refresh_components()
            QMessageBox.information(self, "卸载完成",
                                    f"组件 '{name}' 已从记录中移除。")
            return

        self.comp_progress.setVisible(True)
        self.comp_progress.setValue(0)
        self.comp_status_label = QLabel("准备卸载...")
        self.comp_status_label.setObjectName("muted")
        parent_widget = self.comp_progress.parentWidget()
        if parent_widget:
            parent_layout = parent_widget.layout()
            if parent_layout:
                parent_layout.insertWidget(
                    parent_layout.indexOf(self.comp_progress),
                    self.comp_status_label
                )
        self.comp_status_label.show()
        self.btn_install.setEnabled(False)
        self.btn_uninstall.setEnabled(False)

        keep = self.current_bottle.component_overrides(exclude=name)
        bottle_path = str(self.current_bottle.path)
        manager = self.component_manager

        class UninstallCompThread(QThread):
            progress = pyqtSignal(int, int, str)
            finished_sig = pyqtSignal(bool, str, str, dict)

            def __init__(self, name, bottle_path, files, overrides, keep):
                super().__init__()
                self._name = name
                self._bottle_path = bottle_path
                self._files = files
                self._overrides = overrides
                self._keep = keep

            def run(self):
                def on_progress(v, t, m=None):
                    self.progress.emit(v, t, m or "")
                ok, error_log = manager.uninstall(
                    self._name, self._bottle_path, self._files,
                    self._overrides, keep_overrides=self._keep,
                    progress_callback=on_progress)
                # Report the override names too, so the handler can drop them
                # from the bottle metadata.
                self.finished_sig.emit(ok, self._name, error_log or "",
                                       self._overrides)

        self._uninstall_thread = UninstallCompThread(
            name, bottle_path, files, overrides, keep)
        self._uninstall_thread.progress.connect(self._on_install_progress)
        self._uninstall_thread.finished_sig.connect(self._on_uninstall_done)
        self._uninstall_thread.start()

    def _on_uninstall_done(self, ok: bool, name: str, error_log: str,
                           overrides: dict = None):
        """Handle uninstall completion from the background thread."""
        if ok:
            still_needed = {
                dll.lower()
                for dll in self.current_bottle.component_overrides(exclude=name)
            }
            for dll in (overrides or {}):
                if dll.lower() not in still_needed:
                    self.current_bottle.remove_dll_override(dll)
            self.current_bottle.remove_component(name)
            self.current_bottle.drop_component_record(name)
            self.refresh_components()
            self._load_dll_overrides()
            self.comp_progress.setValue(100)
            QMessageBox.information(self, "卸载完成",
                                    f"组件 '{name}' 已卸载，相关 DLL 与覆盖已还原。")
        else:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setWindowTitle("卸载失败")
            msg_box.setText(f"组件 '{name}' 卸载未完全成功。")
            msg_box.setDetailedText(error_log or "（无详细输出）")
            msg_box.exec_()

        self._reset_components_busy()