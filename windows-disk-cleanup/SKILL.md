---
name: windows-disk-cleanup
version: 1.0.0
display_name: C 盘清理 · 三档分级
display_name_en: Disk Cleanup · Tiered Risk Scan
description: Scan a Windows drive (typically C:) for deletable files and produce a risk-tiered cleanup report. This skill should be used when the user says the disk is full, asks what files can be deleted, wants to free up space, or asks for a cleanup plan with a "list only, do not touch files" constraint. Triggers include 清理C盘、磁盘空间不足、哪些文件能删、扫描磁盘占用、先出清单不动文件. Covers read-only scanning, A/B/C risk tiering, and safe deletion execution.
description_zh: 扫描 Windows 磁盘（通常是 C 盘）找出可删除文件，按 A/B/C 三档风险分级产出清理清单。适用于磁盘空间不足、想知道哪些文件能删、或要求“先出清单不动文件”的场景。覆盖只读扫描、风险分级与安全删除执行。
description_en: Scan a Windows drive (typically C:) for deletable files and produce a risk-tiered cleanup report. Use this skill when the disk is running out of space, the user asks which files can be deleted, or asks for a list-only scan that must not touch any file. It covers read-only scanning, three-tier risk classification (safe to delete / needs confirmation / never delete manually), and deletion that only runs after explicit user confirmation.
agent_created: true
---

# Windows 磁盘清理

## 用途

把"磁盘满了、帮我看看能删什么"这类需求，变成一个可重复、有安全边界的流程：先只读扫描全盘，产出按风险分三档的清理清单，等用户逐项确认后再执行删除，并完整记录。

## 核心原则

**扫描阶段严格只读。** 只要用户说了"先出清单不动文件""先看看""不动我的文件"，就只允许读操作，禁止调用 `Remove-Item`、`Move-Item`、`Clear-RecycleBin` 中的任何一个。

**删除阶段必须先列路径、先警示、先确认。** 不允许只说"这五个目录"，必须逐项列出完整路径和大小。

## 工作流程

### 第一步：确认范围

确认三件事，缺哪个问哪个：

1. 盘符（默认 C:）
2. 是否只读出清单（用户没明说时，默认只读）
3. 是否指定了特定目录

用户只说"帮我清理 C 盘"时，默认按只读出清单处理，不要直接动手删。

### 第二步：执行扫描

运行扫描脚本，**必须后台运行**（全盘扫描约 5~6 分钟）：

```bash
powershell -ExecutionPolicy Bypass -File ~/.workbuddy/skills/windows-disk-cleanup/scripts/scan_disk.ps1 -Drive C: -Deep
```

脚本为纯 ASCII 输出，标签含义：`DISK` 磁盘概况、`JUNK` 已知垃圾点、`DIRSIZE` 根目录、`USERSIZE` 用户目录、`BIG` 大文件、`LOCALAPP`/`ROAMING`/`TEMP` 细项。

`denied=True` 或大小为 0 表示**权限不足读不到**，不是真的为空，必须在报告中如实说明数据可能偏低。

后台运行后用 TaskOutput 等待结果，不要在循环里反复轮询。

### 第三步：分级与判定

按 `references/cleanup-rules.md` 把每一项归入三档：

- **A 档**：安装包、更新包、临时文件、缓存 —— 放心删
- **B 档**：软件数据或程序本体 —— 取决于用户还用不用
- **C 档**：系统组件 —— 禁止手动删，改用 DISM 或系统磁盘清理

读 `references/cleanup-rules.md` 获取具体的可删位置清单、禁止删除清单，以及微信、WPS、豆包、Epic、虎牙、Riot 等常见软件的处理建议。**该文件包含实战验证过的陷阱，执行删除前必读。**

### 第四步：出报告

用 `assets/report_template.md` 作为骨架生成 Markdown 报告，写入工作空间并展示给用户。

报告必须包含：磁盘现状、空间分布、三档清单、建议执行顺序、风险提示。

条件允许时，用可视化展示各目录占用比例，比纯表格更直观。

### 第五步：删除执行（仅在用户确认后）

按以下顺序执行，一步都不能少：

1. 列出每一项完整路径与大小
2. 加粗警示不可逆风险
3. 取得用户明确确认
4. 执行 `Remove-Item -LiteralPath <path> -Recurse -Force`
5. **逐项 `Test-Path` 复核**——系统常返回 `SAFE_DELETE_FAIL_CLOSED` 误报，看到报错不要重复删除，先复查
6. `Clear-RecycleBin -DriveLetter C -Force` 清空回收站，否则空间不会释放
7. 再次测量剩余空间，与删除前对比（用同一个数据来源，避免口径不一致）
8. 追加执行记录：时间、路径、删除前大小、是否可恢复

**已安装的软件优先走卸载程序**，直接删文件夹会留下失效的服务和注册表项。删除前检查是否有残留服务：

```powershell
Get-Service | Where-Object { $_.Name -match 'vgk|vgc|Riot' }
```

## 关键陷阱

| 陷阱 | 表现 | 正确做法 |
|---|---|---|
| safe-delete 钩子误报 | `Remove-Item` 报 `SAFE_DELETE_FAIL_CLOSED / trash-failed` | 用 `Test-Path` 复核，通常实际已删除 |
| 删完空间不变 | 剩余空间纹丝不动 | 内容在回收站里，需 `Clear-RecycleBin` |
| 权限不足 | 系统目录显示 0 MB | 不是真空，报告中说明数据偏低 |
| `Add-Type` 被禁止 | 无法用 VisualBasic 的回收站 API | 改用 `Remove-Item` + `Clear-RecycleBin` |
| 中文输出乱码 | 终端捕获后变成乱码 | 脚本用英文标签，由模型翻译成中文 |
| 扫描太久 | 前台超时 | 后台运行，用 TaskOutput 等待 |

## 参考资源

- `scripts/scan_disk.ps1` —— 只读扫描脚本，支持 `-Drive`、`-BigFileMB`、`-Deep`
- `references/cleanup-rules.md` —— 分级标准、可删清单、禁删清单、常见软件处理建议
- `assets/report_template.md` —— 报告模板
