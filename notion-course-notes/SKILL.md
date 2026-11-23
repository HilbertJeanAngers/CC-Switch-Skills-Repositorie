---
name: notion-course-notes
description: 整理和维护 Notion 笔记，覆盖三类场景：(1) 网课图片批量补文字注释——找出没配文字的截图，识别内容后按风格在每张图前插注释；(2) 把从 AI 复制来的零散知识点补齐、结构化到 Notion 页面；(3) 对已有笔记做布局整理——一级标题一律做成可折叠标题，二级/三级标题按长度适当折叠，防止页面太长影响观看。也用于分析页面图片结构、备份与恢复页面。触发词：Notion 笔记加注释、给图片补文字、网课图片加注释、整理网课笔记、notion 图片注释、把这段知识补到 Notion、补齐笔记、笔记太乱整理一下、Notion 笔记布局、知识点折叠。
agent_created: true
---

# Notion Course Notes

## 架构约定：大脑与手（必读，不要越界）

- **`notion-notes` MCP = 大脑**：唯一持有 Notion 访问能力（令牌、API、块构造）。**所有 Notion 读写必须调用 MCP 工具**；不要自己写脚本、不要用 curl 直连 Notion API，不要在本目录重建脚本。
- **本 skill = 手**：只负责判断用户意图、选工作流、定执行顺序、决定内容写法。不实现任何 API 访问。
- **风格唯一来源**：MCP 的 `notion_get_style_guide` 返回的 `STYLE.md`。本目录不存放风格文件，不要凭记忆猜规则。

**前置条件**：`notion-notes` MCP 已连接（能调用 `notion_search`）。若当前会话搜不到这些工具，提示用户在 WorkBuddy 设置里信任/启用该 MCP 并重启会话——**不要退化成脚本方案**。

## MCP 工具速查（大脑提供的能力）

| 工具 | 用途 | 何时用 |
|---|---|---|
| `notion_search(query, limit)` | 定位目标页面 | 用户只给了页面名关键词时 |
| `notion_read_page(page_ref, max_blocks)` | 读块结构（含层级、折叠标记） | 补知识/整理布局前了解现状 |
| `notion_analyze_images(page_ref)` | 找出缺文字的裸图，返回编号+block_id+section | 图片补注释入口 |
| `notion_download_image(url, name)` | 下载图片到本地（附放大版）供看图识别 | 识别图中知识点时 |
| `notion_insert_caption(page_ref, image_block_id, text, block_type)` | 在图前插注释，内置防重复 | 逐张补注释 |
| `notion_append_blocks(page_ref, blocks)` | 追加任意块（每个 ≤100 项） | 只用于新增内容，**不用于整理** |
| `notion_delete_blocks(ids, dry_run)` | 原地归档块，可批量 | 删除旧块（可 `notion_restore_blocks` 撤销） |
| `notion_update_block(id, patch)` | 原地改块文字/折叠状态 | 把标题设为可折叠等 |
| `notion_nest_blocks(heading_id, ids)` | 把块复制进折叠标题并删原块 | 原地折叠嵌套（先复制后删，失败回滚） |
| `notion_move_blocks(ids, after_id)` | 原地重排块顺序 | 重排（先复制后删） |
| `notion_backup_page(page_ref, output_path)` | 备份页面完整 JSON | **任何改动前必做** |
| `notion_archive_page(page_ids, remember)` | 移入 Notion 回收站（可恢复） | 暂时移出视线 |
| `notion_restore_page(page_ids, from_archive_log)` | 撤销归档 | 恢复被归档页面 |
| `notion_get_style_guide()` | 取权威风格与折叠规则 | 补注释/整理前必调 |

`page_ref` 可传页面标题关键词或页面 ID；多个匹配时 MCP 会返回候选，让用户选或改用 ID。

## 三条核心工作流（按用户意图选）

| 用户说的话 | 走哪条 |
|---|---|
| "给 XX 笔记的图片补注释 / 网课图片加注释" | **A. 图片补注释** |
| "把这段知识补到 Notion / 补齐 XX 笔记" | **B. AI 知识补齐** |
| "XX 笔记太乱 / 整理布局 / 知识点折叠" | **C. 布局整理** |

> 三条都可能组合出现。**无论哪条：先备份、先取风格、改完复验，三条铁律不变。**

### 工作流 A：图片补注释

1. **确认范围**：目标页面 + 补全部裸图还是只补指定的几张（用户说"整理 XX"通常已给页面名）。
2. **备份**：`notion_backup_page(page_ref)` → 记下返回的 `path`，最后告诉用户。
3. **找裸图**：`notion_analyze_images(page_ref)` → 记下每张图的 `n`（编号）、`image_block_id`、`bare`、`section`。`bare=true` 即缺注释。
4. **识别内容**：对要补的图，`notion_download_image(url, name)` 拿到本地路径 → 用看图工具查看 → 记下"编号 → 知识点短语"。短语照图中标题/核心概念命名，简短不加句号；字看不清就看返回的 `large_path` 放大图。
5. **确认风格**：`notion_get_style_guide()` → 按其中的块类型/前缀/后缀写注释。用户本次有特殊要求可临时覆盖，不改配置。
6. **逐张插入**：`notion_insert_caption(page_ref, image_block_id, text, block_type)`。图前已有相同文字会自动跳过；遇到 `unsupported` 块保持原样。
7. **复验收尾**：再跑一次 `notion_analyze_images` 确认裸图已消除、注释顺序正确；告知用户备份路径和恢复方法。

