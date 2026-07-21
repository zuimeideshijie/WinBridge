"""WinBridge main window — Windows-native styled main application window."""

import os
from pathlib import Path
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon, QFont, QPixmap
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem,
    QStackedWidget, QFrame, QStatusBar, QProgressBar,
    QApplication, QFileDialog, QMessageBox, QMenuBar,
    QAction, QActionGroup, QSizePolicy, QSpacerItem,
)
from ..core.config import Config
from ..core.bottle import Bottle, BottleManager
from ..core.wine import Wine
from ..core.download import ComponentManager, COMPONENT_MAP
from ..core.theme import ThemeManager
from ..core.wine_updater import WineUpdater
from .bottle_detail import BottleDetailWidget
from .dialogs import CreateBottleDialog, FirstRunDialog, TaskManagerDialog

FONT_FAMILY = "'Segoe UI', 'Noto Sans CJK SC', 'Microsoft YaHei', 'WenQuanYi Micro Hei', sans-serif"


class BottleListItem(QWidget):
    """A single bottle item in the sidebar list — Windows native style."""

    def __init__(self, bottle: Bottle, parent=None):
        super().__init__(parent)
        self.bottle = bottle
        self.setup_ui()

    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        # Icon area
        icon_label = QLabel()
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setText(self.bottle.name[0].upper() if self.bottle.name else "?")
        icon_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_FAMILY};
                border-radius: 4px;
                font-size: 16px;
                font-weight: 600;
                background: #e8f0fe;
                color: #4a90d9;
            }}
        """)
        layout.addWidget(icon_label)

        # Info area
        info_layout = QVBoxLayout()
        info_layout.setSpacing(1)

        name_label = QLabel(self.bottle.name)
        name_label.setStyleSheet(f"""
            font-size: 13px;
            font-weight: 600;
            color: #1a1a2e;
            font-family: {FONT_FAMILY};
        """)
        info_layout.addWidget(name_label)

        details_text = f"{self.bottle.arch.replace('win', 'Win')} · {self.bottle.windows_version} · {self.bottle.drive_c_size}"
        detail_label = QLabel(details_text)
        detail_label.setStyleSheet(f"""
            font-size: 11px;
            color: #888888;
            font-family: {FONT_FAMILY};
        """)
        info_layout.addWidget(detail_label)

        layout.addLayout(info_layout, 1)

        # Environment badge
        env_label = QLabel(self.bottle.environment.capitalize())
        colors = {
            "gaming": "#e74c3c",
            "office": "#3498db",
            "custom": "#2ecc71",
        }
        env_color = colors.get(self.bottle.environment, "#95a5a6")
        env_label.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_FAMILY};
                border: 1px solid {env_color}80;
                border-radius: 3px;
                padding: 1px 6px;
                font-size: 10px;
                font-weight: 600;
                color: {env_color};
                background: {env_color}15;
            }}
        """)
        env_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(env_label)

        self.setStyleSheet("""
            BottleListItem {
                border-radius: 4px;
                border: 1px solid transparent;
            }
            BottleListItem:hover {
                background: #f5f5f5;
            }
        """)


