# 更新日志

## [1.2.2] - 2026-11-14

### 注册表

- **点「注册表」标签改为打开独立窗口**：弹出 WinBridge 自己的注册表浏览器
  （1080×720、可缩放、可同时与主窗口并排看），主窗口自动切回原来的标签页，
  注册表解析仍在后台线程进行，主界面不再被大文件的解析占住
- **修复打开注册表窗口后整个应用卡死**：原来把 1.7 万个键在 UI 线程一次性建成
  `QTreeWidgetItem`，且每个节点用兄弟节点线性查找（O(n²)）。现在后台只解析路径，
  按层级建立一次索引，树节点在**展开时才创建**；打开耗时约 0.7 秒，展开任意一层
  都是瞬时的（实测 17.5k 键）
- 切换容器时旧窗口会自动关闭并清空，避免看到上一个容器的键

### 快捷方式

- **新增「添加程序」按钮**：位于「快捷方式」卡片右下角，挑选任意 `.exe` 后加入列表，
  自动取文件名作显示名、提取图标并持久化到 `bottle.json`；同一目标重复添加会被拒绝
- **卸载改为运行应用自带的卸载程序**：优先在应用目录找 `unins000.exe` /
  `uninstall.exe` / `*uninst*.exe`，其次读注册表 `Uninstall` 项的
  `UninstallString`（微软安装包会转成 `msiexec /X{...}`）；只接受位于该应用自己
  目录下的卸载器，绝不会启动系统卸载程序。找不到时退回原来的删除目录流程
- **新增「刷新」按钮**：重新扫描容器里的程序与快捷方式，并把缺失的图标补回来
  （在容器里装完新程序后不用重启 WinBridge）；扫到「程序已不存在」的条目会弹窗
  列出并询问是否删除，选「是」即从 `bottle.json` 移除（这类失效 `.lnk` 不会被
  重新识别——发现逻辑只认实际存在的文件）
- **双击失效条目不再只弹提示**：程序文件不存在时直接问「是否删除这个快捷方式」，
  选「是」就移除记录并刷新列表；删目录卸载时也会顺带清掉该应用目录下的**所有**
  条目（更新器、卸载器、翻译小工具等），不再留下一排「程序文件不存在」
- 右键菜单保留「强制删除目录…」作为兜底（清理卸载程序留下的残留）

### 下载

- **多线程分片下载**：大于 4MB 的组件包按 HTTP Range 拆成最多 8 段并发下载，
  进度条显示的是汇总速度与剩余时间；服务器/镜像不支持分段时自动回退单连接，
  分段失败也会回退，不会把安装卡死
- **源策略不变但更快**：GitHub 资源继续走镜像前缀链并记住上次可用的镜像，微软
  官方源直连（TLS 链不完整时按既有规则跳过校验）；已缓存且校验通过的包不再重复
  下载
- **winetricks 的大文件改由 WinBridge 先下**：`.NET 4.8` 依赖 dotnet40 与 ndp48
  两个约 123MB 的官方包，之前由 winetricks 用单连接 curl 拉取且当场才校验。现在
  先按官方 URL 用分片下载器下好、校验 sha256 后放进 winetricks 缓存目录，
  winetricks 直接复用

### 问题修复

- **修复 `.NET Framework 4.8` 安装崩溃 `0xe06d7363`（真正的根因）**：容器的
  `syswow64` 里没有 32 位 `msxml3.dll`，而 .NET 4.x 的安装器是 32 位程序，加载
  MSXML3 失败后抛 `0x80040154`（REGDB_E_CLASSNOTREG）→ 自解压阶段崩溃。补上
  32 位 `msxml3.dll`/`msxml3r.dll` 后同一前缀 dotnet40 立刻 `rc=0`
- **预置 MSI/CAB 完整性校验**：`components/winetricks/msxml3/msxml3.msi` 是截断
  文件（651KB，官方 1,070,592 字节），而 `WINETRICKS_FORCE=1` 会跳过 winetricks
  的 sha256 校验，导致 `msiexec` "安装成功"却什么都没装。现在交给 winetricks
  之前先用 `cabextract -t` 校验 MSI/CAB，无效的预置文件直接丢弃并重新下载
- **MSXML 3.0 改为直接从 msi 提取 DLL**：Wine 11 的 `msiexec` 对 2005 年的
  `msxml3.msi` 返回 84（读取 summary information 失败），winetricks 因此判定
  失败并跳过 64 位步骤。现在装完直接从缓存的 msi 中提取
  `msxml3.dll`/`msxml3r.dll`（按 PE 头判架构）落到 `syswow64`，以此判定成功
- **安装失败/取消后也恢复容器 Windows 版本**：`dotnet48` 依赖的 winetricks verb
  会把容器切到 `winxp`/`win7`，之前只在安装成功时恢复，失败后容器被永久留在
  旧版本（会连带影响其它程序）；现在放在 `finally` 里无条件恢复

### 取消

- **组件页新增「取消」按钮**：安装/下载过程中出现，点击后下载按 64KB 粒度中断
  （未完成的 `.part`/`.seg` 文件会清理），winetricks 进程直接终止；容器不做任何
  改动，弹窗提示「已取消」而不是安装失败
