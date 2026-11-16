"""WinBridge dialogs — Windows-native styled dialogs."""

import os
import subprocess
import threading
from pathlib import Path
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QRadioButton, QCheckBox, QGroupBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QWidget,
    QMessageBox, QFrame, QStackedWidget, QSizePolicy,
    QProgressBar, QStatusBar, QListWidget, QListWidgetItem,
    QApplication, QSplitter, QAbstractItemView, QButtonGroup,
    QFileDialog,
)
from ..core.config import Config
from ..core.wine import Wine
from ..core.bottle import (BottleManager, ENVIRONMENT_LABELS,
                           WINDOWS_VERSIONS, windows_version_label)
from ..core.download import ComponentManager
from ..core import registry
from ..core.wine_runtimes import WineRuntimeManager, available_builds
from ..core.sandbox import app_installed as sandbox_available


class CreateBottleDialog(QDialog):
    """Dialog for creating a new bottle — Windows native style."""

    def __init__(self, config: Config = None, parent=None):
        super().__init__(parent)
        self.config = config or Config()
        self.wine = Wine(self.config.wine_path)
        self.setWindowTitle("新建容器")
        self.setMinimumWidth(520)
        self.setModal(True)
        self.setup_ui()
        self.adjustSize()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(26, 22, 26, 22)

        # Title
        title = QLabel("创建新容器")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel("创建一个新的 Wine 前缀来运行 Windows 应用程序")
        subtitle.setObjectName("hint")
        layout.addWidget(subtitle)

        # Name
        name_label = QLabel("容器名称")
        name_label.setObjectName("fieldLabel")
        layout.addWidget(name_label)

        self.bottle_name = QLineEdit()
        self.bottle_name.setPlaceholderText("例如: myapp, game1, office...")
        layout.addWidget(self.bottle_name)

        # Architecture
        arch_label = QLabel("架构")
        arch_label.setObjectName("fieldLabel")
        layout.addWidget(arch_label)

        arch_layout = QHBoxLayout()
        arch_layout.setSpacing(10)

        self.arch_64 = QRadioButton("64 位 (Win64)")
        self.arch_64.setChecked(True)
        arch_layout.addWidget(self.arch_64)

        self.arch_32 = QRadioButton("32 位 (Win32)")
        arch_layout.addWidget(self.arch_32)

        # Radio buttons sharing a parent are auto-exclusive, so the arch pair
        # and the runtime pair below would otherwise behave as one group:
        # picking "flatpak 沙箱" would silently uncheck the architecture.
        self.arch_group = QButtonGroup(self)
        self.arch_group.addButton(self.arch_64)
        self.arch_group.addButton(self.arch_32)

        arch_layout.addStretch()
        layout.addLayout(arch_layout)

        # Environment
        env_label = QLabel("环境类型")
        env_label.setObjectName("fieldLabel")
        layout.addWidget(env_label)

        self.environment_combo = QComboBox()
        # Item data holds the environment key; the text is only for display
        for key, label in ENVIRONMENT_LABELS.items():
            self.environment_combo.addItem(label, key)
        layout.addWidget(self.environment_combo)

        # Windows Version
        winver_label = QLabel("Windows 版本")
        winver_label.setObjectName("fieldLabel")
        layout.addWidget(winver_label)

        self.windows_version_combo = QComboBox()
        for version in WINDOWS_VERSIONS:
            self.windows_version_combo.addItem(
                windows_version_label(version), version)
        index = self.windows_version_combo.findData("win10")
        self.windows_version_combo.setCurrentIndex(index if index >= 0 else 0)
        layout.addWidget(self.windows_version_combo)

        # Wine Version
        wine_label = QLabel("Wine 版本")
        wine_label.setObjectName("fieldLabel")
        layout.addWidget(wine_label)

        wine_ver_layout = QHBoxLayout()
        wine_ver_layout.setSpacing(10)

        self.wine_source_combo = QComboBox()
        self.wine_source_combo.currentIndexChanged.connect(self.on_wine_source_changed)
        wine_ver_layout.addWidget(self.wine_source_combo, 1)

        self.wine_path_input = QLineEdit()
        self.wine_path_input.setPlaceholderText("选择 Wine 二进制文件...")
        self.wine_path_input.setVisible(False)
        wine_ver_layout.addWidget(self.wine_path_input, 2)

        self.btn_browse_wine = QPushButton("浏览...")
        self.btn_browse_wine.setVisible(False)
        self.btn_browse_wine.setObjectName("btnDefault")
        self.btn_browse_wine.clicked.connect(self.browse_wine_path)
        wine_ver_layout.addWidget(self.btn_browse_wine)

        self.btn_download_wine = QPushButton("管理 Wine…")
        self.btn_download_wine.setObjectName("btnDefault")
        self.btn_download_wine.setToolTip(
            "下载、更新或删除 Wine 版本（Wine 11 / Soda / Proton 11 / Wine-GE）")
        self.btn_download_wine.clicked.connect(self.open_wine_manager)
        wine_ver_layout.addWidget(self.btn_download_wine)

        layout.addLayout(wine_ver_layout)

        self.wine_ver_hint = QLabel(f"当前: {self.wine.version}")
        self.wine_ver_hint.setObjectName("hint")
        layout.addWidget(self.wine_ver_hint)
        self._fill_wine_sources()

        # Runtime: host Wine vs. flatpak sandbox (own Mesa/Vulkan)
        runtime_label = QLabel("运行环境")
        runtime_label.setObjectName("fieldLabel")
        layout.addWidget(runtime_label)

        runtime_layout = QHBoxLayout()
        runtime_layout.setSpacing(10)
        self.runtime_host = QRadioButton("宿主机（默认）")
        self.runtime_host.setChecked(True)
        runtime_layout.addWidget(self.runtime_host)
        self.runtime_sandbox = QRadioButton("flatpak 沙箱")
        runtime_layout.addWidget(self.runtime_sandbox)

        self.runtime_group = QButtonGroup(self)
        self.runtime_group.addButton(self.runtime_host)
        self.runtime_group.addButton(self.runtime_sandbox)

        runtime_layout.addStretch()
        layout.addLayout(runtime_layout)

        self.runtime_hint = QLabel()
        self.runtime_hint.setObjectName("hint")
        self.runtime_hint.setWordWrap(True)
        layout.addWidget(self.runtime_hint)

        if sandbox_available():
            self.runtime_hint.setText(
                "沙箱使用 flatpak 运行时自带的图形库（Mesa/Vulkan），"
                "宿主驱动跑不起来的老游戏可以选它；组件安装需切回宿主机。")
        else:
            self.runtime_sandbox.setEnabled(False)
            self.runtime_hint.setText(
                "未安装沙箱运行时，先执行 winbridge-sandbox-runtime"
                "（源码目录下为 packaging/build-sandbox-runtime.sh）")

        # Description
        desc_label = QLabel("描述 (可选)")
        desc_label.setObjectName("fieldLabel")
        layout.addWidget(desc_label)

        self.description = QTextEdit()
        self.description.setPlaceholderText("添加容器描述...")
        self.description.setMaximumHeight(70)
        layout.addWidget(self.description)

        # Pre-install the components every Windows program expects. The first
        # bottle pays for it (~15 min); after that it is a template copy.
        self.preinstall_check = QCheckBox(
            "预装运行库与字体（VC++ 2022、Core/CJK 字体、.NET 4.8）")
        self.preinstall_check.setChecked(True)
        self.preinstall_check.setToolTip(
            "首次需要十几分钟（.NET 4.8 安装慢），完成后会存成基础模板，"
            "以后新建容器直接复制，几秒就好")
        self.preinstall_check.toggled.connect(self._update_preinstall_hint)
        layout.addWidget(self.preinstall_check)

        self.preinstall_hint = QLabel()
        self.preinstall_hint.setObjectName("hint")
        self.preinstall_hint.setWordWrap(True)
        layout.addWidget(self.preinstall_hint)
        self._update_preinstall_hint(self.preinstall_check.isChecked())

        # Spacer
        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("btnDefault")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_layout.addStretch()

        self.btn_create = QPushButton("创建容器")
        self.btn_create.setObjectName("btnPrimary")
        self.btn_create.clicked.connect(self.accept)
        self.btn_create.setEnabled(False)
        btn_layout.addWidget(self.btn_create)

        layout.addLayout(btn_layout)

        self.bottle_name.setFocus()
        self.bottle_name.textChanged.connect(
            lambda t: self.btn_create.setEnabled(bool(t.strip())))

    def _fill_wine_sources(self, select_path: str = None):
        """Populate the Wine selector: system, installed runners, custom."""
        combo = getattr(self, "wine_source_combo", None)
        if combo is None:
            return
        system_path = self.config.wine_path
        system_exists = bool(system_path) and Path(system_path).exists()
        if select_path is None:
            if combo.count():
                select_path = combo.currentData()
            elif system_exists:
                select_path = system_path
        combo.blockSignals(True)
        combo.clear()
        if system_exists:
            combo.addItem(f"系统默认 Wine（{self.wine.version}）", system_path)
        for runner in WineRuntimeManager(self.config).installed():
            suffix = f" {runner['version']}" if runner["version"] else ""
            combo.addItem(f"{runner['label']}{suffix}", runner["wine_path"])
        combo.addItem("自定义路径...", None)
        index = combo.findData(select_path)
        if index < 0:
            # A deleted system Wine leaves the first runner (or Custom) as
            # the useful default instead of an unusable path.
            index = 0
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self.on_wine_source_changed(combo.currentIndex())

        if not system_exists and combo.count() == 1:
            # Nothing usable at all: say so instead of letting the create
            # button fail with a generic "创建失败".
            self.wine_ver_hint.setText(
                "未检测到系统 Wine，也没有已下载的运行时。"
                "点『管理 Wine…』下载一个，或安装系统 Wine。")

    def open_wine_manager(self):
        """Download, update or delete Wine runners."""
        dialog = WineManagerDialog(self.config, self)
        dialog.exec_()
        if dialog.changed:
            runners = WineRuntimeManager(self.config).installed()
            self._fill_wine_sources(
                runners[0]["wine_path"] if runners else None)
            if runners:
                self.wine_ver_hint.setText(
                    f"已选择: {runners[0]['label']} {runners[0]['version']}")

    def on_wine_source_changed(self, index: int):
        """Handle Wine source selection change."""
        is_custom = self.wine_source_combo.currentData() is None
        self.wine_path_input.setVisible(is_custom)
        self.btn_browse_wine.setVisible(is_custom)
        if is_custom:
            self.wine_ver_hint.setText("选择 Wine 二进制文件")
        else:
            data = self.wine_source_combo.currentData()
            if data == self.config.wine_path:
                self.wine_ver_hint.setText(f"当前: {self.wine.version}")
            else:
                self.wine_ver_hint.setText(
                    f"选择: {self.wine_source_combo.currentText()}")

    def browse_wine_path(self):
        """Browse for a custom Wine binary."""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Wine 二进制文件", "/usr/bin",
            "Wine 二进制 (wine wine64);;所有文件 (*)")
        if path:
            self.wine_path_input.setText(path)
            try:
                result = subprocess.run(
                    [path, "--version"], capture_output=True, text=True, timeout=5
                )
                ver = result.stdout.strip() or "unknown"
                self.wine_ver_hint.setText(f"选择: {ver}")
            except Exception:
                self.wine_ver_hint.setText("无法获取版本信息")

    def get_wine_path(self) -> str:
        """Get the selected Wine path ("" when nothing usable is selected).

        The old fallback returned ``config.wine_path`` even when that file no
        longer existed, so creating a bottle on a machine without Wine failed
        with a generic "创建失败".
        """
        data = self.wine_source_combo.currentData()
        if data:
            return data
        return self.wine_path_input.text().strip()

    def accept(self):
        """Refuse to create a bottle without a usable Wine binary."""
        path = self.get_wine_path()
        if not path or not Path(path).exists():
            box = QMessageBox(QMessageBox.Warning, "没有可用的 Wine",
                              "当前没有可用的 Wine 可执行文件：\n"
                              "系统未安装 Wine，或所选路径不存在。\n\n"
                              "可以先下载一个运行时（Wine 11 / Soda / Proton 11），"
                              "下载完再创建容器。", parent=self)
            manage = box.addButton("打开 Wine 版本管理", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is manage:
                self.open_wine_manager()
            return
        super().accept()

    def get_sandbox(self) -> str:
        """Runtime chosen for the new bottle: "host" or "flatpak"."""
        if self.runtime_sandbox.isEnabled() and self.runtime_sandbox.isChecked():
            return "flatpak"
        return "host"

    def get_preinstall(self) -> bool:
        """Whether to install the default runtime/font components."""
        return self.preinstall_check.isChecked()

    def _update_preinstall_hint(self, checked: bool):
        """Explain how long pre-installation takes for this configuration."""
        if not checked:
            self.preinstall_hint.setText("")
            return
        manager = BottleManager(self.config)
        sandbox = self.get_sandbox()
        if sandbox == "flatpak":
            self.preinstall_hint.setText(
                "沙箱容器里不能装组件，会先跳过；需要时切到宿主机再装。")
            return
        wine = self.get_wine_path() or self.config.wine_path
        if manager.template_exists("win64" if self.arch_64.isChecked() else "win32",
                                   wine):
            self.preinstall_hint.setText(
                "已有基础模板，创建时会直接复制，通常几秒完成。")
        else:
            self.preinstall_hint.setText(
                "首次构建基础模板约 10~20 分钟（主要是 .NET 4.8），"
                "之后新建容器都直接复制模板。")


class FirstRunDialog(QDialog):
    """First-run setup dialog — Windows native style."""

    def __init__(self, config: Config = None, parent=None):
        super().__init__(parent)
        self.config = config or Config()
        self.component_manager = ComponentManager(self.config)
        self.setWindowTitle("欢迎使用 WinBridge")
        self.setMinimumWidth(480)
        self.adjustSize()
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(26, 22, 26, 22)

        # Icon + Title
        logo_pix = QPixmap(str(Path(__file__).parent.parent / "resources" / "logo.png"))
        logo_pix = logo_pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QLabel()
        icon.setPixmap(logo_pix)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(72, 72)
        layout.addWidget(icon)

        title = QLabel("首次使用 WinBridge")
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        desc = QLabel(
            "WinBridge 是一个基于 Wine 的 Windows 应用容器管理器。\n"
            "首次启动建议下载基础文件以获得最佳体验。"
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setObjectName("hint")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(8)

        # Options group
        options_frame = QFrame()
        options_frame.setObjectName("panel")
        options_layout = QVBoxLayout(options_frame)
        options_layout.setSpacing(10)
        options_layout.setContentsMargins(12, 12, 12, 12)

        options_title = QLabel("首次设置")
        options_title.setObjectName("sectionTitle")
        options_layout.addWidget(options_title)

        self.download_base = QCheckBox("下载基础组件 (Wine-GE, DXVK, vcrun 等)")
        self.download_base.setChecked(True)
        options_layout.addWidget(self.download_base)

        hint = QLabel(
            "基础文件将从 GitCode 下载。\n"
            "如果网络不佳，可跳过此步骤稍后手动下载。"
        )
        hint.setObjectName("hint")
        options_layout.addWidget(hint)

        layout.addWidget(options_frame)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.skip_btn = QPushButton("跳过")
        self.skip_btn.setObjectName("btnDefault")
        self.skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.skip_btn)

        btn_layout.addStretch()

        self.continue_btn = QPushButton("继续")
        self.continue_btn.setObjectName("btnPrimary")
        self.continue_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.continue_btn)

        layout.addLayout(btn_layout)