class MainWindow(QMainWindow):
    """Main application window — Windows native style."""

    def __init__(self, config: Config = None, theme_manager: ThemeManager = None):
        super().__init__()
        self.config = config or Config()
        self.theme_manager = theme_manager or ThemeManager()
        self.bottle_manager = BottleManager(self.config)
        self.wine = Wine(self.config.wine_path)
        self.component_manager = ComponentManager(self.config)

        self.setWindowTitle("WinBridge")
        self.setMinimumSize(1000, 680)
        self.resize(1200, 780)

        self.setup_ui()
        self.setup_menu()
        self.load_bottles()

        if self.config.is_first_run:
            QTimer.singleShot(500, self.show_first_run)
        else:
            QTimer.singleShot(1000, self.check_components_completeness)

        # Check Wine version after startup
        QTimer.singleShot(2000, self.check_wine_version)

    def setup_ui(self):
        """Setup the main window UI."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === Header ===
        header = QFrame()
        header.setFixedHeight(48)
        header.setObjectName("appHeader")
        header.setStyleSheet("")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        header_layout.setSpacing(10)

        # App icon + title
        title_label = QLabel("WinBridge")
        title_label.setStyleSheet(f"""
            font-size: 16px;
            font-weight: 600;
            color: #ffffff;
            font-family: {FONT_FAMILY};
            letter-spacing: 0.3px;
        """)
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Theme indicator
        self.theme_indicator = QLabel("☀️")
        self.theme_indicator.setStyleSheet("font-size: 13px; padding: 0 4px;")
        header_layout.addWidget(self.theme_indicator)

        # Wine version badge
        wine_ver = QLabel(f"  {self.wine.version}  ")
        wine_ver.setStyleSheet(f"""
            QLabel {{
                font-family: {FONT_FAMILY};
                font-size: 10px;
                padding: 2px 8px;
                border-radius: 3px;
                font-weight: 500;
                background: rgba(255,255,255,0.1);
                color: rgba(255,255,255,0.8);
            }}
        """)
        header_layout.addWidget(wine_ver)

        main_layout.addWidget(header)

        # === Content area ===
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # === Sidebar ===
        sidebar = QFrame()
        sidebar.setFixedWidth(240)
        sidebar.setObjectName("appSidebar")
        sidebar.setStyleSheet("")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Sidebar header
        sidebar_header = QWidget()
        sidebar_header.setObjectName("sidebarHeader")
        sidebar_header.setStyleSheet("")
        sh_layout = QVBoxLayout(sidebar_header)
        sh_layout.setContentsMargins(12, 10, 12, 10)

        bottles_label = QLabel("我的容器")
        bottles_label.setStyleSheet(f"""
            font-size: 12px;
            font-weight: 600;
            color: #444444;
            font-family: {FONT_FAMILY};
        """)
        sh_layout.addWidget(bottles_label)

        sidebar_layout.addWidget(sidebar_header)

        # Bottle list
        self.bottle_list = QListWidget()
        self.bottle_list.setFrameShape(QFrame.NoFrame)
        self.bottle_list.setSpacing(2)
        self.bottle_list.setContentsMargins(4, 4, 4, 4)
        self.bottle_list.setStyleSheet(f"""
            QListWidget {{
                font-family: {FONT_FAMILY};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                border: none;
                padding: 0px;
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                border-radius: 4px;
            }}
        """)
        self.bottle_list.itemClicked.connect(self.on_bottle_selected)
        sidebar_layout.addWidget(self.bottle_list, 1)

        # Sidebar bottom buttons
        sidebar_bottom = QWidget()
        sidebar_bottom.setObjectName("sidebarBottom")
        sidebar_bottom.setStyleSheet("")
        sb_layout = QVBoxLayout(sidebar_bottom)
        sb_layout.setContentsMargins(8, 8, 8, 8)
        sb_layout.setSpacing(6)

        btn_create = QPushButton("新建容器")
        btn_create.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 7px;
                font-size: 13px;
                font-weight: 600;
                background: #4a90d9;
                color: #ffffff;
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
        btn_create.clicked.connect(self.show_create_dialog)
        sb_layout.addWidget(btn_create)

        btn_import = QPushButton("导入容器")
        btn_import.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px;
                font-size: 12px;
                background: #ffffff;
                color: #333333;
            }}
            QPushButton:hover {{
                background: #e5e5e5;
            }}
            QPushButton:pressed {{
                background: #d9d9d9;
            }}
        """)
        btn_import.clicked.connect(self.import_bottle)
        sb_layout.addWidget(btn_import)

        sidebar_layout.addWidget(sidebar_bottom)

        content_layout.addWidget(sidebar)

        # === Main content area ===
        self.stack = QStackedWidget()

        # Welcome page
        self.welcome_page = self._create_welcome_page()
        self.stack.addWidget(self.welcome_page)

        # Bottle detail page
        self.detail_page = BottleDetailWidget(self.config)
        self.detail_page.bottle_deleted.connect(self.on_bottle_deleted)
        self.detail_page.bottle_updated.connect(self.on_bottle_updated)
        self.stack.addWidget(self.detail_page)

        self.stack.setCurrentWidget(self.welcome_page)
        content_layout.addWidget(self.stack, 1)

        main_layout.addWidget(content, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(f"""
            QStatusBar {{
                font-family: {FONT_FAMILY};
                font-size: 12px;
            }}
        """)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                font-family: {FONT_FAMILY};
                border: 1px solid #cccccc;
                border-radius: 3px;
                text-align: center;
                font-size: 10px;
                background: #ffffff;
                color: #333333;
            }}
            QProgressBar::chunk {{
                background: #4a90d9;
                border-radius: 2px;
            }}
        """)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _create_welcome_page(self) -> QWidget:
        """Create the welcome/landing page."""
        page = QWidget()
        page.setObjectName("welcomePage")
        page.setStyleSheet("")
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)

        # Welcome card
        card = QFrame()
        card.setFixedSize(440, 320)
        card.setObjectName("welcomeCard")
        card.setStyleSheet("")
        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignCenter)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(36, 36, 36, 36)

        logo = QPixmap(str(Path(__file__).parent.parent / "resources" / "logo.png"))
        logo = logo.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon = QLabel()
        icon.setPixmap(logo)
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(72, 72)
        card_layout.addWidget(icon)

        title = QLabel("欢迎使用 WinBridge")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"""
            font-size: 22px;
            font-weight: 600;
            color: #1a1a2e;
            font-family: {FONT_FAMILY};
        """)
        card_layout.addWidget(title)

        desc = QLabel(
            "基于 Wine 的 Windows 应用容器管理器\n"
            "为您的 Linux 桌面带来便捷的 Wine 体验"
        )
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet(f"""
            font-size: 12px;
            color: #666666;
            font-family: {FONT_FAMILY};
            line-height: 1.5;
        """)
        desc.setWordWrap(True)
        card_layout.addWidget(desc)

        card_layout.addSpacing(8)

        btn_new = QPushButton("创建第一个容器")
        btn_new.setFixedWidth(200)
        btn_new.setStyleSheet(f"""
            QPushButton {{
                font-family: {FONT_FAMILY};
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 8px 24px;
                font-size: 13px;
                font-weight: 600;
                background: #4a90d9;
                color: #ffffff;
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
        btn_new.clicked.connect(self.show_create_dialog)
        card_layout.addWidget(btn_new, 0, Qt.AlignCenter)

        layout.addWidget(card, 0, Qt.AlignCenter)
        return page

    def setup_menu(self):
        """Setup the menu bar."""
        menubar = self.menuBar()
        menubar.setStyleSheet(f"""
            QMenuBar {{
                font-family: {FONT_FAMILY};
                font-size: 12px;
            }}
            QMenuBar::item:selected {{
                background: #e0e0e0;
            }}
            QMenu {{
                font-family: {FONT_FAMILY};
                background: #ffffff;
                border: 1px solid #cccccc;
                padding: 4px;
            }}
            QMenu::item {{
                padding: 4px 24px;
                font-size: 12px;
                color: #333333;
            }}
            QMenu::item:selected {{
                background: #4a90d9;
                color: #ffffff;
            }}
            QMenu::separator {{
                height: 1px;
                background: #e0e0e0;
                margin: 4px 8px;
            }}
        """)

        # File menu
        file_menu = menubar.addMenu("文件(&F)")
        create_action = QAction("新建容器", self)
        create_action.triggered.connect(self.show_create_dialog)
        file_menu.addAction(create_action)

        import_action = QAction("导入容器", self)
        import_action.triggered.connect(self.import_bottle)
        file_menu.addAction(import_action)

        file_menu.addSeparator()
        download_action = QAction("下载基础文件", self)
        download_action.triggered.connect(self.download_base_files)
        file_menu.addAction(download_action)

        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        # Tools menu
        tools_menu = menubar.addMenu("工具(&T)")
        taskmgr_action = QAction("任务管理器", self)
        taskmgr_action.triggered.connect(self.open_task_manager)
        tools_menu.addAction(taskmgr_action)

        tools_menu.addSeparator()
        cfg_action = QAction("Wine 配置 (winecfg)", self)
        cfg_action.triggered.connect(self.open_winecfg)
        tools_menu.addAction(cfg_action)

        reg_action = QAction("注册表编辑器 (regedit)", self)
        reg_action.triggered.connect(self.open_regedit)
        tools_menu.addAction(reg_action)

        tools_menu.addSeparator()
        kill_action = QAction("终止所有 Wine 进程", self)
        kill_action.triggered.connect(self.kill_wine)
        tools_menu.addAction(kill_action)

        # View menu
        view_menu = menubar.addMenu("视图(&V)")

        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)

        current_mode = self.theme_manager.mode

        self.action_light = QAction("明色模式", self)
        self.action_light.setCheckable(True)
        self.action_light.setChecked(current_mode == "light")
        self.action_light.triggered.connect(lambda: self.switch_theme("light"))
        self.theme_group.addAction(self.action_light)
        view_menu.addAction(self.action_light)

        self.action_dark = QAction("暗色模式", self)
        self.action_dark.setCheckable(True)
        self.action_dark.setChecked(current_mode == "dark")
        self.action_dark.triggered.connect(lambda: self.switch_theme("dark"))
        self.theme_group.addAction(self.action_dark)
        view_menu.addAction(self.action_dark)

        self.action_system = QAction("跟随系统", self)
        self.action_system.setCheckable(True)
        self.action_system.setChecked(current_mode == "system")
        self.action_system.triggered.connect(lambda: self.switch_theme("system"))
        self.theme_group.addAction(self.action_system)
        view_menu.addAction(self.action_system)

        # Help menu
        help_menu = menubar.addMenu("帮助(&H)")
        about_action = QAction("关于 WinBridge", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def load_bottles(self):
        """Load bottles into the list."""
        self.bottle_list.clear()
        bottles = self.bottle_manager.list_bottles()

        if not bottles:
            self.stack.setCurrentWidget(self.welcome_page)

        for bottle in bottles:
            item = QListWidgetItem()
            widget = BottleListItem(bottle)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.UserRole, bottle.name)
            self.bottle_list.addItem(item)
            self.bottle_list.setItemWidget(item, widget)

    def on_bottle_selected(self, item):
        """Handle bottle selection from the list."""
        name = item.data(Qt.UserRole)
        bottle = self.bottle_manager.get_bottle(name)
        if bottle:
            self.detail_page.load_bottle(bottle)
            self.stack.setCurrentWidget(self.detail_page)
            self.status_bar.showMessage(f"当前容器: {name}")

    def on_bottle_deleted(self, name: str):
        """Handle bottle deletion."""
        self.load_bottles()
        self.status_bar.showMessage(f"容器 '{name}' 已删除")

    def on_bottle_updated(self, name: str):
        """Handle bottle update."""
        self.load_bottles()
        # Re-select the bottle
        for i in range(self.bottle_list.count()):
            item = self.bottle_list.item(i)
            if item.data(Qt.UserRole) == name:
                self.bottle_list.setCurrentItem(item)
                break

    def show_create_dialog(self):
        """Show the create bottle dialog."""
        dialog = CreateBottleDialog(self.config, self)
        if dialog.exec_():
            name = dialog.bottle_name.text().strip()
            arch = "win64" if dialog.arch_64.isChecked() else "win32"
            env = dialog.environment_combo.currentText().lower()
            win_ver = dialog.windows_version_combo.currentText()
            desc = dialog.description.toPlainText().strip()
            wine_path = dialog.get_wine_path()

            self.status_bar.showMessage(f"正在创建容器 '{name}'...")
            QApplication.processEvents()

            bottle = self.bottle_manager.create_bottle(
                name=name, arch=arch, environment=env,
                windows_version=win_ver, description=desc,
                wine_path=wine_path,
            )

            if bottle:
                self.load_bottles()
                self.status_bar.showMessage(f"容器 '{name}' 创建成功")
                # Select the new bottle
                for i in range(self.bottle_list.count()):
                    item = self.bottle_list.item(i)
                    if item.data(Qt.UserRole) == name:
                        self.bottle_list.setCurrentItem(item)
                        self.on_bottle_selected(item)
                        break
            else:
                QMessageBox.warning(self, "创建失败",
                                    f"容器 '{name}' 创建失败，可能已存在。")

    def import_bottle(self):
        """Import an existing Wine prefix."""
        path = QFileDialog.getExistingDirectory(self, "选择 Wine 前缀目录")
        if path:
            path_obj = Path(path)
            if (path_obj / "user.reg").exists():
                name = path_obj.name
                dest = self.config.bottles_dir / name
                if dest.exists():
                    QMessageBox.warning(self, "导入失败", "同名容器已存在。")
                    return
                import shutil
                shutil.copytree(str(path_obj), str(dest))
                bottle = Bottle(str(dest), config=self.config)
                bottle._save_meta()
                self.load_bottles()
                self.status_bar.showMessage(f"容器 '{name}' 导入成功")
            else:
                QMessageBox.warning(self, "导入失败",
                                    "所选目录不是有效的 Wine 前缀。")

    def open_winecfg(self):
        """Open winecfg for the currently selected bottle."""
        current = self.bottle_list.currentItem()
        if current:
            name = current.data(Qt.UserRole)
            bottle = self.bottle_manager.get_bottle(name)
            if bottle:
                self.wine.run(str(bottle.path), "winecfg", wait=False)
                self.status_bar.showMessage(f"已打开 winecfg: {name}")

    def open_regedit(self):
        """Open regedit for the currently selected bottle."""
        current = self.bottle_list.currentItem()
        if current:
            name = current.data(Qt.UserRole)
            bottle = self.bottle_manager.get_bottle(name)
            if bottle:
                self.wine.run(str(bottle.path), "regedit", wait=False)
                self.status_bar.showMessage(f"已打开 regedit: {name}")

    def kill_wine(self):
        """Kill all Wine processes."""
        self.wine.kill()
        self.status_bar.showMessage("已终止所有 Wine 进程")

    def open_task_manager(self):
        """Open the Windows-style Task Manager."""
        name = None
        current = self.bottle_list.currentItem()
        if current:
            name = current.data(Qt.UserRole)
        bottle_path = str(self.config.bottles_dir / name) if name else None
        dialog = TaskManagerDialog(self.wine, bottle_path, self)
        dialog.show()

    def show_first_run(self):
        """Show first run dialog."""
        dialog = FirstRunDialog(self.config, self)
        if dialog.exec_():
            self.config.mark_first_run_done()
            if dialog.download_base:
                self.download_base_files()

    def check_components_completeness(self):
        """Check if the first bottle has components installed; if not, prompt."""
        bottles = self.bottle_manager.list_bottles()
        if not bottles:
            return
        bottle = bottles[0]
        if len(bottle.installed_components) < 3:
            reply = QMessageBox.question(
                self, "组件检测",
                f"容器「{bottle.name}」尚未安装基础组件。\n"
                "是否现在安装？（推荐安装 vcrun、dotnet 等）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                for i in range(self.bottle_list.count()):
                    item = self.bottle_list.item(i)
                    if item.data(Qt.UserRole) == bottle.name:
                        self.bottle_list.setCurrentItem(item)
                        self.on_bottle_selected(item)
                        break
                self.download_base_files()

    def download_base_files(self):
        """Download base files into the currently selected bottle."""
        from PyQt5.QtCore import QThread, pyqtSignal

        bottle = None
        current = self.bottle_list.currentItem()
        if current:
            name = current.data(Qt.UserRole)
            bottle = self.bottle_manager.get_bottle(name)

        if not bottle:
            QMessageBox.information(self, "提示",
                "请先在左侧选择一个容器，再安装组件。")
            return

        installed = set(bottle.installed_components)
        to_install = [(n, i) for n, i in COMPONENT_MAP.items()
                      if n not in installed]

        if not to_install:
            QMessageBox.information(self, "提示",
                "所选容器已安装所有基础组件。")
            return

        class InstallThread(QThread):
            progress = pyqtSignal(int, int)
            finished = pyqtSignal(bool)
            status = pyqtSignal(str)

            def __init__(self, component_manager, bottle_path, components, bottle):
                super().__init__()
                self.component_manager = component_manager
                self.bottle_path = bottle_path
                self.components = components
                self.bottle = bottle

            def run(self):
                total = len(self.components)
                for i, (name, info) in enumerate(self.components):
                    self.status.emit(f"正在安装 {info['label']}...")
                    self.progress.emit(int(i * 100 / total), 100)

                    def on_progress(v, t, m=None):
                        self.progress.emit(v, t)
                        if m:
                            self.status.emit(m)

                    ok = self.component_manager.install(
                        name, self.bottle_path, on_progress)
                    if ok:
                        self.status.emit(f"{info['label']} 安装完成")
                        if self.bottle:
                            self.bottle.add_component(name)
                    else:
                        self.status.emit(f"{info['label']} 安装失败")
                self.progress.emit(100, 100)
                self.finished.emit(True)

        bottle_path = str(bottle.path)
        self.thread = InstallThread(
            self.component_manager, bottle_path, to_install, bottle)
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.finished.connect(
            lambda ok: self.on_download_finished(ok))
        self.thread.status.connect(self.status_bar.showMessage)
        self.progress_bar.setVisible(True)
        self.thread.start()

    def on_download_finished(self, success: bool):
        """Handle download completion."""
        self.progress_bar.setVisible(False)
        if success:
            self.status_bar.showMessage("基础文件下载完成")
        else:
            QMessageBox.warning(self, "下载提示",
                                "部分文件下载失败，可稍后重试。")

    def show_about(self):
        """Show about dialog."""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton

        dialog = QDialog(self)
        dialog.setWindowTitle("关于 WinBridge")
        dialog.setFixedSize(420, 320)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)
        layout.setContentsMargins(24, 20, 24, 20)

        # Logo
        logo_pix = QPixmap(str(Path(__file__).parent.parent / "resources" / "logo.png"))
        logo_pix = logo_pix.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label = QLabel()
        logo_label.setPixmap(logo_pix)
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setFixedSize(64, 64)
        layout.addWidget(logo_label)

        title = QLabel("WinBridge")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: 600; color: #1a1a2e;")
        layout.addWidget(title)

        version = QLabel("版本 0.1.0")
        version.setAlignment(Qt.AlignCenter)
        version.setStyleSheet("font-size: 12px; color: #888888;")
        layout.addWidget(version)

        desc = QLabel("基于 Wine 的 Windows 应用容器管理器")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("font-size: 13px; color: #333333; margin-top: 8px;")
        layout.addWidget(desc)

        # Info card
        info = QLabel(
            f"Wine 版本: {self.wine.version}\n"
            f"容器目录: {self.config.bottles_dir}"
        )
        info.setStyleSheet("""
            font-size: 12px; color: #555555; line-height: 1.6;
            background: #f5f5f5; border-radius: 4px; padding: 10px 14px;
        """)
        layout.addWidget(info)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_check = QPushButton("检查 Wine 更新")
        btn_check.setStyleSheet("""
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
                background: #4a90d9;
                color: #ffffff;
            }
            QPushButton:hover { background: #357abd; border-color: #357abd; }
            QPushButton:pressed { background: #2a6cb5; border-color: #2a6cb5; }
        """)
        btn_check.clicked.connect(lambda: (dialog.accept(), self.check_wine_version()))
        btn_layout.addWidget(btn_check)

        btn_manual = QPushButton("用户手册")
        btn_manual.setStyleSheet("""
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 16px;
                font-size: 12px;
                background: #ffffff;
                color: #333333;
            }
            QPushButton:hover { background: #f5f5f5; }
            QPushButton:pressed { background: #e8e8e8; }
        """)
        btn_manual.clicked.connect(lambda: self._open_user_manual(dialog))
        btn_layout.addWidget(btn_manual)

        btn_layout.addStretch()

        btn_ok = QPushButton("确定")
        btn_ok.setStyleSheet("""
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 24px;
                font-size: 13px;
                background: #f0f0f0;
                color: #333333;
                min-width: 80px;
            }
            QPushButton:hover { background: #e5e5e5; }
            QPushButton:pressed { background: #d9d9d9; }
        """)
        btn_ok.clicked.connect(dialog.accept)
        btn_layout.addWidget(btn_ok)

        layout.addLayout(btn_layout)
        dialog.exec_()

    def _open_user_manual(self, dialog):
        """Open the user manual."""
        import webbrowser
        dialog.accept()
        webbrowser.open("https://gitcode.com/2503_90323139/WinBridge.git")

    def switch_theme(self, mode: str):
        """Switch the application theme."""
        from main import apply_theme, get_theme
        self.theme_manager.set_mode(mode)
        apply_theme(QApplication.instance(), self.theme_manager)
        is_dark = self.theme_manager.is_dark
        self.theme_indicator.setText("🌙" if is_dark else "☀️")
        self.status_bar.showMessage(f"已切换至{self.theme_manager.palette['name']}")

    def check_wine_version(self):
        """Check Wine version and prompt for update if available."""
        self.updater = WineUpdater(parent=self)
        self.updater.version_checked.connect(self._on_wine_version_checked)
        self.updater.check_version()
        self.status_bar.showMessage("正在检查 Wine 版本...")

    def _on_wine_version_checked(self, local: str, remote: str):
        """Handle Wine version check result."""
        if not local:
            self.status_bar.showMessage("Wine: 无法检测本地版本")
            return

        self.status_bar.showMessage(f"Wine: {local}")

        if not remote:
            return  # Can't check remote, skip

        if local == remote:
            return  # Already up to date

        # Newer version available — prompt user
        self._show_wine_update_dialog(local, remote)

    def _show_wine_update_dialog(self, local: str, remote: str):
        """Show a dialog asking if the user wants to update Wine."""
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QPushButton, QProgressBar, QFrame,
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Wine 更新可用")
        dialog.setMinimumWidth(480)
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # Title
        title = QLabel("🍷 Wine 新版本可用")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #1a1a2e;")
        layout.addWidget(title)

        # Version info
        info = QLabel(
            f"本地版本: {local}\n"
            f"最新版本: {remote}\n\n"
            "是否从 GitCode 下载最新的 Wine 源码？"
        )
        info.setStyleSheet("font-size: 13px; color: #333333; line-height: 1.5;")
        layout.addWidget(info)

        # Progress
        self._update_progress = QProgressBar()
        self._update_progress.setVisible(False)
        self._update_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #cccccc;
                border-radius: 3px;
                text-align: center;
                font-size: 10px;
                background: #ffffff;
                color: #333333;
                height: 20px;
            }
            QProgressBar::chunk {
                background: #4a90d9;
                border-radius: 2px;
            }
        """)
        layout.addWidget(self._update_progress)

        self._update_status = QLabel("")
        self._update_status.setStyleSheet("font-size: 11px; color: #888888;")
        self._update_status.setVisible(False)
        layout.addWidget(self._update_status)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_skip = QPushButton("稍后再说")
        btn_skip.setStyleSheet("""
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 6px 20px;
                font-size: 13px;
                background: #f0f0f0;
                color: #333333;
            }
            QPushButton:hover { background: #e5e5e5; }
            QPushButton:pressed { background: #d9d9d9; }
        """)
        btn_skip.clicked.connect(dialog.reject)
        btn_layout.addWidget(btn_skip)

        btn_layout.addStretch()

        btn_update = QPushButton("立即更新")
        btn_update.setStyleSheet("""
            QPushButton {
                font-family: 'Segoe UI', sans-serif;
                border: 1px solid #4a90d9;
                border-radius: 3px;
                padding: 6px 24px;
                font-size: 13px;
                font-weight: 600;
                background: #4a90d9;
                color: #ffffff;
            }
            QPushButton:hover { background: #357abd; border-color: #357abd; }
            QPushButton:pressed { background: #2a6cb5; border-color: #2a6cb5; }
            QPushButton:disabled { background: #d0d0d0; border-color: #d0d0d0; color: #888888; }
        """)
        btn_update.clicked.connect(lambda: self._start_wine_update(
            dialog, btn_update, btn_skip))
        btn_layout.addWidget(btn_update)

        layout.addLayout(btn_layout)
        dialog.exec_()

    def _start_wine_update(self, dialog, btn_update, btn_skip):
        """Start the Wine update process."""
        btn_update.setEnabled(False)
        btn_skip.setEnabled(False)
        self._update_progress.setVisible(True)
        self._update_status.setVisible(True)

        self.updater.progress.connect(self._on_update_progress)
        self.updater.update_finished.connect(
            lambda ok, msg: self._on_update_finished(ok, msg, dialog))
        self.updater.clone_wine()

    def _on_update_progress(self, message: str, percent: int):
        """Handle update progress."""
        self._update_progress.setValue(percent)
        self._update_status.setText(message)

    def _on_update_finished(self, success: bool, message: str, dialog):
        """Handle update completion."""
        self._update_status.setText(message)
        if success:
            self._update_progress.setValue(100)
            self.status_bar.showMessage("Wine 源码已更新，请重新编译。")
        else:
            self.status_bar.showMessage(f"Wine 更新失败: {message}")