### 工作流 B：AI 知识补齐

1. **备份**：`notion_backup_page`。
2. **读现状**：`notion_read_page` 判断是"待展开的零散知识"还是"已成型笔记"。
3. **取风格**：`notion_get_style_guide` → 尤其注意折叠规则。
4. **组织内容**：按 简介 / 安装或准备 / 核心概念速查 / 少量精选示例 / 学习路线 补齐（按领域裁剪，不必凑齐）。**补充适度**：示例 1~2 段够说明问题即可，不要为每个小点堆一大段代码。
5. **写入**：`notion_append_blocks(page_ref, blocks)`，`blocks` 是 JSON 数组字符串，每项如 `{"type":"h1","text":"一、简介","toggleable":true}`。支持 `text/paragraph`、`h1/h2/h3`、`code`、`quote`、`bullet`、`number`、`callout`、`divider`、`toggle`。**一次最多 100 块**，超量分批追加。
6. **复验收尾**：`notion_read_page` 确认结构与折叠标记；告知备份路径。

### 工作流 C：已有笔记布局整理（原地整理）

**铁律：在哪一页就在哪一页改，绝不跨页搬运。** 子页面（child_page）的内容属于子页，必须在子页内整理；不要提取到父页做"整理版导航/摘要"——用户明确否决过这种做法。父页只整理父页自己的块。

1. **备份**：`notion_backup_page`；子页面是 child_page 块、不是独立 page，`/pages/{id}` 会 404，需用块遍历自行存 JSON。
2. **读完整结构**：`notion_read_page(page_ref, max_blocks)` 设大一些，注意递归进 `has_children`（表格、已有折叠标题都有子块）。
3. **取风格**：`notion_get_style_guide` → 折叠规则以此为准。
4. **原地折叠 + 嵌套**（大脑已支持，见下方工具）：
   - `notion_update_block(block_id, '{"heading_1":{"is_toggleable":true}}')` 把标题设为可折叠。
   - `notion_nest_blocks(heading_id, "子块ID,子块ID,...")` 把该章节内容块**复制进标题 children 并校验成功后自动删除原块**（先复制后删，永不先删；失败自动回滚副本）。一次调用处理一个章节（标题到下一同级标题之间的块）。
   - 遍历页面顶层所有同级标题，逐章处理即可完成原地整理。二/三级短标题不要为了折叠而折叠。
5. **删/重排旧块**：`notion_delete_blocks(ids, dry_run)` 原地归档（可 `notion_restore_blocks` 撤销）；`notion_move_blocks(ids, after_id)` 原地重排（同样先复制后删）。
6. **复验收尾（必做）**：遍历页面所有块统计总数，与备份对比，**必须完全相等**才算无丢失；再读顶层确认折叠标记。告知备份路径。

> 注意：`notion_append_blocks` 仍是"追加"工具，只用于新增内容，**不要用它做布局整理**。整理一律走 update/nest/delete/move 原地工具。
> `child_page` 类块不可复制嵌套，遇到时跳过、保持原样。

## 折叠规则（判断依据，细节以 MCP 的 STYLE.md 为准）

- **一级标题（heading_1）必须折叠**：`is_toggleable: true`，内容放 `children`，不管长短。
- **二级/三级标题按长度适当处理**：内容长（多段/多代码/多图）做可折叠；短的直接平铺，不为折叠而折叠。
- **折叠标题只写知识点名**，禁止"（点击展开）""（点开查看）"这类后缀。

## 风格修改与临时覆盖

- 用户说"以后注释风格改成 XXX"→ 编辑 **MCP 目录下的 `STYLE.md`**（`notion_get_style_guide` 返回的 `source` 路径），一次修改全局生效；**不要改本 skill 目录**。
- 用户说"这次用 XX 风格"→ 仅本次调用时覆盖，不改文件。

## 恢复与安全约定

- **撤销归档**：`notion_restore_page(from_archive_log=true)`，或传逗号分隔的页面 ID。
- **内容有损回滚**：用 `notion_backup_page` 产出的 JSON 对照，通过 `notion_append_blocks` 手工重建。
- 令牌由 MCP 统一管理，本 skill 不接触、不落盘。
- 改动前必备份；临时图片由大脑下载到系统临时目录，用完可清理。
- 归档优先于永久删除；不擅自永久删页面。

## 详细参考

- 风格与折叠规则：`notion_get_style_guide()`（唯一权威源，MCP 目录 `STYLE.md`）
- Notion API 要点与踩坑：由 MCP 内部处理；出现异常时看工具返回的错误信息，不要自行绕过 MCP。
