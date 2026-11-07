"""WinBridge dialogs — Windows-native styled dialogs."""

import os
import subprocess
from pathlib import Path
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QRadioButton, QCheckBox, QGroupBox, QTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QWidget,
    QMessageBox, QFrame, QStackedWidget, QSizePolicy,
    QProgressBar, QStatusBar, QListWidget, QListWidgetItem,
    QApplication, QSplitter, QAbstractItemView, QButtonGroup,
)
from ..core.config import Config
from ..core.wine import Wine
from ..core.bottle import ENVIRONMENT_LABELS
from ..core.download import ComponentManager


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
        self.windows_version_combo.addItems([
            "win11", "win10", "win81", "win8", "win7", "vista",
            "win2003", "winxp", "win2k", "winme", "win98", "win95"
        ])
        self.windows_version_combo.setCurrentText("win10")
        layout.addWidget(self.windows_version_combo)

        # Wine Version
        wine_label = QLabel("Wine 版本")
        wine_label.setObjectName("fieldLabel")
        layout.addWidget(wine_label)

        wine_ver_layout = QHBoxLayout()
        wine_ver_layout.setSpacing(10)

        self.wine_source_combo = QComboBox()
        self.wine_source_combo.addItems([
            "系统默认 Wine",
            "自定义路径...",
        ])
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

        layout.addLayout(wine_ver_layout)

        self.wine_ver_hint = QLabel(f"当前: {self.wine.version}")
        self.wine_ver_hint.setObjectName("hint")
        layout.addWidget(self.wine_ver_hint)

        # Description
        desc_label = QLabel("描述 (可选)")
        desc_label.setObjectName("fieldLabel")
        layout.addWidget(desc_label)

        self.description = QTextEdit()
        self.description.setPlaceholderText("添加容器描述...")
        self.description.setMaximumHeight(70)
        layout.addWidget(self.description)

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

    def on_wine_source_changed(self, index: int):
        """Handle Wine source selection change."""
        is_custom = index == 1
        self.wine_path_input.setVisible(is_custom)
        self.btn_browse_wine.setVisible(is_custom)

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
        """Get the selected Wine path."""
        if self.wine_source_combo.currentIndex() == 1:
            return self.wine_path_input.text().strip() or self.config.wine_path
        return self.config.wine_path


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

        self.btn_open_taskmgr = QPushButton("Wine 任务管理器")
        self.btn_open_taskmgr.setObjectName("btnDefault")
        self.btn_open_taskmgr.clicked.connect(self.open_wine_taskmgr)
        bottom.addWidget(self.btn_open_taskmgr)

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

    def refresh_processes(self):
        """Refresh the process list."""
        processes = self.wine.list_processes(self.bottle_path)
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

    def open_wine_taskmgr(self):
        """Open the built-in Wine task manager."""
        try:
            cmd = self.wine.wine_path.replace("wine", "wine-taskmgr")
            subprocess.Popen([cmd], env=os.environ.copy())
        except Exception:
            subprocess.Popen(
                [self.wine.wine_path, "taskmgr"],
                env=os.environ.copy()
            )

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)