- **「下载基础组件」也可取消**：状态栏出现取消按钮，按组件边界停止，已完成的部分
  保留记录

### 组件卸载

- **卸载真正回滚组件**（参考 Bottles 的 `DLLComponent` 做法）：安装时把落位的
  DLL（相对 `drive_c/windows` 的路径）与写入的覆盖记录到 `bottle.json`；卸载时
  优先恢复 `<dll>.bck` 备份，没有备份则删除 DLL 让 Wine 回到内置实现，并通过
  `"dll"=-` 一次性删除 `HKCU\Software\Wine\DllOverrides` 里对应的值——此前「卸载」
  只从 `installed_components` 里删掉一条记录，DLL 和覆盖全部留在容器里，DXVK/
  VKD3D 卸载后其实还在生效
- **安装前备份被覆盖的 DLL**：`<dll>.bck` 保存原文件（只在该文件已存在且尚无备份时
  创建），重复安装不会覆盖第一次的备份
- **原子写入**：先写同目录临时文件再 `os.replace`，复制失败不会留下截断的 DLL
- **共用覆盖保护**：多个组件都声明同一个 DLL 覆盖时（如后续新增的组件），卸载其中
  一个不会删掉另一个仍在使用的覆盖
- **卸载说明更诚实**：winetricks / 微软 MSI 安装的组件没有文件记录，确认框会写明
  「只移除记录和覆盖，容器内已装文件需自行处理」，卸载在后台线程执行，不再卡界面
- 组件页的卸载按钮不再静默「假成功」，文件或覆盖回滚失败会弹出详细日志

### 问题修复

- **修复微软安装器崩溃 `0xe06d7363`**：容器里存在应用级 DLL 覆盖
  （`*msxml3=native`、`*gdiplus=native` 等，通常由字体/运行库组件写入）时，
  .NET 4.0 安装器会带着这些原生 DLL 启动并以 C++ 异常崩溃。实测同一前缀：
  无覆盖 → 17 秒装完 `rc=0`；有覆盖 → `rc=99` 且崩溃。现在安装器运行期间会临时
  挂起 `*` 开头的覆盖，结束后原样恢复（`_suspend_app_overrides` /
  `_restore_dll_overrides`）
- **修复安装/注册表操作随机抛 `UnicodeDecodeError`**：`subprocess(... text=True)`
  默认按 UTF-8 解码，Wine/安装器输出里一旦出现 GBK 字节（中文环境常见）就会抛
  异常，注册表写入、VC++ 安装等都可能中招；现在统一 `encoding="utf-8",
  errors="replace"`
- **组件「装完不生效」**：原生 DLL 复制进容器却缺配套的 DLL 覆盖时，Wine 仍会
  加载内置版本——界面显示成功但功能毫无变化。现在每条安装路径都会写入
  `HKCU\Software\Wine\DllOverrides` 并**读回校验**（失败重试一次，仍失败即报错），
  覆盖同时同步到容器的「DLL 覆盖」页
- **VKD3D / DXVK 的 32 位 DLL 从未安装**：vkd3d-proton 的预编译包用 `x86/`
  而非 `x32/`，旧代码只找 `x32/`，32 位程序一直拿不到 `d3d12*.dll`
- **DirectX 9/11 的 64 位 DLL 从未安装**：DirectX redist 的 cab 名为
  `*_x86.cab` / `*_x64.cab`，旧代码按 `amd64` 匹配导致 64 位 `d3dx*` 全部落空；
  现在逐个 DLL 校验，缺失即报错而不是假装成功
- **MSXML 6 没写 DLL 覆盖**：原生 `msxml6.dll`/`msxml6r.dll` 已复制但覆盖缺失，
  Wine 继续使用内置实现；32/64 位改由 PE 头判定，不再依赖 GUID 猜测
- **VC++ 运行时**：装完补写 vcruntime 系列的 `native,builtin` 覆盖，并在安装器
  跳过 `msvcp140`（Wine 内置版本号更高，wine bug 57518）时按安装包补齐；
  `3010`（需要重启）等退出码不再误报失败
- **.NET Framework 4.8 改走 winetricks**：直接 `/quiet` 跑 ndp48 只会留下一个
  装不完整的运行时；winetricks 的 `dotnet48` 会先移除 mono、安装 dotnet40 前置、
  切到 win7 并以 `fusion=b` 启动安装器，装完恢复容器原本的 Windows 版本
- **FAudio 只装一个 dll**：按上游 `wine_setup_faudio.sh` 安装 `x64/` 下所有
  dll（`xaudio2_7`、`xactengine3_7`…）并逐个覆盖——只放 `FAudio.dll` 不会被任何
  内置 xaudio2 使用。20.07 只有 64 位构建，32 位程序会在结果里明确提示
- **重复下载**：VC++ / DXVK / VKD3D / FAudio 已缓存且校验通过的安装包不再重新下载
- 删除已无组件使用的 GitCode 源码克隆 / `.exe` 安装死代码（该路径会因缺少
  `repo` 字段直接抛 `KeyError`）

### 测试

- 新增 `tests/test_component_install.py`：PE 架构识别、包内目录布局、DLL 放置
  目录、cab 成员名归一化与组件配置校验（19 项，无需 Wine）

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
