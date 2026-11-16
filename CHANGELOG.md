# 更新日志

## [1.3.4] - 2026-11-16

### 程序与容器

- **新建容器自带运行库与字体**：对话框新增「预装运行库与字体（VC++ 2022、
  Core/CJK 字体、.NET 4.8）」，默认勾选。当前 Wine 版本首次会构建一次
  **基础模板**（`~/.local/share/winebridge/templates/<架构>-<运行时>`，约
  10~20 分钟，状态栏有进度、可取消），之后新建容器直接复制模板——实测存/复制
  各 1 秒，复制出来的容器 `.NET 4.8` 校验正常
- **新增「复制容器」**：容器工具栏一键复制任意容器（含已安装组件与程序），
  不必为第二个容器再等一次组件安装；重名自动加 `__1`
- **新建容器改为后台线程 + 忙碌对话框**：`wineboot` 与字体注入要几十秒，之前
  界面全白不动像卡死；现在弹「正在创建容器…」并显示进度圈，完成后自动关闭
- **没有可用 Wine 时给出明确指引**：deb 里 Wine 只是 Recommends，全新机器可能
  完全没装。现在对话框直接提示「未检测到系统 Wine，也没有已下载的运行时」，
  点创建会弹「没有可用的 Wine」并提供「打开 Wine 版本管理」；不再悄悄回退到
  不存在的 `/usr/bin/wine` 后只报「创建失败，可能已存在」
- **.NET 4.8 安装进度带耗时**：每行日志前加 `[已用 m:ss]`，首行提示「预计 12
  分钟左右」，长时间静默安装不会再像卡住

## [1.3.3] - 2026-11-16

### 程序与容器

- **修复「模拟虚拟桌面」关不掉、开了也没效果**：Wine 的开关是
  `HKCU\Software\Wine\Explorer` → `Desktop = Default`，尺寸只是它下面的
  `Desktops\Default`；1.3.2 只写/删了尺寸，于是开启不生效、关闭清不掉已有的
  开关（Wine 继续按屏幕大小起桌面窗口，就是「关了窗口还是很大」）。现在按
  winecfg / Bottles 的写法同时写两个值、关闭时两个都删，界面状态也以开关为准
- **窗口开关改完提示重启容器**：桌面窗口属于当前会话，只重启程序不会变小；
  应用成功后会弹窗询问并可直接结束该容器会话（`wineserver -k`），下次启动即生效

## [1.3.2] - 2026-11-16

### 程序与容器

