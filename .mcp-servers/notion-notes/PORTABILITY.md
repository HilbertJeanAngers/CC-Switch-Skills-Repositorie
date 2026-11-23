# MCP 配置移植性改造说明（2026-11-21）

## 改了什么

把 4 个 mysql MCP 从"硬编码失效路径 + 明文密钥"改造成"npx 现拉包 + 环境变量引用"，功能完全不变。

| 项目 | 改造前 | 改造后 |
|---|---|---|
| 启动命令 | `cmd /c node C:\nvm4w\nodejs\node_modules\@pickstar-2002\mysql-mcp\dist\index.js`（路径已失效→红点） | `npx -y @pickstar-2002/mysql-mcp`（运行时现拉同一个包） |
| 数据库地址/密码 | 明文写在配置里 | `${MYSQL_组_字段}` 引用，真实值在用户环境变量 |
| Python 版 mcpServers-mysql | 命令保持 uvx 不变 | 仅 env 改成变量引用 |

**没动**：context7、node_repl。

notion（官方 MCP）记录已于 09:17 从 CC Switch 删除（此前已取消分发、无人使用）；notion-notes 自身的改造见下方小节。

## 为什么这样改

- npm 包 `@pickstar-2002/mysql-mcp` 本体还在 npm 缓存里，`npx -y` 能现拉，15 个 `mysql_*` 工具完整保留——不是换成别的包。
- 包用标准 `process.env.MYSQL_*` 读配置，环境变量名与原来一致。
- Claude Code 官方支持配置里的 `${VAR}` 展开（command/args/env/headers 都行），所以外置是标准做法。

## 新设的用户环境变量（15 个）

```
MYSQL_WTTG_HOST/PORT/USER/PASSWORD/DATABASE     39.184.152.5 / 10061 / ...
MYSQL_ZHGT_HOST/PORT/USER/PASSWORD/DATABASE     183.236.130.104 / 23306 / ...
MYSQL_HDGT_HOST/PORT/USER/PASSWORD/DATABASE     59.32.228.130 / 7574 / ...
```

## 改了两处（必须一致）

1. `C:\Users\123456\.cc-switch\cc-switch.db` 的 `mcp_servers` 表（CC Switch 的源）
2. `C:\Users\123456\.claude.json` 的 `mcpServers`（Claude Code 实际读取）

## 备份位置

- 数据库：`C:\Users\123456\.cc-switch\cc-switch.db.bak-before-portability-20261121-090157`
- Claude 配置：`C:\Users\123456\.claude.json.bak-before-portability-20261121-091202`

## 生效步骤（重要）

CC Switch 当时正在运行（PID 23068，从 2026-11-20 16:21 起）。它内存里是旧配置，**若此时触发写回会覆盖本次改动**。请：

1. **完全退出 CC Switch**（托盘图标右键退出，不是关窗口）
2. 重新打开 CC Switch——它会重新读数据库，加载新配置
3. 重启 Claude Code 会话（让新环境变量生效，并重新读 `.claude.json`）

## notion 官方 MCP 记录已删除（2026-11-21 09:17）

旧的 notion 官方 MCP（`cmd /c npx -y @notionhq/notion-mcp-server`）此前已取消分发、`.claude.json` 和 `config.toml` 里也都没有它，属于无人使用的僵尸记录，已从 CC Switch 数据库删除。删除前备份：`cc-switch.db.bak-before-delete-notion-20261121-091712`。

Notion 能力由本目录的 notion-notes 独占提供（大脑）；`notion-course-notes` Skill 只做流程判断（手），不含脚本、不直连 API。

## notion-notes 自身改造（2026-11-21 09:17）

按同样的"现拉包"标准改造我自建的 notion-notes server：

| 项目 | 改造前 | 改造后 |
|---|---|---|
| 启动命令 | 硬编码 `C:/Users/123456/.workbuddy/binaries/python/versions/3.13.12/python.exe` | `uv run --with mcp>=2 --with Pillow python server.py`（uv 在 PATH，运行时自动装依赖） |
| 依赖 | 需预装 mcp + Pillow 到特定 Python | uv 自动拉取，换机不用 `pip install` |

- CC Switch 已把 notion-notes 导入数据库并分发给 WorkBuddy；改了两处保持一致：`~/.workbuddy/mcp.json` + 数据库 `mcp_servers` 表
- 备份：`.workbuddy/mcp.json.bak-before-notionnotes-uv-20261121-091739` 和 `cc-switch.db.bak-before-notionnotes-uv-20261121-091739`
- 验证通过：按新配置启动握手成功、8 工具齐全、`notion_search` 返回 2 条结果

## 换电脑时的迁移步骤

```
1. 装 Node.js（npx 需要，任意版本，加入 PATH）
2. 装 uv（notion-notes 需要：pip install uv 或官网脚本，加入 PATH）
3. 设 15 个用户环境变量（照上面清单，值见旧机环境变量）
4. 把 .claude.json 里的 mcpServers 段拷过去（已是 ${VAR} 引用，无需改路径）
5. 把 ~/.workbuddy/mcp.json 拷过去（notion-notes 用 uv 现拉，无硬编码路径）
6. 若用 CC Switch：把改好的 cc-switch.db 拷过去，或在新机 CC Switch 里重新导入
```

不再需要装 mysql-mcp 到固定目录，也不用给 notion-notes 预装 Python 依赖——路径失效问题从根上消除。

## 验证记录（2026-11-21）

- npx 现拉包：握手成功，15 个 `mysql_*` 工具完整注册
- 环境变量从注册表注入 → `mysql_connect` 成功连到 `39.184.152.5:10061`
- `mysql_query("SELECT 1 AS ok, DATABASE() AS db")` 返回 `{"ok":1,"db":"wttg"}` ✅
- notion-notes 经 `uv run --with` 现拉依赖：握手成功、8 工具齐全、`notion_search` 返回 2 条结果 ✅
