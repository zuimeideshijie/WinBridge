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
from ..core.download import ComponentManager

FONT_FAMILY = "'Segoe UI', 'Noto Sans CJK SC', 'Microsoft YaHei', 'WenQuanYi Micro Hei', sans-serif"


class CreateBottleDialog(QDialog):
    """Dialog for creating a new bottle — Windows native style."""

    def __init__(self, config: Config = None, parent=None):
        super().__init__(parent)
        self.config = config or Config()
        self.wine = Wine(self.config.wine_path)
        self.setWindowTitle("新建容器")
        self.setMinimumSize(500, 500)
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Title
        title = QLabel("创建新容器")
        title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 600;
            color: #1a1a2e;
            font-family: {FONT_FAMILY};
            padding-bottom: 4px;
        """)
        layout.addWidget(title)

        subtitle = QLabel("创建一个新的 Wine 前缀来运行 Windows 应用程序")
        subtitle.setStyleSheet(f"""
            font-size: 12px;
            color: #666666;
            font-family: {FONT_FAMILY};
            margin-bottom: 8px;
        """)
        layout.addWidget(subtitle)

        # Name
        name_label = QLabel("容器名称")
        name_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
            margin-top: 4px;
        """)
        layout.addWidget(name_label)

        self.bottle_name = QLineEdit()
        self.bottle_name.setPlaceholderText("例如: myapp, game1, office...")
        self.bottle_name.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: {FONT_FAMILY};
                background: #ffffff;
            }}
            QLineEdit:focus {{
                border-color: #4a90d9;
                background: #ffffff;
            }}
        """)
        layout.addWidget(self.bottle_name)

        # Architecture
        arch_label = QLabel("架构")
        arch_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
            margin-top: 8px;
        """)
        layout.addWidget(arch_label)

        arch_layout = QHBoxLayout()
        arch_layout.setSpacing(16)

        self.arch_64 = QRadioButton("64 位 (Win64)")
        self.arch_64.setChecked(True)
        self.arch_64.setStyleSheet(f"""
            QRadioButton {{
                font-family: {FONT_FAMILY};
                font-size: 13px;
                color: #333333;
                spacing: 6px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 8px;
                border: 2px solid #999999;
            }}
            QRadioButton::indicator:checked {{
                background: #4a90d9;
                border-color: #4a90d9;
            }}
        """)
        arch_layout.addWidget(self.arch_64)

        self.arch_32 = QRadioButton("32 位 (Win32)")
        self.arch_32.setStyleSheet(self.arch_64.styleSheet())
        arch_layout.addWidget(self.arch_32)

        arch_layout.addStretch()
        layout.addLayout(arch_layout)

        # Environment
        env_label = QLabel("环境类型")
        env_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
            margin-top: 8px;
        """)
        layout.addWidget(env_label)

        self.environment_combo = QComboBox()
        self.environment_combo.addItems([
            "游戏/多媒体 (gaming)",
            "办公软件 (office)",
            "自定义 (custom)",
        ])
        self.environment_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: {FONT_FAMILY};
                background: #ffffff;
            }}
            QComboBox:focus {{ border-color: #4a90d9; }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                font-family: {FONT_FAMILY};
                background: #ffffff;
                border: 1px solid #cccccc;
                selection-background-color: #4a90d9;
                selection-color: #ffffff;
            }}
        """)
        layout.addWidget(self.environment_combo)

        # Windows Version
        winver_label = QLabel("Windows 版本")
        winver_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
            margin-top: 8px;
        """)
        layout.addWidget(winver_label)

        self.windows_version_combo = QComboBox()
        self.windows_version_combo.addItems([
            "win11", "win10", "win81", "win8", "win7", "vista",
            "win2003", "winxp", "win2k", "winme", "win98", "win95"
        ])
        self.windows_version_combo.setCurrentText("win10")
        self.windows_version_combo.setStyleSheet(self.environment_combo.styleSheet())
        layout.addWidget(self.windows_version_combo)

        # Wine Version
        wine_label = QLabel("Wine 版本")
        wine_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
            margin-top: 8px;
        """)
        layout.addWidget(wine_label)

        wine_ver_layout = QHBoxLayout()
        wine_ver_layout.setSpacing(8)

        self.wine_source_combo = QComboBox()
        self.wine_source_combo.addItems([
            "系统默认 Wine",
            "自定义路径...",
        ])
        self.wine_source_combo.setStyleSheet(self.environment_combo.styleSheet())
        self.wine_source_combo.currentIndexChanged.connect(self.on_wine_source_changed)
        wine_ver_layout.addWidget(self.wine_source_combo, 1)

        self.wine_path_input = QLineEdit()
        self.wine_path_input.setPlaceholderText("选择 Wine 二进制文件...")
        self.wine_path_input.setVisible(False)
        self.wine_path_input.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: {FONT_FAMILY};
                background: #ffffff;
            }}
            QLineEdit:focus {{
                border-color: #4a90d9;
            }}
        """)
        wine_ver_layout.addWidget(self.wine_path_input, 2)

        self.btn_browse_wine = QPushButton("浏览...")
        self.btn_browse_wine.setVisible(False)
        self.btn_browse_wine.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 5px 12px;
                font-size: 12px;
                background: #f0f0f0;
                color: #333333;
            }}
            QPushButton:hover {{
                background: #e5e5e5;
            }}
            QPushButton:pressed {{
                background: #d9d9d9;
            }}
        """)
        self.btn_browse_wine.clicked.connect(self.browse_wine_path)
        wine_ver_layout.addWidget(self.btn_browse_wine)

        layout.addLayout(wine_ver_layout)

        self.wine_ver_hint = QLabel(f"当前: {self.wine.version}")
        self.wine_ver_hint.setStyleSheet(f"""
            font-size: 11px;
            color: #999999;
            font-family: {FONT_FAMILY};
        """)
        layout.addWidget(self.wine_ver_hint)

        # Description
        desc_label = QLabel("描述 (可选)")
        desc_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
            margin-top: 8px;
        """)
        layout.addWidget(desc_label)

        self.description = QTextEdit()
        self.description.setPlaceholderText("添加容器描述...")
        self.description.setMaximumHeight(70)
        self.description.setStyleSheet(f"""
            QTextEdit {{
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: {FONT_FAMILY};
                background: #ffffff;
            }}
            QTextEdit:focus {{
                border-color: #4a90d9;
                background: #ffffff;
            }}
        """)
        layout.addWidget(self.description)

        # Spacer
        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 20px;
                font-size: 13px;
                background: #f0f0f0;
                color: #333333;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background: #e5e5e5;
            }}
            QPushButton:pressed {{
                background: #d9d9d9;
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_layout.addStretch()

        self.btn_create = QPushButton("创建容器")
        self.btn_create.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 6px 24px;
                font-size: 13px;
                font-weight: 600;
                background: #4a90d9;
                color: #ffffff;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background: #357abd;
                border-color: #357abd;
            }}
            QPushButton:pressed {{
                background: #2a6cb5;
                border-color: #2a6cb5;
            }}
            QPushButton:disabled {{
                background: #d0d0d0;
                border-color: #d0d0d0;
                color: #888888;
            }}
        """)
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
        self.setMinimumSize(480, 400)
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Icon + Title
        logo_pix = QPixmap(str(Path(__file__).parent / "resources" / "logo.png"))
        logo_pix = logo_pix.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QLabel()
        icon.setPixmap(logo_pix)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(72, 72)
        layout.addWidget(icon)

        title = QLabel("首次使用 WinBridge")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            font-size: 20px;
            font-weight: 600;
            color: #1a1a2e;
            font-family: {FONT_FAMILY};
        """)
        layout.addWidget(title)

        desc = QLabel(
            "WinBridge 是一个基于 Wine 的 Windows 应用容器管理器。\n"
            "首次启动建议下载基础文件以获得最佳体验。"
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet(f"""
            font-size: 12px;
            color: #666666;
            font-family: {FONT_FAMILY};
            line-height: 1.5;
        """)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addSpacing(8)

        # Options group
        options_frame = QFrame()
        options_frame.setStyleSheet(f"""
            QFrame {{
                border: 1px solid #e0e0e0;
                border-radius: 4px;
                background: #fafafa;
                padding: 12px;
            }}
        """)
        options_layout = QVBoxLayout(options_frame)
        options_layout.setSpacing(10)
        options_layout.setContentsMargins(12, 12, 12, 12)

        options_title = QLabel("首次设置")
        options_title.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        options_layout.addWidget(options_title)

        self.download_base = QCheckBox("下载基础组件 (Wine-GE, DXVK, vcrun 等)")
        self.download_base.setChecked(True)
        self.download_base.setStyleSheet(f"""
            QCheckBox {{
                font-family: {FONT_FAMILY};
                font-size: 13px;
                color: #333333;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 2px;
                border: 2px solid #999999;
            }}
            QCheckBox::indicator:checked {{
                background: #4a90d9;
                border-color: #4a90d9;
            }}
        """)
        options_layout.addWidget(self.download_base)

        hint = QLabel(
            "基础文件将从 GitCode 下载。\n"
            "如果网络不佳，可跳过此步骤稍后手动下载。"
        )
        hint.setStyleSheet(f"""
            font-size: 11px;
            color: #999999;
            font-family: {FONT_FAMILY};
        """)
        options_layout.addWidget(hint)

        layout.addWidget(options_frame)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.skip_btn = QPushButton("跳过")
        self.skip_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 20px;
                font-size: 13px;
                background: #f0f0f0;
                color: #333333;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background: #e5e5e5;
            }}
            QPushButton:pressed {{
                background: #d9d9d9;
            }}
        """)
        self.skip_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.skip_btn)

        btn_layout.addStretch()

        self.continue_btn = QPushButton("继续")
        self.continue_btn.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 6px 24px;
                font-size: 13px;
                font-weight: 600;
                background: #4a90d9;
                color: #ffffff;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background: #357abd;
                border-color: #357abd;
            }}
            QPushButton:pressed {{
                background: #2a6cb5;
                border-color: #2a6cb5;
            }}
        """)
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
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("添加 DLL 覆盖")
        title.setStyleSheet(f"""
            font-size: 16px;
            font-weight: 600;
            color: #1a1a2e;
            font-family: {FONT_FAMILY};
            padding-bottom: 4px;
        """)
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)

        self.dll_name = QLineEdit()
        self.dll_name.setPlaceholderText("例如: d3d9, d3d11, xaudio2_7")
        self.dll_name.setStyleSheet(f"""
            QLineEdit {{
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: {FONT_FAMILY};
                background: #ffffff;
            }}
            QLineEdit:focus {{
                border-color: #4a90d9;
            }}
        """)
        dll_label = QLabel("DLL 名称:")
        dll_label.setStyleSheet(f"""
            font-size: 13px;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        form.addRow(dll_label, self.dll_name)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "native,builtin (优先原生)",
            "builtin,native (优先内置)",
            "native (仅原生)",
            "builtin (仅内置)",
            "disable (禁用)",
        ])
        self.mode_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 10px;
                font-size: 13px;
                font-family: {FONT_FAMILY};
                background: #ffffff;
            }}
            QComboBox:focus {{ border-color: #4a90d9; }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox QAbstractItemView {{
                font-family: {FONT_FAMILY};
                background: #ffffff;
                border: 1px solid #cccccc;
                selection-background-color: #4a90d9;
                selection-color: #ffffff;
            }}
        """)
        mode_label = QLabel("加载模式:")
        mode_label.setStyleSheet(f"""
            font-size: 13px;
            color: #333333;
            font-family: {FONT_FAMILY};
        """)
        form.addRow(mode_label, self.mode_combo)

        layout.addLayout(form)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_cancel = QPushButton("取消")
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 20px;
                font-size: 13px;
                background: #f0f0f0;
                color: #333333;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background: #e5e5e5;
            }}
            QPushButton:pressed {{
                background: #d9d9d9;
            }}
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        btn_layout.addStretch()

        self.btn_ok = QPushButton("确定")
        self.btn_ok.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 6px 24px;
                font-size: 13px;
                font-weight: 600;
                background: #4a90d9;
                color: #ffffff;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background: #357abd;
                border-color: #357abd;
            }}
            QPushButton:pressed {{
                background: #2a6cb5;
                border-color: #2a6cb5;
            }}
            QPushButton:disabled {{
                background: #d0d0d0;
                border-color: #d0d0d0;
                color: #888888;
            }}
        """)
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
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("任务管理器")
        title.setStyleSheet(f"""
            font-size: 16px;
            font-weight: 600;
            color: #1a1a2e;
            font-family: {FONT_FAMILY};
            padding-bottom: 4px;
        """)
        layout.addWidget(title)

        # Process table
        self.process_table = QTableWidget()
        self.process_table.setColumnCount(6)
        self.process_table.setHorizontalHeaderLabels([
            "进程名称", "PID", "CPU %", "内存 %", "状态", "用户"
        ])
        self.process_table.horizontalHeader().setStretchLastSection(True)
        self.process_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.process_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.process_table.setSelectionMode(QTableWidget.SingleSelection)
        self.process_table.setAlternatingRowColors(True)
        self.process_table.verticalHeader().setVisible(False)
        self.process_table.setStyleSheet(f"""
            QTableWidget {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                font-size: 12px;
                background: #ffffff;
                alternate-background-color: #f5f5f5;
                gridline-color: #e0e0e0;
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                color: #333333;
                background: #ffffff;
            }}
            QTableWidget::item:selected {{
                background: #e8f0fe;
                color: #1a1a2e;
            }}
            QTableWidget::item:alternate {{
                background: #f5f5f5;
                color: #333333;
            }}
            QHeaderView::section {{
                font-family: {FONT_FAMILY};
                background: #f0f0f0;
                border: none;
                border-bottom: 1px solid #cccccc;
                padding: 6px 8px;
                font-weight: 600;
                font-size: 12px;
                color: #444444;
            }}
        """)
        layout.addWidget(self.process_table, 1)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: #666666;
            font-family: {FONT_FAMILY};
        """)
        bottom.addWidget(self.status_label)

        bottom.addStretch()

        self.btn_end = QPushButton("结束进程")
        self.btn_end.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #e74c3c;
                border-radius: 3px;
                padding: 6px 16px;
                font-size: 12px;
                background: #ffffff;
                color: #e74c3c;
            }}
            QPushButton:hover {{
                background: #e74c3c;
                color: #ffffff;
            }}
            QPushButton:pressed {{
                background: #c0392b;
                border-color: #c0392b;
            }}
            QPushButton:disabled {{
                border-color: #cccccc;
                color: #aaaaaa;
                background: #f0f0f0;
            }}
        """)
        self.btn_end.clicked.connect(self.kill_selected_process)
        self.btn_end.setEnabled(False)
        bottom.addWidget(self.btn_end)

        self.btn_open_taskmgr = QPushButton("Wine 任务管理器")
        self.btn_open_taskmgr.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 16px;
                font-size: 12px;
                background: #f0f0f0;
                color: #333333;
            }}
            QPushButton:hover {{
                background: #e5e5e5;
            }}
            QPushButton:pressed {{
                background: #d9d9d9;
            }}
        """)
        self.btn_open_taskmgr.clicked.connect(self.open_wine_taskmgr)
        bottom.addWidget(self.btn_open_taskmgr)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 16px;
                font-size: 12px;
                background: #f0f0f0;
                color: #333333;
            }}
            QPushButton:hover {{
                background: #e5e5e5;
            }}
            QPushButton:pressed {{
                background: #d9d9d9;
            }}
        """)
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