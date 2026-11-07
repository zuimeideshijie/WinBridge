# 更新日志

## [1.2.1] - 2026-11-07

### 问题修复

- **修复 Chromium 类程序装进容器后「启动失败」（窗口不出现）**：新建容器时
  `register_all_fonts()` 会把整个字体表（`HKLM\Software\Microsoft\Windows NT\
  CurrentVersion\Fonts`）替换成容器里那几十个字体文件，Wine 自己注册的上千个
  宿主字体（含 `@` 开头的横排/竖排字面与内置替换）全部丢失。Chromium 内核的
  程序（千问、夸克、各类 Electron 应用）在这种情况下会直接退出：进程能起来、
  网页也加载完成，但主窗口始终不显示。现在改为**合并**写入字体表，保留 Wine
  已注册的字面；字体表若已被清空（旧版本创建的容器），会用一个临时前缀重建
  宿主字体表后补齐
- **修复写注册表被 wineserver 覆盖**：`create_prefix()` 之后先等 wineserver
  退出并落盘，再写 `system.reg`，避免内存中的注册表稍后把字体表冲掉
- **修复后台启动的程序可能卡死**：`wine.run(wait=False)` 之前给子进程接了
  `PIPE` 却从不读取，Wine 日志写满 64 KB 缓冲后进程会堵死；改为丢弃输出

## [1.2.0] - 2026-11-07

### 快捷方式

- **只显示当前容器内的应用**：不再扫描宿主 Linux 桌面；来源限定为容器内的
  桌面/开始菜单 `.lnk` 与 `Program Files` 下的可执行文件
- **持久化记录**：快捷方式写入 `bottle.json`，删除 Windows 桌面上的 `.lnk` 后
  条目依然保留；图标缺失或程序被删除时条目变灰而不是消失
- **图标**：新增 PE 资源解析（`shortcuts.extract_icon`），从 exe 的
  `RT_GROUP_ICON` / `RT_ICON` 生成 `.ico` 缓存；Wine 生成的 exe 常缺
  `GROUP_ICON`，此时直接取最大 `RT_ICON`。图标在后台线程提取，不阻塞界面
- **右键菜单**：打开 / 重命名（只改显示名，不动程序文件）/ 添加到桌面 / 卸载
- **卸载**：删除应用自己的安装目录（仅限 `Program Files`、`ProgramData`、
  `AppData\Local\Programs` 等独立目录，系统程序与共享目录一律拒绝）、容器内相关
  快捷方式、桌面上的 `.desktop`，并移除记录；确认框会先列出目录、占用空间与将删除
  的快捷方式数量，注册表残留不做处理
- **桌面项**：生成的 `.desktop` 带图标（`.ico` 转 PNG，失败时回退应用 logo），
  `Exec` 走 `winbridge --bottle <容器> --run <程序>`，双击即启动
- **新增 `--bottle` / `--run` 启动参数**：供桌面项调用，只启动程序不打开主窗口

### 界面重写

- **统一的视觉系统**：`theme.py` 重写为唯一视觉来源（色板 + 全局 QSS + 语义化
  角色名如 `btnPrimary` / `card` / `sectionTitle`），明色与暗色两套配色同等完整，
  默认跟随系统，可在「视图」菜单切换
- **收敛内联样式**：主窗口、容器详情、各对话框的 150+ 处 `setStyleSheet` 全部
  移除，改为 `objectName` 角色 + 全局 QSS；不再有硬编码色值导致的暗色模式错乱
- **去除模板感**：去掉标题栏渐变、卡片投影、彩色渐变按钮与 emoji 图标；改为平面
  分层、1px 细边框、单一强调色与统一的 4/8px 间距
- **状态文案去装饰**：下载/安装进度不再带 📥 ✅ ⚙ 📦 等前缀，改为「正在下载 /
  正在安装 / 处理中」等纯文字
- **环境类型**：新增 `ENVIRONMENT_LABELS` 与 `environment_key()`，兼容旧容器里
  保存的中文环境字符串（如「游戏/多媒体 (gaming)」），下拉框改为按 key 存储

### 组件下载源更新

- **GitHub 资源统一走镜像源**：`download.py` 新增镜像层，所有 `github.com` /
  `raw.githubusercontent.com` 资源按 `gh-proxy.org → v6.gh-proxy.org →
  gh-proxy.com → ghproxy.net → ghfast.top → 直连` 顺序尝试，记住可用的镜像并
  后续优先使用；微软下载源（aka.ms、download.microsoft.com、
  download.visualstudio.microsoft.com）保持直连不变
- **winetricks 内的 GitHub 下载同步走镜像**：新增 `WINETRICKS_GH_MIRROR` 钩子，
  由 WinBridge 自动注入镜像列表；首次尝试第一个镜像，重试时依次换下一个，用尽后
  回退原始地址（未设置该变量时行为与上游一致）。corefonts 的硬编码镜像前缀已还原
  为原始 GitHub 地址，交由该钩子统一改写
- **DXVK / VKD3D 改用预编译包**：DXVK 2.7.1 与 VKD3D-PROTON 2.14.1（`.tar.zst`）
  直接下载解压，无需 meson/ninja
