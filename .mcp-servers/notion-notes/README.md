# Notion Notes MCP Server

Notion 笔记的**能力中枢（大脑）**——唯一持有 Notion 访问能力（令牌/API/块构造）的 MCP 服务，任何支持 MCP 的 agent（Codex、Claude Code、Cursor、WorkBuddy、Cline 等）都通过它访问 Notion。

**架构分工（2026-11-23 标准化）**：本 MCP 是"大脑"，提供全部能力；`notion-course-notes` skill 是"手"，只承载流程判断与场景话术，**不含任何脚本、不自行访问 API**。两者职责不重叠，所有 Notion 读写必须经由此处。

## 它能做什么（10 个工具）

| 工具 | 用途 |
|---|---|
| `notion_search` | 搜索/列出 Notion 页面 |
| `notion_read_page` | 读取页面块结构（含折叠状态） |
| `notion_analyze_images` | 找出页面里缺文字注释的"裸图" |
| `notion_download_image` | 下载图片到本地供 agent 看图识别 |
| `notion_insert_caption` | 在指定图片前插入注释文字 |
| `notion_append_blocks` | 追加任意块（标题/代码/折叠标题等），用于知识库重建 |
| `notion_backup_page` | 改动前备份页面 |
| `notion_archive_page` | 把页面移入 Notion 回收站（可恢复） |
| `notion_restore_page` | 撤销归档，或按记录批量恢复 |
| `notion_get_style_guide` | 返回本目录权威注释/布局风格规则 |

**关键：令牌不用在客户端填。** server 会先从环境变量 `NOTION_TOKEN` 读，读不到自动回退到 Windows 用户注册表——已在 `HKCU\Environment` 设好，所以下面所有配置都**不需要写 key**。

## 通用调用流程（给 agent 的提示词参考）

```
1. notion_get_style_guide            → 了解注释/折叠风格规则
2. notion_search("前端")              → 定位页面，拿到 page_id
3. notion_analyze_images(page_id)     → 找出裸图（bare=true），拿到编号和 block_id
4. notion_download_image(url)         → 下载裸图，看图识别内容
5. notion_insert_caption(page_id, image_block_id, "知识点名")  → 逐张补注释
（改动前先 notion_backup_page(page_id) 留底）
```

纯文字笔记整理则跳过 3-5，用 `notion_read_page` 了解结构后，`notion_append_blocks` 重建。

## 各 agent 接入配置

**用 uv 现拉依赖启动**（2026-11-21 改造）：不依赖预装 Python 或固定解释器路径，只要有 `uv`（在 PATH 里）即可，`mcp` + `Pillow` 由 uv 运行时自动拉取。换机不用 `pip install`。

server.py 路径：`C:/Users/123456/.mcp-servers/notion-notes/server.py`

### WorkBuddy（~/.workbuddy/mcp.json）
```json
{
  "mcpServers": {
    "notion-notes": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--with", "mcp>=2", "--with", "Pillow", "python",
               "C:/Users/123456/.mcp-servers/notion-notes/server.py"]
    }
  }
}
```
WorkBuddy 需先在连接器管理里点"信任"，再新开会话。

### Codex（config.toml）
```toml
[mcp_servers.notion_notes]
command = "uv"
args = ["run", "--with", "mcp>=2", "--with", "Pillow", "python", "C:/Users/123456/.mcp-servers/notion-notes/server.py"]
```
用 `codex mcp list` 验证。

### Claude Code（.mcp.json，项目根或 ~/.claude.json）
```json
{
  "mcpServers": {
    "notion-notes": {
      "command": "uv",
      "args": ["run", "--with", "mcp>=2", "--with", "Pillow", "python",
               "C:/Users/123456/.mcp-servers/notion-notes/server.py"]
    }
  }
}
```

### Cursor / Cline / Windsurf（mcp.json）
同上 JSON 结构，可加 `"transport": "stdio"`。

> 如果某个 agent 的启动环境读不到注册表（少数情况），可在对应配置里加 `"env": {"NOTION_TOKEN": "你的token"}` 兜底。正常情况不需要——server 会自动从 Windows 用户注册表读。

## 风格配置

风格规则在 `STYLE.md`（本目录，**唯一权威来源**）。改注释风格只动这个文件，全局生效；`notion_get_style_guide` 只读这里。skill 侧不存放风格文件，避免两处不一致。

## 迁移到别的电脑

整个 `C:/Users/123456/.mcp-servers/notion-notes/` 目录拷过去，装好 `uv`（配置里用它现拉依赖，无需预装 Python 库），设置用户级 `NOTION_TOKEN`，再按上面格式加配置即可。与 WorkBuddy Skill 完全解耦，不依赖它。

## 运维

- 依赖：`uv`（`uv run --with mcp --with Pillow` 自动拉取，无需预装）
- 令牌：环境变量 `NOTION_TOKEN` > Windows 用户注册表回退
- 传输：stdio（所有 MCP 客户端通用）
- 临时文件：`%TEMP%/mcp_notion_imgs/`（下载的图片）、`%TEMP%/notion_backup_*.json`（备份）
- 2026-11-20 端到端测试通过：8 工具注册、search/analyze/read/style 实测成功、注册表 token 回退验证通过
- 2026-11-21 移植性改造：改用 uv 现拉依赖，去掉硬编码 Python 路径，实测通过
- 2026-11-23 标准化改造：新增 archive/restore 工具（共 10 个）；STYLE.md 成为大脑侧唯一权威源；skill 重写为纯流程手册，删除其 7 个重复脚本，职责不再重叠。备份：`~/.notion-refactor-backup-20261123-095418/`