class DLLOverrideDialog(QDialog):
    """Dialog for adding/editing a DLL override — Windows native style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DLL 覆盖设置")
        self.setMinimumWidth(380)
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(26, 22, 26, 22)

        title = QLabel("添加 DLL 覆盖")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.dll_name = QLineEdit()
        self.dll_name.setPlaceholderText("例如: d3d9, d3d11, xaudio2_7")
        dll_label = QLabel("DLL 名称")
        dll_label.setObjectName("fieldLabel")
        form.addRow(dll_label, self.dll_name)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "native,builtin (优先原生)",
            "builtin,native (优先内置)",
            "native (仅原生)",
            "builtin (仅内置)",
            "disable (禁用)",
        ])
        mode_label = QLabel("加载模式")
        mode_label.setObjectName("fieldLabel")
        form.addRow(mode_label, self.mode_combo)

        layout.addLayout(form)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("btnDefault")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_layout.addStretch()

        self.btn_ok = QPushButton("确定")
        self.btn_ok.setObjectName("btnPrimary")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_ok.setEnabled(False)
        btn_layout.addWidget(self.btn_ok)

        layout.addLayout(btn_layout)

        self.dll_name.textChanged.connect(
            lambda t: self.btn_ok.setEnabled(bool(t.strip())))

    def get_result(self) -> tuple:
        """Get the DLL name and mode."""
        mode_map = {
            "native,builtin (优先原生)": "native,builtin",
            "builtin,native (优先内置)": "builtin,native",
            "native (仅原生)": "native",
            "builtin (仅内置)": "builtin",
            "disable (禁用)": "",
        }
        return self.dll_name.text().strip(), mode_map.get(self.mode_combo.currentText(), "native,builtin")


class RegistryValueDialog(QDialog):
    """Create or edit one registry value."""

    def __init__(self, parent=None, name: str = "",
                 type_name: str = "REG_SZ", data: str = "",
                 editing: bool = False):
        super().__init__(parent)
        self.setWindowTitle("编辑注册表值" if editing else "新建注册表值")
        self.setMinimumWidth(460)
        self.setModal(True)
        self.editing = editing
        self.setup_ui(name, type_name, data)

    def setup_ui(self, name: str, type_name: str, data: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(26, 22, 26, 22)

        title = QLabel("编辑注册表值" if self.editing else "新建注册表值")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText("留空表示默认值")
        self.name_input.setReadOnly(self.editing)
        name_label = QLabel("名称")
        name_label.setObjectName("fieldLabel")
        form.addRow(name_label, self.name_input)

        self.type_combo = QComboBox()
        for key in registry.REG_TYPES:
            self.type_combo.addItem(registry.REG_TYPE_LABELS[key], key)
        index = self.type_combo.findData(type_name)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        type_label = QLabel("类型")
        type_label.setObjectName("fieldLabel")
        form.addRow(type_label, self.type_combo)

        self.data_edit = QTextEdit()
        self.data_edit.setPlainText(data)
        self.data_edit.setMaximumHeight(120)
        data_label = QLabel("数据")
        data_label.setObjectName("fieldLabel")
        form.addRow(data_label, self.data_edit)

        layout.addLayout(form)

        hint = QLabel(
            "DWORD/QWORD：十进制或 0x 十六进制；二进制：十六进制字节；"
            "多字符串：每行一个。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("btnDefault")
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)
        buttons.addStretch()
        btn_ok = QPushButton("确定")
        btn_ok.setObjectName("btnPrimary")
        btn_ok.clicked.connect(self.accept)
        buttons.addWidget(btn_ok)
        layout.addLayout(buttons)

        self.data_edit.setFocus()

    def get_result(self) -> tuple:
        return (self.name_input.text().strip(),
                self.type_combo.currentData(),
                self.data_edit.toPlainText())


class WineManagerDialog(QDialog):
    """Manage installed Wine runtimes (install / delete / inspect)."""

    def __init__(self, config: Config = None, parent=None):
        super().__init__(parent)
        self.config = config or Config()
        self.manager = WineRuntimeManager(self.config)
        self.changed = False
        self._thread = None
        self._cancel_event = None
        self.setWindowTitle("Wine 版本管理")
        self.setMinimumWidth(640)
        self.setModal(True)
        self.setup_ui()
        self.refresh_state()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(26, 22, 26, 22)

        title = QLabel("Wine 版本管理")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        hint = QLabel(
            "管理已安装的 Wine 版本，或从镜像站下载新的版本。"
            "容器可在配置页单独选择使用哪一个。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        installed_label = QLabel("已安装的 Wine 版本")
        installed_label.setObjectName("sectionTitle")
        layout.addWidget(installed_label)

        self.installed_table = QTableWidget(0, 3)
        self.installed_table.setHorizontalHeaderLabels(["名称", "版本", "路径"])
        self.installed_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.installed_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.installed_table.horizontalHeader().setStretchLastSection(True)
        self.installed_table.verticalHeader().setVisible(False)
        self.installed_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.installed_table.setSelectionMode(QTableWidget.SingleSelection)
        self.installed_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.installed_table.setMaximumHeight(160)
        self.installed_table.itemSelectionChanged.connect(
            self._update_delete_button)
        layout.addWidget(self.installed_table)

        installed_buttons = QHBoxLayout()
        installed_buttons.setSpacing(8)
        btn_refresh = QPushButton("刷新列表")
        btn_refresh.setObjectName("btnDefault")
        btn_refresh.clicked.connect(self.refresh_state)
        installed_buttons.addWidget(btn_refresh)

        self.btn_delete_wine = QPushButton("删除选中的 Wine 版本")
        self.btn_delete_wine.setObjectName("btnDanger")
        self.btn_delete_wine.setEnabled(False)
        self.btn_delete_wine.clicked.connect(self.delete_selected)
        installed_buttons.addWidget(self.btn_delete_wine)
        installed_buttons.addStretch()
        layout.addLayout(installed_buttons)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setObjectName("detailSep")
        layout.addWidget(separator)

        install_label = QLabel("安装新版本")
        install_label.setObjectName("sectionTitle")
        layout.addWidget(install_label)

        self.build_combo = QComboBox()
        for build in available_builds():
            self.build_combo.addItem(build["label"], build["id"])
        self.build_combo.currentIndexChanged.connect(self._update_description)
        layout.addWidget(self.build_combo)

        self.description = QLabel("")
        self.description.setObjectName("hint")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        self.progress = QProgressBar()
        self.progress.setObjectName("progressLabeled")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_close = QPushButton("关闭")
        self.btn_close.setObjectName("btnDefault")
        self.btn_close.clicked.connect(self.reject)
        buttons.addWidget(self.btn_close)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btnDefault")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_install)
        buttons.addWidget(self.btn_cancel)

        buttons.addStretch()

        self.btn_install = QPushButton("安装")
        self.btn_install.setObjectName("btnPrimary")
        self.btn_install.clicked.connect(self.install_selected)
        buttons.addWidget(self.btn_install)
        layout.addLayout(buttons)

    def _installed_for(self, build_id: str) -> list:
        return [runner for runner in self.manager.installed()
                if runner["id"] == build_id]

    def refresh_state(self):
        self.refresh_installed()
        self._update_description()

    def refresh_installed(self):
        """Rebuild the installed list, including the system Wine entry."""
        self.installed_table.blockSignals(True)
        try:
            self.installed_table.setRowCount(0)
            system = self.manager.system_wine()
            if system["exists"]:
                self._add_installed_row(
                    "系统 Wine", system["version"] or "未知", system["path"],
                    {"kind": "system", **system})
            for runner in self.manager.installed():
                self._add_installed_row(
                    runner["label"], runner["version"] or "未知",
                    runner["wine_path"], {"kind": "runner", **runner})
        finally:
            self.installed_table.blockSignals(False)
        self._update_delete_button()

    def _add_installed_row(self, name: str, version: str, path: str,
                           payload: dict):
        row = self.installed_table.rowCount()
        self.installed_table.insertRow(row)
        name_item = QTableWidgetItem(name)
        name_item.setData(Qt.UserRole, payload)
        self.installed_table.setItem(row, 0, name_item)
        self.installed_table.setItem(row, 1, QTableWidgetItem(version))
        path_item = QTableWidgetItem(path)
        path_item.setToolTip(path)
        self.installed_table.setItem(row, 2, path_item)

    def _update_delete_button(self):
        self.btn_delete_wine.setEnabled(
            self.installed_table.currentRow() >= 0)

    def _bottles_using(self, wine_path: str) -> list:
        """Names of bottles whose saved Wine resolves to ``wine_path``."""
        from ..core.bottle import BottleManager
        wanted = os.path.realpath(wine_path or "")
        names = []
        for bottle in BottleManager(self.config).list_bottles():
            try:
                current = bottle.wine_path
            except Exception:
                continue
            if os.path.realpath(current or "") == wanted:
                names.append(bottle.name)
        return names

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return (f"{value:.0f} {unit}" if unit == "B"
                        else f"{value:.1f} {unit}")
            value /= 1024
        return f"{value:.1f} GB"

    def delete_selected(self):
        row = self.installed_table.currentRow()
        if row < 0:
            return
        item = self.installed_table.item(row, 0)
        payload = item.data(Qt.UserRole) if item else None
        if not payload:
            return
        if payload.get("kind") == "system":
            self._delete_system_wine()
        else:
            self._delete_runner(payload)

    def _delete_runner(self, runner: dict):
        used = self._bottles_using(runner.get("wine_path", ""))
        if used:
            QMessageBox.warning(
                self, "正在使用",
                "以下容器正在使用这个 Wine 版本：\n"
                + "\n".join(f"· {name}" for name in used)
                + "\n\n请先在容器配置的「Wine 版本」里切换到其他版本，"
                  "再删除。")
            return
        label = f"{runner['label']} {runner.get('version') or ''}".strip()
        reply = QMessageBox.warning(
            self, "删除 Wine 版本",
            f"确定删除 {label} 吗？\n\n{runner.get('wine_path', '')}\n\n"
            "将删除该运行时目录内的所有文件，不可撤销。\n"
            "请先确保没有程序正在使用它。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        ok, message = self.manager.delete_runner(runner)
        if not ok:
            QMessageBox.warning(self, "删除失败", message)
            return
        self.changed = True
        self.status.setText(message)
        self.refresh_state()

    def _delete_system_wine(self):
        plan = self.manager.system_wine_removal_plan()
        if not plan["removable"]:
            QMessageBox.warning(self, "无法删除系统 Wine",
                                plan["reason"] or "请手动处理")
            return

        used = (self._bottles_using(plan["path"])
                or self._bottles_using(plan["target"]))

        lines = [f"程序：{plan['path']}"]
        if plan["packages"]:
            lines.append("将使用系统包管理器卸载："
                         + ", ".join(plan["packages"]))
        else:
            lines.append(f"运行时目录：{plan['root']}"
                         f"（{self._format_size(plan['size'])}）")
            if plan["links"]:
                lines.append("启动器：" + "、".join(plan["links"]))
        lines.append("")
        lines.append("需要管理员权限，删除后不可撤销。"
                     "请先确保没有程序正在使用系统 Wine。")

        reply = QMessageBox.warning(
            self, "删除系统 Wine",
            "确定要删除系统 Wine 吗？\n\n" + "\n".join(lines),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if used:
            runners = self.manager.installed()
            if not runners:
                QMessageBox.warning(
                    self, "正在使用",
                    "以下容器正在使用系统 Wine：\n"
                    + "\n".join(f"· {name}" for name in used)
                    + "\n\n请先在「安装新版本」里安装其他 Wine 版本，"
                      "再把容器切换过去，然后删除系统 Wine。")
                return
            target = runners[0]
            target_label = (f"{target['label']} "
                            f"{target.get('version') or ''}").strip()
            switch = QMessageBox.question(
                self, "切换容器使用的 Wine",
                "以下容器正在使用系统 Wine：\n"
                + "\n".join(f"· {name}" for name in used)
                + f"\n\n删除前需要先切换到「{target_label}」，是否继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if switch != QMessageBox.Yes:
                return
            from ..core.bottle import BottleManager
            bottle_manager = BottleManager(self.config)
            for name in used:
                bottle = bottle_manager.get_bottle(name)
                if bottle is not None:
                    bottle.wine_path = target["wine_path"]
            self.changed = True

        ok, message = self.manager.remove_system_wine()
        if not ok:
            QMessageBox.warning(self, "删除失败", message)
            return
        self.changed = True
        self.status.setText(message)
        self.refresh_state()
        QMessageBox.information(
            self, "已删除",
            message + "\n\n系统默认 Wine 已不可用；请安装或选择其他 Wine "
                      "版本后再启动容器。")

    def _update_description(self):
        build_id = self.build_combo.currentData()
        installed = self._installed_for(build_id)
        build = next((item for item in available_builds()
                      if item["id"] == build_id), {})
        text = build.get("description", "")
        if installed:
            labels = ", ".join(
                f"{item['version'] or '已安装'}" for item in installed)
            text += f"\n已安装：{labels}。再次安装会覆盖同名版本。"
            self.btn_install.setText("重新安装")
        else:
            self.btn_install.setText("安装")
        self.description.setText(text)

    def install_selected(self):
        build_id = self.build_combo.currentData()
        if not build_id or (self._thread and self._thread.isRunning()):
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_install.setEnabled(False)
        self.build_combo.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._cancel_event = threading.Event()

        class InstallThread(QThread):
            progress = pyqtSignal(int, str)
            finished_sig = pyqtSignal(bool, str)

            def __init__(self, manager, build_id, cancel_event):
                super().__init__()
                self._manager = manager
                self._build_id = build_id
                self._cancel_event = cancel_event

            def run(self):
                try:
                    ok, message = self._manager.install(
                        self._build_id, self.progress.emit,
                        self._cancel_event)
                except Exception as error:  # noqa: BLE001 - shown in dialog
                    ok, message = False, str(error)
                self.finished_sig.emit(ok, message)

        self._thread = InstallThread(
            self.manager, build_id, self._cancel_event)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_sig.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, percent: int, message: str):
        self.progress.setValue(percent)
        self.status.setText(message)

    def _on_finished(self, ok: bool, message: str):
        self.progress.setVisible(False)
        self.btn_install.setEnabled(True)
        self.build_combo.setEnabled(True)
        self.btn_close.setEnabled(True)
        self.btn_cancel.setVisible(False)
        if ok:
            self.changed = True
            self.status.setText(f"已安装：{message}")
            self.refresh_state()
        elif getattr(self, "_cancel_event", None) and self._cancel_event.is_set():
            self.status.setText("已取消")
        else:
            self.status.setText(f"安装失败：{message}")
            QMessageBox.warning(self, "安装失败", message)
        self._thread = None

    def cancel_install(self):
        if self._cancel_event:
            self._cancel_event.set()
            self.btn_cancel.setEnabled(False)
            self.status.setText("正在取消...")

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            QMessageBox.information(
                self, "正在安装",
                "下载/解压仍在进行，请先点击「取消」并等待完成后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)


class WineUpdateDialog(QDialog):
    """Prompt for new Wine runner releases and install them in one go."""

    def __init__(self, config: Config = None, updates: list = None, parent=None):
        super().__init__(parent)
        self.config = config or Config()
        self.manager = WineRuntimeManager(self.config)
        self.updates = updates or []
        self.changed = False
        self._finished = False
        self._thread = None
        self._cancel_event = None
        self.setWindowTitle("Wine 运行时更新")
        self.setMinimumWidth(520)
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(26, 22, 26, 22)

        title = QLabel("Wine 运行时更新")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        lines = ["检测到以下新版本："]
        for update in self.updates:
            lines.append(
                f"{update['label']}：{update['version']} → "
                f"{update['latest_version']}")
        info = QLabel("\n".join(lines))
        info.setObjectName("fieldLabel")
        info.setWordWrap(True)
        layout.addWidget(info)

        hint = QLabel("更新会重新下载并覆盖对应版本，容器里已保存的 Wine 选择不变。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.progress = QProgressBar()
        self.progress.setObjectName("progressLabeled")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.btn_later = QPushButton("稍后")
        self.btn_later.setObjectName("btnDefault")
        self.btn_later.clicked.connect(self.reject)
        buttons.addWidget(self.btn_later)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("btnDefault")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_updates)
        buttons.addWidget(self.btn_cancel)

        buttons.addStretch()

        self.btn_update = QPushButton("全部更新")
        self.btn_update.setObjectName("btnPrimary")
        self.btn_update.clicked.connect(self._on_primary)
        buttons.addWidget(self.btn_update)
        layout.addLayout(buttons)

    def _on_primary(self):
        if self._finished:
            self.accept()
        else:
            self.install_updates()

    def install_updates(self):
        if not self.updates or (self._thread and self._thread.isRunning()):
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status.setText("准备更新...")
        self.btn_update.setEnabled(False)
        self.btn_later.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self._cancel_event = threading.Event()

        updates = list(self.updates)

        class UpdateThread(QThread):
            progress = pyqtSignal(int, str)
            finished_sig = pyqtSignal(bool, str)   # ok, message

            def __init__(self, manager, updates, cancel_event):
                super().__init__()
                self._manager = manager
                self._updates = updates
                self._cancel_event = cancel_event

            def run(self):
                failed = []
                completed = 0
                total = len(self._updates)
                for index, update in enumerate(self._updates):
                    if self._cancel_event.is_set():
                        break
                    self.progress.emit(
                        int(index * 100 / total),
                        f"正在更新 {update['label']} → "
                        f"{update['latest_version']}...")

                    def on_progress(value, _total, message=None):
                        overall = int((index * 100 + value) / total)
                        self.progress.emit(overall, message or "")

                    ok, error = self._manager.install(
                        update["id"], on_progress, self._cancel_event)
                    if ok:
                        completed += 1
                    elif self._cancel_event.is_set():
                        break
                    else:
                        failed.append(f"{update['label']}: {error[:80]}")

                if self._cancel_event.is_set():
                    self.finished_sig.emit(
                        completed > 0, f"已取消，已完成 {completed} 项更新")
                elif failed:
                    self.finished_sig.emit(
                        completed > 0, "部分更新失败：" + "；".join(failed))
                else:
                    self.finished_sig.emit(True, "Wine 运行时更新完成")

        self._thread = UpdateThread(
            self.manager, updates, self._cancel_event)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_sig.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, percent: int, message: str):
        self.progress.setValue(percent)
        if message:
            self.status.setText(message)

    def _on_finished(self, ok: bool, message: str):
        self.progress.setVisible(False)
        self.status.setText(message)
        self.btn_update.setEnabled(True)
        self.btn_update.setText("关闭")
        self.btn_later.setVisible(False)
        self.btn_cancel.setVisible(False)
        self._finished = True
        self._thread = None
        if ok:
            self.changed = True

    def cancel_updates(self):
        if self._cancel_event:
            self._cancel_event.set()
            self.btn_cancel.setEnabled(False)
            self.status.setText("正在取消...")

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            QMessageBox.information(
                self, "正在更新",
                "更新仍在进行，请先点击「取消」并等待完成后再关闭。")
            event.ignore()
            return
        super().closeEvent(event)


class TaskManagerDialog(QDialog):
    """Windows-style Task Manager for Wine processes — Windows native style."""

    def __init__(self, wine, bottle_path: str = None, parent=None):
        super().__init__(parent)
        self.wine = wine
        self.bottle_path = bottle_path
        self.setWindowTitle("任务管理器")
        self.setMinimumSize(700, 450)
        self.resize(800, 500)
        self.setModal(False)
        self.setup_ui()
        self.refresh_processes()

    def setup_ui(self):
        """Setup the task manager UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(10)

        # Title
        title = QLabel("任务管理器")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        # Process table
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(6)
        self.process_table.setHorizontalHeaderLabels([
            "进程名称", "PID", "CPU %", "内存 %", "状态", "用户"
        ])
        self.process_table.horizontalHeader().setStretchLastSection(True)
        self.process_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.process_table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.process_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.process_table.setSelectionMode(QTableWidget.SingleSelection)
        self.process_table.setAlternatingRowColors(True)
        self.process_table.verticalHeader().setVisible(False)
        self.process_table.setShowGrid(False)
        layout.addWidget(self.process_table, 1)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("muted")
        bottom.addWidget(self.status_label)

        bottom.addStretch()

        self.btn_end = QPushButton("结束进程")
        self.btn_end.setObjectName("btnDanger")
        self.btn_end.clicked.connect(self.kill_selected_process)
        self.btn_end.setEnabled(False)
        bottom.addWidget(self.btn_end)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setObjectName("btnDefault")
        self.btn_refresh.clicked.connect(self.refresh_processes)
        bottom.addWidget(self.btn_refresh)

        layout.addLayout(bottom)

        # Auto-refresh timer
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh_processes)
        self.timer.start()

        self.process_table.itemSelectionChanged.connect(
            lambda: self.btn_end.setEnabled(bool(self.process_table.currentRow() >= 0)))

    def _selected_pid(self) -> str:
        """PID of the highlighted row ("" when nothing is selected)."""
        row = self.process_table.currentRow()
        if row < 0:
            return ""
        item = self.process_table.item(row, 1)
        return item.text() if item else ""

    def refresh_processes(self):
        """Refresh the process list without losing the current selection."""
        selected_pid = self._selected_pid()
        scroll = self.process_table.verticalScrollBar().value()
        processes = self.wine.list_processes(self.bottle_path)

        # Clearing the table fires selectionChanged, which used to un-highlight
        # the process the user picked every three seconds.
        self.process_table.blockSignals(True)
        try:
            self.process_table.setRowCount(0)
            for proc in processes:
                row = self.process_table.rowCount()
                self.process_table.insertRow(row)

                name = proc["name"][:40] if len(proc["name"]) > 40 else proc["name"]
                self.process_table.setItem(row, 0, QTableWidgetItem(name))
                self.process_table.setItem(row, 1, QTableWidgetItem(proc["pid"]))
                self.process_table.setItem(row, 2, QTableWidgetItem(proc["cpu"]))
                self.process_table.setItem(row, 3, QTableWidgetItem(proc["memory"]))
                self.process_table.setItem(row, 4, QTableWidgetItem(proc["status"]))
                self.process_table.setItem(row, 5, QTableWidgetItem(proc["user"]))
        finally:
            self.process_table.blockSignals(False)

        if selected_pid:
            for row in range(self.process_table.rowCount()):
                item = self.process_table.item(row, 1)
                if item and item.text() == selected_pid:
                    self.process_table.selectRow(row)
                    break

        self.process_table.verticalScrollBar().setValue(scroll)
        self.btn_end.setEnabled(bool(self.process_table.currentRow() >= 0))
        self.status_label.setText(f"进程数: {len(processes)}")

    def kill_selected_process(self):
        """Kill the selected process."""
        row = self.process_table.currentRow()
        if row < 0:
            return

        pid = self.process_table.item(row, 1).text()
        name = self.process_table.item(row, 0).text()

        reply = QMessageBox.warning(
            self, "结束进程",
            f"确定要结束进程 \"{name}\" (PID: {pid}) 吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.wine.kill_process(pid):
                self.status_label.setText(f"已结束进程 {name} (PID: {pid})")
                self.refresh_processes()
            else:
                QMessageBox.warning(self, "错误", f"无法结束进程 {pid}")

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)