- **FAudio 改为预编译包**：下载 Kron4ek FAudio-Builds 20.07（`.tar.xz`），不再克隆
  源码（上游源码仓库没有安装脚本）
- **`.tar.zst` 支持**：校验用 `zstd -t`，解压用 `zstd -dc` 流式喂给 tarfile

### 问题修复

- **修复 VKD3D 下载 404**：vkd3d-proton 只发布 `.tar.zst`，原先的 `.tar.gz` 并不存在
- **修复 DXVK/VKD3D DLL 落位颠倒**：win64 容器中 x64 → `system32`、x32 → `syswow64`
  （此前写反，DXVK/VKD3D 装上也不生效）

### 其他

- 下载进度会显示当前使用的镜像主机，例如「正在下载 DXVK（镜像 gh-proxy.org）」

## [0.1.2] - 2026-08-18

### 新增功能

- **注册表功能增强**
  - 新增"新建文件夹"按钮，可在当前选中项下新建子键
  - 新增"新建项(32位)"和"新建项(64位)"按钮，支持指定视图创建注册表项
  - 新增"删除选中项"按钮，支持删除注册表键（含子项）
  - 注册表加载改为**异步后台线程**，UI 不再卡死，加载时显示"注册表正在加载中..."
  - 切换到其他标签页时自动取消后台加载
- **新增"前往C盘"按钮**：点击后用系统文件管理器打开容器的 C 盘目录
- **directmusic 排除出"下载基础文件"默认列表**：避免因源不可用导致整体安装失败

### 界面优化

- **色彩系统重构**
  - 主色调改为深靛蓝 `#2D3748`，用于标题栏、主按钮
  - 强调色改为青绿 `#38B2AC`，用于操作按钮、进度条、标签高亮
  - 页面背景改为浅灰 `#F7FAFC`，卡片纯白 `#FFFFFF`
  - 主文字 `#2D3748`，次要文字 `#718096`，边框 `#E2E8F0`
- **概览区卡片化**：架构/版本/环境/大小/创建时间改为独立卡片，圆角 10px + 柔和投影 + 留白
- **按钮升级**：全部圆角 6px，主按钮青绿渐变，次要按钮 outlined 风格，删除按钮浅红 + hover 变红
- **组件表/DLL 覆盖表**：选中行改为白底 + 白边，去除黑底黑边
- **删除深色模式**：视图菜单仅保留"明色模式"
- **概览卡片尺寸拉大**（170×76 → 210×80）：文字完整显示不被截断

### 组件下载源更新

- **vcrun2019 / vcrun2022**：改为微软官方 aka.ms/vc14 永久链接（弃用 gitcode AIO 镜像包）
- **dotnet48**：改为微软官方 CDN 下载源（download.visualstudio.microsoft.com）
- **msxml6**：改为微软官方下载中心直链（KB2758696）
- **d3dx9 / d3dx11_43**：改为微软官方直链（弃用 holarse 403 源）
- **下载缓存目录迁移**：从只读的 `components_dir` 改为用户可写的 `cache_dir`（`~/.local/share/winbridge/cache`），修复 deb 包安装失败问题
- **微软官方域名 SSL 降级重试**：解决 CN CDN 节点证书链不完整导致的下载失败
- **预缓存软链接机制**：将内置字体/组件缓存软链接到用户缓存目录，避免重复下载

### 问题修复

- **修复 allfonts 安装闪退**：`download.py` 未 `import shutil` 导致 NameError
- **修复 system.reg 字体段损坏**：`re.sub` 字符串替换折叠反斜杠导致注册表段损坏
- **修复注册表重构引入的闪退**：`finished_note` 信号不存在 → 改用 Qt 自带 `finished` 信号
- **修复删除容器后复发**：`wineserver -w` 超时后 SIGKILL 兜底，防止 wineserver flush 重建目录
- **修复 msxml3 安装失败**：winetricks 缓存目录指向只读系统目录 → 改为用户可写目录
- **修复 msxml6 安装失败**：KB2758696 自解压 CAB 用 cabextract 提取 DLL（wine 静默安装会失败）
- **修复 stdbuf 报错**：win32 瓶子跳过 stdbuf（LD_PRELOAD 64 位库在 32 位进程报错），并过滤 libstdbuf 噪音行
- **修复下载卡住**：微软官方域名直接无验证连接，避免三次 60s 串行超时叠加
- **修复"下载基础文件"返回值解包缺失**：`install()` 返回 `(ok, error_log)` 元组未解包，导致失败被当成功
- **修复虚拟桌面残留**：删除 Ballance 排查时写入的虚拟桌面注册表残留
- **版本号统一修正**：界面版本号、User-Agent、`__init__.py` 统一为 0.1.2

### 其他

- 内置 35 个字体文件（calibri/cambria/candara/consolas/droid/sourcehansans 等）
- 集成 winetricks + metadata（离线字体枚举可用）
- 补全旧 deb 缺失的 `winbridge/` Python 模块

---

## [0.1.1] - 2026-07-30

- 初始 deb 包发布