- **修复配置页「窗口」开关点应用必报失败**：写注册表用的 `reg add/delete`
  少了 `HKCU\` 前缀，Wine 直接回「无效的系统键」，两个开关都没写进容器；
  错误框里显示的还只是 `wineserver: using server-side synchronization.`、
  `lsteamclient disabled` 这类噪音。现在补上前缀，并且 `reg` 调用带
  `WINEDEBUG=-all`、错误只取 `reg:` 开头的那一行

## [1.3.1] - 2026-11-16

### 程序与容器

- **每个快捷方式可保存启动参数**：右键快捷方式 →「启动参数…」，参数按空格分隔
  （含空格的用引号括起）并写进 `bottle.json`，双击、桌面快捷方式（`--run`）
  都会自动带上。给只能靠命令行开关的程序（如 Electron 应用的
  `--disable-features=Windows10CustomTitlebar`）用，不必每次手输
- **配置页新增「窗口」开关**：可关闭「允许窗口管理器绘制标题栏」、可开启
  「模拟虚拟桌面」并填尺寸（默认当前屏幕可用区域）。这两项直接写容器的
  `HKCU\Software\Wine\X11 Driver` / `Explorer\Desktops`，用来绕过「自带标题栏
  的程序在 Wine 下点击位置偏上一个标题栏」的问题；改完重新启动程序生效

### 沙箱容器

- **修复沙箱容器里启动 Wine 自带工具会卡死**：flatpak 沙箱有独立的 `/tmp`，
  而 wineserver 的 socket 目录固定在 `/tmp/.wine-<uid>`，于是每次启动都会给同一个
  prefix 起**第二个 wineserver**，wine 自带 taskmgr 就在申请前缀锁时挂住
  （窗口标题变成「任务管理器 (没有响应)」、客户区全黑）。沙箱现在把
  `/tmp/.wine-<uid>` 单独挂进去（不挂整个 `/tmp`），同一 prefix 只保留一个
  wineserver，先后启动的沙箱会直接复用
- **移除任务管理器窗口里的「Wine 任务管理器」按钮**：它是上面卡死的直接触发点；
  WinBridge 自己的任务管理器（读宿主 `/proc` + wineserver 结束进程）在宿主和
  flatpak 沙箱容器上都能用，不需要再套一层 Wine 的

### 组件安装

- **修复 deb 版组件安装失败（源码版正常）**：安装版把组件目录解析到旧的
  `~/winbridge/components`，而那里的预置缓存叫 `winetricks-cache`，代码只认
  `winetricks/`，于是所有预置都被当成不存在，全部退化成联网下载，`msxml3`、
  `dotnet48` 这类大文件在慢网下就失败；`All Fonts` 更是直接报「缓存目录不存在」。
  现在两种目录名都认，并且选择组件目录时优先挑「真的有预置」的那个（空目录不再
  顶替有预置的目录），另外新增 `WINBRIDGE_COMPONENTS_DIR` 环境变量可手工指定
- 没有任何预置缓存时，安装进度会明确提示「本次将联网下载全部文件（较慢）」，
  而不是看起来像卡住

### 打包与 APT 源

- **把 Wine 从硬依赖改为推荐依赖**：deb 的 `Depends` 不再强制拉取
  `wine | wine64 | wine-stable`，改放到 `Recommends`，用户可以只装 WinBridge
  再在「Wine 版本管理」里下载运行时
- **新增 `packaging/build-apt-repo.sh`**：从 `debian/winbridge_*.deb` 生成可托管的
  静态 APT 仓库（`apt-repo/pool/main` + `dists/stable` 的 `Packages`、`Release`），
  支持用 `WINBRIDGE_GPG_KEY` 生成 `InRelease` / `Release.gpg` / `public.key`
- **APT 源改走 Gitee raw**：Gitee 仓库名是 `WinBidge`（页面标题为 WinBridge），
  源地址为 `https://gitee.com/zuimeideshijie/WinBidge/raw/apt-repo/`；README 先加入
  未签名的 `[trusted=yes]` 测试安装命令
- **新增 `packaging/install.sh` 一键安装脚本**：检查 Linux/apt/架构与网络，自动识别
  仓库是否提供 `public.key`（有则用 `signed-by`，否则用 `trusted=yes`），写源、
  只更新该源索引、安装/升级 winbridge，并回读 deb 版本与代码版本做验证；脚本随
  APT 仓库发布到 `install.sh`

## [1.3] - 2026-11-16

### Wine 版本管理

- **新增「Wine 版本管理」窗口**：工具菜单、新建容器和容器配置页都能打开，可下载
  **Wine 11**、**Soda 11**、**Proton 11**、**Wine-GE** 四种自包含运行时；下载走
  GitHub 镜像链，安装到 `~/.local/share/winbridge/runners/`，每个容器可单独选择
- **启动时自动检查已安装运行时的上游新版本**：有新版时弹窗列出「旧版本 → 新版本」，
  支持全部更新、进度与取消；没有更新时只在状态栏提示
- **新增删除 Wine 版本**：下载版只允许删 WinBridge 管理的运行时目录并清理压缩包缓存；
  有容器正在使用时先提示切换。系统 Wine 若由包管理器安装，会通过
  `pkexec apt-get remove` 卸载对应包，非包管理的便携树才走 `pkexec rm -rf`，
  并拒绝 `/usr`、`/etc`、`/var`、`/boot` 等系统目录
- **组件安装/卸载改用容器当前选择的 Wine**：`bottle.json` 的 `wine_path` 优先，
  缺失才回退系统 Wine；winetricks 的 `WINE`/`WINESERVER`、DLL 覆盖、字体注册和
  redist 安装都跟随该运行时，删除系统 Wine 后宿主模式的 runner 容器仍能装组件
- **便携运行时自动补 `LD_LIBRARY_PATH`**；发行版 Wine 不加，避免顶掉系统库
- `Soda 11` 实测可运行平衡球（D3D8）；`GE-Proton11` 在该游戏会报
  `No render driver found`，属于 Proton 内置 d3d8 的兼容差异

### 注册表

- **注册表浏览器补齐编辑能力**：新建值、编辑值、删除值，支持
  `REG_SZ / REG_EXPAND_SZ / REG_DWORD / REG_QWORD / REG_MULTI_SZ / REG_BINARY`；
  新增重命名项、导出 `.reg`、按项/值名查找，值表增加「类型」列，双击可编辑
