# 磁盘清理分类规则

## 一、三档分级标准

产出清单时必须把每一项归入以下三档，不允许只给一个笼统列表。

| 档位 | 判定标准 | 典型内容 |
|---|---|---|
| **A 档 · 放心删** | 软件已安装完成后的安装包、更新包、临时文件、缓存。删掉后任何程序都能正常运行，需要时会自动重建 | `*Setup*.exe`、`*update*.exe`、`Temp\`、浏览器 Cache、`update_data\`、`.crdownload` 残片 |
| **B 档 · 需确认** | 属于某个软件的个人数据或程序本体，删不删取决于用户是否还在用 | 游戏客户端、聊天软件数据、办公软件备份、云盘缓存 |
| **C 档 · 禁止手动删** | 由 Windows 自身管理的组件，手动删除会导致系统无法更新或程序损坏 | WinSxS、Containers、MRT.exe、swapfile.sys、Edge 旧版本目录 |

## 二、A 档常见位置（可直接列入）

- `%LOCALAPPDATA%\Temp`（含各类 `*-update-*` 子目录）
- `%LOCALAPPDATA%\@*-updater\`（各软件的自更新残留）
- `C:\ProgramData\NVIDIA Corporation\Downloader\`（显卡驱动安装包，常达 500 MB）
- `C:\ProgramData\Thunder Network\XLLiveUD\Download\`（迅雷更新包）
- `C:\QMDownload\SoftMgr\`（腾讯电脑管家下载的软件安装包）
- `C:\Windows\SoftwareDistribution\Download`（Windows 更新缓存，需管理员权限）
- `C:\Windows.old`（升级 Windows 后遗留，可达 20 GB，需管理员权限）
- 各软件 `User Data\update_data\` 目录（豆包、Edge 等 Electron 应用常见）
- 浏览器 `Default\Cache`、`Code Cache`、`GPUCache`
- `%LOCALAPPDATA%\Microsoft\Windows\Explorer\thumbcache_*.db`
- `*.crdownload` / `*.part` / `*.opdownload`（未完成的下载残片）
- `%LOCALAPPDATA%\CrashDumps`、`.dmp` 文件

## 三、C 档 · 禁止手动删除清单

| 路径 / 文件 | 原因 | 正确做法 |
|---|---|---|
| `C:\Windows\WinSxS` | 硬链接目录，看似巨大实为共享副本，手删会导致系统更新失败 | `DISM /Online /Cleanup-Image /StartComponentCleanup` |
| `C:\Windows\Containers\*.wim` | 系统组件镜像 | 同上 |
| `C:\Windows\System32\MRT.exe` | 恶意软件清除工具，随系统更新替换 | 不要动 |
| `C:\swapfile.sys`、`pagefile.sys`、`hiberfil.sys` | 系统交换/休眠文件 | 在系统设置里调整，不要删文件 |
| Edge 旧版本目录 `EdgeCore\<旧版本>\` | 由浏览器自身更新机制清理 | 等待自动清理或重装 |
| `C:\Windows\Installer` | MSI 安装包缓存，删了会导致软件无法卸载或修复 | 保留 |
| 任何 `desktop.ini` | 文件夹个性化配置，删了会丢失文件夹设置 | 保留 |

## 四、B 档 · 按软件给出建议（不要直接删整个目录）

| 软件 | 数据位置 | 建议 |
|---|---|---|
| 微信 / QQ | `AppData\Roaming\Tencent` | **绝不能直接删**，含聊天记录。在微信「设置 → 存储空间」里清理缓存，或迁移到其他盘 |
| WPS | `AppData\Roaming\kingsoft` | 在 WPS 内清理备份，或删除 `backup` 子目录 |
| 豆包 / 各类 Electron 应用 | `AppData\Local\<应用名>` | 只删 `update_data`、`Cache`、`Code Cache`、`logs`，程序本体删了就得重装 |
| Epic 启动器 | `AppData\Local\EpicGamesLauncher\Saved` | 只删 `Saved`（日志与网页缓存），`Saved\Config` 含启动器设置；游戏本体不在此目录 |
| 虎牙 / YY / 多玩 | `AppData\Roaming\HuyaPCLive`、`AppData\Roaming\duowan` | 若软件已卸载则整删；若还在用，只删 `Log`、`HuyaUpdate` 子目录 |
| PUBG | `AppData\Local\TslGame\Saved` | 含回放与键位设置，删除会丢失，需提前告知用户 |
| Riot 游戏 | `C:\Riot Games` | 先查是否有 Vanguard 驱动（`Get-Service vgk,vgc`）。有驱动时应走卸载程序，直接删文件夹会留下失效的内核服务 |
| Steam / 游戏库 | `SteamLibrary`、`steamapps` | 用 Steam 自带的卸载，不要手动删 |

## 五、删除执行的硬性流程

1. **列出完整路径**：删除前必须逐项列出路径与大小，不允许只说"这五个目录"
2. **加粗警示**：明确告知不可逆风险
3. **取得明确确认**：用户必须明确同意，不能靠默认推断
4. **执行后逐项复核**：用 `Test-Path` 确认每个目标真的没了
5. **清空回收站**：`Clear-RecycleBin -DriveLetter C -Force`，否则空间不会释放
6. **写执行记录**：记录时间、路径、删除前大小、是否可恢复

## 六、环境与工具陷阱（实战验证，务必遵守）

- **扫描耗时**：全盘扫描约 5~6 分钟，必须后台运行，不能前台干等
- **权限不足**：默认非管理员，`C:\Windows\Temp`、`Prefetch`、`$Recycle.Bin` 会返回 0 或拒绝访问。这不是真的空，需要在报告中如实说明"数据可能偏低"
- **safe-delete 钩子误报**：`Remove-Item` 常返回 `SAFE_DELETE_FAIL_CLOSED / trash-failed` 错误，但**目标实际已被删除**。看到该报错不要重复删除，先用 `Test-Path` 复核
- **删完不释放空间**：删除的内容先进回收站，磁盘剩余空间不变，必须清空回收站
- **`Add-Type` 被禁止**：安全策略禁止运行时编译 .NET，不能用 `Microsoft.VisualBasic.FileSystem` 的 SendToRecycleBin
- **中文输出乱码**：PowerShell 输出经终端捕获后中文常变成乱码，脚本一律用英文标签输出，由模型翻译成中文写进报告
- **编码差异**：`Get-PSDrive` 与 `Get-WmiObject Win32_LogicalDisk` 报告的剩余空间可能不一致，前后对比时用同一个来源

## 七、只读承诺

当用户说"先出清单不动文件"时，整个扫描阶段严禁任何 `Remove-Item`、`Move-Item`、`Clear-RecycleBin` 调用。
只允许 `Get-ChildItem`、`Measure-Object`、`Test-Path`、`Get-WmiObject`。