- **修复新建/删除注册表项可能操作到错误键**：树内路径使用双反斜杠，传给 `wine reg`
  前统一转成单反斜杠
- 兼容 Wine 11 的 `str(N):` 值格式，同时保留旧版 `hex(N):` 解析

### 任务管理器

- **flatpak 沙箱容器也支持任务管理器**：按宿主 `/proc/<pid>/environ` 的 `WINEPREFIX`
  归属进程，并剔除 `bwrap`/`flatpak`/`bash` 等包装进程
- **修复刷新时选中的进程被取消选中**：刷新前记住 PID 与滚动位置，重建表格后恢复；
  只有进程真的退出才取消选中

### 快捷方式与文件选择

- **修复强制删除目录误报「没找到卸载程序」**：扩展应用目录识别到
  `AppData\Local\<App>`、`ProgramData\<App>`、`C:\<App>`、`steamapps\common\<Game>`
  等常见布局；共享目录仍拒绝删除，无法定位时改为明确提示
- **右键快捷方式新增「打开程序所在目录」**
- **文件选择改用系统原生文件对话框**，不再强制使用自绘 QFileDialog

### 组件与界面

- **打开应用时的组件检测只检查四项**：Core Fonts、CJK Fonts、All Fonts、
  .NET Framework 4.8，且只安装缺失项；flatpak 容器提示先切宿主安装，避免连续失败
- **Windows 版本显示改为 `win8.1`、`win2000`**：界面显示名与 `winecfg -v` 使用的
  `win81`、`win2k` 存储键分离，旧容器可正确回显
- README 的「安装wine」章节改为「安装 / 管理 Wine」，补充内置下载、切换、删除
  与启动更新检查说明

## [1.2.5] - 2026-11-15

### 快捷方式

- **右键新增「删除选中的快捷方式」**：只把这一条从列表移除，程序文件与容器数据都不动。
  删除的目标会记进 `bottle.json` 的 `hidden_shortcuts`，后续刷新/重扫不会把它加回来；
  用「添加程序」再次选中同一个 exe 时自动解除隐藏

## [1.2.4] - 2026-11-15

### 打包

- **deb 现在随包携带沙箱运行时的构建脚本**：新增 `/usr/bin/winbridge-sandbox-runtime`
  入口（等价于源码目录的 `packaging/build-sandbox-runtime.sh`）。1.2.3 只装了
  `winbridge/`，「未安装沙箱运行时」的提示指向的文件在安装版里并不存在
- 新建容器对话框与容器详情的提示、README 统一改为 `winbridge-sandbox-runtime`

## [1.2.3] - 2026-11-15

### 容器

- **新建容器可选择「运行环境」**：新增 flatpak 沙箱选项。沙箱容器仍保存在
  `~/.local/share/winbridge/bottles`、仍用系统 Wine，只是 Wine 进程跑在 flatpak
  运行时里，图形库（Mesa/glvnd/Vulkan）来自运行时而不是宿主。适合宿主驱动跑不起来
  的老游戏（D3D8 等），不必改系统 Mesa
- **修复「架构」与「运行环境」不能同时选择**：Qt 里同一父窗口的单选按钮会自动并成
  一组，选「flatpak 沙箱」会把架构一起取消勾选。现在两组各自用 `QButtonGroup` 隔离
- 容器详情工具栏新增运行环境下拉，随时在「宿主机 / flatpak 沙箱」之间切换
  （切换前会先停掉该容器的 wine 进程，避免两个 wineserver 抢同一个前缀）
- 沙箱容器内暂不支持安装组件：flatpak 运行时没有 cabextract/7z/winetricks 工具链，
  安装时会明确提示切回「宿主机」，装完再切回来
- 沙箱运行时用 `packaging/build-sandbox-runtime.sh` 构建并安装（`--uninstall` 可卸载）：
  它只是一个仅含 bash 的 flatpak 应用，不需要 SDK，也不随 deb 分发

### 程序启动

- **修复从快捷方式启动老程序时工作目录不对**：`Bottle.run()` 现在以程序所在目录作为
  工作目录。Virtools（平衡球）、部分安装器这类按相对路径找 `..\Managers`、`Textures\`
  的引擎，之前在 WinBridge 自己的目录下启动会直接报「初始化失败」

### 清理

- 删除仓库里过期的界面原型 `ui迎来大改动.html` 与升级介绍桌面项
  `WinBridge迎来全新升级.desktop`

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
